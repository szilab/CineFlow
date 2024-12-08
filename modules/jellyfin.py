from bases.abs import ModuleBase
from bases.enums import MediaType
from bases.utils import st
from system.config import Config
from system.database import Database as db
from system.logger import log


class JellyfinModule(ModuleBase):
    def __init__(self, type: MediaType):
        self._name = "Jellyfin"
        self._type = type.value
        self._ready = self._is_required_config_set(['JELLYFIN_KEY', 'JELLYFIN_LIBRARIES', 'JELLYFIN_USER'])
        self._req = self._init(
            url=Config().JELLYFIN_URL
        )
        if self._ready:
            self._user_id = self._get_user_id()
            self._library_id = self._get_library_id(Config().JELLYFIN_LIBRARIES)

    def collect(self):
        data = self._collect(in_library=True)
        self._favs = self._favorites()
        log(f"Collected {len(data)} existing {self._type}s from {self._name}")
        for metadata in data:
            self._to_db(metadata, collected=True)

    def search(self):
        all_db = db().get_all(self._type)
        all_items = self._collect(in_library=False)
        lib_items_ids = [item.get('Id') for item in self._collect(in_library=True)]
        items = [item for item in all_items if item.get('Id') not in lib_items_ids]
        for db_item in all_db:
            if metadata := self._search(in_data=items, title=db_item['title'], year=db_item['year'], aliases=db_item['aliases']):
                self._to_db(metadata, collected=False)

    def _collect(self, in_library: bool = True) -> list:
        params = {"ApiKey": Config().JELLYFIN_KEY, "fields": "OriginalTitle,ParentId", "Recursive": "true", "includeItemTypes": self._type}
        if in_library:
            params["ParentId"] = self._library_id
        response = self._req.get(
            endpoint="Items",
            params=params,
            key="Items"
        )
        return response.data

    def _search(self, in_data: list, title: str, year: str, aliases: str = '') -> dict:
        for data in in_data:
            if str(data.get('ProductionYear')) == year:
                if st(data.get('Name')) == st(title) or st(data.get('Name')) + ',' in st(aliases):
                    return data
                if st(data.get('OriginalTitle')) == st(title) or st(data.get('OriginalTitle')) + ',' in st(aliases):
                    return data
        return None

    def _to_db(self, metadata: dict, collected: bool):
        db().add(
            table=self._type,
            title=st(metadata.get('OriginalTitle')),
            year=metadata.get('ProductionYear'),
            alias=st(metadata.get('Name')) if metadata.get('Name') != metadata.get('OriginalTitle') else "",
            favorite=str(self._media_favorite(metadata)).lower() if collected else "false",
            collected=str(collected).lower(),
        )

    def _media_favorite(self, metadata: dict) -> bool:
        return metadata.get('Id') in self._favs

    def _favorites(self) -> list:
        response = self._req.get(
            endpoint=f"Users/{self._user_id}/Items",
            params={"ApiKey": Config().JELLYFIN_KEY, "IsFavorite": "true", "Recursive": "true", "includeItemTypes": self._type},
            key="Items"
        )
        return [item.get('Id') for item in response.data or []]

    def _get_user_id(self):
        response = self._req.get(endpoint="Users", params={"ApiKey": Config().JELLYFIN_KEY})
        for user in response.data or []:
                if user.get("Name") == Config().JELLYFIN_USER:
                    return user.get("Id")
        log(
            f"Failed to get UserId for user 'JELLYFIN_USER', "
            "Jellyfin related functions may not work.", level="WARNING"
        )
        self._ready = False
        return None

    def _get_library_id(self, libraries: str) -> bool:
        response = self._req.get(endpoint="Library/MediaFolders", params={"ApiKey": Config().JELLYFIN_KEY}, key="Items")
        resp_names = [lib.get("Name") for lib in response.data or [] if lib.get("CollectionType") == f"{self._type}s"]
        for library in libraries.split(","):
            if library in resp_names:
                return [lib.get("Id") for lib in response.data if lib.get("Name") == library][0]
        log(f"Failed to get LibraryId for library ID from 'JELLYFIN_LIBRARIES',"
            "Jellyfin related functions may not work.", level="WARNING")
        self._ready = False
        return None
