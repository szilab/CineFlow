"""Jackett module for collecting and searching items from Jackett API."""

import re
from typing import Any
from bases.abs import ModuleBase
from bases.utils import st
from bases.utils import sort_data
from bases.enums import MediaType
from system.config import Config
from system.database import Database as db
from system.logger import log


class JackettModule(ModuleBase):
    """Jackett module for collecting and searching items from Jackett API."""

    def __init__(self, media_type: MediaType):
        self._name = "Jackett"
        self._type = media_type.value
        self._limit = 5
        self._ready = self._is_required_config_set(['JACKETT_URL', 'JACKETT_KEY'])
        self._default_categories = '2000' if self._type == MediaType.MOVIE else '5000'
        self._categories = Config().jacket_categories or self._default_categories
        self._req = self._init(
            url=Config().jacket_url + "/api/v2.0/indexers/all"
        )

    def collect(self) -> list:
        """Collect popular items from Jackett API."""
        data = self._collect()
        log(f"Collected {len(data)} popular {self._type}s from {self._name}")
        for metadata in data:
            self._to_db(metadata)

    def search(self):
        """Search for items in Jackett API."""
        all_rows = db().get_all(self._type)
        for item in all_rows:
            if metadata := self._search(title=item['title'], year=item['year']):
                self._to_db(metadata)

    def _search(self, title: str, year: str) -> Any:
        query = f"{title} {year} {Config().jacket_include}".strip()
        results = self._req.get(
            endpoint="results",
            params={"apikey": Config().jacket_key, "Category[]": self._categories, "Query": query},
            key="Results"
        )
        result = sort_data(data=results.data, param="Seeders", reverse=True)
        if title:
            for item in result:
                if st(title) in st(item.get('Title')) and year in item.get('Title'):
                    return item
                else:
                    log(f"Could not find '{title} ({year})' with Jackett", level='DEBUG')
                    return None
        return result

    def _collect(self):
        return self._search(title="", year="")[:self._limit]

    def _to_db(self, metadata: dict):
        if self._media_title(metadata) and self._media_year(metadata):
            db().add(
                table=self._type,
                title=st(self._media_title(metadata)),
                year=self._media_year(metadata),
                alias=st(self._media_alias(metadata)),
                seeds=metadata.get('Seeders'),
                link=metadata.get('Link'),
                torrent=metadata.get('Title'),
            )

    def _title_groups(self, metadata: dict) -> None:
        result = re.search(r'(.+)\.([12]\d\d\d)\.', metadata.get('Title'))
        if not result or len(groups := result.groups()) < 2:
            return None
        return groups

    def _media_title(self, metadata: dict) -> None:
        if group := self._title_groups(metadata):
            return group[0].replace('.', ' ').strip()
        return None

    def _media_year(self, metadata: dict) -> None:
        if group := self._title_groups(metadata):
            return group[1]
        return None

    def _media_alias(self, metadata: dict) -> None:
        desc = metadata.get('Description')
        desc = desc.split('[')[0].strip() if '[' in desc else desc
        if desc:
            return desc
        return None
