from system.config import Config
from bases.module import ModuleBase
from bases.enums import RequestType


class Module(ModuleBase):
    name = "tmdb"

    def __init__(self, **kwargs):
        # make sure config is valid
        Config().required([
            f"{self.name}.api.params.api_key"
        ])
        # set default configuration values
        Config().defaults([
            f"{self.name}.api.url=https://api.themoviedb.org/3",
            f"{self.name}.api.params.language=en-US",
            f"{self.name}.api.params.adult=false",
            f"{self.name}.limit=20",
        ])
        # call parent constructor
        super().__init__(**kwargs)
        # load TMDB API configuration
        self.api.url = Config().get(f"{self.name}.api.url")
        self.api.params = Config().get(f"{self.name}.api.params")

    def mapper(self, data: dict) -> dict:
        """
        Map media item title and year from TMDb data.
        :param data: TMDb data.
        """
        if not data.get('title') or not data.get('release_date'):
            return None
        return {"title": data.get('title'), "year": data.get('release_date')[:4], f"{self.name}": data}

    def get_name(self, data: dict) -> str:
        """
        Generate item name of media item from TMDb data.
        :param data: TMDb data.
        """
        if data.get('title') and data.get('release_date'):
            return f"{data.get('title')} ({data.get('release_date')[:4]})"
        return None

    def search(self, query: str = None, year: str = None, page: int = 1) -> list:
        """
        Search for media items in TMDb database.
        :param query: Search query.
        :param year: Year of release.
        :param page: Page number.
        """
        # prepare query parameters
        params = {}
        if query:
            params["query"] = query
        if year:
            params["year"] = year
        # make request to TMDb API
        return self.api.request(
            method=RequestType.GET,
            endpoint=f"/search/{self.type}",
            params=params,
            key="results"
        )

    def collect(self) -> list:
        """Get popular media items from TMDb database."""
        # prepare to store data
        data, limit = [], int(Config().get(f"{self.name}.limit"))
        # make requests to TMDb API until limit is reached
        for page in range(1, 20):

            # make request to TMDb API and store results
            chunk = self.api.request(
                method=RequestType.GET,
                endpoint=f"/{self.type}/popular",
                params={"page": page},
                key="results"
            )
            data.extend(chunk)

            # break if limit is reached
            if len(data) >= limit:
                break
        # return limited data because chunking contains unknown number of items
        return data[:limit]