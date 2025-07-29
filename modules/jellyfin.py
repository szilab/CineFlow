"""Jellyfin API consumer module."""

from typing import List, Any
from system.logger import log
from bases.module import ConsumerBase


class Jellyfin(ConsumerBase):
    """
    Jellyfin API consumer module.

    Configuration:
        - url: Jellyfin base URL (e.g., http://localhost:8096)
        - token: Jellyfin API key (required)
        - limit: Number of results to return (default: 20)

    Functions:
        - search: Search media for a given title.
    """

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config, required=['url', 'token'])
        self.rate_limit = 0
        self.cache_time = 0
        self.mappings = {
            'title': ['OriginalTitle', 'Name'],
            'year': ['ProductionYear', 'PremiereDate'],
            'jellyfinid': ['Id'],
        }
        self.transforms = {
            "year": lambda x: str(x)[0:4],
        }
        self.params = {
            "ApiKey": self.cfg("token")
        }
        self._user_list = self._get_users()
        self._library_list = self._get_libraries()

    def get(self, query: Any = None) -> List[dict]:
        """Collect media from Jellyfin."""
        query = self._parse_query(query)
        if query.get("isInverse"):
            del query["isInverse"]
            results = self._inverse_items(query_items=self._get_items(query=query))
        else:
            results = self._get_items(query=query)
        return {item['jellyfinid']: item for item in results}.values()

    def search(self, title: str, year: int) -> List[dict]:
        """Search media for the given title."""
        results = self._get_items()
        return self.match(results=results, title=title, year=year)

    def _parse_query(self, query: Any) -> dict:
        if not query:
            return {}
        if isinstance(query, str):
            return {"searchTerm": query}
        if not isinstance(query, dict):
            raise ValueError("Jellyfin 'query' must be a string or a dictionary.")
        if query.get("isInverse") and query.get("perUser"):
            raise ValueError("Cannot set both 'isInverse' and 'perUser' in one query.")
        if query.get("parentLibrary"):
            if query.get("parentLibrary") not in self._library_list:
                raise ValueError(f"Library '{query['parentLibrary']}' not found in Jellyfin.")
            query["ParentId"] = self._library_list[query["parentLibrary"]]
            del query["parentLibrary"]
        return query

    def _query_user_ids(self, query: dict) -> List[dict]:
        if not query:
            return [None]
        if query.get("allUsers"):
            del query["allUsers"]
            users = [id for _, id in self._user_list.items()]
            if not users:
                raise ValueError("No users found in Jellyfin, skip the rest.")
            return users
        if query.get("userName"):
            if query.get("userName") not in self._user_list:
                raise ValueError(f"User '{query['userName']}' not found in Jellyfin.")
            user_name = query["userName"]
            del query["userName"]
            return [self._user_list.get(user_name)]
        return [None]

    def _get_items(self, query: dict = None) -> List[dict]:
        results = []
        for u in self._query_user_ids(query=query):
            response = self._handler.get(
                endpoint=f"/Users/{u}/Items" if u else "/Items",
                params={
                    "fields": "OriginalTitle,ParentId",
                    "Recursive": "true",
                    "includeItemTypes": self._kind,
                    **(query or {}),
                },
            )
            if not response.data or not response.data.get('Items'):
                continue
            results.extend(response.data.get('Items'))
        return [self.map(item=item) for item in results]

    def _inverse_items(self, query_items: List[dict]) -> List[dict]:
        all_items = self._get_items()
        query_ids = {item['jellyfinid'] for item in query_items}
        return [item for item in all_items if item['jellyfinid'] not in query_ids]

    def _get_users(self):
        response = self._handler.get(
            endpoint="/Users",
        )
        if not response.data or len(response.data) == 0:
            raise ValueError("No users found in Jellyfin, skipp the rest.")
        user_list = {}
        for user in response.data:
            if user.get("Name") in self.cfg('ignore.users', []):
                log(f"Ignoring user '{user.get('Name')}'.")
                continue
            user_list.update({
                user.get("Name"): user.get("Id"),
            })
        return user_list

    def _get_libraries(self) -> List[dict]:
        response = self._handler.get(
            endpoint="/Library/VirtualFolders",
        )
        if not response.data or len(response.data) == 0:
            raise ValueError("No libraries found in Jellyfin, skipp the rest.")
        library_list = {}
        for library in response.data:
            library_list.update({
                library["Name"]: library["ItemId"],
            })
        return library_list
