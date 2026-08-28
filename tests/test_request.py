"""Regression tests for HTTP response and cache handling."""

from json import JSONDecodeError
from unittest.mock import Mock

import pytest
import requests

from cineflow.utils.request import RequestHandler


def response(
    status: int = 200,
    content: bytes = b'{"result": true}',
    data: object = None,
    text: str = "",
    headers: dict | None = None,
    cookies: dict | None = None,
) -> Mock:
    """Create a minimal mocked requests response."""
    mocked = Mock()
    mocked.status_code = status
    mocked.content = content
    mocked.text = text
    mocked.headers = headers or {}
    mocked.cookies.get_dict.return_value = cookies or {}
    if data is None:
        mocked.json.side_effect = JSONDecodeError("not JSON", text, 0)
    else:
        mocked.json.return_value = data
    return mocked


def handler() -> RequestHandler:
    """Return a request handler without rate-limit delays."""
    request_handler = RequestHandler("https://example.invalid")
    request_handler.rate_limit = 0
    return request_handler


def test_successful_json_response_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_response = response(data={"result": True})
    request = Mock(return_value=mocked_response)
    monkeypatch.setattr(requests, "request", request)

    result = handler().get("status")

    assert result.data == {"result": True}
    assert result.status == 200


def test_non_json_response_preserves_protocol_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_response = response(
        content=b" torrent data \n",
        text=" torrent data \n",
        headers={"Content-Type": "text/plain"},
        cookies={"sid": "x"},
    )
    monkeypatch.setattr(requests, "request", Mock(return_value=mocked_response))

    result = handler().get("torrent")

    assert result.data == "torrent data"
    assert result.status == 200
    assert result.headers == {"Content-Type": "text/plain"}
    assert result.cookies == {"sid": "x"}


def test_empty_accepted_response_preserves_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_response = response(
        status=204,
        content=b"",
        headers={"X-Request-ID": "abc"},
        cookies={"sid": "x"},
    )
    monkeypatch.setattr(requests, "request", Mock(return_value=mocked_response))

    result = handler().get("empty")

    assert result.data is None
    assert result.status == 204
    assert result.headers == {"X-Request-ID": "abc"}
    assert result.cookies == {"sid": "x"}


def test_transport_exception_returns_status_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(requests, "request", Mock(side_effect=requests.RequestException("offline")))

    result = handler().get("offline")

    assert result.status == 0
    assert result.data is None


@pytest.mark.parametrize("cached", [[], {}])
def test_falsy_cached_values_do_not_issue_requests(monkeypatch: pytest.MonkeyPatch, cached: object) -> None:
    request_handler = handler()
    request_handler.cache_time = 60
    request_handler._cache_handler.read = Mock(return_value=cached)
    request = Mock()
    monkeypatch.setattr(requests, "request", request)

    result = request_handler.get("cached")

    assert result.data == cached
    request.assert_not_called()


def test_custom_ok_statuses_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    request_handler = handler()
    request_handler.ok_statuses = {206}
    monkeypatch.setattr(requests, "request", Mock(return_value=response(status=206, data={"partial": True})))

    assert request_handler.get("partial").status == 206


def test_none_ok_statuses_uses_raise_for_status(monkeypatch: pytest.MonkeyPatch) -> None:
    request_handler = handler()
    request_handler.ok_statuses = None
    mocked_response = response(status=200, data={"result": True})
    monkeypatch.setattr(requests, "request", Mock(return_value=mocked_response))

    assert request_handler.get("ok").status == 200
    mocked_response.raise_for_status.assert_called_once()


def test_invalid_ok_statuses_are_rejected() -> None:
    with pytest.raises(TypeError, match="ok_statuses"):
        handler().ok_statuses = [200]


def test_default_headers_are_not_shared_between_handlers() -> None:
    first = handler()
    second = handler()

    first.headers["X-Request-ID"] = "first"

    assert "X-Request-ID" not in second.headers
