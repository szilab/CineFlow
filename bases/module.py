import sys
from typing import Any
from system.logger import log
from handlers.request import RequestHandler
from bases.enums import RequestType


class ModuleBase:
    name = "ModuleBase"

    def __init__(self, library_handler) -> None:
        """
        Initialize module with library handler.
        :param library_handler: Library handler instance.
        """
        self.library_handler = library_handler
        self.type = self.library_handler.type()
        self.api = APICConsumer()

    # def cfg(self, key: str, default=None) -> Any:
    #     """
    #     Get configuration value for the module.
    #     :param key: Configuration key.
    #     :param default: Default value.
    #     """
    #     from system.config import Config
    #     return Config().get(f"{self.name}.{key}", default=default)

    # def required(self, list: list) -> None:
    #     """
    #     Check if required configuration is set.
    #     :param list: List of required keys.
    #     """
    #     from system.config import Config
    #     for key in list:
    #         Config().required(f"{self.name}.{key}")

    # def defaults(self, list: list) -> Any:
    #     """
    #     Set default configuration values for the module.
    #     :param list: List key and value pairs in the form of key=value.
    #     """
    #     from system.config import Config
    #     for item in list:
    #         if '=' in item:
    #             path, value = item.split('=')
    #             Config().set(path=path, value=value)
    #         else:
    #             Config().set(path=item, value=None)



    # def default_delete(self) -> list:
    #     """Delete media items with the module."""
    #     for name in self.library_handler.get():
    #         data = self.found(name=name)
    #         if data:
    #             self.library_handler.remove(name=name)

    # def found(self, name: str):
    #     data = self.library_handler.metadata(name=name)
    #     found = self.matching(data)
    #     if not found:
    #         log(f"Failed to find matching item for '{data.get('name')}'.")
    #         return None
    #     if self.own_data(data):
    #         log(f"Skipping item '{data.get('name')}' (already contains {self.name} data).")
    #         return None
    #     return {**self.metadataof(found), **data}

    # def export(self):
    #     log("This module has no 'export' method", level='WARNING')

    # def update(self):
    #     log("This module has no 'export' method", level='WARNING')

    # def delete(self):
    #     log("This module has no 'export' method", level='WARNING')


    def collect(self):
        self.__method_missing('collect')

    def mapper(self, data: dict):
        self.__method_missing('mapper')

    def export(self) -> list:
        """
        Export popular/trending items by the module.
        """
        from system.misc import sanitize_name
        for data in self.collect():
            if name := sanitize_name(self.get_name(data)):
                if self.library_handler.exists(item=name):
                    log(f"Skipp export for {name} (already exists).", level='DEBUG')
                if self.library_handler.add(
                    item=name,
                    metadata={'name': name, **self.mapper(data)},
                ):
                    log(f"Exporting item '{name}' with {self.name}")

    def update(self) -> list:
        """
        Update media items with the module.
        """
        from system.misc import sanitize_name
        for name in self.library_handler.get():
            # load metadata for the library item
            ld = self.library_handler.metadataof(item=name)
            # skip if item the module data is already present
            if ld and ld.get(self.name):
                log(f"Skipp update for {name} (already contains {self.name} data).", level='DEBUG')
                continue
            # make sure items for search are available
            found = False
            if ld and ld.get('name') and ld.get('year'):
                # loop through search results and update if item name matches
                for data in self.search(query=ld.get('title'), year=ld.get('year')):
                    if name == sanitize_name(self.get_name(data)):
                        self.library_handler.update(item=name, metadata={self.name: data, **ld})
                        log(f"Updating item '{name}' with {self.name} data.")
                        found = True
            if not found:
                log(f"Failed to find matching item for '{name}' with '{self.name}'.", level='DEBUG')


    # def matching(self, item):
    #     """Find matching item in the API."""
    #     raise NotImplementedError("This module should implement 'matching' method")

    # def metadataof(self, item):
    #     """Get metadata for the item."""
    #     raise NotImplementedError("This module should implement 'metadata' method")

    # def mapper(self, data: dict):
    #     if hasattr(self, 'mapping') and isinstance(self.mapping, dict):
    #         return {key: data.get(value) for key, value in self.mapping.items()}

    def __method_missing(self, name: str):
        log(f"This module '{self.name}' should implement '{name}' method", level='ERROR')
        sys.exit(3)

class APICConsumer:
    def __init__(self):
        self.url = None
        self.params = {}
        self.headers = {}

    def request(self, method: RequestType, endpoint: str, params: dict = None, key: str = None, **kwargs) -> Any:
        """
        Perform API request through the module.
        :param method: HTTP method from RequestType enum like RequestType.GET.
        :param endpoint: API endpoint.
        :param params: Query parameters.
        :param key: Key to extract data from JSON response.
        :param kwargs: Additional arguments for python requests library like header, cookies, auth.
        """
        # run the API request
        self.__init_request_handler()
        response = self.request_handler.make_request(method=method, endpoint=endpoint, params=params, **kwargs)
        # extract data from JSON response
        if response and response.status_code == 200 and response.json():
            if key:
                return response.json().get(key, response.json())
            return response.json()
        else:
            log(f"{method} request failed to '{endpoint}': {response.text}", level='WARNING')
        return None

    def __init_request_handler(self):
        """
        Initialize request handler wich will be used to execute API calls.
        """
        # Ensure the request handler is initialized only once
        if hasattr(self, 'request_handler'):
            return
        # Ensure the API URL is set
        if not self.url:
            log("This module should implement 'url' config parameter", level='ERROR')
            sys.exit(3)
        # Initialize the request handler
        self.request_handler = RequestHandler(
            base_url=self.url,
            params=self.params,
            headers=self.headers
        )