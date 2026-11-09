"""Flow Runner"""

import copy
import hashlib
import os
from pathlib import Path
from typing import Any
import inspect
import threading
import time
from datetime import datetime
import yaml
from cineflow.core.config import cfg
from cineflow.core.bases.module import ModuleBase, _merge_config
from cineflow.core.bases.worker import WorkerBase
from cineflow.core.logger import log, log_context
from cineflow.core.schema import DEFAULT_MEDIA_KIND, FLOW_SETTINGS, flow_media_kind, run_kinds, validate_value
from cineflow.utils.misc import load_module
from cineflow.runtime import config_directory


class FlowManager(WorkerBase):
    """Flow Runner class to manage the execution of tasks."""

    def __init__(self) -> None:
        """Initialize the task runner."""
        super().__init__()
        try:
            self._delay = int(os.environ.get("FM_REFRESH_SEQ", 60))
        except ValueError:
            log("Invalid 'FM_REFRESH_SEQ' value, using default 60 minutes.", level="WARNING")
            self._delay = 60
        self._dir = str(config_directory())
        self._flows = {}
        self._flow_hashes = {}
        self._next_due = {}
        self._manage_lock = threading.RLock()
        self._exec_mode = cfg('execution', default='parallel')
        if self._exec_mode not in ('parallel', 'sequential'):
            log(
                f"Invalid execution mode '{self._exec_mode}', falling back to parallel.",
                level="WARNING"
            )
            self._exec_mode = 'parallel'
        if os.path.exists(self._dir):
            self.start()

    def _get_flow_files(self) -> list:
        """Get the list of flow files."""
        files = []
        for filename in os.listdir(self._dir):
            file_path = os.path.join(self._dir, filename)
            if os.path.isdir(file_path) or filename == "config.yaml":
                continue
            if filename.endswith(('.yaml', '.yml')):
                files.append(file_path)
            else:
                log(f"Skipping non-YAML file: {filename}")
        return files

    def refresh(self) -> None:
        """Load added, changed and removed flow files now, e.g. after a GUI save."""
        if os.path.exists(self._dir):
            self._manage_flows(self._get_flow_files())

    def flows(self) -> dict:
        """Return the loaded flows by file path."""
        with self._manage_lock:
            return dict(self._flows)

    def next_due(self, file: str) -> float | None:
        """Return the next sequential run as a UNIX timestamp, if scheduled."""
        due = self._next_due.get(file)
        return None if due is None else time.time() + (due - time.monotonic())

    def reset_modules(self) -> None:
        """Make every flow rebuild its modules so configuration changes apply."""
        for flow in self.flows().values():
            flow.reset_modules()

    @property
    def execution_mode(self) -> str:
        """Return the effective execution mode."""
        return self._exec_mode

    def _manage_flows(self, files: list) -> None:
        """Add new flows and remove old ones."""
        with self._manage_lock:
            self._manage_flows_locked(files)

    def _manage_flows_locked(self, files: list) -> None:
        """Add new flows and remove old ones while holding the manage lock."""
        for file in files:
            file_hash = self._get_file_hash(file)
            if file not in self._flows or self._flow_hashes.get(file) != file_hash:
                if file in self._flows:
                    log(f"Flow '{self._flows[file].name}' changed, reloading.", level="INFO")
                    if not self._flows[file].stop():
                        log(
                            f"Flow '{self._flows[file].name}' is still stopping; "
                            "reload deferred.", level="WARNING"
                        )
                        continue
                flow = Flow(file)
                self._report_issues(file)
                self._flows[file] = flow
                self._flow_hashes[file] = file_hash
                if self._exec_mode == 'parallel' and flow.valid and flow.enabled:
                    flow.start()
                elif self._exec_mode == 'sequential' and flow.valid and flow.enabled:
                    self._next_due[file] = time.monotonic()
                else:
                    self._next_due.pop(file, None)

        for key in [key for key, flow in self._flows.items() if key not in files]:
            log(f"Flow '{self._flows[key].name}' removed from the system.", level="INFO")
            if not self._flows[key].stop():
                log(
                    f"Flow '{self._flows[key].name}' is still stopping; removal deferred.",
                    level="WARNING"
                )
                continue
            del self._flows[key]
            del self._flow_hashes[key]
            self._next_due.pop(key, None)

    @staticmethod
    def _report_issues(file: str) -> None:
        """Log validation findings of a loaded flow; they never block the runtime."""
        # pylint: disable=import-outside-toplevel
        from cineflow.core import store, validation
        from cineflow.core.config import Config
        try:
            flow = store.parse_flow_yaml(Path(file).read_text(encoding='utf-8'))
            issues = validation.validate_flow(flow, Config().data())
        except (OSError, ValueError) as exc:
            log(f"Flow file '{os.path.basename(file)}' not validated: {exc}", level="DEBUG")
            return
        for issue in issues:
            log(f"Flow file '{os.path.basename(file)}': {issue}", level="WARNING")

    @staticmethod
    def _get_file_hash(file: str) -> str | None:
        """Return a content hash for a flow file."""
        try:
            return hashlib.sha256(Path(file).read_bytes()).hexdigest()
        except OSError as exc:
            log(f"Unable to read flow file '{file}': {exc}", level="WARNING")
            return None

    def run(self) -> None:
        """Run the flow manager."""
        if self._stop_event.is_set():
            return
        files = self._get_flow_files()
        if not files:
            log("No flow files found to run.", level="INFO")
        self._manage_flows(files)
        if self._exec_mode == 'sequential':
            log("Sequential flow execution started.", level="INFO")
            now = time.monotonic()
            due_flows = [
                (file, flow) for file, flow in self.flows().items()
                if flow.valid and flow.enabled and self._next_due.get(file, now) <= now
            ]
            for file, flow in sorted(due_flows, key=lambda item: item[1].priority):
                if self._stop_event.is_set():
                    return
                flow.run()
                self._next_due[file] = time.monotonic() + flow.delay * 60

    def close(self) -> bool:
        """Stop managed flows and report whether all flow execution terminated."""
        flows_stopped = True
        for flow in self.flows().values():
            log(f"Stopping flow '{flow.name}'.", level="INFO")
            if not flow.stop():
                flows_stopped = False
        manager_stopped = self._thread is None or self.stop()
        if not manager_stopped or not flows_stopped:
            log("Flow execution is still stopping; dependent resources left open.", level="WARNING")
            return False
        return True


class Flow(WorkerBase):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Class to manage the execution of a flow."""

    def __init__(self, file: str, definition: dict | None = None) -> None:
        """Initialize the task runner from a flow file, or from ``definition`` when given."""
        super().__init__()
        self._file = file
        self._definition = definition
        self._filename = os.path.basename(file)
        self.name = 'Unnamed Flow'
        self.steps = []
        self.priority = 99
        self.delay = 60
        self.kind = DEFAULT_MEDIA_KIND
        # media kind of the pass in progress; a flow of kind 'both' runs one pass per kind
        self.run_kind = DEFAULT_MEDIA_KIND
        self.enabled = True
        self._enabled_valid = True
        self._kind_valid = True
        # flow settings handed to the modules that use them (see FLOW_SETTINGS)
        self.settings = {}
        self._settings_valid = True
        self._mod_cache = {}
        self._outputs = {}
        self._run_lock = threading.Lock()
        self._runner = None
        self.state = {
            'running': False, 'last_start': None, 'last_end': None,
            'last_status': None, 'last_error': None, 'last_step': None,
        }
        self._valid = self._validate_flow()
        if self._valid:
            log(f"Flow '{self._filename}' initialized.", level="INFO")

    def run(self) -> None:
        """Run the flow on its schedule."""
        super().run()
        self.execute()

    def execute(self, force: bool = False) -> str | None:
        """Run the flow once unless it is already running; return the result status.

        ``force`` runs a valid but disabled flow, for a manual run.
        """
        if not self._valid or not (self.enabled or force):
            return None
        if not self._run_lock.acquire(blocking=False):
            log(f"Flow '{self.name}' is already running, run skipped.", level="INFO")
            return None
        try:
            self._runner = threading.current_thread()
            self.state.update(running=True, last_start=time.time(), last_error=None, last_step=None)
            with log_context(self.name):
                status, message = self._execute_steps()
            self.state.update(last_status=status, last_error=message)
            return status
        finally:
            self._runner = None
            self.state.update(running=False, last_end=time.time())
            self._run_lock.release()

    def stop(self, timeout: float = 5) -> bool:
        """Stop the schedule and wait for a running (also manual) run to end."""
        stopped = super().stop(timeout=timeout)
        if self._runner is threading.current_thread():
            return stopped
        if not self._run_lock.acquire(timeout=timeout):
            return False
        self._run_lock.release()
        return stopped

    def trigger(self) -> bool:
        """Start one manual run in the background; False when it cannot start."""
        if not self._valid or self._run_lock.locked():
            return False
        thread = threading.Thread(
            target=self.execute, kwargs={'force': True}, daemon=True,
            name=f"flow:{self.name}:manual:{datetime.now():%H%M%S}",
        )
        thread.start()
        return True

    @property
    def running(self) -> bool:
        """Return whether a run is in progress."""
        return self._run_lock.locked()

    def reset_modules(self) -> None:
        """Drop cached module instances; the next step builds them from fresh settings."""
        self._mod_cache = {}

    def _execute_steps(self) -> tuple[str, str | None]:
        """Run the steps once per media kind of the flow; return the status and an error message.

        The passes of a flow of kind 'both' are independent: a failed movie pass
        does not stop the TV pass, but the run is reported as failed.
        """
        kinds = run_kinds(self.kind)
        failures = []
        try:
            for kind in kinds:
                self.run_kind = kind
                if len(kinds) > 1:
                    log(f"Flow '{self.name}' runs for media kind '{kind}'.", level="INFO")
                status, message = self._execute_pass()
                if status == 'stopped':
                    return status, message
                if status != 'success':
                    failures.append(f"{kind}: {message}" if len(kinds) > 1 else message)
        finally:
            self.run_kind = kinds[0]
        if failures:
            return 'failed', '; '.join(failures)
        return 'success', None

    def _execute_pass(self) -> tuple[str, str | None]:  # noqa: C901
        """Run the steps once for ``run_kind`` and return the status and an error message."""
        self._outputs = {}
        log(f"Flow '{self.name}' from file '{self._filename}' started.", level="INFO")
        for step in self.steps:
            if self._stop_event.is_set():
                log(f"Flow '{self.name}' stopped before the next step.", level="INFO")
                return 'stopped', None
            self.state['last_step'] = step.get('name')
            log(f"Start step '{step.get('name')}'", level="MSG")
            outp = None
            try:
                if not (inst := self._load_module(step=step)):
                    return 'failed', f"Module of step '{step.get('name')}' could not be loaded."
                if not (action := self._load_action(inst=inst, step=step)):
                    return 'failed', f"Action of step '{step.get('name')}' not found."
                if not (inp := self._load_input(step=step)):
                    log(f"No input data for step '{step.get('name')}'.")
                outp = self._call_action(action=action, inp=inp)
            except Exception as exc:  # pylint: disable=broad-except
                log(f"Stop flow, error calling action '{step.get('name')}' -> {exc}", level="ERROR")
                return 'failed', f"Step '{step.get('name')}': {exc}"
            if outp is None and step.get("action") == "get":
                log(
                    f"Step '{step.get('name')}' failed to retrieve data. "
                    "Aborting flow to prevent logic errors.", level="ERROR")
                return 'failed', f"Step '{step.get('name')}' failed to retrieve data."
            if step.get("name"):
                self._outputs[step.get("name")] = outp
            self._outputs['latest'] = outp
            log(f"Step '{step.get('name')}' executed successfully.", level="MSG")
        log(f"Flow '{self.name}' executed successfully.", level="INFO")
        return 'success', None

    @property
    def valid(self) -> bool:
        """Return whether the parsed flow is runnable."""
        return self._valid

    def _module_settings(self, module_id: str) -> dict:
        """Return the flow settings for one module; they always come from the flow."""
        values = {}
        for flow_key, setting in FLOW_SETTINGS.items():
            if module_id not in setting.modules:
                continue
            if flow_key in self.settings:
                values[setting.module_key] = copy.deepcopy(self.settings[flow_key])
            elif setting.kind_default:
                values[setting.module_key] = self.run_kind
            else:
                values[setting.module_key] = copy.deepcopy(setting.field.default)
        return values

    def _load_module(self, step: dict) -> ModuleBase | None:
        """Load a module by its name."""
        name = step.get('module')
        config = step.get('config') or {}
        instance_id = step.get('instance')
        if instance_id:
            instance = (cfg('instances') or {}).get(instance_id)
            if not isinstance(instance, dict) or instance.get('module') != name:
                log(f"Module instance '{instance_id}' of '{name}' not found, stop flow.", level="ERROR")
                return None
            # module defaults < instance settings < step settings
            config = _merge_config(instance.get('config') or {}, config)
        # every module handles the media kind of the flow
        config = _merge_config(config, {'kind': self.run_kind})
        config = _merge_config(config, self._module_settings(name))
        # Use a hash of the config to reuse instances with identical settings
        cache_key = f"{name}_{instance_id}_{hash(str(config))}"

        if cache_key in self._mod_cache:
            return self._mod_cache[cache_key]

        if not (mod_class := load_module(name)):
            log(f"Module '{name}' not found, stop flow.", level="ERROR")
            return None

        instance = mod_class(config=config)
        self._mod_cache[cache_key] = instance
        return instance

    def _load_action(self, inst: ModuleBase, step: dict) -> callable:
        """Load an action function from the module."""
        name = step.get("action")
        if not (action := getattr(inst, name, None)):
            log(f"Action '{name}' not found in '{step.get('module')}', stop flow.", level="ERROR")
            return None
        if not callable(action):
            log(f"Wrong '{action}' in module '{step.get('module')}', stop flow.", level="ERROR")
            return None
        return action

    def _load_input(self, step: dict) -> Any:
        """Load input data for the action."""
        inp = step.get("input")
        if not inp or inp == "none":
            return None
        if inp == "previous":
            return self._outputs.get('latest')
        if isinstance(inp, list):
            return self._handle_list_input(inp)
        if isinstance(inp, str):
            return self._handle_string_input(inp)
        if isinstance(inp, dict):
            return self._handle_dict_input(inp)
        return inp

    def _handle_list_input(self, inp: list) -> list:
        """Handle list input by merging outputs from previous steps."""
        merged = []
        for s in inp:
            output_key = str(s).strip("{}")
            if output_key in self._outputs:
                val = self._outputs[output_key]
                if val is not None:
                    merged.extend(val if isinstance(val, list) else [val])
            else:
                log(f"Output '{output_key}' not found in outputs.", level="WARNING")
        return merged

    def _handle_string_input(self, inp: str) -> Any:
        """Handle string input, resolving references to previous step outputs."""
        if inp.startswith("{{") and inp.endswith("}}"):
            output_key = inp.strip("{}")
            if output_key in self._outputs:
                return self._outputs[output_key]
            log(f"Output '{output_key}' not found, passing raw input.", level="WARNING")
        return inp

    def _handle_dict_input(self, inp: dict) -> dict:
        """Handle dictionary input, resolving 'previous' data reference."""
        new_inp = copy.deepcopy(inp)
        data = new_inp.get("data")
        if data == "previous":
            new_inp["data"] = self._outputs.get('latest')
        elif isinstance(data, str) and data.startswith("{{") and data.endswith("}}"):
            new_inp["data"] = self._handle_string_input(data)
        elif isinstance(data, list):
            new_inp["data"] = self._handle_list_input(data)
        return new_inp

    def _call_action(self, action: callable, inp: Any) -> Any:
        """Call the action with the provided input data."""
        params = inspect.signature(action).parameters
        if len(params) == 0 or inp is None:
            return action()
        if len(params) == 1:
            if isinstance(inp, dict):
                if next(iter(params)) == next(iter(inp)):
                    return action(**inp)
            elif isinstance(inp, list):
                return action(inp)
            return action(inp)
        if isinstance(inp, dict):
            return action(**inp)
        # only items (e.g. ``input: previous``): they are the first argument, the rest keep their defaults
        return action(inp)

    def _parse_file(self) -> None:
        if self._definition is not None:
            self._apply_definition(copy.deepcopy(self._definition))
            return
        with open(self._file, 'r', encoding='UTF-8') as stream:
            try:
                self._apply_definition(yaml.safe_load(stream))
            except yaml.YAMLError as exc:
                log(f"Error loading flow file '{self._filename}': {exc}", level="WARNING")

    def _apply_definition(self, data) -> None:
        """Take the flow settings from a parsed definition."""
        if data and isinstance(data, dict) and data.get("steps"):
            self.name = data.get("name", self.name)
            self.steps = data.get("steps", self.steps)
            self.delay = data.get("delay", self.delay)
            self.priority = data.get("priority", self.priority)
            kind = flow_media_kind(data)
            if kind is None:
                self._kind_valid = False
                log(f"Invalid media kind in '{self._filename}': expected movie, tv or both.", level="WARNING")
            else:
                self.kind = kind
                self.run_kind = run_kinds(kind)[0]
            self._apply_settings(data)
            enabled = data.get("enabled", True)
            if isinstance(enabled, bool):
                self.enabled = enabled
            else:
                self.enabled = False
                self._enabled_valid = False
                log(
                    f"Invalid 'enabled' value in '{self._filename}': "
                    "expected a YAML boolean.", level="WARNING"
                )

    def _apply_settings(self, data: dict) -> None:
        """Take the flow settings; an invalid value stops the flow (fail closed)."""
        self.settings = {}
        for flow_key, setting in FLOW_SETTINGS.items():
            value = data.get(flow_key)
            if value is None or value == '' or value == []:
                continue
            if issues := validate_value(setting.field, value, (flow_key,)):
                self._settings_valid = False
                log(f"Invalid '{flow_key}' in '{self._filename}': {issues[0].message}", level="WARNING")
                continue
            self.settings[flow_key] = value

    def _validate_flow(self) -> bool:
        self._parse_file()
        if not self._enabled_valid or not self._kind_valid or not self._settings_valid:
            return False
        if not isinstance(self.steps, list) or not self.steps:
            log(f"Flow steps are missing or invalid in '{self._filename}'.", level="WARNING")
            return False
        for step in self.steps:
            if not isinstance(step, dict):
                log(f"Invalid step definition: {step}. Expected a dictionary.", level="WARNING")
                return False
            name = step.get("name")
            if not step.get("module") or not step.get("action"):
                log(
                    f"Invalid step definition: '{name or step}' missing 'module' or 'action'.",
                    level="WARNING"
                )
                return False
        return True
