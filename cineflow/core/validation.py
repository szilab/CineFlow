"""Preflight validation of the global configuration, module instances and flows.

Validation never contacts external services and never starts workers. Results
are lists of :class:`~cineflow.core.schema.Issue` so the CLI and the GUI can
both point at the exact setting that is wrong.
"""

import copy
import re
from typing import Any

from cineflow.core import catalog
from cineflow.core.schema import (
    FLOW_SETTINGS, MEDIA_KINDS, Issue, error, warning, has_errors, validate_fields, validate_value, get_path,
)

EXECUTION_MODES = ('parallel', 'sequential')
CONFIG_ROOT_KEYS = ('execution', 'instances')
FLOW_KEYS = ('name', 'description', 'version', 'enabled', 'delay', 'priority', 'kind', *FLOW_SETTINGS, 'steps')
STEP_KEYS = ('name', 'module', 'action', 'instance', 'input', 'config')
INSTANCE_ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')

STATUS_VALID = 'valid'
STATUS_INCOMPLETE = 'incomplete'
STATUS_INVALID = 'invalid'


def merge_config(base: dict, override: dict) -> dict:
    """Return a recursive merge, matching the runtime module configuration merge."""
    merged = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def instances(config: dict) -> dict:
    """Return the named module instances of a configuration."""
    value = (config or {}).get('instances')
    return value if isinstance(value, dict) else {}


def instance_config(config: dict, instance_id: str) -> dict:
    """Return the effective settings of a named instance or a module default."""
    config = config or {}
    if instance_id in catalog.module_ids():
        section = config.get(instance_id)
        return copy.deepcopy(section) if isinstance(section, dict) else {}
    instance = instances(config).get(instance_id)
    if not isinstance(instance, dict):
        return {}
    module_defaults = config.get(instance.get('module'))
    return merge_config(
        module_defaults if isinstance(module_defaults, dict) else {}, instance.get('config') or {},
    )


def status_of(issues: list[Issue]) -> str:
    """Summarize issues as valid, incomplete (only missing values) or invalid."""
    errors = [issue for issue in issues if issue.level == 'error']
    if not errors:
        return STATUS_VALID
    if all(issue.code == 'required' for issue in errors):
        return STATUS_INCOMPLETE
    return STATUS_INVALID


def validate_module_config(module_id: str, values: Any, path: tuple = (), required: bool = True) -> list[Issue]:
    """Validate the settings of one module."""
    definition = catalog.definition(module_id)
    if definition is None:
        return [error(path, f"Unknown module '{module_id}'.", 'unknown_module')]
    return validate_fields(
        definition.fields, values, path, check_required=required, env_prefix=module_id,
    )


def validate_instance(config: dict, instance_id: str) -> list[Issue]:
    """Validate a named instance or a module default with its inherited settings."""
    config = config or {}
    if instance_id in catalog.module_ids():
        return validate_module_config(instance_id, instance_config(config, instance_id), (instance_id,))
    path = ('instances', instance_id)
    instance = instances(config).get(instance_id)
    if not isinstance(instance, dict):
        return [error(path, f"Unknown module instance '{instance_id}'.", 'unknown_instance')]
    issues = []
    if not INSTANCE_ID.match(str(instance_id)):
        issues.append(error(path, "Instance IDs use lower-case letters, digits, '-' and '_'.", 'format'))
    if catalog.definition(instance.get('module')) is None:
        return issues + [error((*path, 'module'), f"Unknown module '{instance.get('module')}'.", 'unknown_module')]
    if not isinstance(instance.get('name', ''), str):
        issues.append(error((*path, 'name'), "Expected text.", 'type'))
    if not isinstance(instance.get('config') or {}, dict):
        return issues + [error((*path, 'config'), "Expected a mapping.", 'type')]
    issues.extend(validate_module_config(
        instance['module'], instance_config(config, instance_id), (*path, 'config'),
    ))
    return issues


def validate_config(config: Any) -> list[Issue]:  # noqa: C901
    """Validate the global configuration without contacting services."""
    if config is None:
        config = {}
    if not isinstance(config, dict):
        return [error((), "The configuration must be a mapping.", 'type')]
    issues = []
    execution = config.get('execution', 'parallel')
    if execution not in EXECUTION_MODES:
        issues.append(error(('execution',), "Expected 'parallel' or 'sequential'.", 'choice'))
    modules = catalog.module_ids()
    for key, value in config.items():
        if key in CONFIG_ROOT_KEYS:
            continue
        if key not in modules:
            issues.append(warning((key,), f"Unknown configuration section '{key}'.", 'unknown'))
        elif not isinstance(value, dict):
            issues.append(error((key,), "Module settings must be a mapping.", 'type'))
        else:
            # module defaults may be partial: steps and instances complete them
            issues.extend(validate_module_config(key, value, (key,), required=False))
    raw_instances = config.get('instances')
    if raw_instances is not None and not isinstance(raw_instances, dict):
        issues.append(error(('instances',), "Instances must be a mapping.", 'type'))
    for instance_id in instances(config):
        if instance_id in modules:
            issues.append(error(('instances', instance_id), "Instance IDs must differ from module names.", 'conflict'))
            continue
        issues.extend(validate_instance(config, instance_id))
    return issues


def _reference(value: Any) -> str | None:
    """Return the step name of a ``{{name}}`` reference."""
    if isinstance(value, str) and value.startswith('{{') and value.endswith('}}'):
        return value.strip('{}').strip()
    return None


def _data_source_issues(source: Any, path: tuple, index: int, earlier: list[str]) -> list[Issue]:
    """Validate a data source: previous, a reference or a list of step names."""
    if source == 'previous':
        if index == 0:
            return [error(path, "The first step has no previous output.", 'reference')]
        return []
    if (name := _reference(source)) is not None:
        if name not in earlier:
            return [error(path, f"Step '{name}' is not an earlier step.", 'reference')]
        return []
    if isinstance(source, list):
        issues = []
        for position, item in enumerate(source):
            name = _reference(item) or (item if isinstance(item, str) else None)
            if name is None or name not in earlier:
                issues.append(error((*path, position), f"Step '{item}' is not an earlier step.", 'reference'))
        return issues
    return [error(path, "Expected 'previous', '{{step name}}' or a list of step names.", 'type')]


def _input_issues(step_input: Any, path: tuple, index: int, earlier: list[str], action) -> list[Issue]:  # noqa: C901
    """Validate the input of a step against the runtime input shapes."""
    if step_input in (None, '', 'none'):
        if action is not None and action.takes_data and not action.takes_query:
            return [warning(path, "This action expects items but receives no input.", 'input')]
        return []
    if step_input == 'previous' or isinstance(step_input, list) or _reference(step_input) is not None:
        issues = _data_source_issues(step_input, path, index, earlier)
        if action is not None and not action.takes_data and not issues:
            issues.append(warning(path, "This action does not use item input.", 'input'))
        return issues
    if isinstance(step_input, str):
        if action is not None and not action.takes_query:
            return [warning(path, "This action does not take a text query.", 'input')]
        return []
    if not isinstance(step_input, dict):
        return [error(path, "Unsupported input shape.", 'type')]
    issues = []
    if 'data' in step_input:
        issues.extend(_data_source_issues(step_input['data'], (*path, 'data'), index, earlier))
    if action is None:
        return issues
    if 'query' in step_input:
        query = step_input['query']
        if not action.takes_query:
            issues.append(warning((*path, 'query'), "This action does not take a query.", 'input'))
        elif isinstance(query, dict):
            issues.extend(validate_fields(action.query, query, (*path, 'query'), check_required=False))
        elif not isinstance(query, (str, list)):
            issues.append(error((*path, 'query'), "Expected a mapping or text.", 'type'))
    issues.extend(validate_fields(action.arguments, step_input, path, check_required=False))
    known = {'data', 'query', *(item.key for item in action.arguments)}
    for key in step_input:
        if key not in known:
            issues.append(warning((*path, key), f"Unknown input key '{key}'.", 'unknown'))
    return issues


def _instance_issues(step: dict, path: tuple, config: dict) -> tuple[list[Issue], dict]:
    """Validate the instance reference of a step and return its settings."""
    module_id = step.get('module')
    instance_id = step.get('instance')
    if instance_id in (None, ''):
        return [], instance_config(config, module_id)
    instance = instances(config).get(instance_id)
    if not isinstance(instance, dict):
        return [error((*path, 'instance'), f"Unknown module instance '{instance_id}'.", 'unknown_instance')], {}
    if instance.get('module') != module_id:
        return [error(
            (*path, 'instance'),
            f"Instance '{instance_id}' belongs to module '{instance.get('module')}'.", 'conflict',
        )], {}
    if (status := status_of(validate_instance(config, instance_id))) != STATUS_VALID:
        return [error((*path, 'instance'), f"Instance '{instance_id}' is {status}.", 'instance_status')], {}
    return [], instance_config(config, instance_id)


def _step_issues(step: Any, index: int, earlier: list[str], config: dict) -> list[Issue]:  # noqa: C901
    """Validate one step."""
    path = ('steps', index)
    if not isinstance(step, dict):
        return [error(path, "A step must be a mapping.", 'type')]
    issues = []
    for key in step:
        if key not in STEP_KEYS:
            issues.append(warning((*path, key), f"Unknown step key '{key}'.", 'unknown'))
    name = step.get('name')
    if name in (None, ''):
        issues.append(warning((*path, 'name'), "Unnamed steps cannot be referenced.", 'required'))
    elif not isinstance(name, str):
        issues.append(error((*path, 'name'), "Expected text.", 'type'))
    elif name in earlier:
        issues.append(error((*path, 'name'), f"Step name '{name}' is used twice.", 'duplicate'))
    module_id, action_id = step.get('module'), step.get('action')
    if not module_id:
        return issues + [error((*path, 'module'), "A module is required.", 'required')]
    if not action_id:
        return issues + [error((*path, 'action'), "An action is required.", 'required')]
    definition = catalog.definition(module_id)
    if definition is None:
        return issues + [error((*path, 'module'), f"Unknown module '{module_id}'.", 'unknown_module')]
    action = definition.action(action_id)
    if action is None:
        if callable(getattr(catalog.module_class(module_id), str(action_id), None)) \
                and not str(action_id).startswith('_'):
            issues.append(warning((*path, 'action'), f"Action '{action_id}' is not documented.", 'undocumented'))
        else:
            return issues + [error((*path, 'action'), f"Module '{module_id}' has no action '{action_id}'.",
                                   'unknown_action')]
    step_config = step.get('config') or {}
    if not isinstance(step_config, dict):
        return issues + [error((*path, 'config'), "Expected a mapping.", 'type')]
    instance_issues, base = _instance_issues(step, path, config)
    issues.extend(instance_issues)
    action_fields = action.fields if action else ()
    issues.extend(validate_fields(action_fields, step_config, (*path, 'config'), check_required=False))
    effective = merge_config(base, step_config)
    if not instance_issues:
        # required settings may come from defaults, the instance or the step
        for issue in validate_fields(definition.fields, effective, (), env_prefix=module_id):
            if get_path(step_config, issue.path[0]) is not None:
                issues.append(error((*path, 'config', *issue.path), issue.message, issue.code))
            elif issue.code == 'required':
                issues.append(error(
                    (*path, 'config', *issue.path),
                    f"{issue.message} Set it in the module settings or the step.", issue.code,
                ))
    known = {item.key.split('.')[0] for item in (*definition.fields, *action_fields)}
    for key in step_config:
        if key not in known:
            issues.append(warning((*path, 'config', key), f"Unknown setting '{key}'.", 'unknown'))
    issues.extend(_input_issues(step.get('input'), (*path, 'input'), index, earlier, action))
    return issues


def validate_flow(flow: Any, config: dict | None = None) -> list[Issue]:  # noqa: C901
    """Validate a flow definition against the module catalog and configuration."""
    config = config or {}
    if not isinstance(flow, dict):
        return [error((), "A flow must be a mapping.", 'type')]
    issues = []
    for key in flow:
        if key not in FLOW_KEYS:
            issues.append(warning((key,), f"Unknown flow key '{key}'.", 'unknown'))
    if not isinstance(flow.get('name'), str) or not flow.get('name', '').strip():
        issues.append(error(('name',), "A flow name is required.", 'required'))
    if not isinstance(flow.get('enabled', True), bool):
        issues.append(error(('enabled',), "Expected true or false.", 'type'))
    delay = flow.get('delay', 60)
    if isinstance(delay, bool) or not isinstance(delay, int) or delay < 1:
        issues.append(error(('delay',), "Delay must be a whole number of minutes, at least 1.", 'range'))
    priority = flow.get('priority', 99)
    if isinstance(priority, bool) or not isinstance(priority, int):
        issues.append(error(('priority',), "Priority must be a whole number.", 'type'))
    if 'description' in flow and not isinstance(flow['description'], (str, type(None))):
        issues.append(error(('description',), "Expected text.", 'type'))
    if flow.get('kind') is not None and flow.get('kind') not in MEDIA_KINDS:
        issues.append(error(('kind',), "Expected one of: movie, tv.", 'choice'))
    for flow_key, setting in FLOW_SETTINGS.items():
        if flow.get(flow_key) not in (None, '', []):
            issues.extend(validate_value(setting.field, flow[flow_key], (flow_key,)))
    steps = flow.get('steps')
    if not isinstance(steps, list) or not steps:
        return issues + [error(('steps',), "A flow needs at least one step.", 'required')]
    earlier = []
    for index, step in enumerate(steps):
        issues.extend(_step_issues(step, index, earlier, config))
        if isinstance(step, dict) and isinstance(step.get('name'), str) and step['name']:
            earlier.append(step['name'])
    return issues


def flow_is_runnable(flow: Any, config: dict | None = None) -> bool:
    """Return whether a flow has no validation errors."""
    return not has_errors(validate_flow(flow, config))
