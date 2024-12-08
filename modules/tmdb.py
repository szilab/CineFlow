from bases.abs import ModuleBase
from bases.enums import MediaType
from bases.utils import st
from system.config import Config
from system.database import Database as db
from system.logger import log


class TmdbModule(ModuleBase):
    def __init__(self, type: MediaType):
        self._name = "TMDb"
        self._type = type.value
        self._limit = 20
        self._imageurl = "https://image.tmdb.org/t/p/original"
        self._ready = self._is_required_config_set(['TMDB_KEY'])
        self._req = self._init(
            url="https://api.themoviedb.org/3",
        )

    def collect(self):
        data = self._collect()
        log(f"Collected {len(data)} popular {self._type}s from {self._name}")
        for metadata in data:
            self._to_db(metadata)

    def search(self):
        all = db().get_all(self._type)
        for item in all:
            if metadata := self._search(title=item['title'], year=item['year'], aliases=item['aliases']):
                self._to_db(metadata)

    def _search(self, title: str, year: str, aliases: str = '') -> list:
        for lang in [Config().TMDB_LANG, "en-US"]:
            response = self._req.get(
                endpoint=f"search/{self._type}",
                params={"api_key": Config().TMDB_KEY, "query": title, "year": year, "language": lang},
                key="results"
            )
            for result in response.data:
                if result.get('release_date')[:4] == year:
                    if st(result.get('title')) == st(title) or st(result.get('title')) + ',' in st(aliases):
                        return result
                    if st(result.get('original_title')) == st(title) or st(result.get('original_title')) + ',' in st(aliases):
                        return result
        log(f"Could not identify '{title} ({year})' with TMDb", level='DEBUG')
        return None

    def _collect(self):
        data = []
        for page in range(1, 20):
            chunk = self._req.get(
                endpoint=f"{self._type}/popular",
                params={"api_key": Config().TMDB_KEY, "page": page, "language": Config().TMDB_LANG},
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
        return metadata.get('original_title') if metadata.get('original_title') else metadata.get('title')

    def _media_year(self, metadata: dict) -> None:
        return metadata.get('release_date')[:4]

    def _media_alias(self, metadata: dict) -> None:
        return metadata.get('title') if self._media_title(metadata) != metadata.get('title') else ""

    def _media_poster(self, metadata: dict) -> None:
        return self._imageurl + str(metadata.get('poster_path')) if metadata.get('poster_path') else ""
