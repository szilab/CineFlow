"""Flow Runner"""

import copy
import hashlib
import os
from pathlib import Path
from typing import Any
import inspect
import time
import yaml
from cineflow.core.config import cfg
from cineflow.core.bases.module import ModuleBase
from cineflow.core.bases.worker import WorkerBase
from cineflow.core.logger import log
from cineflow.utils.misc import load_module


class FlowManager(WorkerBase):
    """Flow Runner class to manage the execution of tasks."""

    def __init__(self) -> None:
        """Initialize the task runner."""
        super().__init__()
        try:
            self._delay = int(os.environ.get("FM_REFRESH_SEQ", os.environ.get("FM_RERESH_SEQ", 60)))
        except ValueError:
            log(
                "Invalid refresh sequence value in "
                "'FM_REFRESH_SEQ' or legacy 'FM_RERESH_SEQ', using default 60 minutes.",
                level="WARNING"
            )
            self._delay = 60
        self._dir = os.environ.get("CFG_DIRECTORY", "/config")
        self._flows = {}
        self._flow_hashes = {}
        self._next_due = {}
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

    def _manage_flows(self, files: list) -> None:
        """Add new flows and remove old ones."""
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
                (file, flow) for file, flow in self._flows.items()
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
        for flow in self._flows.values():
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

    def __init__(self, file: str) -> None:
        """Initialize the task runner."""
        super().__init__()
        self._file = file
        self._filename = os.path.basename(file)
        self.name = 'Unnamed Flow'
        self.steps = []
        self.priority = 99
        self.delay = 60
        self.enabled = True
        self._enabled_valid = True
        self._mod_cache = {}
        self._outputs = {}
        self._valid = self._validate_flow()
        if self._valid:
            log(f"Flow '{self._filename}' initialized.", level="INFO")

    def run(self) -> None:  # noqa: C901
        """Run the flow."""
        super().run()
        if not self._valid or not self.enabled:
            return
        self._outputs = {}
        log(f"Flow '{self.name}' from file '{self._filename}' started.", level="INFO")
        for step in self.steps:
            if self._stop_event.is_set():
                log(f"Flow '{self.name}' stopped before the next step.", level="INFO")
                return
            log(f"Start step '{step.get('name')}'", level="MSG")
            outp = None
            try:
                if not (inst := self._load_module(step=step)):
                    return
                if not (action := self._load_action(inst=inst, step=step)):
                    return
                if not (inp := self._load_input(step=step)):
                    log(f"No input data for step '{step.get('name')}'.")
                outp = self._call_action(action=action, inp=inp)
            except Exception as exc:
                log(f"Stop flow, error calling action '{step.get('name')}' -> {exc}", level="ERROR")
                return
            if outp is None and step.get("action") == "get":
                log(
                    f"Step '{step.get('name')}' failed to retrieve data. "
                    "Aborting flow to prevent logic errors.", level="ERROR")
                return
            if step.get("name"):
                self._outputs[step.get("name")] = outp
            self._outputs['latest'] = outp
            log(f"Step '{step.get('name')}' executed successfully.", level="MSG")
        log(f"Flow '{self.name}' executed successfully.", level="INFO")

    @property
    def valid(self) -> bool:
        """Return whether the parsed flow is runnable."""
        return self._valid

    def _load_module(self, step: dict) -> ModuleBase | None:
        """Load a module by its name."""
        name = step.get('module')
        config = step.get('config') or {}
        # Use a hash of the config to reuse instances with identical settings
        cache_key = f"{name}_{hash(str(config))}"

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
        if new_inp.get("data") == "previous":
            new_inp["data"] = self._outputs.get('latest')
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
        return action(**inp)

    def _parse_file(self) -> None:
        with open(self._file, 'r', encoding='UTF-8') as stream:
            try:
                data = yaml.safe_load(stream)
                if data and isinstance(data, dict) and data.get("steps"):
                    self.name = data.get("name", self.name)
                    self.steps = data.get("steps", self.steps)
                    self.delay = data.get("delay", self.delay)
                    self.priority = data.get("priority", self.priority)
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
            except yaml.YAMLError as exc:
                log(f"Error loading flow file '{self._filename}': {exc}", level="WARNING")

    def _validate_flow(self) -> bool:
        self._parse_file()
        if not self._enabled_valid:
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
