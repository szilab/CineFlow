"""Data helpers: de-duplication, item filter, wait and debug export/import."""

import json
import time
from pathlib import Path
from typing import Any, List, Dict
from cineflow.core.logger import log
from cineflow.utils.misc import has_word
from cineflow.runtime import debug_directory
from cineflow.core.schema import (
    ModuleDefinition, ActionDefinition, Field, INPUT_BOTH, INPUT_DATA, INPUT_NONE, ITEM_FIELDS,
)

FILENAME = Field('filename', 'string', 'File name', "File in the debug folder of the application data.",
                 default='exported_data.json')
SECONDS = Field('seconds', 'integer', 'Seconds', "Time to wait before the next step.",
                default=10, minimum=1, maximum=300)
FILTER_FIELDS = ITEM_FIELDS
FILTER_MATCHES = ('equals', 'contains', 'has_word', 'at_least', 'at_most')
FILTER_CONDITION = (
    Field('field', 'select', 'Field', options=FILTER_FIELDS, required=True),
    Field('match', 'select', 'Match', options=FILTER_MATCHES,
          option_labels=('equals', 'contains', 'has word', 'at least', 'at most'), default='equals'),
    Field('value', 'string', 'Value', "A number for at least and at most.", required=True),
)
FILTER_QUERY = (
    Field('conditions', 'list', 'Conditions', item_type='object', item_fields=FILTER_CONDITION,
          item_label='Condition', required=True),
    Field('combine', 'select', 'Combine',
          "All: every condition must match. Any: one matching condition is enough.",
          options=('all', 'any'), option_labels=('all (and)', 'any (or)'), default='all'),
    Field('matching', 'select', 'Matching items',
          "Keep: only the matching items go on. Drop: the matching items are removed and the rest go on.",
          options=('keep', 'drop'), default='keep'),
    Field('kind', 'select', 'Media kind',
          "Which items the filter applies to. The other items go on unchanged, so one flow can "
          "filter movies and series differently.",
          options=('both', 'movie', 'tv'), option_labels=('Movies and TV', 'Movies', 'TV'), default='both'),
)


class Tools():  # pylint: disable=too-few-public-methods
    """Tools module class"""

    DEFINITION = ModuleDefinition(
        id='tools', label='Tools', category='internal',
        description="Data helpers: de-duplication, item filter, wait and debug export/import.",
        actions=(
            ActionDefinition('remove_duplicates', 'Remove duplicates',
                             "Drop items with an already seen IMDb ID, TMDb ID or title and year.",
                             input=INPUT_DATA, stage='combine'),
            ActionDefinition('filter_items', 'Filter by field',
                             "Keep or drop the items that match conditions on their fields "
                             "(equals, contains, has word, at least, at most).",
                             input=INPUT_BOTH, query=FILTER_QUERY, local=True),
            ActionDefinition('wait', 'Wait',
                             "Pass the items on after some seconds, e.g. until added torrents get "
                             "their metadata. No wait without items.",
                             input=INPUT_DATA, arguments=(SECONDS,), stage='output'),
            ActionDefinition('data_export', 'Export data', "Write the items to a JSON file.",
                             input=INPUT_DATA, output='none', arguments=(FILENAME,), side_effects=True),
            ActionDefinition('data_import', 'Import data', "Read items from a JSON file.",
                             input=INPUT_NONE, arguments=(FILENAME,)),
        ),
    )

    def __init__(self, config: dict = None) -> None:
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        self._cfg = config or {}

    def wait(self, data: List[Dict] = None, seconds: int = 10) -> List[Dict]:
        """Return the items after ``seconds`` (1-300); return at once without items."""
        if data:
            seconds = min(max(int(seconds), 1), 300)
            log(f"Waiting {seconds} seconds.")
            time.sleep(seconds)
        return data

    def data_export(self, data: List[Dict], filename: str = 'exported_data.json'):
        """Export data to a file"""
        full_path = debug_directory() / filename
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with full_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        log(f"Data exported to '{full_path}'.")

    def data_import(self, filename: str = 'exported_data.json') -> List[Dict]:
        """Import data from a file"""
        path = Path(filename)
        if not path.is_absolute():
            path = debug_directory() / path
        if not path.exists():
            log(f"File '{path}' not found.", level='WARNING')
            return []
        with path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        log(f"Data imported from '{path}'.")
        return data

    def filter_items(self, data: List[Dict], query: Any = None) -> List[Dict]:
        """Keep the items that match the conditions; ``matching: drop`` removes them instead.

        Every condition compares an item ``field`` with a ``value``: ``equals``,
        ``contains`` and ``has_word`` (a whole word, any character other than a
        letter or digit separates words) compare text without case, ``equals`` compares
        numbers by value, so ``year: 2024`` matches ``"2024"``; ``at_least`` and
        ``at_most`` compare numbers. An item without the field, or without a
        number for a number comparison, does not match the condition.
        ``combine: all`` (default) needs every condition, ``any`` one of them.
        ``kind: movie`` or ``kind: tv`` limits the filter to the items of that media
        kind (their ``kind`` field, else the kind of the flow pass); the other items
        go on unchanged. The default ``both`` filters every item.
        A filter without usable conditions keeps every item.
        """
        query = query if isinstance(query, dict) else {}
        conditions = query.get('conditions')
        conditions = [item for item in conditions if isinstance(item, dict)] if isinstance(conditions, list) else []
        if not conditions or any(not self._usable(condition) for condition in conditions):
            log("Filter has no or incomplete conditions, items are kept.", level='WARNING')
            return list(data or [])
        combine = any if query.get('combine') == 'any' else all
        drop = query.get('matching') == 'drop'
        kind = query.get('kind') if query.get('kind') in ('movie', 'tv') else None
        kept = [
            item for item in data or []
            if not self._in_scope(item, kind)
            or combine(self._matches(item.get(condition['field']), condition['value'],
                                     condition.get('match') or 'equals')
                       for condition in conditions) != drop
        ]
        text = f" {'or' if combine is any else 'and'} ".join(
            f"{condition['field']} {(condition.get('match') or 'equals').replace('_', ' ')} '{condition['value']}'"
            for condition in conditions)
        scope = f" for {kind} items" if kind else ""
        log(f"Filter {text} ({'drop' if drop else 'keep'}{scope}): {len(kept)} of {len(data or [])} items kept.")
        return kept

    def _in_scope(self, item: dict, kind: str | None) -> bool:
        """Return whether the filter applies to the item: any item, or one of the given media kind."""
        if kind is None:
            return True
        item_kind = item.get('kind') or self._cfg.get('kind')
        if isinstance(item_kind, (list, tuple)):
            return kind in item_kind
        return item_kind == kind

    @staticmethod
    def _usable(condition: dict) -> bool:
        """Return whether a condition names a field, a known match and a value."""
        value = condition.get('value')
        return (bool(condition.get('field')) and value is not None and str(value) != ''
                and (condition.get('match') or 'equals') in FILTER_MATCHES)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except ValueError:
            return None

    @classmethod
    def _matches(cls, actual: Any, value: Any, match: str) -> bool:
        """Return whether an item value matches the filter value."""
        if actual is None or actual == '':
            return False
        if isinstance(actual, (list, tuple)):
            actual = ' '.join(str(part) for part in actual)
        text, wanted = str(actual).strip().lower(), str(value).strip().lower()
        if match == 'has_word':
            return has_word(text, wanted, case_sensitive=False)
        if match == 'contains':
            return wanted in text
        number, limit = cls._number(text), cls._number(wanted)
        if match in ('at_least', 'at_most'):
            if number is None or limit is None:
                return False
            return number >= limit if match == 'at_least' else number <= limit
        if number is not None and limit is not None:
            return number == limit
        return text == wanted

    def remove_duplicates(self, data: List[Dict]):
        """Loop on data and filter out duplicates"""
        filtered = []
        imdbids = set()
        tmdbids = set()
        name_years = set()
        for item in data:
            imdbid = item.get('imdbid')
            if imdbid and imdbid in imdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('imdbid')}] is a duplicate.")
                continue
            tmdbid = item.get('tmdbid')
            if tmdbid and tmdbid in tmdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('tmdbid')}] is a duplicate.")
                continue
            title_year = (item.get('title'), item.get('year'))
            if all(title_year) and title_year in name_years:
                log(f"Item '{item.get('title')}' ({item.get('year')}) is a duplicate.")
                continue
            filtered.append(item)
            if imdbid:
                imdbids.add(imdbid)
            if tmdbid:
                tmdbids.add(tmdbid)
            if all(title_year):
                name_years.add(title_year)
        return filtered
