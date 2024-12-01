import re
from system.misc import sanitize_name
from system.config import Config
from bases.module import ModuleBase
from bases.enums import RequestType


class Module(ModuleBase):
    name = "jackett"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # make sure config is valid
        Config().required([
            f"{self.name}.api.url",
            f"{self.name}.api.params.apikey",
        ])
        Config().defaults([
            f"{self.name}.api.minimum_seeders=5",
            f"{self.name}.api.limit=20",
        ])
        # set Jackket category
        if Config().get(f"{self.name}.categories"):
            categories = Config().get(f"{self.name}.categories")
            Config().defaults([f"{self.name}.api.params.Category[]={categories}"])
        elif self.type == "movie":
            Config().defaults([f"{self.name}.api.params.Category[]=2000"])
        elif self.type == "tv":
            Config().defaults([f"{self.name}.api.params.Category[]=5000"])
        # load TMDB API configuration
        self.api.url = Config().get(f"{self.name}.api.url") + "/api/v2.0/indexers/all"
        self.api.params = Config().get(f"{self.name}.api.params")

    def mapper(self, data: dict) -> dict:
        """
        Map media item title and year from Jacket data.
        :param data: Jackett data.
        """
        title, year = self.__extract_title_year(data.get('Title', ''))
        if title and year:
            return {"title": title, "year": year, f"{self.name}": data}
        return None

    def get_name(self, data: dict) -> str:
        """
        Generate item name of media item from Jackett data.
        :param data: TMDb data.
        """
        title, year = self.__extract_title_year(data.get('Title', ''))
        if title and year:
            return f"{title} ({year})"
        return None

    def collect(self) -> list:
        """List latest torrents from Jackett"""
        data = self.search()
        if min_seeders := Config().get(f"{self.name}.minimum_seeders"):
            data = [r for r in data if r.get("Seeders", 0) >= int(min_seeders)]
        return data

    def search(self, query: str = None, year: str = None):
        """Search torrents from Jackett"""
        # prepare query parameters
        if query:
            query = sanitize_name(query)
        if year and query:
            query += f" {year}"
        if include_only := Config().get(f"{self.name}.include_only"):
            query = include_only if not query else f"{query} {include_only}"
        # make request to JAckett API
        data = self.api.request(
            method=RequestType.GET,
            endpoint=f"/results",
            params={'Query': query} if query else {},
            key="Results"
        )
        return self.__filters_result(data=data)

    def __extract_title_year(self, string: str) -> tuple:
        """Return the title and year from the Jackett item Title."""
        search = re.search(r'(.+)\.([12]\d\d\d)\.', string)
        groups = search.groups() if search and len(search.groups()) == 2 else None
        title = groups[0].replace('.', ' ').strip() if groups else None
        year = groups[1] if groups else None
        return title, year

    def __filters_result(self, data: list) -> list:
        """Fix Jackett search results."""
        # return empty list if no data
        if not data:
            return []
        # sort data by seeders
        data = sorted(data, key=lambda x: x.get("Seeders"), reverse=True)
        # apply filters from configuration
        if exclude := Config().get(f"{self.name}.exclude"):
            data = [r for r in data if exclude not in r.get("Title", "")]
        # apply minimum seeders filter
        if min_seeders := Config().get(f"{self.name}.minimum_seeders"):
            data = [r for r in data if r.get("Seeders", 0) >= int(min_seeders)]
        # apply limit filter
        if limit := Config().get(f"{self.name}.limit"):
            data = data[:limit]
        return data