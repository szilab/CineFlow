"""Jellyfin module for collecting and searching media data from Jellyfin server."""

from bases.abs import ModuleBase
from bases.enums import MediaType
from bases.utils import st
from system.config import cfg
from system.database import Database as db
from system.logger import log


class JellyfinModule(ModuleBase):
    """Jellyfin module for collecting and searching media data from Jellyfin server."""

    def __init__(self, media_type: MediaType):
        self._name = "Jellyfin"
        self._type = media_type.value
        self._ready = self._is_required_config_set(
            names=['key', 'url', 'libraries', 'user'],
            category='jellyfin'
        )
        self._req = self._init(
            url=cfg(name='url', category='jellyfin')
        )
        if self._ready:
            self._favs = []
            self._user_id = self._get_user_id()
            self._library_id = self._get_library_id(cfg(name='libraries', category='jellyfin'))

    def collect(self):
        """Collect existing items from Jellyfin server."""
        data = self._collect(in_library=True)
        self._favs = self._favorites()
        log(f"Collected {len(data)} existing {self._type}s from {self._name}")
        for metadata in data:
            self._to_db(metadata, collected=True)

    def search(self):
        """Search for items in Jellyfin server."""
        all_db = db().get_all(self._type)
        all_items = self._collect(in_library=False)
        lib_items_ids = [item.get('Id') for item in self._collect(in_library=True)]
        items = [item for item in all_items if item.get('Id') not in lib_items_ids]
        for db_item in all_db:
            metadata = self._search(
                in_data=items,
                title=db_item['title'],
                year=db_item['year'],
                aliases=db_item['aliases']
            )
            if metadata:
                self._to_db(metadata, collected=False)

    def _collect(self, in_library: bool = True) -> list:
        params = {
            "ApiKey": cfg(name='key', category='jellyfin'),
            "fields": "OriginalTitle,ParentId",
            "Recursive": "true",
            "includeItemTypes": self._type
        }
        if in_library:
            params["ParentId"] = self._library_id
        response = self._req.get(
            endpoint="Items",
            params=params,
            key="Items"
        )
        return response.data

    def _search(self, in_data: list, title: str, year: str, aliases: str = '') -> dict:
        def _is_in_title(key, title, aliases):
            return (
                st(data.get(key)) == st(title)
                or
                st(data.get(key)) + ',' in st(aliases)
            )

        for data in in_data:
            if str(data.get('ProductionYear')) == year:
                if _is_in_title('Name', title, aliases):
                    return data
                if _is_in_title('OriginalTitle', title, aliases):
                    return data
        return None

    def _to_db(self, metadata: dict, collected: bool):
        db().add(
            table=self._type,
            title=st(metadata.get('OriginalTitle')),
            year=metadata.get('ProductionYear'),
            alias=st(self._media_alias(metadata)),
            favorite=str(self._media_favorite(metadata)).lower() if collected else "false",
            collected=str(collected).lower(),
        )

    def _media_favorite(self, metadata: dict) -> bool:
        return metadata.get('Id') in self._favs

    def _media_alias(self, metadata: dict) -> str:
        return metadata.get('Name') if metadata.get('Name') != metadata.get('OriginalTitle') else ""

    def _favorites(self) -> list:
        response = self._req.get(
            endpoint=f"Users/{self._user_id}/Items",
            params={
                "ApiKey": cfg(name='key', category='jellyfin'),
                "IsFavorite": "true",
                "Recursive": "true",
                "includeItemTypes": self._type
            },
            key="Items"
        )
        return [item.get('Id') for item in response.data or []]

    def _get_user_id(self):
        response = self._req.get(
            endpoint="Users",
            params={"ApiKey": cfg(name='key', category='jellyfin')}
        )
        for user in response.data or []:
            if user.get("Name") == cfg(name='user', category='jellyfin'):
                return user.get("Id")
        log(
            "Failed to get UserId for user 'JELLYFIN_USER', "
            "Jellyfin related functions may not work.",
            level="WARNING"
        )
        self._ready = False
        return None

    def _get_library_id(self, libraries: str) -> bool:
        response = self._req.get(
            endpoint="Library/MediaFolders",
            params={"ApiKey": cfg(name='key', category='jellyfin')},
            key="Items"
        )
        resp_names = []
        for lib in response.data or []:
            if lib.get("CollectionType") == f"{self._type}s":
                resp_names.append(lib.get("Name"))
        for library in libraries.split(","):
            if library in resp_names:
                return [lib.get("Id") for lib in response.data if lib.get("Name") == library][0]
        log(
            "Failed to get LibraryId for library ID from 'JELLYFIN_LIBRARIES', "
            "Jellyfin related functions may not work.",
            level="WARNING"
        )
        self._ready = False
        return None
