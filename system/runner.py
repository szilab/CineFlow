"""Flow Runner"""

import os
from typing import Any
import inspect
import yaml
from bases.module import ModuleBase
from system.logger import log
from system.misc import load_module


class FlowManager():
    """Flow Runner class to manage the execution of tasks."""

    def __init__(self) -> None:
        """Initialize the task runner."""
        self._dir = os.environ.get("CFG_DIRECTORY" ,"/config")
        self._files = []
        for file in os.listdir(self._dir):
            if not os.path.isdir(file) and (file.endswith('.yaml') or file.endswith('.yml')):
                self._files.append(os.path.join(self._dir, file))
                self._parse(file=file)
            else:
                log(f"Skipping non-YAML file: {file}")

    def _parse(self, file: str) -> None:
        with open(os.path.join(self._dir, file), 'r', encoding='UTF-8') as stream:
            try:
                data = yaml.safe_load(stream)
                if data and isinstance(data, dict) and data.get("steps"):
                    log(f"Execute flow: '{data.get("name", file)}'", level="INFO")
                    Flow(flow_data=data)
                else:
                    log(f"Invalid flow '{file}': Bad formating or missing 'steps'.", level="ERROR")
            except yaml.YAMLError as exc:
                log(f"Error loading flow file '{file}': {exc}", level="ERROR")


class Flow():
    """Class to manage the execution of a flow."""

    def __init__(self, flow_data: dict) -> None:
        """Initialize the task runner."""
        self._name = flow_data.get("name")
        self._steps = flow_data.get("steps")
        self._mod_cache = {}
        self._outputs = {}
        if self.validate():
            self.run()

    def validate(self) -> bool:
        """Validate the flow data."""
        if not isinstance(self._steps, list):
            log("Flow steps are missing or invalid.", level="ERROR")
            return False
        for step in self._steps:
            if not isinstance(step, dict):
                log(f"Invalid step definition: {step}. Expected a dictionary.", level="ERROR")
                return False
            name = step.get("name")
            if not step.get("module") or not step.get("action"):
                log(
                    f"Invalid step definition: '{name or step}' missing 'module' or 'action'.",
                    level="ERROR"
                )
                return False
        return True

    def run(self) -> None:
        """Run the flow."""
        for step in self._steps:
            log(f"Start step '{step.get('name')}'", level="MSG")
            outp = None
            # try:
            if not (inst := self._load_module(step=step)):
                return
            if not (action := self._load_action(inst=inst, step=step)):
                return
            if not (inp := self._load_input(step=step)):
                log(f"No input data for step '{step.get('name')}'.")
            outp = self._call_action(action=action, inp=inp)
            # except (ValueError, TypeError) as exc:
            #     log(f"Stop flow, error calling action '{step}': {exc}", level="ERROR")
            #     # log (f"Parameters: {inp}")
            #     return
            # if outp:
            if step.get("name"):
                self._outputs[step.get("name")] = outp
            self._outputs['latest'] = outp
            log(f"Step '{step.get('name')}' executed successfully.", level="MSG")
        log(f"Flow '{self._name}' executed successfully.", level="INFO")

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
        elif len(params) == 1:
            return action(inp)
        return action(**inp)
