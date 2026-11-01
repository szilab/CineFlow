"""JSON API behind the CineFlow web GUI.

The API is transport independent: :meth:`Api.handle` maps a method, path and
JSON body to a status code and a JSON-serializable payload, so it is tested
without sockets. All business rules and validation live in the backend; the
frontend only renders the definitions and issues returned here.
"""

import copy
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import yaml

from cineflow.core import catalog, preview, store, validation
from cineflow.core.config import Config
from cineflow.core.logger import log, recent_logs
from cineflow.core.schema import FLOW_SETTINGS, has_errors
from cineflow.runtime import export_directory

INSTANCE_ID = validation.INSTANCE_ID


class ApiError(Exception):
    """An error answered with a status code and an optional issue list."""

    def __init__(self, status: int, message: str, issues: list | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.issues = issues or []


def _issues(issues: list) -> list[dict]:
    return [issue.to_dict() for issue in issues]


def _revision(flow_id: str) -> str:
    """Return a content hash used to detect concurrent flow edits."""
    return hashlib.sha256(store.flow_path(flow_id).read_bytes()).hexdigest()[:16]


class Api:
    """Route GUI requests to configuration, flow and runtime operations."""

    def __init__(self, flow_manager=None) -> None:
        self._manager = flow_manager
        self._tests: dict[str, dict] = {}
        self._routes: list[tuple[str, re.Pattern, Callable]] = []
        for method, pattern, handler in (
            ('GET', r'/api/health', self.health),
            ('GET', r'/api/catalog', self.catalog),
            ('GET', r'/api/instances', self.list_instances),
            ('POST', r'/api/instances', self.create_instance),
            ('POST', r'/api/instances/test-all', self.test_all_instances),
            ('GET', r'/api/instances/(?P<instance_id>[^/]+)', self.get_instance),
            ('PUT', r'/api/instances/(?P<instance_id>[^/]+)', self.update_instance),
            ('DELETE', r'/api/instances/(?P<instance_id>[^/]+)', self.delete_instance),
            ('POST', r'/api/instances/(?P<instance_id>[^/]+)/validate', self.validate_instance),
            ('POST', r'/api/instances/(?P<instance_id>[^/]+)/test', self.test_instance),
            ('GET', r'/api/flows', self.list_flows),
            ('POST', r'/api/flows', self.create_flow),
            ('POST', r'/api/flows/validate', self.validate_flow),
            ('POST', r'/api/flows/import', self.import_flow),
            ('POST', r'/api/flows/test', self.test_flow),
            ('GET', r'/api/flows/(?P<flow_id>[^/]+)', self.get_flow),
            ('PUT', r'/api/flows/(?P<flow_id>[^/]+)', self.update_flow),
            ('DELETE', r'/api/flows/(?P<flow_id>[^/]+)', self.delete_flow),
            ('POST', r'/api/flows/(?P<flow_id>[^/]+)/run', self.run_flow),
            ('GET', r'/api/flows/(?P<flow_id>[^/]+)/yaml', self.export_flow),
            ('GET', r'/api/flows/(?P<flow_id>[^/]+)/logs', self.flow_logs),
            ('GET', r'/api/settings', self.get_settings),
            ('PUT', r'/api/settings', self.update_settings),
            ('GET', r'/api/validate', self.validate_all),
            ('GET', r'/api/config/export', self.export_config),
        ):
            self._routes.append((method, re.compile(f'^{pattern}$'), handler))

    def handle(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """Answer one request with a status code and a payload."""
        path = path.rstrip('/') or '/'
        allowed = False
        for route_method, pattern, handler in self._routes:
            if not (match := pattern.match(path)):
                continue
            allowed = True
            if route_method != method:
                continue
            try:
                result = handler(body=body, **match.groupdict())
            except ApiError as exc:
                return exc.status, {'error': {'message': exc.message, 'issues': _issues(exc.issues)}}
            except store.StoreError as exc:
                status = 404 if 'not found' in str(exc) else 400
                return status, {'error': {'message': str(exc), 'issues': []}}
            except Exception as exc:  # pylint: disable=broad-except
                log(f"Web API error on {method} {path}: {exc}", level='ERROR')
                return 500, {'error': {'message': 'Internal error, see the log.', 'issues': []}}
            return result if isinstance(result, tuple) else (200, result)
        if allowed:
            return 405, {'error': {'message': 'Method not allowed.', 'issues': []}}
        return 404, {'error': {'message': 'Not found.', 'issues': []}}

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _config() -> dict:
        return Config().data()

    def _save_config(self, config: dict) -> None:
        Config().replace(config)
        if self._manager is not None:
            self._manager.reset_modules()

    @staticmethod
    def _body(body: Any, *keys: str) -> dict:
        if not isinstance(body, dict):
            raise ApiError(400, 'Expected a JSON object.')
        for key in keys:
            if key not in body:
                raise ApiError(400, f"Missing '{key}'.")
        return body

    def _instance_summary(self, config: dict, instance_id: str) -> dict:
        named = validation.instances(config).get(instance_id)
        is_default = instance_id in catalog.module_ids()
        module_id = instance_id if is_default else (named or {}).get('module')
        definition = catalog.definition(module_id)
        if is_default:
            own = config.get(instance_id) if isinstance(config.get(instance_id), dict) else {}
            name = f"{definition.label} (default)" if definition else instance_id
        else:
            own = (named or {}).get('config') or {}
            name = (named or {}).get('name') or instance_id
        masked, secrets = store.mask(module_id, own)
        issues = validation.validate_instance(config, instance_id)
        return {
            'id': instance_id,
            'module': module_id,
            'name': name,
            'default': is_default,
            'config': masked,
            'secrets': secrets,
            'status': validation.status_of(issues),
            'issues': _issues(issues),
            'test': self._tests.get(instance_id),
        }

    def _require_instance(self, config: dict, instance_id: str) -> None:
        if instance_id not in catalog.module_ids() and instance_id not in validation.instances(config):
            raise ApiError(404, f"Instance '{instance_id}' not found.")

    def _candidate(self, config: dict, instance_id: str, body: Any) -> dict:
        """Return the configuration with an unsaved instance edit applied."""
        config = copy.deepcopy(config)
        body = body if isinstance(body, dict) else {}
        if 'config' not in body:
            return config
        values = body['config']
        if not isinstance(values, dict):
            raise ApiError(400, "'config' must be an object.")
        if instance_id in catalog.module_ids():
            old = config.get(instance_id) if isinstance(config.get(instance_id), dict) else {}
            config[instance_id] = store.restore_secrets(instance_id, values, old)
        else:
            instance = config.setdefault('instances', {})[instance_id]
            instance['config'] = store.restore_secrets(instance['module'], values, instance.get('config') or {})
            if isinstance(body.get('name'), str) and body['name'].strip():
                instance['name'] = body['name'].strip()
        return config

    def _flows_using(self, instance_id: str) -> list[str]:
        users = []
        for path in store.flow_files():
            try:
                flow = store.read_flow(path.stem)
            except store.StoreError:
                continue
            if any(isinstance(step, dict) and step.get('instance') == instance_id
                   for step in flow.get('steps') or []):
                users.append(path.stem)
        return users

    def _runtime(self, flow_id: str) -> dict | None:
        if self._manager is None:
            return None
        for file, flow in self._manager.flows().items():
            if Path(file).stem == flow_id:
                return {
                    **flow.state,
                    'running': flow.running,
                    'loaded': True,
                    'valid': flow.valid,
                    'next_due': self._manager.next_due(file),
                    'mode': self._manager.execution_mode,
                }
        return {'loaded': False, 'mode': self._manager.execution_mode}

    def _refresh(self) -> None:
        if self._manager is not None:
            self._manager.refresh()

    @staticmethod
    def _check_saveable(flow: dict, config: dict) -> list:
        """Validate a flow before saving; only flows without errors may be enabled."""
        issues = validation.validate_flow(flow, config)
        if has_errors(issues) and flow.get('enabled', True) is not False:
            raise ApiError(
                422, 'The flow has errors. Fix them or save it disabled as a draft.', issues,
            )
        if not isinstance(flow.get('steps'), list):
            raise ApiError(422, 'A flow needs a list of steps.', issues)
        return issues

    # ------------------------------------------------------------------ routes

    def health(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Report that the API is up."""
        from cineflow import __version__  # pylint: disable=import-outside-toplevel

        return {'status': 'ok', 'version': __version__, 'runtime': self._manager is not None}

    def catalog(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Return every module definition, the flow settings and the library export root."""
        return {
            'modules': [item.to_dict() for item in catalog.definitions().values()],
            'flow_settings': [
                {'key': key, 'field': setting.field.to_dict(), 'module_key': setting.module_key,
                 'modules': list(setting.modules), 'kind_default': setting.kind_default}
                for key, setting in FLOW_SETTINGS.items()
            ],
            'export_directory': str(export_directory()),
        }

    def list_instances(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Return the module defaults and named instances with their status."""
        config = self._config()
        ids = [module_id for module_id, item in catalog.definitions().items() if item.fields]
        ids += list(validation.instances(config))
        return {'instances': [self._instance_summary(config, instance_id) for instance_id in ids]}

    def get_instance(self, instance_id: str, body=None) -> dict:  # pylint: disable=unused-argument
        """Return one instance."""
        config = self._config()
        self._require_instance(config, instance_id)
        return self._instance_summary(config, instance_id)

    def create_instance(self, body=None) -> tuple[int, dict]:
        """Create a named module instance."""
        body = self._body(body, 'module', 'name')
        if catalog.definition(body['module']) is None:
            raise ApiError(400, f"Unknown module '{body['module']}'.")
        name = str(body['name']).strip()
        if not name:
            raise ApiError(400, 'A name is required.')
        config = self._config()
        taken = set(validation.instances(config)) | set(catalog.module_ids())
        instance_id = body.get('id') or re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:50] or 'instance'
        if body.get('id'):
            if not INSTANCE_ID.match(instance_id) or instance_id in taken:
                raise ApiError(400, f"Instance id '{instance_id}' is invalid or taken.")
        else:
            base, number = instance_id, 2
            while instance_id in taken:
                instance_id, number = f"{base}-{number}", number + 1
        values = body.get('config', {})
        if not isinstance(values, dict):
            raise ApiError(400, "'config' must be an object.")
        instances = config.get('instances') if isinstance(config.get('instances'), dict) else {}
        instances[instance_id] = {'module': body['module'], 'name': name, 'config': values}
        config['instances'] = instances
        self._save_config(config)
        return 201, self._instance_summary(config, instance_id)

    def update_instance(self, instance_id: str, body=None) -> dict:
        """Save the settings of a module default or a named instance."""
        body = self._body(body, 'config')
        config = self._config()
        self._require_instance(config, instance_id)
        config = self._candidate(config, instance_id, body)
        issues = validation.validate_instance(config, instance_id)
        if validation.status_of(issues) == validation.STATUS_INVALID:
            raise ApiError(422, 'The settings are invalid.', issues)
        self._tests.pop(instance_id, None)
        self._save_config(config)
        return self._instance_summary(config, instance_id)

    def delete_instance(self, instance_id: str, body=None) -> dict:  # pylint: disable=unused-argument
        """Delete a named instance that no flow uses."""
        config = self._config()
        if instance_id not in validation.instances(config):
            raise ApiError(404 if instance_id not in catalog.module_ids() else 400,
                           'Only named instances can be deleted.')
        if users := self._flows_using(instance_id):
            raise ApiError(409, f"The instance is used by: {', '.join(users)}.")
        del config['instances'][instance_id]
        self._save_config(config)
        self._tests.pop(instance_id, None)
        return {'deleted': instance_id}

    def validate_instance(self, instance_id: str, body=None) -> dict:
        """Validate unsaved or saved instance settings."""
        config = self._config()
        self._require_instance(config, instance_id)
        issues = validation.validate_instance(self._candidate(config, instance_id, body), instance_id)
        return {'status': validation.status_of(issues), 'issues': _issues(issues)}

    def _connection_test(self, config: dict, instance_id: str) -> dict:
        """Run the connection test of an instance with the given configuration."""
        module_id = instance_id if instance_id in catalog.module_ids() \
            else config['instances'][instance_id]['module']
        if has_errors(validation.validate_instance(config, instance_id)):
            result = {'ok': False, 'message': 'Fix the settings before testing.'}
        else:
            settings = validation.instance_config(config, instance_id)
            try:
                module = catalog.module_class(module_id)(config=settings)
                result = module.check_connection()
            except Exception as exc:  # pylint: disable=broad-except
                result = {'ok': False, 'message': str(exc)}
        self._tests[instance_id] = result
        return result

    def test_instance(self, instance_id: str, body=None) -> dict:
        """Run the module connection test with unsaved or saved settings."""
        config = self._config()
        self._require_instance(config, instance_id)
        candidate = self._candidate(config, instance_id, body)
        module_id = instance_id if instance_id in catalog.module_ids() \
            else candidate['instances'][instance_id]['module']
        definition = catalog.definition(module_id)
        if not definition or not definition.connection_test:
            raise ApiError(400, 'This module has no connection test.')
        return self._connection_test(candidate, instance_id)

    def test_all_instances(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Test every valid instance that supports a connection test."""
        config = self._config()
        ids = [module_id for module_id, item in catalog.definitions().items()
               if item.connection_test and isinstance(config.get(module_id), dict)]
        ids += [instance_id for instance_id, item in validation.instances(config).items()
                if isinstance(item, dict) and getattr(catalog.definition(item.get('module')),
                                                      'connection_test', False)]
        # only complete settings can connect; incomplete ones are reported by their status
        ids = [item for item in ids
               if validation.status_of(validation.validate_instance(config, item)) == validation.STATUS_VALID]
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix='web-test') as pool:
            results = dict(zip(ids, pool.map(lambda item: self._connection_test(config, item), ids)))
        return {'results': results}

    def list_flows(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Return every flow with its validation and runtime state."""
        config = self._config()
        flows = []
        for path in store.flow_files():
            entry = {'id': path.stem, 'file': path.name, 'runtime': self._runtime(path.stem)}
            try:
                flow = store.read_flow(path.stem)
            except store.StoreError as exc:
                flows.append({**entry, 'name': path.stem, 'status': 'invalid', 'errors': 1,
                              'warnings': 0, 'message': str(exc)})
                continue
            issues = validation.validate_flow(flow, config)
            flows.append({
                **entry,
                'name': flow.get('name') or path.stem,
                'description': flow.get('description') or '',
                'enabled': flow.get('enabled', True),
                'delay': flow.get('delay', 60),
                'priority': flow.get('priority', 99),
                'steps': len(flow.get('steps') or []) if isinstance(flow.get('steps'), list) else 0,
                'status': 'invalid' if has_errors(issues) else 'valid',
                'errors': sum(issue.level == 'error' for issue in issues),
                'warnings': sum(issue.level == 'warning' for issue in issues),
            })
        return {'flows': flows}

    def get_flow(self, flow_id: str, body=None) -> dict:  # pylint: disable=unused-argument
        """Return one flow for the editor."""
        flow = store.read_flow(flow_id)
        masked, secrets = store.mask_flow(flow)
        return {
            'id': flow_id,
            'flow': masked,
            'secrets': secrets,
            'revision': _revision(flow_id),
            'issues': _issues(validation.validate_flow(flow, self._config())),
            'runtime': self._runtime(flow_id),
        }

    def create_flow(self, body=None) -> tuple[int, dict]:
        """Create a flow file."""
        flow = self._body(body, 'flow')['flow']
        if not isinstance(flow, dict):
            raise ApiError(400, "'flow' must be an object.")
        flow = {**flow, 'version': 1}
        issues = self._check_saveable(flow, self._config())
        flow_id = store.save_flow(flow)
        self._refresh()
        return 201, {'id': flow_id, 'issues': _issues(issues), 'revision': _revision(flow_id)}

    def update_flow(self, flow_id: str, body=None) -> dict:
        """Overwrite a flow file unless it changed since the editor loaded it."""
        body = self._body(body, 'flow')
        flow = body['flow']
        if not isinstance(flow, dict):
            raise ApiError(400, "'flow' must be an object.")
        if body.get('revision') and body['revision'] != _revision(flow_id):
            raise ApiError(409, 'The flow changed on disk since it was opened. Reload it first.')
        old = store.read_flow(flow_id)
        flow = store.restore_flow_secrets(flow, old)
        version = old.get('version') if isinstance(old.get('version'), int) else 0
        flow['version'] = version + 1
        issues = self._check_saveable(flow, self._config())
        store.save_flow(flow, flow_id)
        self._refresh()
        return {'id': flow_id, 'issues': _issues(issues), 'revision': _revision(flow_id)}

    def delete_flow(self, flow_id: str, body=None) -> dict:  # pylint: disable=unused-argument
        """Delete a flow file (a backup is kept)."""
        store.delete_flow(flow_id)
        self._refresh()
        return {'deleted': flow_id}

    def validate_flow(self, body=None) -> dict:
        """Validate an unsaved flow."""
        flow = self._body(body, 'flow')['flow']
        issues = validation.validate_flow(flow, self._config())
        return {'valid': not has_errors(issues), 'issues': _issues(issues)}

    def test_flow(self, body=None) -> dict:
        """Test-run an unsaved flow up to a step: real reads, no side effects."""
        body = self._body(body, 'flow')
        flow = body['flow']
        if not isinstance(flow, dict):
            raise ApiError(400, "'flow' must be an object.")
        if body.get('id'):
            flow = store.restore_flow_secrets(flow, store.read_flow(body['id']))
        until = body.get('until')
        if until is not None and (isinstance(until, bool) or not isinstance(until, int) or until < 0):
            raise ApiError(400, "'until' must be a step index.")
        steps = flow.get('steps') if isinstance(flow.get('steps'), list) else []
        if until is not None:
            steps = steps[:until + 1]
        issues = validation.validate_flow({**flow, 'steps': steps}, self._config())
        if has_errors(issues):
            raise ApiError(422, 'Fix the errors of these steps before testing.', issues)
        result = preview.run_test({**flow, 'steps': steps, 'enabled': True})
        if result is None:
            raise ApiError(429, 'Other tests are running. Try again shortly.')
        return result

    def import_flow(self, body=None) -> tuple[int, dict]:
        """Import a flow from YAML text as a new flow file."""
        text = self._body(body, 'yaml')['yaml']
        if not isinstance(text, str):
            raise ApiError(400, "'yaml' must be text.")
        flow = store.parse_flow_yaml(text)
        issues = validation.validate_flow(flow, self._config())
        if has_errors(issues) and flow.get('enabled', True) is not False:
            if not body.get('as_draft'):
                raise ApiError(422, 'The imported flow has errors. Import it as a disabled draft '
                                    'or fix the YAML.', issues)
            flow['enabled'] = False
        flow_id = store.save_flow(flow)
        self._refresh()
        return 201, {'id': flow_id, 'issues': _issues(issues), 'enabled': flow.get('enabled', True)}

    def export_flow(self, flow_id: str, body=None) -> tuple[int, dict]:  # pylint: disable=unused-argument
        """Return the flow as YAML without secret step settings."""
        masked, _ = store.mask_flow(store.read_flow(flow_id))
        return 200, {'yaml': store.flow_yaml(masked), 'filename': f"{flow_id}.yaml"}

    def run_flow(self, flow_id: str, body=None) -> tuple[int, dict]:  # pylint: disable=unused-argument
        """Start one manual run of a flow."""
        if self._manager is None:
            raise ApiError(503, 'The flow runtime is not running.')
        store.flow_path(flow_id)
        self._manager.refresh()
        for file, flow in self._manager.flows().items():
            if Path(file).stem != flow_id:
                continue
            if not flow.valid:
                raise ApiError(409, 'The flow is not runnable.')
            if not flow.trigger():
                raise ApiError(409, 'The flow is already running.')
            return 202, {'started': flow_id}
        raise ApiError(404, f"Flow '{flow_id}' is not loaded.")

    def flow_logs(self, flow_id: str, body=None) -> dict:  # pylint: disable=unused-argument
        """Return the recent log messages of a flow."""
        flow = store.read_flow(flow_id)
        return {'logs': recent_logs(flow=flow.get('name') or 'Unnamed Flow')}

    def get_settings(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Return the global runtime settings."""
        config = self._config()
        configured = config.get('execution', 'parallel')
        effective = self._manager.execution_mode if self._manager else configured
        return {
            'execution': configured,
            'execution_effective': effective,
            'restart_required': configured != effective,
            'modes': list(validation.EXECUTION_MODES),
        }

    def update_settings(self, body=None) -> dict:
        """Save the global runtime settings."""
        body = self._body(body, 'execution')
        if body['execution'] not in validation.EXECUTION_MODES:
            raise ApiError(422, "Expected 'parallel' or 'sequential'.")
        config = self._config()
        config['execution'] = body['execution']
        self._save_config(config)
        return self.get_settings()

    def validate_all(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Validate the configuration and every flow."""
        config = self._config()
        flows = {}
        for path in store.flow_files():
            try:
                flows[path.stem] = _issues(validation.validate_flow(store.read_flow(path.stem), config))
            except store.StoreError as exc:
                flows[path.stem] = [{'level': 'error', 'path': [], 'message': str(exc), 'code': 'yaml'}]
        return {'config': _issues(validation.validate_config(config)), 'flows': flows}

    def export_config(self, body=None) -> dict:  # pylint: disable=unused-argument
        """Return the global configuration as YAML without secrets."""
        exported = store.mask_config(self._config())
        return {
            'yaml': yaml.safe_dump(exported, default_flow_style=False, allow_unicode=True, sort_keys=False),
            'filename': 'config.yaml',
        }
