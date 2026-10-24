"""Regression tests for Jackett empty-search handling."""

from dataclasses import dataclass

import pytest

from cineflow.integrations.jackett import Jackett


@dataclass
class FakeResponse:
    """Minimal response stand-in for Jackett requests."""

    data: dict | None
    status: int = 200


class FakeHandler:
    """Return a fixed Jackett payload while recording calls."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = 0

    def get(self, endpoint: str, params: dict) -> FakeResponse:
        self.calls += 1
        return self.response


def jackett_with_handler(
    data: dict | None, status: int = 200, **config: object
) -> tuple[Jackett, FakeHandler]:
    """Build a Jackett client whose HTTP requests are intercepted."""
    consumer = Jackett(config={"url": "https://jackett.invalid", "token": "test", **config})
    handler = FakeHandler(FakeResponse(data, status))
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


def test_get_with_zero_results_returns_empty_list() -> None:
    consumer, _ = jackett_with_handler({"Results": []})

    assert consumer.get() == []


@pytest.mark.parametrize(
    ("data", "status"),
    [(None, 0), (None, 500), ([], 200), ({}, 200)],
)
def test_get_returns_none_for_failed_or_invalid_response(data: object, status: int) -> None:
    consumer, _ = jackett_with_handler(data, status=status)

    assert consumer.get() is None


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


def jackett_items(*torrents: str) -> tuple[Jackett, list[dict]]:
    consumer, _ = jackett_with_handler({"Results": []})
    return consumer, [
        {"torrent": torrent, "seeders": 50, "resolution": "1080p", "size": 2.0} for torrent in torrents
    ]


def test_exclude_true_inverts_the_include_filter() -> None:
    consumer, items = jackett_items("Film.2024.1080p.HUN", "Film.2024.1080p.ENG")

    result = consumer._apply_query(items, {"include": "HUN", "exclude": True})

    assert [item["torrent"] for item in result] == ["Film.2024.1080p.ENG"]


@pytest.mark.parametrize("exclude", ["CAM TS", ["CAM", "TS"]])
def test_exclude_words_are_removed_while_include_still_applies(exclude: object) -> None:
    consumer, items = jackett_items("Film.2024.HUN.CAM", "Film.2024.HUN.WEB", "Film.2024.ENG.WEB")

    result = consumer._apply_query(items, {"include": "HUN", "exclude": exclude})

    assert [item["torrent"] for item in result] == ["Film.2024.HUN.WEB"]


def test_query_filters_tolerate_missing_fields() -> None:
    consumer, _ = jackett_items()

    assert consumer._apply_query([{"torrent": "Film.2024"}], {"seeders": 1, "size": 10}) == []
    assert consumer._apply_size_limit([{"torrent": "x"}]) == [{"torrent": "x"}]
    consumer._cfg["size_limit_gb"] = 10
    assert consumer._apply_size_limit([{"torrent": "x"}, {"torrent": "y", "size": 1.0}]) == [
        {"torrent": "y", "size": 1.0}
    ]


def test_results_without_imdb_or_link_use_magnet_and_are_kept() -> None:
    payload = {"Results": [{
        "Title": "Arrival 2016 1080p", "Link": None, "MagnetUri": "magnet:?xt=urn:btih:abc",
        "Size": 1_073_741_824, "Seeders": 10, "CategoryDesc": "Movies", "Imdb": None,
    }]}
    consumer, _ = jackett_with_handler(payload)

    result = consumer.get()

    assert len(result) == 1
    assert result[0]["link"] == "magnet:?xt=urn:btih:abc"
    assert "imdbid" not in result[0]
