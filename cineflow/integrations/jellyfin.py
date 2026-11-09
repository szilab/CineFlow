"""Jellyfin API consumer module."""

from typing import List, Any
from cineflow.core.logger import log
from cineflow.core.bases.module import MediaServerBase
from cineflow.core.schema import (
    ModuleDefinition, ActionDefinition, Field, LIMIT, MEDIA_SERVER_QUERY, INPUT_BOTH, consumer_actions,
)
from cineflow.utils.misc import fix_imdbid, plan_season
WATCHED_PERCENT = Field(
    'watched_percent', 'integer', 'Watched before the next season (%)',
    "Share of the latest season's episodes in the libraries that someone must have watched "
    "before the next season is downloaded.", default=75, minimum=1, maximum=100,
)


class Jellyfin(MediaServerBase):
    """
    Jellyfin API consumer module.

    Configuration:
        - url: Jellyfin base URL (e.g., http://localhost:8096)
        - token: Jellyfin API key (required)
        - kind: 'movie' (default) or 'tv' to query series, given by the flow

    Functions:
        - search: Search media for a given title.
    """

    ID_KEY = 'jellyfinid'
    LIBRARY_KEY = 'ParentId'
    ITEM_TYPES = {'movie': 'Movie', 'tv': 'Series'}
    CHECK_ENDPOINT = '/System/Info'
    DEFINITION = ModuleDefinition(
        id='jellyfin', label='Jellyfin', category='media server', connection_test=True,
        description="Jellyfin media server: libraries, favorites and played state.",
        fields=(
            Field('url', 'url', 'URL', "Jellyfin base URL, e.g. http://jellyfin:8096.", required=True),
            Field('token', 'secret', 'API key', "Jellyfin API key.", required=True),
            LIMIT,
            Field('ignore.users', 'list', 'Ignored users', "User names left out of queries.",
                  advanced=True),
        ),
        actions=(*consumer_actions('Jellyfin', query=(
            *MEDIA_SERVER_QUERY,
            Field('isFavorite', 'boolean', 'Favorites only'),
            Field('isPlayed', 'boolean', 'Played'),
            # one dropdown in the GUI: the first user, every user or one user
            Field('allUsers', 'boolean', 'All users', "Query every user.", hidden=True),
            Field('userName', 'string', 'User', "Whose items to query; without a choice the first user.",
                  choices='users', all_key='allUsers'),
        )), ActionDefinition(
            'next_season', 'Next season to download',
            "For TV series: season 1 of a series not in the libraries yet, the missing aired episodes "
            "of the latest season, or the season after it once enough of it is watched by anyone. "
            "Other series are dropped.",
            input=INPUT_BOTH, fields=(WATCHED_PERCENT,),
            query=tuple(spec for spec in MEDIA_SERVER_QUERY if spec.key in ('parentLibrary', 'isInverse')),
        )),
    )

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
        # users and libraries are loaded on first use, not at construction time
        self._user_list = None
        self._library_list = None

    def _users(self) -> dict:
        """Return the Jellyfin users, loading them on first use."""
        if self._user_list is None:
            self._user_list = self._get_users()
        return self._user_list

    def _libraries(self) -> dict:
        """Return the Jellyfin libraries, loading them on first use."""
        if self._library_list is None:
            self._library_list = self._get_libraries()
        return self._library_list

    def next_season(self, data: List[dict], query: Any = None) -> List[dict]:
        """Keep the TV series with a season to download and set that ``season`` on them.

        When only some aired episodes of that season are missing, they are
        listed in ``wanted_episodes``; otherwise the whole season is wanted.

        The series are looked up in the queried libraries (e.g. every library
        except the CineFlow ones); an episode counts as watched when any user
        watched it. Failures stop the step instead of choosing a season blindly.
        """
        if not data:
            return []
        if self._kind != 'tv':
            log("'Next season' only works on TV series; the items are passed on unchanged.", level='WARNING')
            return data
        query = {**(query if isinstance(query, dict) else {}), 'allUsers': True}
        series = self._collect(query=query)
        if series is None:
            raise ValueError("Failed to query the Jellyfin series, no season is chosen.")
        users = list(self._users().values())
        if not users:
            raise ValueError("No Jellyfin users to read the watched state from.")
        percent = self.cfg('watched_percent', default=WATCHED_PERCENT.default)
        chosen = []
        for media in data:
            found = self.match(results=series, media=media)
            have, watched = self._episode_state(found['jellyfinid'], users) if found else (set(), set())
            plan = plan_season(have, watched, media.get('seasons_aired'), percent)
            if plan is None:
                log(f"No season of '{media.get('title')}' to download now.")
                continue
            season, missing = plan
            item = {**media, 'season': season}
            item.pop('episode', None)
            item.pop('wanted_episodes', None)
            if missing:
                item['wanted_episodes'] = missing
                log(f"Season {season} of '{media.get('title')}' misses episodes {missing}.")
            else:
                log(f"Season {season} of '{media.get('title')}' is next.")
            chosen.append(item)
        return chosen

    def _episode_state(self, series_id: str, users: List[str]) -> tuple[set, set]:
        """Return the (season, episode) pairs of a series in the library and those watched by anyone."""
        have, watched = set(), set()
        for user in users:
            response = self._handler.get(
                endpoint=f"/Shows/{series_id}/Episodes", params={'UserId': user, 'Fields': 'UserData'},
            )
            if response.status == 0 or response.status >= 400 or not isinstance(response.data, dict):
                raise ValueError(f"Failed to query the episodes of Jellyfin series {series_id}: HTTP {response.status}")
            for episode in response.data.get('Items') or []:
                season, number = episode.get('ParentIndexNumber'), episode.get('IndexNumber')
                # specials and "missing" (virtual) episodes are not in the library
                if not isinstance(season, int) or not isinstance(number, int) or season < 1 \
                        or episode.get('LocationType') == 'Virtual':
                    continue
                have.add((season, number))
                if (episode.get('UserData') or {}).get('Played'):
                    watched.add((season, number))
        return have, watched

    def field_choices(self, source: str) -> list[str] | None:
        """Return the user names besides the library names."""
        if source == 'users':
            return sorted(self._users())
        return super().field_choices(source)

    def _parse_query(self, query: Any) -> dict:
        if isinstance(query, dict) and query.get("isInverse") and query.get("perUser"):
            raise ValueError("Cannot set both 'isInverse' and 'perUser' in one query.")
        return super()._parse_query(query)

    def _inverse_query(self, query: dict) -> dict:
        """Compare against the full library of the same users."""
        return {key: query[key] for key in ("allUsers", "userName") if query.get(key)}

    def _query_user_ids(self, query: dict) -> List[dict]:
        users = self._users()
        if not query or not isinstance(query, dict):
            return [next(iter(users.values()))] if users else [None]
        if query.get("allUsers"):
            del query["allUsers"]
            user_ids = list(users.values())
            if not user_ids:
                raise ValueError("No users found in Jellyfin, skip the rest.")
            return user_ids
        if query.get("userName"):
            if query.get("userName") not in users:
                raise ValueError(f"User '{query['userName']}' not found in Jellyfin.")
            user_name = query["userName"]
            del query["userName"]
            return [users.get(user_name)]
        return [next(iter(users.values()))] if users else [None]

    def _get_items(self, query: dict = None) -> List[dict] | None:
        results = []
        for u in self._query_user_ids(query=query):
            params = {
                "fields": "OriginalTitle,ParentId,ProviderIds",
                "Recursive": "true",
                **(query if isinstance(query, dict) else {}),
            }
            if self._kind:
                params["includeItemTypes"] = self.ITEM_TYPES[self._kind]
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

    def _inverse_items(
        self, query_items: List[dict], query: dict = None
    ) -> List[dict] | None:
        all_items = self._get_items(query=query or {})
        if all_items is None:
            log("Failed to query the Jellyfin library for inverse calculation.", level="ERROR")
            return None
        query_ids = {
            str(item['jellyfinid']) for item in query_items if item.get('jellyfinid')
        }
        return [
            item for item in all_items
            if item.get('jellyfinid') and str(item['jellyfinid']) not in query_ids
        ]

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
