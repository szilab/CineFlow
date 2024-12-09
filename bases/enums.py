"""Enum definitions for the project."""

from enum import Enum


class Phases(Enum):
    """Enum for the different phases of the execution."""
    COLLECT = 1
    SEARCH = 2
    EXPORT = 3


class MediaType(Enum):
    """Enum for the different types of media."""
    MOVIE = "movie"
    TV = "tv"
