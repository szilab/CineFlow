"""TMDb module for collecting metadata from The Movie Database API."""

from bases.abs import ModuleBase
from bases.enums import MediaType
from bases.utils import st
from system.config import cfg
from system.database import Database as db
from system.logger import log


class TmdbModule(ModuleBase):
    """TMDb module for collecting metadata from The Movie Database API."""

    def __init__(self, media_type: MediaType):
        self._name = "TMDb"
        self._type = media_type.value
        self._limit = cfg(name='limit', category='modules')
        self._imageurl = "https://image.tmdb.org/t/p/original"
        self._ready = self._is_required_config_set(
            names=['key'],
            category='tmdb'
        )
        self._req = self._init(
            url="https://api.themoviedb.org/3",
        )

    def collect(self):
        """Collect popular media items from TMDb API."""
        data = self._collect()
        log(f"Collected {len(data)} popular {self._type}s from {self._name}")
        for metadata in data:
            self._to_db(metadata)

    def search(self):
        """Search and update metadata for media items in database."""
        all_rows = db().get_all(self._type)
        for item in all_rows:
            metadata = self._search(
                title=item['title'],
                year=item['year'],
                aliases=item['aliases']
            )
            if metadata:
                self._to_db(metadata)

    def _search(self, title: str, year: str, aliases: str = '') -> list:
        def _is_in_title(string, title, aliases):
            return (
                st(string) == st(title)
                or
                st(string) + ',' in st(aliases)
            )

        for lang in [cfg(name='lang', category='tmdb'), "en-US"]:
            response = self._req.get(
                endpoint=f"search/{self._type}",
                params={
                    "api_key": cfg(name='key', category='tmdb'),
                    "query": title,
                    "year": year,
                    "language": lang
                },
                key="results"
            )
            for result in response.data:
                if result.get('release_date')[:4] == year:
                    if _is_in_title(result.get('title'), title, aliases):
                        return result
                    if _is_in_title(result.get('original_title'), title, aliases):
                        return result
        log(f"Could not identify '{title} ({year})' with TMDb", level='DEBUG')
        return None

    def _collect(self):
        data = []
        for page in range(1, 20):
            chunk = self._req.get(
                endpoint=f"{self._type}/popular",
                params={
                    "api_key": cfg(name='key', category='tmdb'),
                    "page": page,
                    "language": cfg(name='lang', category='tmdb')
                },
                key="results"
            )
            data.extend(chunk.data)
            if len(data) >= self._limit:
                break
        return data[:self._limit]

    def _to_db(self, metadata: dict):
        db().add(
            table=self._type,
            title=st(self._media_title(metadata)),
            year=self._media_year(metadata),
            alias=st(self._media_alias(metadata)),
            poster=self._media_poster(metadata),
            tmdb=metadata.get('id'),
            backdrop=metadata.get('backdrop_path'),
            overview=metadata.get('overview'),
        )

    def _media_title(self, metadata: dict) -> None:
        if metadata.get('original_title'):
            return metadata.get('original_title')
        return metadata.get('title')

    def _media_year(self, metadata: dict) -> None:
        return metadata.get('release_date')[:4]

    def _media_alias(self, metadata: dict) -> None:
        if self._media_title(metadata) != metadata.get('title'):
            return metadata.get('title')
        return ""

    def _media_poster(self, metadata: dict) -> None:
        if metadata.get('poster_path'):
            return self._imageurl + str(metadata.get('poster_path'))
        return ""
