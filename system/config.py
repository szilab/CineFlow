"""App config module"""

import os


class Config():  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """App configuration"""
    _instances = {}

    def __call__(self, *args, **kwargs):
        if self not in self._instances:
            self._instances[self] = super(Config, self).__call__(*args, **kwargs)  # pylint: disable=no-member,super-with-arguments
        return self._instances[self]

    def __init__(self) -> None:
        self.data_dir = os.getenv('DATA_DIR', './config')
        self.library_dir = os.getenv('LIBRARY_DIR', './config')
        self.retention = int(os.getenv('RETENTION')) or 90
        self.interval = int(os.getenv('INTERVAL')) or 120
        self.twshows = bool(os.getenv('TWSHOWS'))
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.log_colors = bool(os.getenv('LOG_COLORS'))
        self.tmdb_key = os.getenv('TMDB_KEY', '')
        self.tmdb_lang = os.getenv('TMDB_LANG', 'en-US')
        self.jacket_url = os.getenv('JACKETT_URL', '')
        self.jacket_key = os.getenv('JACKETT_KEY', '')
        self.jacket_categories = os.getenv('JACKETT_CATEGORIES', '')
        self.jacket_include = os.getenv('JACKETT_INCLUDE', '')
        self.jacket_exclude = os.getenv('JACKETT_EXCLUDE', 'dummy_BvTKb37YD3hadR89zkUI')
        self.jellyfin_url = os.getenv('JELLYFIN_URL', '')
        self.jellyfin_key = os.getenv('JELLYFIN_KEY', '')
        self.jellyfin_user = os.getenv('JELLYFIN_USER', '')
        self.jellyfin_libraries = os.getenv('JELLYFIN_LIBRARIES', '')
        self.trakt_client_id = os.getenv('TRAKT_CLIENT_ID', '')
        self.trakt_client_secret = os.getenv('TRAKT_CLIENT_SECRET', '')
        self.trakt_access_token = os.getenv('TRAKT_ACCESS_TOKEN', '')
        self.border_rules = os.getenv('BORDER_RULES', '')
        self.downloader_url = os.getenv('DOWNLOADER_URL', '')
        self.downloader_user = os.getenv('DOWNLOADER_USER', '')
        self.downloader_passw = os.getenv('DOWNLOADER_PASSW', '')
        self.downloader_savepath= os.getenv('DOWNLOADER_SAVEPATH', '')
