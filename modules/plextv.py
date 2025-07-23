"""Plex API consumer class"""

from typing import List, Dict
from system.config import cfg
from bases.module import ConsumerBase, requires_ready


# class PlextvData(MediaData):  # pylint: disable=too-few-public-methods
#     """TMDB data."""

#     def __init__(self, data: dict = {}, **kwargs) -> None:  # pylint: disable=dangerous-default-value
#         super().__init__(data=data, **kwargs)
#         self.data = {
#             'poster': '',
#             **self.data,
#         }
#         self._mappings = {
#             'kind': ['type'],
#             'poster': ['thumb'],
#         }
#         self._transforms = {
#             "year": lambda x: int(str(x)[0:4]),
#         }

# class Plextv(ConsumerBase):
#     """
#     Plex.tv API consumer class

#     Configuration:
#         - token: Plex.tv API token (required)
#         - kind: media type: movie, tv (default: movie)
#         - limit: number of items to collect (default: 20)
#         - params: additional parameters for the API request (optional)

#     Functions:
#         - get: collect media from Plex.tv API return list of media
#         - search: search for media in Plex.tv API return the match or None
#     """

#     def __init__(self) -> None:
#         """Initialize the Plex.tv consumer."""
#         super().__init__(url="https://discover.provider.plex.tv")
#         self._req_module_cfgs = ['token']

#     def ready(self) -> None:
#         """Check if the Plex.tv module is ready."""
#         super().ready()
#         self._handler.params = {
#             'X-Plex-Product': 'Plex Web',
#             'X-Plex-Version': '4.145.1',
#             'X-Plex-Model': 'bundled',
#             'X-Plex-Device': 'Windows',
#             'X-Plex-Text-Format': 'plain',
#             'X-Plex-Language': cfg("language", default="en-US"),
#             'X-Plex-Token': self._cfg.get('token'),
#         }
#         return True

#     def get(self, data: list) -> List[dict]:
#         """Collect media from the Plex.tv API."""
#         self.ready()
#         if not self._ready:
#             return [*data]
#         collected = []
#         index = 0
#         while len(collected) < self._limit:
#             response = self._handler.get(
#                 endpoint="/hubs/sections/home/recommended-on-services",
#                 params={**{
#                     'X-Plex-Container-Start': index,
#                     'X-Plex-Container-Size': 10,
#                 },
#                     **self._cfg.get('params', {})}
#             )
#             for item in response.data.get('MediaContainer', {}).get('Metadata') or []:
#                 if item.get('type') == self._kind:
#                     if media := PlextvData(kind=self._kind).map(item=item):
#                         collected.append(media)
#                         if len(collected) >= self._limit:
#                             return collected
#             index += 10
#         return [*data, *collected]

#     def search(self, title: str, year: str) -> Dict:  # pylint: disable=redefined-builtin
#         """Search for media in Plex.tv."""


# https://discover.provider.plex.tv/hubs/sections/home?x-plex-token=_AEJsaNtDJL-4yyPsoc4
# https://discover.provider.plex.tv/hubs/sections/home?x-plex-token=122oe_rjgQfY8JYb26Es
# https://discover.provider.plex.tv/hubs/sections/home/recommended-on-services?x-plex-token=_AEJsaNtDJL-4yyPsoc4
# https://discover.provider.plex.tv/library/search?-plex-token=_AEJsaNtDJL-4yyPsoc4&query=the+matrix&limit=10&searchProviders=discover&searchTypes=movies,tv

# https://discover.provider.plex.tv/actions/scrobble?X-Plex-Token=_AEJsaNtDJL-4yyPsoc4&key=5d776898d11dd300202284a5
# https://discover.provider.plex.tv/actions/unscrobble?X-Plex-Token=_AEJsaNtDJL-4yyPsoc4&key=5d776898d11dd300202284a5
