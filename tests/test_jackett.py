"""Regression tests for Jackett empty-search handling."""

from dataclasses import dataclass

from cineflow.integrations.jackett import Jackett


@dataclass
class FakeResponse:
    """Minimal response stand-in for Jackett requests."""

    data: dict | None


class FakeHandler:
    """Return a fixed Jackett payload while recording calls."""

    def __init__(self, data: dict | None) -> None:
        self.data = data
        self.calls = 0

    def get(self, endpoint: str, params: dict) -> FakeResponse:
        self.calls += 1
        return FakeResponse(self.data)


def jackett_with_handler(data: dict | None, **config: object) -> tuple[Jackett, FakeHandler]:
    """Build a Jackett client whose HTTP requests are intercepted."""
    consumer = Jackett(config={"url": "https://jackett.invalid", "token": "test", **config})
    handler = FakeHandler(data)
    consumer._handler = handler
    return consumer, handler


def test_search_with_zero_results_returns_none() -> None:
    consumer, handler = jackett_with_handler({"Results": []})

    assert consumer.search({"title": "Arrival", "year": "2016"}) is None
    assert handler.calls == 2


def test_collection_helpers_accept_empty_results() -> None:
    consumer, _ = jackett_with_handler({"Results": []})

    assert consumer._apply_search_pref([]) == []
    assert consumer._apply_size_limit([]) == []
    assert consumer._remove_duplicates([]) == []


def test_successful_search_still_returns_matching_torrent() -> None:
    payload = {
        "Results": [{
            "Title": "Arrival 2016 1080p",
            "Link": "https://example.invalid/arrival",
            "Size": 1_073_741_824,
            "Seeders": 10,
            "CategoryDesc": "Movies",
            "Imdb": "tt2543164",
        }],
    }
    consumer, _ = jackett_with_handler(payload, quick_match=True)

    match = consumer.search({"title": "Arrival", "year": "2016"})

    assert match is not None
    assert match["title"] == "Arrival"
