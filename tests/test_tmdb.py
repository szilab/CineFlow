"""Regression tests for TMDb collection and lookup behavior."""

from dataclasses import dataclass

import pytest

from cineflow.integrations.tmdb import Tmdb


@dataclass
class FakeResponse:
    """Small request response stand-in."""

    data: dict | None
    status: int = 200


class FakeHandler:
    """Records TMDb requests and returns configured payloads."""

    def __init__(self, responses: dict[tuple[str, int | None], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int | None]] = []
        self.kwargs: dict[str, dict] = {}

    def get(self, endpoint: str, params: dict | None = None, **kwargs) -> FakeResponse:
        self.kwargs[endpoint] = kwargs
        page = (params or {}).get("page")
        request = (endpoint, page)
        self.calls.append(request)
        response = self.responses.get(request)
        return response if isinstance(response, FakeResponse) else FakeResponse(response)


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


def test_get_returns_collected_items_after_successful_empty_page() -> None:
    handler = FakeHandler({
        ("/trending/movie/week", 1): {"results": [tmdb_item(1)]},
        ("/trending/movie/week", 2): {"results": []},
    })
    consumer = tmdb_with_handler(handler, limit=100)

    assert len(consumer.get()) == 1


@pytest.mark.parametrize(
    "response",
    [FakeResponse(None, 0), FakeResponse(None, 500), FakeResponse([]), FakeResponse({})],
)
def test_get_returns_none_for_failed_or_invalid_response(response: FakeResponse) -> None:
    consumer = tmdb_with_handler(FakeHandler({("/trending/movie/week", 1): response}))

    assert consumer.get() is None


def test_get_returns_none_when_later_page_fails() -> None:
    handler = FakeHandler({
        ("/trending/movie/week", 1): {"results": [tmdb_item(1)]},
        ("/trending/movie/week", 2): FakeResponse(None, 0),
    })

    assert tmdb_with_handler(handler, limit=100).get() is None


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


def test_get_looks_up_imdb_ids_only_for_collected_items_with_long_cache() -> None:
    item = {key: value for key, value in tmdb_item(1).items() if key != "imdb_id"}
    other = {**item, "id": 2, "title": "Other"}
    handler = FakeHandler({
        ("/trending/movie/week", 1): {"results": [item, other]},
        ("/trending/movie/week", 2): {"results": []},
        ("/movie/1/external_ids", None): {"imdb_id": "tt0000042"},
    })
    consumer = tmdb_with_handler(handler, limit=100)

    results = consumer.get(query="Arrival")

    assert [result["imdbid"] for result in results] == [42]
    assert ("/movie/2/external_ids", None) not in handler.calls
    assert handler.kwargs["/movie/1/external_ids"] == {"cache_time": Tmdb.IMDB_CACHE_TIME}


def test_trending_request_sends_only_supported_parameters() -> None:
    handler = FakeHandler({("/trending/movie/week", 1): {"results": []}})
    params = []
    original = handler.get

    def recording_get(endpoint, params_=None, **kwargs):
        params.append(params_)
        return original(endpoint, params_, **kwargs)

    handler.get = lambda endpoint, params=None, **kwargs: recording_get(endpoint, params, **kwargs)
    tmdb_with_handler(handler).get()

    assert params == [{"page": 1}]


def test_search_with_imdb_id_uses_find_endpoint() -> None:
    found = {key: value for key, value in tmdb_item(329865).items() if key != "imdb_id"}
    handler = FakeHandler({("/find/tt2543164", None): {"movie_results": [found]}})
    consumer = tmdb_with_handler(handler)

    match = consumer.search({"title": "Arrival", "year": "2016", "imdbid": 2543164})

    assert match["tmdbid"] == 329865
    assert match["imdbid"] == 2543164
    assert handler.calls == [("/find/tt2543164", None)]


def test_title_search_looks_up_imdb_id_only_for_the_match() -> None:
    results = [
        {key: value for key, value in tmdb_item(identifier, title).items() if key != "imdb_id"}
        for identifier, title in ((1, "Arrival"), (2, "Arrival Again"), (3, "Other"))
    ]
    handler = FakeHandler({
        ("/search/movie", None): {"results": results},
        ("/movie/1/external_ids", None): {"imdb_id": "tt2543164"},
    })
    consumer = tmdb_with_handler(handler)

    match = consumer.search({"title": "Arrival", "year": "2016"})

    assert match["imdbid"] == 2543164
    assert handler.calls == [("/search/movie", None), ("/movie/1/external_ids", None)]


def test_failed_imdb_lookup_keeps_the_item_without_imdb_id() -> None:
    item = {key: value for key, value in tmdb_item(1).items() if key != "imdb_id"}
    handler = FakeHandler({
        ("/trending/movie/week", 1): {"results": [item]},
        ("/trending/movie/week", 2): {"results": []},
        ("/movie/1/external_ids", None): FakeResponse(None, 0),
    })

    results = tmdb_with_handler(handler).get()

    assert len(results) == 1
    assert "imdbid" not in results[0]
