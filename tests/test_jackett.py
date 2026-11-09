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
    consumer, _ = jackett_with_handler(payload)

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

    assert consumer._apply_query([{"torrent": "Film.2024"}], {"include": "HUN"}) == []
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


def test_module_release_filters_apply_to_get_and_search() -> None:
    payload = {"Results": [
        {"Title": "Arrival 2016 1080p HUN", "Link": "https://t/a", "Size": 2 * 1024 ** 3, "Seeders": 50,
         "CategoryDesc": "Movies", "Imdb": "tt2543164"},
        {"Title": "Arrival 2016 2160p HUN", "Link": "https://t/b", "Size": 2 * 1024 ** 3, "Seeders": 80,
         "CategoryDesc": "Movies", "Imdb": "tt2543164"},
        {"Title": "Arrival 2016 1080p ENG", "Link": "https://t/c", "Size": 2 * 1024 ** 3, "Seeders": 3,
         "CategoryDesc": "Movies", "Imdb": "tt2543164"},
    ]}
    consumer, _ = jackett_with_handler(payload, min_seeders=10, resolution="1080p")

    assert [item["torrent"] for item in consumer.get()] == ["Arrival 2016 1080p HUN"]
    assert consumer.search({"title": "Arrival", "year": "2016"})["torrent"] == "Arrival 2016 1080p HUN"

    # without module filters the best seeded release of the title wins
    unfiltered, _ = jackett_with_handler(payload)
    assert [item["torrent"] for item in unfiltered.get()] == ["Arrival 2016 2160p HUN"]


def test_get_step_shows_the_module_release_filters() -> None:
    definition = Jackett.DEFINITION
    get = definition.action("get")

    assert get.overrides == ("min_seeders", "resolution", "size_limit_gb")
    assert all(definition.field(key).step for key in get.overrides)
    query = {spec.key: spec for spec in get.query}
    assert query["include"].advanced and query["exclude"].advanced
    assert set(query) == {"include", "exclude"}
    assert definition.action("enrich").overrides == ()


def test_get_joins_a_blank_and_a_current_year_search(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    queries = []

    def release(title: str, seeders: int) -> dict:
        return {"Title": title, "Link": f"https://t/{title}", "Size": 1024 ** 3, "Seeders": seeders,
                "CategoryDesc": "Movies"}

    answers = {
        "": [release("Arrival 2016 1080p", 10), release("Dune 2021 1080p", 30)],
        str(date.today().year): [release("Dune 2021 1080p", 30), release("Wicked 2024 1080p", 20)],
    }

    class Handler:
        def get(self, endpoint, params):
            queries.append(params["Query"].strip())
            return FakeResponse({"Results": answers[params["Query"].strip()]})

    consumer, _ = jackett_with_handler({"Results": []})
    consumer._handler = Handler()

    # merged without duplicates, most seeded first
    assert [item["title"] for item in consumer.get()] == ["Dune", "Wicked", "Arrival"]
    assert queries == ["", str(date.today().year)]
    consumer._limit = 2
    assert len(consumer.get()) == 2

    class Failing(Handler):
        def get(self, endpoint, params):
            if params["Query"].strip():
                return FakeResponse(None, status=500)
            return super().get(endpoint, params)

    consumer._handler = Failing()
    assert consumer.get() is None


def test_get_searches_the_include_words_of_its_query() -> None:
    """A blank search only reaches the last releases; include words go to the indexers."""
    from datetime import date

    queries = []
    year = date.today().year

    class Handler:
        def get(self, endpoint, params):
            queries.append(params["Query"])
            return FakeResponse({"Results": [
                {"Title": "The.Cycle.2026.1080p.WEB-DL", "Link": "https://t/1", "Size": 1024 ** 3, "Seeders": 9},
                {"Title": "Motorcycle.Diaries.2004.1080p", "Link": "https://t/2", "Size": 1024 ** 3, "Seeders": 3},
            ]})

    consumer, _ = jackett_with_handler({"Results": []})
    consumer._handler = Handler()

    assert [item["torrent"] for item in consumer.get({"include": "Cycle 2026"})] == ["The.Cycle.2026.1080p.WEB-DL"]
    assert queries == ["cycle 2026"] if year == 2026 else ["cycle 2026", f"cycle 2026 {year}"]
    queries.clear()
    consumer.get({"include": ["cycle"]})
    assert queries == ["cycle", f"cycle {year}"]

    queries.clear()
    assert [item["torrent"] for item in consumer.get({"include": "cycle", "exclude": True})] == []
    assert queries == ["", str(year)]
