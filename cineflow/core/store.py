"""File persistence of flows and configuration for the GUI.

YAML files in ``CFG_DIRECTORY`` stay the source of truth, so flows edited in
the GUI and by hand are the same files and the existing runtime, hot reload
and Docker volume layout keep working. Every overwrite or delete first copies
the previous file to ``CFG_DIRECTORY/.backups``.
"""

import copy
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import yaml

from cineflow.core import catalog
from cineflow.core.schema import is_secret_key
from cineflow.runtime import config_directory

BACKUP_DIRECTORY = '.backups'
BACKUPS_KEPT = 20
CONFIG_FILE = 'config.yaml'
FLOW_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
FLOW_KEY_ORDER = ('name', 'description', 'version', 'enabled', 'delay', 'priority', 'steps')
STEP_KEY_ORDER = ('name', 'module', 'instance', 'action', 'input', 'config')


class StoreError(ValueError):
    """A requested flow or file operation is not possible."""


def backup_directory() -> Path:
    """Return the directory holding previous file versions."""
    return config_directory() / BACKUP_DIRECTORY


def backup(path: Path) -> Path | None:
    """Copy a file to the backup directory and prune old copies of it."""
    if not path.is_file():
        return None
    target_dir = backup_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    target = target_dir / f"{path.name}.{stamp}-{uuid4().hex[:6]}.bak"
    target.write_bytes(path.read_bytes())
    copies = sorted(target_dir.glob(f"{path.name}.*.bak"), key=lambda item: item.stat().st_mtime)
    for old in copies[:-BACKUPS_KEPT]:
        old.unlink(missing_ok=True)
    return target


def write_text(path: Path, text: str) -> None:
    """Back up and atomically replace a text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def flow_files() -> list[Path]:
    """Return the flow files, using the same rule as the flow manager."""
    directory = config_directory()
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.name != CONFIG_FILE and path.suffix in ('.yaml', '.yml')
    )


def flow_path(flow_id: str) -> Path:
    """Return the existing file of a flow id."""
    if not isinstance(flow_id, str) or not FLOW_ID.match(flow_id):
        raise StoreError(f"Invalid flow id '{flow_id}'.")
    for path in flow_files():
        if path.stem == flow_id:
            return path
    raise StoreError(f"Flow '{flow_id}' not found.")


def read_flow(flow_id: str) -> dict:
    """Return the parsed definition of a flow file."""
    return parse_flow_yaml(flow_path(flow_id).read_text(encoding='utf-8'))


def parse_flow_yaml(text: str) -> dict:
    """Parse flow YAML text into a mapping."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise StoreError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise StoreError("A flow file must contain a mapping.")
    return data


def _slug(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')
    return slug[:60] or 'flow'


def new_flow_id(name: str) -> str:
    """Return an unused flow id derived from a flow name."""
    base = _slug(name)
    taken = {path.stem for path in flow_files()}
    candidate, number = base, 2
    while candidate in taken or candidate == Path(CONFIG_FILE).stem:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


def _ordered(data: dict, order: tuple) -> dict:
    """Return a mapping with known keys first, in a stable order."""
    ordered = {key: data[key] for key in order if key in data}
    ordered.update({key: value for key, value in data.items() if key not in ordered})
    return ordered


def flow_yaml(flow: dict) -> str:
    """Serialize a flow in the hand-written YAML style."""
    flow = _ordered(flow, FLOW_KEY_ORDER)
    if isinstance(flow.get('steps'), list):
        flow['steps'] = [
            _ordered(step, STEP_KEY_ORDER) if isinstance(step, dict) else step for step in flow['steps']
        ]
    return yaml.safe_dump(flow, default_flow_style=False, allow_unicode=True, sort_keys=False)


def save_flow(flow: dict, flow_id: str | None = None) -> str:
    """Create or overwrite a flow file and return its id."""
    if flow_id is None:
        flow_id = new_flow_id(flow.get('name', 'flow'))
        path = config_directory() / f"{flow_id}.yaml"
    else:
        path = flow_path(flow_id)
    write_text(path, flow_yaml(flow))
    return flow_id


def delete_flow(flow_id: str) -> None:
    """Back up and delete a flow file."""
    path = flow_path(flow_id)
    backup(path)
    path.unlink()


def _secret_keys(module_id: str | None, values: dict) -> set:
    definition = catalog.definition(module_id) if module_id else None
    declared = set(definition.secret_keys) if definition else set()
    return {key for key in values if key in declared or is_secret_key(key)}


def mask(module_id: str | None, values: dict) -> tuple[dict, list[str]]:
    """Return settings without secret values, and the names of the secrets that are set."""
    if not isinstance(values, dict):
        return {}, []
    secrets = _secret_keys(module_id, values)
    masked = {key: copy.deepcopy(value) for key, value in values.items() if key not in secrets}
    return masked, sorted(key for key in secrets if values.get(key) not in (None, ''))


def restore_secrets(module_id: str | None, new: dict, old: dict) -> dict:
    """Keep stored secrets the client did not send; an empty string clears one."""
    merged = copy.deepcopy(new or {})
    for key in _secret_keys(module_id, old or {}):
        if key not in merged:
            merged[key] = old[key]
        elif merged[key] in (None, ''):
            del merged[key]
    return merged


def mask_flow(flow: dict) -> tuple[dict, dict]:
    """Return a flow without secret step settings, and the set secrets by step index."""
    flow = copy.deepcopy(flow)
    present = {}
    for index, step in enumerate(flow.get('steps') or []):
        if isinstance(step, dict) and isinstance(step.get('config'), dict):
            step['config'], keys = mask(step.get('module'), step['config'])
            if keys:
                present[index] = keys
    return flow, present


def restore_flow_secrets(new: dict, old: dict | None) -> dict:
    """Restore secret step settings of steps that kept their name and module."""
    new = copy.deepcopy(new)
    old_steps = {
        (step.get('name'), step.get('module')): step
        for step in (old or {}).get('steps') or [] if isinstance(step, dict)
    }
    for step in new.get('steps') or []:
        if not isinstance(step, dict):
            continue
        previous = old_steps.get((step.get('name'), step.get('module')))
        if previous and isinstance(previous.get('config'), dict):
            restored = restore_secrets(step.get('module'), step.get('config') or {}, previous['config'])
            if restored:
                step['config'] = restored
    return new


def mask_config(config: dict) -> dict:
    """Return the global configuration without any secret value, for export."""
    exported = {}
    for key, value in (config or {}).items():
        if key == 'instances' and isinstance(value, dict):
            exported[key] = {
                instance_id: {
                    **{k: v for k, v in instance.items() if k != 'config'},
                    'config': mask(instance.get('module'), instance.get('config') or {})[0],
                } if isinstance(instance, dict) else instance
                for instance_id, instance in value.items()
            }
        elif isinstance(value, dict):
            exported[key] = mask(key, value)[0]
        else:
            exported[key] = copy.deepcopy(value)
    return exported
