"""This module provides a class to handle directories."""

from typing import List, Dict
from PIL import Image
from cineflow.core.logger import log
from cineflow.utils.misc import evaluate, fix_imdbid, search_preference_score
from cineflow.utils.image import ImageHandler
from cineflow.core.bases.module import LibraryBase
from cineflow.core.schema import (
    ModuleDefinition, ActionDefinition, Field, KIND, SEARCH_PREFERENCE, INPUT_DATA, INPUT_NONE,
)


class Library(LibraryBase):
    """
    Module to handle media library.

    Configuration:
        - directory: library directory inside EXPORT_DIRECTORY (required)
        - limit: number of maximum items in library (default: 500, minimum: 10)
        - age: maximum age of items in library in days (default: 120, minimum: 30)
        - search_preference: release name preferences used to rank releases (optional)
        - kind: 'movie' (default) or 'tv'; series get a 'Season NN' folder

    Functions:
        - get: list the media in the library
        - put: import media to the library
        - remove: remove media from the library

    Items exceeding the limits are removed by a background cleanup worker.
    """

    DEFINITION = ModuleDefinition(
        id='library', label='Library', category='internal',
        description="Exported placeholder library that a media server can scan.",
        fields=(
            Field('directory', 'path', 'Directory', "Library folder inside EXPORT_DIRECTORY.",
                  required=True, step=True),
            Field('limit', 'integer', 'Item limit', "Maximum number of items kept.",
                  default=500, minimum=10, step=True),
            Field('age', 'integer', 'Maximum age (days)', "Older items are removed.",
                  default=120, minimum=30, step=True),
            KIND, SEARCH_PREFERENCE,
            Field('rules', 'list', 'Poster rules',
                  "Poster modification rules (list of mappings).", advanced=True),
        ),
        actions=(
            ActionDefinition('get', 'Get library items', "List the exported items.",
                             input=INPUT_NONE, retrieval=True),
            ActionDefinition('put', 'Export to library', "Export items with posters to the library.",
                             input=INPUT_DATA, side_effects=True),
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
        if not self.cfg('rules'):
            log("No modification rules to apply to the library images.")
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
                img.apply_from_rule(rule=rule)
        return img
