"""Flow Runner"""

import os
from typing import Any
import inspect
import yaml
from cineflow.bases.module import ModuleBase
from cineflow.bases.worker import WorkerBase
from cineflow.system.logger import log
from cineflow.system.misc import load_module


class FlowManager(WorkerBase):
    """Flow Runner class to manage the execution of tasks."""

    def __init__(self) -> None:
        """Initialize the task runner."""
        super().__init__()
        self._dir = os.environ.get("CFG_DIRECTORY", "/config")
        self._flows = {}
        if os.path.exists(self._dir):
            self.start()

    def run(self) -> None:
        """Run the flow manager."""
        files = []
        for file in os.listdir(self._dir):
            if os.path.isdir(file) or file == "config.yaml":
                continue
            if file.endswith('.yaml') or file.endswith('.yml'):
                files.append(os.path.join(self._dir, file))
            log(f"Skipping non-YAML file: {file}")
        if not files:
            log("No flow files found to run.", level="INFO")
            return
        # add new flows
        for file in files:
            if file not in self._flows:
                self._flows[file] = Flow(file)
        # remove deleted flows
        for key, flow in self._flows.items():
            if key not in files:
                log(f"Flow '{flow.name}' removed from the system.", level="INFO")
                self._flows.pop(key)
                del flow

    def close(self) -> None:
        """Close the flow manager."""
        for flow in self._flows.values():
            log(f"Stopping flow '{flow.name}'.", level="INFO")
            flow.stop()


class Flow(WorkerBase):  # pylint: disable=too-few-public-methods
    """Class to manage the execution of a flow."""

    def __init__(self, file: str) -> None:
        """Initialize the task runner."""
        super().__init__()
        self._file = file
        self._filename = os.path.basename(file)
        self.name = 'Unnamed Flow'
        self.steps = []
        self.delay = 60
        self._mod_cache = {}
        self._outputs = {}
        log(f"Flow '{self._filename}' initialized.", level="INFO")
        self.start()

    def run(self) -> None:
        """Run the flow."""
        super().run()
        if not self._validate_flow():
            return
        log(f"Flow '{self.name}' from file '{self._filename}' started.", level="INFO")
        for step in self.steps:
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
            except (ValueError, TypeError) as exc:
                log(f"Stop flow, error calling action '{step}': {exc}", level="ERROR")
                # log (f"Parameters: {inp}")
                return
            # if outp:
            if step.get("name"):
                self._outputs[step.get("name")] = outp
            self._outputs['latest'] = outp
            log(f"Step '{step.get('name')}' executed successfully.", level="MSG")
        log(f"Flow '{self.name}' executed successfully.", level="INFO")

    def _load_module(self, step: dict) -> ModuleBase | None:
        """Load a module by its name."""
        name = step.get('module')
        if name in self._mod_cache:
            mod = self._mod_cache[name]
        else:
            mod = load_module(name)
        if not mod:
            log(f"Module '{name}' not found, stop flow.", level="ERROR")
            return None
        if name not in self._mod_cache:
            self._mod_cache[name] = mod
        return mod(config=step.get("config"))

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

    def _load_input(self, step: dict) -> dict:
        """Load input data for the action."""
        inp = step.get("input")
        if not inp or inp == "none":
            return None
        if inp == "previous":
            return self._outputs.get('latest')
        if isinstance(inp, str):
            if str(inp).startswith("{{") and str(inp).endswith("}}"):
                if str(inp).strip("{}") in self._outputs:
                    return self._outputs[str(inp).strip("{}")]
        if isinstance(inp, dict):
            if inp.get("data") and inp.get("data") == "previous":
                inp["data"] = self._outputs.get('latest')
        return inp

    def _call_action(self, action: callable, inp: dict) -> Any:
        """Call the action with the provided input data."""
        params = inspect.signature(action).parameters
        if len(params) == 0:
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
            except yaml.YAMLError as exc:
                log(f"Error loading flow file '{self._filename}': {exc}", level="WARNING")

    def _validate_flow(self) -> bool:
        self._parse_file()
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
