"""
External service integrations.

Each module provides a consumer class that interfaces with an external API.
New integrations should be added here and will be auto-discovered.
"""
from cineflow.integrations.tmdb import Tmdb                  # noqa: F401
from cineflow.integrations.jackett import Jackett            # noqa: F401
from cineflow.integrations.jellyfin import Jellyfin          # noqa: F401
from cineflow.integrations.plex import Plex                  # noqa: F401
from cineflow.integrations.transmission import Transmission  # noqa: F401
