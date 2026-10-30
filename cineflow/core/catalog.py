"""Catalog of the workflow modules and their self-declared definitions."""

from cineflow.core.schema import ModuleDefinition


def module_ids() -> list[str]:
    """Return the workflow module names, integrations first."""
    from cineflow import integrations, internal  # pylint: disable=import-outside-toplevel

    return [*integrations.MODULES.values(), *internal.MODULES.values()]


def module_class(module_id: str):
    """Return the class of a workflow module, or None when it does not exist."""
    from cineflow.utils.misc import load_module  # pylint: disable=import-outside-toplevel

    if not isinstance(module_id, str) or module_id not in module_ids():
        return None
    return load_module(module_id)


def definition(module_id: str) -> ModuleDefinition | None:
    """Return the definition of a module, or None when it is unknown."""
    cls = module_class(module_id)
    return getattr(cls, 'DEFINITION', None) if cls else None


def definitions() -> dict[str, ModuleDefinition]:
    """Return every module definition by module id."""
    return {module_id: definition(module_id) for module_id in module_ids() if definition(module_id)}
