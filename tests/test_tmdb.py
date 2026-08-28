"""Regression tests for TMDb collection and lookup behavior."""

from dataclasses import dataclass

from cineflow.integrations.tmdb import Tmdb


@dataclass
class FakeResponse:
    """Small request response stand-in."""

    data: dict | None


class FakeHandler:
    """Records TMDb requests and returns configured payloads."""

    def __init__(self, responses: dict[tuple[str, int | None], dict | None]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int | None]] = []

    def get(self, endpoint: str, params: dict | None = None) -> FakeResponse:
        page = (params or {}).get("page")
        request = (endpoint, page)
        self.calls.append(request)
        return FakeResponse(self.responses.get(request))


def tmdb_with_handler(handler: FakeHandler, **config: object) -> Tmdb:
    """Build a TMDb consumer with all requests intercepted."""
    consumer = Tmdb(config={"token": "test-token", **config})
    consumer._handler = handler
    return consumer


def tmdb_item(identifier: int, title: str = "Arrival") -> dict:
    """Return a minimal valid TMDb media payload."""
    return {
        "id": identifier,
        "title": title,
        "original_title": title,
        "release_date": "2016-11-11",
        "imdb_id": "tt2543164",
    }


def test_get_stops_after_twenty_pages() -> None:
    responses = {
        ("/trending/movie/week", page): {"results": [tmdb_item(page)]}
        for page in range(1, 21)
    }
    handler = FakeHandler(responses)
    consumer = tmdb_with_handler(handler, limit=100)

    results = consumer.get()

    assert len(results) == 20
    assert handler.calls == [("/trending/movie/week", page) for page in range(1, 21)]


def test_get_stops_when_tmdb_returns_an_empty_page() -> None:
    handler = FakeHandler({("/trending/movie/week", 1): {"results": []}})
    consumer = tmdb_with_handler(handler, limit=100)

    assert consumer.get() == []
    assert handler.calls == [("/trending/movie/week", 1)]


def test_search_with_tmdb_id_returns_detail_match_without_title_search() -> None:
    handler = FakeHandler({("/movie/329865", None): tmdb_item(329865)})
    consumer = tmdb_with_handler(handler)
    media = {"title": "Arrival", "year": "2016", "tmdbid": "329865"}

    assert consumer.search(media) == {
        "title": "Arrival",
        "alttitle": "Arrival",
        "year": "2016",
        "tmdbid": 329865,
        "imdbid": 2543164,
    }
    assert handler.calls == [("/movie/329865", None)]


def test_search_falls_back_to_title_when_tmdb_id_is_unusable() -> None:
    handler = FakeHandler({
        ("/search/movie", None): {"results": [tmdb_item(329865)]},
    })
    consumer = tmdb_with_handler(handler)
    media = {"title": "Arrival", "year": "2016"}

    assert consumer.search(media)["tmdbid"] == 329865
    assert handler.calls == [("/search/movie", None)]
