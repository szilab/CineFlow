"""Base class for field mappers."""


class MediaData():
    """Base class for field mappers."""

    def __init__(self, data: dict = {}, **kwargs) -> None:  # pylint: disable=dangerous-default-value
        """Initialize the mapper."""
        self.data = {
            'id': 0,
            'title': '',
            'year': '',
            'kind': '',
            **data,
            **kwargs,
        }
        self._mappings = {}
        self._transforms = {
            "year": lambda x: int(str(x)[0:4]),
        }

    def _transform(self):
        for key, value in self.data.items():
            if key not in self._transforms:
                continue
            if not value:
                continue
            if  not callable(self._transforms[key]):
                continue
            self.data[key] = self._transforms[key](value)

    def map(self, item: dict) -> dict:
        """Map the item to the data object."""
        for key, value in self.data.items():
            if key in item and not value:
                self.data[key] = item[key]
        for key, value in self.data.items():
            if key in self._mappings and not value:
                for mapping in self._mappings[key]:
                    if mapping in item:
                        self.data[key] = item[mapping]
                        break
        self._transform()
        return self.data
