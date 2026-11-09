"""This module provides a class to handle directories."""

from dataclasses import fields
from typing import List, Dict
from PIL import Image
from cineflow.core.logger import log
from cineflow.utils.misc import evaluate, fix_imdbid, sanitize_name, search_preference_score
from cineflow.utils.image import ImageHandler, KnownColors
from cineflow.core.bases.module import LibraryBase
from cineflow.runtime import EXPORT_ENVIRONMENT
from cineflow.core.schema import (
    ModuleDefinition, ActionDefinition, Field, INPUT_DATA, INPUT_NONE, ITEM_FIELDS, MUST_MATCH,
)

POSTER_RULE = (
    Field('property', 'select', 'Field', options=ITEM_FIELDS, required=True),
    Field('expression', 'select', 'Match',
          options=('token', 'contains', 'eq', 'ne', 'gt', 'lt', 'exists', 'missing'),
          option_labels=('has word', 'contains', 'equals', 'not equals', 'greater than', 'less than',
                         'exists', 'missing'), default='exists'),
    Field('value', 'string', 'Value', "Not needed for exists and missing."),
    Field('case_sensitive', 'boolean', 'Case sensitive', default=True, hidden=True),
    Field('modification', 'select', 'Change', options=('border', 'triangle', 'grayscale'),
          option_labels=('border', 'corner', 'black and white'), default='border'),
    Field('color', 'select', 'Color', "Of the border or the corner.",
          options=tuple(f.name for f in fields(KnownColors)), default='red'),
    Field('position', 'select', 'Corner', options=('top-left', 'top-right', 'bottom-left', 'bottom-right'),
          option_labels=('top left', 'top right', 'bottom left', 'bottom right'), default='top-right'),
)
POSTER_RULES = Field(
    'poster_rules', 'list', 'Poster rules',
    "Change the posters of the items that match: a colored border or corner, or black and white. "
    "Every matching rule applies, in order.",
    item_type='object', item_fields=POSTER_RULE, item_label='Rule',
)


class Library(LibraryBase):
    """
    Module to handle media library.

    Configuration:
        - export_directory: root of the library folders (default: <CINEFLOW_HOME>/library);
          the EXPORT_DIRECTORY environment variable overrides it
        - limit: number of maximum items in library (default: 500, minimum: 10)
        - age: maximum age of items in library in days (default: 120, minimum: 30)

    Given by the 'put' step:
        - poster_rules: poster changes (border, corner, black and white) of matching items

    Given by the flow:
        - directory: library folder inside the export directory (flow ``library_directory``,
          default: the media kind)
        - search_preference: release name preferences used to rank releases
        - kind: 'movie' (default) or 'tv'; series get a 'Season NN' folder

    Functions:
        - get: list the media in the library
        - enrich: add the stored data of the matching library items to the items
        - put: import media to the library
        - remove: remove media from the library

    Items exceeding the limits are removed by a background cleanup worker.
    """

    DEFINITION = ModuleDefinition(
        id='library', label='Library', category='internal',
        description="Exported placeholder library that a media server can scan.",
        fields=(
            Field('export_directory', 'string', 'Export directory',
                  "Folder of the exported libraries that the media server scans; every flow creates its "
                  "library folder inside it. Empty: the library folder of the application data.",
                  env=EXPORT_ENVIRONMENT),
            Field('limit', 'integer', 'Item limit', "Maximum number of items kept.",
                  default=500, minimum=10, step=True),
            Field('age', 'integer', 'Maximum age (days)', "Older items are removed.",
                  default=120, minimum=30, step=True),
        ),
        actions=(
            ActionDefinition('get', 'Get library items', "List the exported items.",
                             input=INPUT_NONE, retrieval=True),
            ActionDefinition('enrich', 'Enrich with Library',
                             "Add the data stored with the matching library item (data.json) to each item.",
                             input=INPUT_DATA, fields=(MUST_MATCH,)),
            ActionDefinition('put', 'Export to library', "Export items with posters to the library.",
                             input=INPUT_DATA, side_effects=True, fields=(POSTER_RULES,)),
            ActionDefinition('remove', 'Remove from library', "Delete the items from the library.",
                             input=INPUT_DATA, output='none', destructive=True),
        ),
    )

    def __init__(self, config: dict = None) -> None:
        """Initialize the library module."""
        super().__init__(config=config, required=['directory'])
        self.mappings = {
            'directory': ['directory'],
            'title': ['title'],
            'year': ['year'],
            'tmdbid': ['tmdbid'],
            'imdbid': ['imdbid'],
            'season': ['season'],
        }
        self.transforms = {
            'tmdbid': lambda x: int(x) if x else None,
            'imdbid': fix_imdbid,
        }

    def get(self) -> List[Dict]:
        """Get the list of items in the library."""
        results = []
        directories = self._handler.all()
        for directory in directories:
            if not self._valid_item_name(directory.name):
                log(f"Item '{directory.name}' does not have a valid name format.", level='WARNING')
                continue
            media = self._handler.imprt(item=directory.name)
            if not media or not media.get('title') or (self.kind != 'tv' and not media.get('year')):
                log(f"Item '{directory.name}' not found in library.", level='WARNING')
                results.append({'directory': directory.name})
            else:
                results.append(media)
        log(f"Items in library: '{len(results)}'")
        data = []
        for item in results:
            mapped_item = self.map(item=item)
            if mapped_item:
                data.append(mapped_item)
        return data

    def enrich(self, data: List[Dict]) -> List[Dict]:
        """Add the stored data of the matching library item to each item; its own values win.

        Items match by TMDb or IMDb ID, else by title (or alternate title) and
        year; a series without a known year matches by title. Items without a
        match pass on unchanged, or are dropped with ``must_match``.
        """
        stored = []
        for directory in self._handler.all():
            if self._valid_item_name(directory.name) and (media := self._handler.imprt(item=directory.name)):
                stored.append({**media, 'directory': directory.name})
        result = []
        for media in data or []:
            if match := self._stored_match(items=stored, media=media):
                for key, value in match.items():
                    media.setdefault(key, value)
                log(f"Item '{media.get('title')}' ({media.get('year')}) extended from the library.")
            elif self.cfg('must_match', default=False):
                log(f"Item '{media.get('title')}' ({media.get('year')}) not in the library, dropped.", level='MSG')
                continue
            result.append(media)
        return result

    def _stored_match(self, items: List[Dict], media: dict) -> Dict | None:
        """Return the stored item of the same identity, else of the same title and year."""
        if match := next((item for item in items if self._same_identity(first=item, second=media)), None):
            return match
        titles = {sanitize_name(media.get(key)).lower() for key in ('title', 'alttitle')} - {''}
        for item in items:
            if sanitize_name(item.get('title')).lower() not in titles:
                continue
            year_unknown = self.kind == 'tv' and not (item.get('year') and media.get('year'))
            if year_unknown or str(item.get('year')) == str(media.get('year')):
                return item
        return None

    def put(self, data: List[Dict]) -> List[Dict]:
        """Import the media to the library."""
        for media in data or []:
            item = self._item_name(media=media)
            existing = None
            if matching_items := self._matching_items(media=media):
                existing = self._preferred_item(items=matching_items)
                item = existing['directory']
            elif self._handler.exists(item=item):
                existing = self._handler.imprt(item=item)
            if existing:
                preferences = self.cfg('search_preference', default=[])
                current_score = search_preference_score(
                    existing.get('torrent'), preferences,
                )
                candidate_score = search_preference_score(
                    media.get('torrent'), preferences,
                )
                if candidate_score <= current_score:
                    log(
                        f"Item '{item}' already has an equal or better release "
                        f"({current_score} >= {candidate_score}), skipping export.")
                    continue
            if media.get('poster'):
                image = self._create_poster(media=media)
                export_media = {**media, 'directory': item}
                if self._handler.publish(
                    item=item,
                    media=export_media,
                    image=image,
                    resolution=media.get('resolution'),
                    kind=self.kind,
                ):
                    media['directory'] = item
            else:
                log(f"Item '{media['title']}' has no poster, skipped.", level='WARNING')
        return data

    def remove(self, data: List[Dict]) -> None:
        """Remove the media from the library."""
        for media in data or []:
            item = self._item_name(media=media)
            if self._handler.exists(item=item):
                self._handler.remove(item=item)
            try:
                item = self._item_name(media=media, key='alttitle')
                if self._handler.exists(item=item):
                    self._handler.remove(item=item)
            except KeyError:
                pass

    def _item_name(self, media: dict, key: str = 'title') -> str:
        """Generate a library item name for the media."""
        name = media[key]
        # series parsed from release names may have no year
        if media.get('year') or self.kind != 'tv':
            name += " (" + str(media['year']) + ")"
        if media.get('tmdbid'):
            name += f" [tmdbid-{media['tmdbid']}]"
        return name

    def _valid_item_name(self, name: str) -> bool:
        """Return whether a directory name looks like an exported item."""
        if '(' in name and ')' in name:
            return True
        return self.kind == 'tv' and '[tmdbid-' in name and name.endswith(']')

    def _matching_items(self, media: dict) -> List[Dict]:
        """Find existing records with the same TMDb or IMDb identity."""
        matches = []
        for directory in self._handler.all():
            existing = self._handler.imprt(item=directory.name)
            if existing and self._same_identity(first=existing, second=media):
                matches.append({**existing, 'directory': directory.name})
        return matches

    @staticmethod
    def _same_identity(first: dict, second: dict) -> bool:
        """Return whether two records share a TMDb or IMDb identifier."""
        for key in ('tmdbid', 'imdbid'):
            if first.get(key) and second.get(key) and str(first[key]) == str(second[key]):
                return True
        return False

    def _preferred_item(self, items: List[Dict]) -> Dict:
        """Choose the highest-ranked release with a stable tie breaker."""
        preferences = self.cfg('search_preference', default=[])
        return max(
            items,
            key=lambda item: (
                search_preference_score(item.get('torrent'), preferences),
                item.get('directory', ''),
            ),
        )

    def _create_poster(self, media: dict) -> Image.Image:
        """Create a poster for the item."""
        img = ImageHandler(url=media.get('poster'))
        if not img:
            log(f"Failed to load image for item '{media['title']}'.")
            return None
        rules = self.cfg('poster_rules')
        if not rules:
            return img
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get('property'):
                log(f"Invalid poster rule: {rule}", level='WARNING')
                continue
            value = media.get(rule.get('property'))
            if evaluate(
                # numbers such as seeders are compared as text digits
                left=None if value is None else str(value),
                right=None if rule.get('value') is None else str(rule.get('value')),
                expression=rule.get('expression', 'exists'),
                wcase=rule.get('case_sensitive', True)
            ):
                img.apply_from_rule(rule={'modification': 'border', **rule})
        return img
        for rule in self.cfg('rules'):
            if not isinstance(rule, dict) or not rule.get('property'):
                log(f"Invalid library modification: {rule}", level='WARNING')
                continue
            if evaluate(
                left=media.get(rule.get('property')),
                right=rule.get('value'),
                expression=rule.get('expression', 'exists'),
                wcase=rule.get('case_sensitive', True)
            ):
                img.apply_from_rule(rule={'modification': 'border', **rule})
        return img
