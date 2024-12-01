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