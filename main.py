
from system.config import cfg
from system.logger import log
from handlers.library import LibraryHandler
from system.misc import list_modules


def main():
    for i, lib in enumerate(cfg('libraries')):
        # Check if library configuration has path
        if not lib.get('path'):
            log(f"Library '{i}' incorrect 'path' node missing", level='ERROR')
            continue
        # Check if library configurations has modules
        log(f"Start operations for library '{lib.get('path')}'")
        library_handler = LibraryHandler(
            path=lib.get('path'),
            limit=lib.get('limit', 30),
            retention=lib.get('retention', 90),
            type=lib.get('type', 'movie')
        )
        # Run all modules
        all_modules = list_modules()
        for action in lib.get('modules', []):
            # Check if action is in the format 'module.task'
            if '.' not in action:
                log("Action must be in the format 'module.task' and should exists", level='ERROR')
                break
            # Split action into module and task
            name = action.split('.')[0]
            task = action.split('.')[1]
            module = [m for m in all_modules if m.name == name]
            # Check if module exists
            if not module:
                log(f"Module '{name}' not found", level='WARNING')
            # Check if module has task and run task
            module = module[0]
            if hasattr(module, task):
                log(f"Execute task '{task}' for module '{name}'")
                class_instance = module(library_handler=library_handler)
                class_function = getattr(class_instance, task, None)
                class_function()
            else:
                log(f"Module '{module}' has no task '{task}'", level='ERROR')
        # Cleanup library
        log(f"Cleanup library '{lib.get('path')}'")
        library_handler.cleanup()


if __name__ == "__main__":
    main()
