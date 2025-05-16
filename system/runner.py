"""Workflow Runner"""

import os
import yaml
from bases.worker import WorkerBase
from system.logger import log
from system.misc import module


class FlowManager():
    """Workflow Runner class to manage the execution of tasks."""

    def __init__(self) -> None:
        """Initialize the task runner."""
        self._file = os.environ.get("CFG_DIRECTORY" ,"/config")
        yaml_files = [
            f for f in os.listdir(self._file) if f.endswith('.yaml') or f.endswith('.yml')
        ]
        if not yaml_files:
            log("No YAML files found in the configuration directory.", level="WARNING")
            return
        for file in yaml_files:
            log(f"Loading workflow file: '{file}'", level="INFO")
            with open(os.path.join(self._file, file), 'r', encoding='UTF-8') as stream:
                try:
                    data = yaml.safe_load(stream)
                    if data:
                        FlowRunner(data)
                except yaml.YAMLError as exc:
                    log(f"Error loading workflow file '{file}': {exc}", level="ERROR")

class FlowRunner(WorkerBase):
    """Workflow Runner class to manage the execution of tasks."""

    def __init__(self, data: dict) -> None:
        """Initialize the task runner."""
        super().__init__()
        self.data = data
        self.name = self.data.get("name", "unknown")
        if not self.data.get("modules"):
            log(f"No modules found in the workflow '{self.name}'.", level="WARNING")
            return
        self.start()

    def run(self):
        """Run the workflow."""
        log (f"Start workflow '{self.name}'", level="INFO")
        self._modules()
        log (f"End workflow '{self.name}'", level="INFO")

    def _modules(self) -> None:
        data = {}
        for index,item in enumerate(self.data.get("modules", [])):
            config = self._module_config(item=item)
            module_class = self._find_class(index=index, item=item)
            if module_class:
                instance = module_class(config=config)
                module_func = self._find_function(index=index, item=item, instance=instance)
                if module_func:
                    func_data = self._call_function(module_func=module_func, item=item, data=data)
                    if func_data:
                        data = func_data

    def _module_config(self, item: dict) -> dict:
        if not self.data.get("config", {}).get(item.get("name")):
            return {}
        if not isinstance(self.data.get("config", {}).get(item.get("name")), dict):
            return {}
        log(f"Module config '{item.get('name')}' loaded", level="DEBUG")
        return self.data.get("config", {}).get(item.get("name"))

    def _find_class(self, index: int, item: str) -> object:
        if not item.get("name"):
            log(f"Module name missing '{self.name} -> {index}'", level="WARNING")
            return None
        if not item.get("function"):
            log(f"Module function name missing '{self.name} -> {index}'", level="WARNING")
            return None
        if not (module_class := module(name=item.get("name"))):
            log(f"Module '{item.get('name')}' not found.", level="WARNING")
            return None
        log(f"Module '{item.get('name')}' loaded", level="DEBUG")
        return module_class

    def _find_function(self, index: int, item: str, instance: object) -> callable:
        module_func = getattr(instance, item.get("function"))
        if not module_func or not callable(module_func):
            log(f"Module function missing '{self.name} -> {index}'", level="WARNING")
            return None
        log(f"Module function '{item.get('function')}' loaded", level="DEBUG")
        return module_func

    def _call_function(self, module_func: callable, item: dict, data: dict) -> dict:
        kwargs = item.get("args", {})
        for key, value in kwargs.items():
            if isinstance(value, str):
                if value.startswith("@@"):
                    kwargs[key] = data
                elif value.startswith("@") and isinstance(data, dict):
                    kwargs[key] = data.get(value[1:], None)
                elif value.startswith("$"):
                    kwargs[key] = os.environ.get(value[1:], None)
                else:
                    log(f"Invalid argument '{key}' in module '{item.get('name')}'", level="WARNING")
        if item.get('mode') == "one-by-one":
            return [row for row in module_func(**kwargs)]
        return module_func(**kwargs)
