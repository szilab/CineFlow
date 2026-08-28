"""Regression tests for consumer matching and set operations."""

import pytest

from cineflow.core.bases.module import ConsumerBase


class FakeConsumer(ConsumerBase):
    """Minimal consumer with deterministic remote results."""

    def __init__(self, results: list[dict] | None) -> None:
        super().__init__(url="https://example.invalid")
        self.results = results

    def get(self, query=None) -> list[dict] | None:
        return self.results

    def search(self, media: dict) -> dict:
        return None


@pytest.fixture
def media() -> list[dict]:
    return [
        {"title": "Arrival", "year": "2016", "tmdbid": "329865"},
        {"title": "Primer", "year": "2004", "imdbid": "tt0390384"},
    ]


def test_common_returns_items_present_in_remote_results(media: list[dict]) -> None:
    consumer = FakeConsumer([{"title": "Arrival", "year": "2016"}])

    assert consumer.common(media) == [media[0]]


def test_common_returns_empty_when_remote_results_are_empty(media: list[dict]) -> None:
    assert FakeConsumer([]).common(media) == []


def test_unique_returns_input_when_remote_results_are_empty(media: list[dict]) -> None:
    assert FakeConsumer([]).unique(media) == media


def test_unique_returns_empty_when_remote_query_fails(media: list[dict]) -> None:
    assert FakeConsumer(None).unique(media) == []


@pytest.mark.parametrize("kind", ["movie", "tv"])
def test_kind_accepts_supported_values(kind: str) -> None:
    consumer = FakeConsumer([])

    consumer.kind = kind

    assert consumer.kind == kind


@pytest.mark.parametrize("kind", ["banana", None, ""])
def test_kind_rejects_unsupported_values(kind: str | None) -> None:
    consumer = FakeConsumer([])

    with pytest.raises(ValueError, match="Kind must be either"):
        consumer.kind = kind


def test_limit_can_be_updated_and_keeps_its_minimum_value() -> None:
    consumer = FakeConsumer([])

    consumer.limit = 2
    assert consumer.limit == 10
    consumer.limit = 25

    assert consumer.limit == 25


def test_match_uses_title_and_year_without_ids() -> None:
    consumer = FakeConsumer([])
    media = {"title": "The Arrival", "year": "2016"}
    result = {"title": "The Arrival", "year": "2016"}

    assert consumer.match([result], media) == result


def test_match_tolerates_missing_alternate_titles() -> None:
    consumer = FakeConsumer([])
    media = {"title": "The Arrival", "year": "2016"}
    result = {"title": "The Arrival", "year": "2016"}

    assert consumer._match_w_title(result, media) is True


def test_match_uses_alternate_title_after_primary_title() -> None:
    consumer = FakeConsumer([])
    media = {"title": "Localized Title", "alttitle": "Original Title", "year": "2016"}
    result = {"title": "Different Title", "alttitle": "Original Title", "year": "2016"}

    assert consumer.match([result], media) == result
