"""Declarative module, action and field definitions with structured validation.

Every workflow module declares a ``DEFINITION`` describing its configuration
fields and the actions it publishes. The GUI renders forms from these
definitions and the validator checks configuration and workflows against them,
so adding a module or action needs no frontend change.
"""

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

FIELD_TYPES = (
    'string', 'integer', 'number', 'boolean', 'select', 'url', 'path', 'secret', 'list', 'object',
)
# how an action consumes its step input
INPUT_NONE = 'none'      # takes no input
INPUT_DATA = 'data'      # takes the item list of earlier steps
INPUT_QUERY = 'query'    # takes an optional query
INPUT_BOTH = 'data+query'
INPUT_KINDS = (INPUT_NONE, INPUT_DATA, INPUT_QUERY, INPUT_BOTH)
# where an action belongs in the simple flow editor: sources collect items, enrich
# steps add data to them, a combine step merges several sources, filters drop
# items, and outputs change something outside CineFlow
STAGES = ('source', 'enrich', 'combine', 'filter', 'output')


@dataclass(frozen=True)
class Field:  # pylint: disable=too-many-instance-attributes
    """One configuration value of a module, action or query."""

    key: str
    type: str = 'string'
    label: str = ''
    description: str = ''
    required: bool = False
    default: Any = None
    options: tuple = ()
    # GUI text of each option, same order as ``options``; the option value when empty
    option_labels: tuple = ()
    minimum: float | None = None
    maximum: float | None = None
    # module fields a workflow step may override in its ``config``
    step: bool = False
    advanced: bool = False
    # accepted in YAML but never shown in the GUI
    hidden: bool = False
    # item type of a 'list': 'text' (words, edited as labels) or 'object' (mappings)
    item_type: str = 'text'
    # fields of every mapping of an 'object' list; the GUI edits each item as a card
    item_fields: tuple = ()
    # name of one item of such a list in the GUI, e.g. 'Condition'
    item_label: str = ''
    # the order of a list is a priority; the GUI numbers its items
    ordered: bool = False
    # name of a list of valid values the module reads from its service (see
    # ModuleBase.field_choices), e.g. 'libraries'; the GUI shows a dropdown
    choices: str = ''
    # boolean key the dropdown's "All" entry sets instead of this field, e.g. 'allUsers'
    all_key: str = ''
    # a text field that also takes a list of values (e.g. several libraries)
    multiple: bool = False
    # boolean query key that turns this selection into "everything except it",
    # e.g. 'isInverse'; the GUI shows All / Only / All except
    inverse_key: str = ''
    # environment variable that overrides this module setting; default <MODULE>_<KEY>
    env: str = ''

    def environment_name(self, module_id: str) -> str:
        """Return the environment variable that overrides this setting of a module."""
        return self.env or f"{module_id}_{self.key}".upper()

    def __post_init__(self) -> None:
        if self.type not in FIELD_TYPES:
            raise ValueError(f"Unknown field type '{self.type}' for '{self.key}'.")
        if self.type == 'select' and not self.options:
            raise ValueError(f"Select field '{self.key}' needs options.")
        if self.item_type not in ('text', 'object'):
            raise ValueError(f"Unknown list item type '{self.item_type}' for '{self.key}'.")

    def to_dict(self) -> dict:
        """Return the JSON-serializable field description."""
        return {
            'key': self.key,
            'type': self.type,
            'label': self.label or self.key.replace('_', ' ').capitalize(),
            'description': self.description,
            'required': self.required,
            'default': self.default,
            'options': list(self.options),
            'option_labels': list(self.option_labels),
            'minimum': self.minimum,
            'maximum': self.maximum,
            'step': self.step,
            'advanced': self.advanced,
            'hidden': self.hidden,
            'item_type': self.item_type,
            'item_fields': [item.to_dict() for item in self.item_fields],
            'item_label': self.item_label,
            'ordered': self.ordered,
            'choices': self.choices,
            'all_key': self.all_key,
            'multiple': self.multiple,
            'inverse_key': self.inverse_key,
            'env': self.env,
        }


@dataclass(frozen=True)
class ActionDefinition:  # pylint: disable=too-many-instance-attributes
    """One action a module publishes for workflow steps."""

    id: str
    label: str
    description: str = ''
    input: str = INPUT_NONE
    output: str = 'items'
    # step ``config`` keys that only make sense for this action
    fields: tuple[Field, ...] = ()
    # known keys of the structured ``query`` input
    query: tuple[Field, ...] = ()
    # other keyword arguments given next to ``data`` in a structured input
    arguments: tuple[Field, ...] = ()
    destructive: bool = False
    # changes state outside CineFlow (downloads, files); test runs skip it
    side_effects: bool = False
    # 'get' semantics: None output means retrieval failure and stops the flow
    retrieval: bool = False
    # stage in the simple flow editor; derived from the other values when empty
    stage: str = ''
    # module setting keys always shown on the step, with the module value as the
    # default and an override on the step (``config``)
    overrides: tuple[str, ...] = ()
    # works on the items alone without contacting the module's service, so it
    # is the same action in every module that publishes it
    local: bool = False

    def __post_init__(self) -> None:
        if self.input not in INPUT_KINDS:
            raise ValueError(f"Unknown input kind '{self.input}' for action '{self.id}'.")
        if self.stage and self.stage not in STAGES:
            raise ValueError(f"Unknown stage '{self.stage}' for action '{self.id}'.")

    @property
    def effective_stage(self) -> str:
        """Return the declared stage, or the one implied by the input and side effects."""
        if self.stage:
            return self.stage
        if self.side_effects or self.destructive:
            return 'output'
        if not self.takes_data:
            return 'source'
        return 'filter' if self.takes_query else 'enrich'

    @property
    def takes_data(self) -> bool:
        """Return whether the action consumes items of earlier steps."""
        return self.input in (INPUT_DATA, INPUT_BOTH)

    @property
    def takes_query(self) -> bool:
        """Return whether the action accepts a query."""
        return self.input in (INPUT_QUERY, INPUT_BOTH)

    def to_dict(self) -> dict:
        """Return the JSON-serializable action description."""
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
            'input': self.input,
            'output': self.output,
            'fields': [item.to_dict() for item in self.fields],
            'query': [item.to_dict() for item in self.query],
            'arguments': [item.to_dict() for item in self.arguments],
            'destructive': self.destructive,
            'side_effects': self.side_effects or self.destructive,
            'retrieval': self.retrieval,
            'stage': self.effective_stage,
            'local': self.local,
            'overrides': list(self.overrides),
        }


@dataclass(frozen=True)
class ModuleDefinition:  # pylint: disable=too-many-instance-attributes
    """Self-description of a workflow module."""

    id: str
    label: str
    description: str = ''
    category: str = 'integration'
    version: str = '1'
    fields: tuple[Field, ...] = ()
    actions: tuple[ActionDefinition, ...] = ()
    connection_test: bool = False

    def field(self, key: str) -> Field | None:
        """Return a module field by key."""
        return next((item for item in self.fields if item.key == key), None)

    def action(self, action_id: str) -> ActionDefinition | None:
        """Return an action by id."""
        return next((item for item in self.actions if item.id == action_id), None)

    @property
    def secret_keys(self) -> tuple[str, ...]:
        """Return the keys of sensitive fields."""
        return tuple(item.key for item in self.fields if item.type == 'secret')

    def to_dict(self) -> dict:
        """Return the JSON-serializable module description."""
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
            'category': self.category,
            'version': self.version,
            'fields': [item.to_dict() for item in self.fields],
            'actions': [item.to_dict() for item in self.actions],
            'connection_test': self.connection_test,
        }


@dataclass(frozen=True)
class Issue:
    """One validation finding, addressed by a path the GUI can highlight."""

    level: str      # 'error' or 'warning'
    path: tuple     # e.g. ('steps', 2, 'config', 'limit')
    message: str
    code: str = 'invalid'

    def to_dict(self) -> dict:
        """Return the JSON-serializable issue."""
        return {'level': self.level, 'path': list(self.path), 'message': self.message, 'code': self.code}

    def __str__(self) -> str:
        location = '.'.join(str(part) for part in self.path) or '<root>'
        return f"{self.level.upper()} {location}: {self.message}"


def error(path, message: str, code: str = 'invalid') -> Issue:
    """Return an error issue."""
    return Issue('error', tuple(path), message, code)


def warning(path, message: str, code: str = 'invalid') -> Issue:
    """Return a warning issue."""
    return Issue('warning', tuple(path), message, code)


def has_errors(issues: list[Issue]) -> bool:
    """Return whether any issue is an error."""
    return any(issue.level == 'error' for issue in issues)


def get_path(values: dict, key: str, default: Any = None) -> Any:
    """Return a value by dotted key, e.g. ``ignore.users``."""
    current = values
    for part in key.split('.'):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_value(spec: Field, value: Any, path: tuple) -> list[Issue]:  # noqa: C901
    """Validate one present, non-empty value against its field type and range."""
    if spec.multiple and isinstance(value, list):
        single = replace(spec, multiple=False)
        return [issue for index, item in enumerate(value) for issue in validate_value(single, item, (*path, index))]
    kind = spec.type
    if kind == 'boolean' and not isinstance(value, bool):
        return [error(path, "Expected true or false.", 'type')]
    if kind == 'integer' and (isinstance(value, bool) or not isinstance(value, int)):
        return [error(path, "Expected a whole number.", 'type')]
    if kind == 'number' and (isinstance(value, bool) or not isinstance(value, (int, float))):
        return [error(path, "Expected a number.", 'type')]
    if kind in ('string', 'secret', 'path', 'url') and not isinstance(value, (str, int, float)):
        return [error(path, "Expected text.", 'type')]
    if kind == 'list' and not isinstance(value, list):
        return [error(path, "Expected a list.", 'type')]
    if kind == 'list' and spec.item_fields:
        return [issue for index, item in enumerate(value)
                for issue in validate_fields(spec.item_fields, item, (*path, index))]
    if kind == 'object' and not isinstance(value, dict):
        return [error(path, "Expected a mapping.", 'type')]
    if kind == 'select' and value not in spec.options:
        options = ', '.join(str(option) for option in spec.options)
        return [error(path, f"Expected one of: {options}.", 'choice')]
    if kind == 'url':
        parts = urlsplit(str(value))
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            return [error(path, "Expected an http:// or https:// URL.", 'format')]
    if kind == 'path' and (Path(str(value)).is_absolute() or '..' in Path(str(value)).parts):
        return [error(path, "Expected a relative path inside the export directory.", 'format')]
    if kind in ('integer', 'number'):
        if spec.minimum is not None and value < spec.minimum:
            return [error(path, f"Must be at least {spec.minimum:g}.", 'range')]
        if spec.maximum is not None and value > spec.maximum:
            return [error(path, f"Must be at most {spec.maximum:g}.", 'range')]
    return []


def validate_fields(
    specs: tuple[Field, ...], values: Any, path: tuple = (), *,
    check_required: bool = True, allow_unknown: bool = True, env_prefix: str | None = None,
) -> list[Issue]:
    """Validate a configuration mapping against field definitions.

    ``env_prefix`` names the module whose environment variables (``<MODULE>_<KEY>``
    or ``Field.env``) may supply required values, matching the runtime precedence.
    """
    if values is None:
        values = {}
    if not isinstance(values, dict):
        return [error(path, "Expected a mapping.", 'type')]
    issues = []
    known = {spec.key.split('.')[0] for spec in specs}
    for spec in specs:
        value = get_path(values, spec.key)
        if _is_empty(value) or value == []:
            from_env = env_prefix and spec.environment_name(env_prefix) in os.environ
            if check_required and spec.required and not from_env:
                issues.append(error((*path, spec.key), f"'{spec.label or spec.key}' is required.", 'required'))
            continue
        issues.extend(validate_value(spec, value, (*path, spec.key)))
    if not allow_unknown:
        for key in values:
            if key not in known:
                issues.append(warning((*path, key), f"Unknown setting '{key}' is ignored by the GUI.", 'unknown'))
    return issues


def mask_secrets(definition: ModuleDefinition | None, values: dict) -> tuple[dict, list[str]]:
    """Return a copy without secret values and the keys of secrets that are set."""
    if not isinstance(values, dict):
        return {}, []
    secrets = set(definition.secret_keys if definition else ())
    masked = {key: value for key, value in values.items() if key not in secrets}
    present = sorted(key for key in secrets if not _is_empty(values.get(key)))
    return masked, present


MEDIA_KINDS = ('movie', 'tv')
DEFAULT_MEDIA_KIND = 'movie'
# a flow of kind 'both' runs once for every media kind
BOTH_KINDS = 'both'
FLOW_KINDS = (*MEDIA_KINDS, BOTH_KINDS)


def flow_media_kind(flow: Any) -> str | None:
    """Return the media kind of a flow (default movie), or None when it is invalid."""
    if not isinstance(flow, dict):
        return None
    kind = flow.get('kind') or DEFAULT_MEDIA_KIND
    return kind if kind in FLOW_KINDS else None


def run_kinds(kind: str) -> tuple[str, ...]:
    """Return the media kinds one run of a flow of ``kind`` covers, in run order."""
    return MEDIA_KINDS if kind == BOTH_KINDS else (kind,)


def is_secret_key(key: str) -> bool:
    """Return whether an undeclared setting name looks like a credential."""
    lowered = str(key).lower()
    return any(word in lowered for word in ('token', 'password', 'apikey', 'api_key', 'secret', 'passkey'))


# item fields offered by the condition editors (filter conditions, poster rules)
ITEM_FIELDS = (
    'title', 'alttitle', 'year', 'kind', 'tmdbid', 'imdbid', 'torrent', 'resolution',
    'seeders', 'size', 'season', 'episode', 'directory', 'percent_done',
)

# Fields shared by several modules
# safety cap of collecting actions; high enough that users never need to change it
LIMIT = Field('limit', 'integer', 'Limit', "Maximum number of collected items.", default=200, minimum=1,
              step=True, hidden=True)
SEARCH_PREFERENCE = Field(
    'search_preference', 'list', 'Release preference',
    "Release name words by priority: the first word decides, the next one only on a tie "
    "(a HUN release beats any release without HUN). Picks the torrent and decides whether a "
    "library item is replaced by a better release.", default=[], ordered=True,
)
LIBRARY_DIRECTORY = Field(
    'library_directory', 'path', 'Library folder',
    "Folder inside the export directory where library items are created. "
    "Default: the media kind (movie or tv).",
)


@dataclass(frozen=True)
class FlowSetting:
    """A flow setting the flow hands to the modules that use it."""

    field: Field
    module_key: str          # the module setting it fills
    modules: tuple           # module ids that receive it
    kind_default: bool = False  # when the flow sets no value, the media kind is the value


# flow key -> setting
FLOW_SETTINGS = {
    'library_directory': FlowSetting(LIBRARY_DIRECTORY, 'directory', ('library',), kind_default=True),
    'search_preference': FlowSetting(SEARCH_PREFERENCE, 'search_preference', ('jackett', 'library')),
}


MUST_MATCH = Field(
    'must_match', 'boolean', 'Must match',
    "Drop items that have no match instead of passing them on unchanged.", default=False,
)

# query keys shared by the media server modules
MEDIA_SERVER_QUERY = (
    Field('parentLibrary', 'string', 'Libraries',
          "All libraries, only the chosen ones, or all except them (e.g. the CineFlow libraries).",
          choices='libraries', multiple=True, inverse_key='isInverse'),
    Field('searchTerm', 'string', 'Search term', advanced=True),
    # set by the Libraries choice "All except"
    Field('isInverse', 'boolean', 'All except', "Return the library items outside the query.", hidden=True),
)


def consumer_actions(server: str, query: tuple[Field, ...] = ()) -> tuple[ActionDefinition, ...]:
    """Return the shared query, enrich and set actions of consumer modules."""
    return (
        ActionDefinition(
            'get', f'Get from {server}', f"Collect items from {server}.",
            input=INPUT_QUERY, query=query, retrieval=True,
        ),
        ActionDefinition(
            'enrich', f'Enrich with {server}', f"Add {server} data to each item.",
            input=INPUT_DATA, fields=(MUST_MATCH,),
        ),
        ActionDefinition(
            'unique', f'Not in {server}', f"Keep items that are missing from the {server} query.",
            input=INPUT_BOTH, query=query,
        ),
        ActionDefinition(
            'common', f'Also in {server}', f"Keep items that are also in the {server} query.",
            input=INPUT_BOTH, query=query,
        ),
        ActionDefinition(
            'exclude', 'Exclude by ID', "Drop items whose IMDb or TMDb ID is listed.",
            input=INPUT_BOTH, local=True, query=(
                Field('imdb_ids', 'list', 'IMDb IDs', "Numeric IMDb IDs to drop."),
                Field('tmdb_ids', 'list', 'TMDb IDs', "TMDb IDs to drop."),
            ),
        ),
    )


# download clients: give the downloads Jellyfin folder names
RENAME_FOLDERS = ActionDefinition(
    'rename', 'Name folders for Jellyfin',
    "Renames the folder of each added torrent to Title (year) [tmdbid-N], so Jellyfin recognizes it. "
    "Put a Wait step before it: a new torrent needs a few seconds to get its file list.",
    input=INPUT_DATA, side_effects=True,
    fields=(Field('suffix', 'string', 'Text after the name',
                  "Added after Title (year) [tmdbid-N]; {field} inserts a field of the item. "
                  "E.g. ' - {resolution}' gives 'Film (2020) [tmdbid-1] - 1080p'."),),
)


# query of the download clients' get, unique and common actions
TORRENT_QUERY = (
    Field('min_age', 'number', 'Added at least (hours) ago',
          "Only torrents added at least this many hours ago; 0 keeps every torrent. "
          "A torrent whose add time is unknown is left out.", default=0, minimum=0),
)
# download clients: remove and move the downloads
DELETE_TORRENTS = ActionDefinition(
    'delete', 'Remove torrents',
    "Removes the torrent of each item from the client. The downloaded files stay unless "
    "'Delete files' is on.",
    input=INPUT_DATA, destructive=True,
    fields=(Field('delete_files', 'boolean', 'Delete files',
                  "Also delete the downloaded data from the disk.", default=False),),
)
ADD_TORRENTS = ActionDefinition(
    'put', 'Add torrents', "Add the item release links to the client.",
    input=INPUT_DATA, side_effects=True,
    fields=(Field('kind_folder', 'boolean', 'Folder by media kind',
                  "Add the media kind (movie or tv) to the download directory, e.g. <directory>/tv. "
                  "Needs a download directory.", default=False),),
)
MOVE_TORRENTS = ActionDefinition(
    'move', 'Move torrents',
    "Moves the data of each item's torrent into a folder of the client's machine.",
    input=INPUT_DATA, side_effects=True,
    fields=(Field('location', 'string', 'Target folder', "Folder on the client's machine.", required=True),),
)
