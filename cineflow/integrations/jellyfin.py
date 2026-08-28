"""Jellyfin API consumer module."""

from typing import List, Any
from cineflow.core.logger import log
from cineflow.core.bases.module import ConsumerBase
from cineflow.utils.misc import fix_imdbid


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
            'title': ['Name'],
            'alttitle': ['OriginalTitle'],
            'year': ['ProductionYear', 'PremiereDate'],
            'jellyfinid': ['Id'],
            'tmdbid': ['ProviderIds'],
            'imdbid': ['ProviderIds'],
        }
        self.transforms = {
            "year": lambda x: str(x)[0:4],
            "tmdbid": lambda x: dict(x).get('Tmdb'),
            "imdbid": fix_imdbid
        }
        self.params = {
            "ApiKey": self.cfg("token")
        }
        self._user_list = self._get_users()
        self._library_list = self._get_libraries()

    def get(self, query: Any = None) -> List[dict] | None:
        """Collect media from Jellyfin."""
        input_items = query if isinstance(query, list) else []
        query = self._parse_query(query)
        results = None
        if query.get("isInverse"):
            del query["isInverse"]
            q_items = self._get_items(query=query)
            if q_items is not None:
                results = self._inverse_items(query_items=input_items or q_items)
        else:
            results = self._get_items(query=query)
        if results is None:
            return None
        return list({
            item['jellyfinid']: item for item in results if item.get('jellyfinid')
        }.values())

    def search(self, media: dict) -> dict:
        """Search media for the given title."""
        results = self._get_items()
        return self.match(results=results, media=media)

    def _parse_query(self, query: Any) -> dict:
        if not query:
            return {}
        if isinstance(query, str):
            return {"searchTerm": query}
        if not isinstance(query, (dict, list)):
            raise ValueError("Jellyfin 'query' must be a string or a dictionary.")
        if isinstance(query, dict):
            query = dict(query)
            if query.get("isInverse") and query.get("perUser"):
                raise ValueError("Cannot set both 'isInverse' and 'perUser' in one query.")
            if query.get("parentLibrary"):
                if query.get("parentLibrary") not in self._library_list:
                    raise ValueError(f"Library '{query['parentLibrary']}' not found in Jellyfin.")
                query["ParentId"] = self._library_list[query["parentLibrary"]]
                del query["parentLibrary"]
        return query

    def _query_user_ids(self, query: dict) -> List[dict]:
        if not query or not isinstance(query, dict):
            return [next(iter(self._user_list.values()))] if self._user_list else [None]
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
        return [next(iter(self._user_list.values()))] if self._user_list else [None]

    def _get_items(self, query: dict = None) -> List[dict] | None:
        results = []
        for u in self._query_user_ids(query=query):
            params = {
                "fields": "OriginalTitle,ParentId,ProviderIds",
                "Recursive": "true",
                **(query if isinstance(query, dict) else {}),
            }
            if self._kind:
                params["includeItemTypes"] = self._kind
            params = {k: v for k, v in params.items() if v is not None and v != ""}
            response = self._handler.get(
                endpoint=f"/Users/{u}/Items" if u else "/Items",
                params=params,
            )
            if response.status == 0 or response.status >= 400:
                log(f"Jellyfin API error {response.status} for query: {params}", level="ERROR")
                return None
            if not response.data or not response.data.get('Items'):
                continue
            results.extend(response.data.get('Items'))
        return [self.map(item=item) for item in results]

    def _inverse_items(self, query_items: List[dict]) -> List[dict] | None:
        if not query_items:
            log(
                "Query items are empty, skipping inverse calculation "
                "to prevent library wipeout.", level="WARNING")
            return []
        all_items = self._get_items(query={})
        if all_items is None:
            log("Failed to query the Jellyfin library for inverse calculation.", level="ERROR")
            return None
        exclude_ids = set()
        for item in query_items:
            for key in ['jellyfinid', 'tmdbid', 'imdbid']:
                if item.get(key):
                    exclude_ids.add(str(item[key]))
        not_in_query = []
        for item in all_items:
            found = False
            for key in ['jellyfinid', 'tmdbid', 'imdbid']:
                if item.get(key) and str(item[key]) in exclude_ids:
                    found = True
                    break
            if not found:
                not_in_query.append(item)
        return not_in_query

    def _get_users(self):
        response = self._handler.get(
            endpoint="/Users",
        )
        if response.status == 0 or response.status >= 400:
            raise ValueError(f"Failed to query Jellyfin users: HTTP {response.status}")
        if not response.data or len(response.data) == 0:
            raise ValueError("No users found in Jellyfin")
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
        if response.status == 0 or response.status >= 400:
            raise ValueError(f"Failed to query Jellyfin libraries: HTTP {response.status}")
        if not response.data or len(response.data) == 0:
            raise ValueError("No libraries found in Jellyfin")
        library_list = {}
        for library in response.data:
            library_list.update({
                library["Name"]: library["ItemId"],
            })
        return library_list
