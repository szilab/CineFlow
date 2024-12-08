from enum import Enum


class Phases(Enum):
    COLLECT = 1
    SEARCH = 2
    EXPORT = 3


class MediaType(Enum):
    MOVIE = "movie"
    TV = "tv"

class ConfigParams(Enum):
    DATA_DIR = 1, 'str', './config'
    LIBRARY_DIR = 1, 'str', './config'
    RETENTION = 3, 'int', 90
    INTERVAL = 4, 'int', 120
    TWSHOWS = 5, 'bool', False
    LOG_LEVEL = 6, 'str', 'INFO'
    LOG_COLORS = 7, 'bool', False
    TMDB_KEY = 8, 'str', ''
    TMDB_LANG = 9, 'str', 'en-US'
    JACKETT_URL = 9, 'str', ''
    JACKETT_KEY = 10, 'str', ''
    JACKETT_CATEGORIES = 11, 'str', ''
    JACKETT_RESOLUTIONS = 12, 'str', ''
    JACKETT_INCLUDE = 13, 'str', ''
    JACKETT_EXCLUDE = 14, 'str', 'dummy_BvTKb37YD3hadR89zkUI'
    JELLYFIN_URL = 15, 'str', ''
    JELLYFIN_KEY = 16, 'str', ''
    JELLYFIN_USER = 17, 'str', ''
    JELLYFIN_LIBRARIES = 18, 'str', ''
    TRAKT_CLIENT_ID = 19, 'str', ''
    TRAKT_CLIENT_SECRET = 20, 'str', ''
    TRAKT_ACCESS_TOKEN = 21, 'str', ''
    BORDER_RULES = 22, 'str', ''
    DOWNLOADER_URL = 23, 'str', ''
    DOWNLOADER_USER = 24, 'str', ''
    DOWNLOADER_PASSW = 25, 'str', ''
    DOWNLOADER_SAVEPATH = 26, 'str', ''