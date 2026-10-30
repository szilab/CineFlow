"""TV series support across release parsing, integrations and the library."""

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cineflow.integrations.jackett import Jackett
from cineflow.integrations.jellyfin import Jellyfin
from cineflow.integrations.qbittorrent import QBittorrent
from cineflow.integrations.tmdb import Tmdb
from cineflow.integrations.transmission import Transmission
from cineflow.internal.library import Library
from cineflow.utils import directory
from cineflow.utils.misc import release_parsers, series_info


@pytest.mark.parametrize(("name", "expected"), [
    ("The.Last.of.Us.S01E02.1080p.WEB.H264",
     {"title": "The Last of Us", "year": None, "season": 1, "episode": 2}),
    ("Shogun.2024.S01.COMPLETE.2160p",
     {"title": "Shogun", "year": "2024", "season": 1, "episode": None}),
    ("Fargo (2014) Season 5 1080p",
     {"title": "Fargo", "year": "2014", "season": 5, "episode": None}),
    ("Show.Name.S1E2.x264", {"title": "Show Name", "year": None, "season": 1, "episode": 2}),
    ("Show.S01-HUN", {"title": "Show", "year": None, "season": 1, "episode": None}),
    ("1923.S01E01.720p", {"title": "1923", "year": None, "season": 1, "episode": 1}),
])
def test_series_info_parses_episode_and_season_releases(name: str, expected: dict) -> None:
    assert series_info(name) == expected


@pytest.mark.parametrize("name", ["", None, "Movie.2019.1080p", "S01E01.Something", "Sneaky.Movie.2020"])
def test_series_info_rejects_names_without_a_season_marker(name) -> None:
    assert series_info(name) is None


def test_release_parsers_keep_movie_parsing_for_movies() -> None:
    mappings, transforms = release_parsers(kind="movie", source="name")

    assert mappings == {"title": ["name"], "year": ["name"]}
    assert transforms["year"]("A.Movie.2024.1080p") == "2024"


def test_module_kind_comes_from_configuration() -> None:
    assert Tmdb(config={"token": "t", "kind": "tv"}).kind == "tv"
    assert Tmdb(config={"token": "t"}).kind == "movie"
    with pytest.raises(ValueError, match="Kind"):
        Tmdb(config={"token": "t", "kind": "anime"})


def test_tv_mapping_accepts_a_missing_year_but_movies_do_not() -> None:
    tv = Tmdb(config={"token": "t", "kind": "tv"})
    movie = Tmdb(config={"token": "t"})

    assert tv.map({"name": "Dark"}) == {"title": "Dark"}
    assert movie.map({"title": "Dark"}) == {}


def test_tv_title_match_ignores_an_unknown_year() -> None:
    tv = Tmdb(config={"token": "t", "kind": "tv"})
    movie = Tmdb(config={"token": "t"})

    assert tv.match([{"title": "Dark"}], {"title": "Dark", "year": "2017"}) == {"title": "Dark"}
    assert movie.match([{"title": "Dark"}], {"title": "Dark", "year": "2017"}) is None
    # a known, different year still prevents a series match
    assert tv.match([{"title": "Dark", "year": "2001"}], {"title": "Dark", "year": "2017"}) is None


def test_tmdb_tv_uses_tv_endpoints() -> None:
    client = Tmdb(config={"token": "t", "kind": "tv", "limit": 10})
    client._handler = Mock()
    client._handler.get.side_effect = [
        SimpleNamespace(status=200, data={"results": [
            {"id": 1, "name": "Dark", "first_air_date": "2017-12-01", "poster_path": "/p.jpg"},
        ]}),
        SimpleNamespace(status=200, data={"imdb_id": "tt5753856"}),
        SimpleNamespace(status=200, data={"results": []}),
    ]

    result = client.get()

    assert result == [{
        "title": "Dark", "year": "2017", "tmdbid": 1,
        "poster": "https://image.tmdb.org/t/p/original/p.jpg", "imdbid": 5753856,
    }]
    endpoints = [call.kwargs["endpoint"] for call in client._handler.get.call_args_list]
    assert endpoints[0] == "/trending/tv/week"
    assert "/tv/1/external_ids" in endpoints


@dataclass
class FakeResponse:
    data: dict | None
    status: int = 200


def jackett(results: list, **config) -> tuple[Jackett, Mock]:
    client = Jackett(config={"url": "https://jackett.invalid", "token": "t", "kind": "tv", **config})
    client._handler = Mock()
    client._handler.get.return_value = FakeResponse({"Results": results})
    return client, client._handler


def release(title: str, seeders: int = 10) -> dict:
    return {"Title": title, "Link": f"https://t/{title}", "Size": 1024 ** 3, "Seeders": seeders}


def test_jackett_tv_uses_the_tv_category_and_skips_single_episodes() -> None:
    client, handler = jackett([
        release("Dark.S01E01.1080p", seeders=50),
        release("Dark.S01.1080p.HUN", seeders=20),
        release("Dark.S02.720p", seeders=5),
    ])

    results = client.get()

    assert handler.get.call_args.kwargs["params"]["Category[]"] == "5000"
    assert [(item["title"], item["season"]) for item in results] == [("Dark", 1), ("Dark", 2)]
    assert all("episode" not in item for item in results)


def test_jackett_tv_can_keep_single_episodes() -> None:
    client, _ = jackett([release("Dark.S01E01.1080p"), release("Dark.S01E02.1080p")], season_pack_only=False)

    assert [item["episode"] for item in client.get()] == [1, 2]


def test_jackett_tv_search_uses_the_title_only_and_matches_without_year() -> None:
    client, handler = jackett([release("Dark.S01.1080p")])

    match = client.search({"title": "Dark", "year": "2017", "tmdbid": 1})

    assert match["link"] == "https://t/Dark.S01.1080p"
    assert handler.get.call_count == 1
    assert handler.get.call_args.kwargs["params"]["Query"] == "Dark"


def test_jackett_tv_search_propagates_api_failure() -> None:
    client, handler = jackett([])
    handler.get.return_value = FakeResponse(None, status=500)

    assert client._search_w_title({"title": "Dark"}) is None


def test_jellyfin_tv_queries_series_items() -> None:
    client = Jellyfin(config={"url": "http://jf", "token": "t", "kind": "tv"})
    client._user_list = {"me": "u1"}
    client._handler = Mock()
    client._handler.get.return_value = SimpleNamespace(status=200, data={"Items": [
        {"Name": "Dark", "ProductionYear": 2017, "Id": "j1", "ProviderIds": {"Tmdb": "1"}},
    ]})

    assert client._get_items({}) == [{"title": "Dark", "year": "2017", "jellyfinid": "j1", "tmdbid": "1"}]
    assert client._handler.get.call_args.kwargs["params"]["includeItemTypes"] == "Series"


@pytest.mark.parametrize("client_class", [Transmission, QBittorrent])
def test_torrent_clients_parse_series_names(client_class) -> None:
    client = client_class(config={"url": "http://client", "kind": "tv"})

    assert client.map({"name": "Dark.S02E03.1080p", "progress": 1}) == {
        "title": "Dark", "season": 2, "episode": 3,
        **({"percent_done": 1} if client_class is QBittorrent else {}),
    }


def test_library_exports_series_with_a_season_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXPORT_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("MEDIA_DIRECTORY", str(tmp_path / "no-media"))
    library = Library(config={"directory": "shows", "kind": "tv"})
    monkeypatch.setattr(library, "_create_poster", lambda media: None)

    library.put([{"title": "Dark", "year": "2017", "tmdbid": 1, "season": 2, "poster": "p"}])
    library.put([{"title": "Unknown Year", "tmdbid": 5, "poster": "p"}])

    item = tmp_path / "shows" / "Dark (2017) [tmdbid-1]"
    assert (item / "Season 02" / "Dark S02E01.mkv").is_file()
    assert json.loads((item / "data.json").read_text())["season"] == 2
    assert (tmp_path / "shows" / "Unknown Year [tmdbid-5]" / "Season 01").is_dir()
    assert sorted(entry["title"] for entry in library.get()) == ["Dark", "Unknown Year"]


def test_directory_season_number_is_clamped() -> None:
    assert directory.DirectoryHandler._season_number("3") == 3
    assert directory.DirectoryHandler._season_number(None) == 1
    assert directory.DirectoryHandler._season_number(500) == 99
