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
    assert series_info(name) == {**expected, 'seasons': None, 'episodes': None, 'complete': False}


@pytest.mark.parametrize(("name", "seasons"), [
    ("Dark.S01-S03.1080p", [1, 2, 3]),
    ("Dark.S01-03.1080p", [1, 2, 3]),
    ("Dark.S01.S02.S03.1080p", [1, 2, 3]),
    ("Dark.Season.1-3.1080p", [1, 2, 3]),
    ("Dark.Seasons.2-3", [2, 3]),
    ("The.Office.S01-S09.COMPLETE", list(range(1, 10))),
    ("Dark.S02.1080p", [2]),
    ("Shogun.2024.S01.COMPLETE.2160p", [1]),
    ("Show.S01-HUN", [1]),
    ("Dark.S02E01-E03.1080p", []),          # episodes, not a season
    ("Dark.Complete.Series.1080p", None),   # the whole series
])
def test_release_seasons_cover_ranges_lists_and_complete_series(name: str, seasons) -> None:
    from cineflow.utils.misc import release_seasons

    info = series_info(name)
    assert info["title"] == "Dark" or info["title"] in ("The Office", "Shogun", "Show")
    assert release_seasons(info) == seasons


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


# ------------------------------------------------------------ next season

@pytest.mark.parametrize(("have", "watched", "aired", "expected"), [
    # a series not in the libraries starts with the whole season 1
    (set(), set(), {1: 8, 2: 8}, (1, None)),
    (set(), set(), None, (1, None)),
    (set(), set(), {}, (1, None)),
    # the whole next season follows once 75% of the latest one is watched
    ({(1, e) for e in range(1, 9)}, {(1, e) for e in range(1, 7)}, {1: 8, 2: 8}, (2, None)),
    ({(1, e) for e in range(1, 9)}, {(1, e) for e in range(1, 6)}, {1: 8, 2: 8}, None),
    # the latest season in the libraries counts, older ones do not
    ({(1, 1), (2, 1), (2, 2)}, {(1, 1), (2, 1), (2, 2)}, {1: 1, 2: 2, 3: 5}, (3, None)),
    ({(1, 1), (2, 1), (2, 2)}, {(1, 1)}, {1: 1, 2: 2, 3: 5}, None),
    # aired episodes missing from the latest season come first, watched or not
    ({(2, 1), (2, 2)}, set(), {1: 8, 2: 5}, (2, [3, 4, 5])),
    ({(2, 1), (2, 3)}, {(2, 1), (2, 3)}, {2: 3, 3: 8}, (2, [2])),
    # a season that has not aired yet is not chosen; without TMDb data it is assumed
    ({(1, 1)}, {(1, 1)}, {1: 1}, None),
    ({(1, 1)}, {(1, 1)}, None, (2, None)),
])
def test_season_plan_follows_the_watched_share(have, watched, aired, expected) -> None:
    from cineflow.utils.misc import plan_season

    assert plan_season(have, watched, aired, 75) == expected


@pytest.mark.parametrize(("name", "episode", "episodes"), [
    ("Dark.S02E01-E03.1080p", 1, [1, 2, 3]),
    ("Dark.S02E01-03.1080p", 1, [1, 2, 3]),
    ("Dark.S02E04E05.1080p", 4, [4, 5]),
    ("Dark.S02E05.1080p", 5, None),
    ("Dark.S02E05-1080p", 5, None),
])
def test_episode_ranges_of_releases(name: str, episode: int, episodes) -> None:
    from cineflow.utils.misc import release_episodes

    info = series_info(name)
    assert (info["episode"], info["episodes"]) == (episode, episodes)
    assert release_episodes(info) == (episodes or [episode])


def test_tmdb_aired_seasons_stop_at_the_last_aired_episode() -> None:
    details = {
        "seasons": [
            {"season_number": 0, "episode_count": 3},   # specials
            {"season_number": 1, "episode_count": 8},
            {"season_number": 2, "episode_count": 10},
            {"season_number": 3, "episode_count": 9},   # announced
        ],
        "last_episode_to_air": {"season_number": 2, "episode_number": 4},
    }

    assert Tmdb.aired_seasons(details) == {1: 8, 2: 4}
    assert Tmdb.aired_seasons({"seasons": []}) == {}
    assert Tmdb.aired_seasons(None) == {}


def test_tmdb_enrich_adds_aired_seasons_to_series_only() -> None:
    details = {"id": 7, "name": "Dark", "first_air_date": "2017-12-01",
               "seasons": [{"season_number": 1, "episode_count": 10}],
               "last_episode_to_air": {"season_number": 1, "episode_number": 10}}
    tv = Tmdb(config={"token": "t", "kind": "tv"})
    tv._handler = Mock()
    tv._handler.get.return_value = SimpleNamespace(status=200, data=details)

    assert tv.search({"title": "Dark", "tmdbid": 7})["seasons_aired"] == {1: 10}
    movie = Tmdb(config={"token": "t"})
    movie._handler = Mock()
    movie._handler.get.return_value = SimpleNamespace(
        status=200, data={"id": 8, "title": "Arrival", "release_date": "2016-01-01"})
    assert "seasons_aired" not in movie.search({"title": "Arrival", "year": "2016", "tmdbid": 8})


def jellyfin_tv(episodes: dict) -> Jellyfin:
    """Jellyfin for TV whose series list and episode lists are canned; ``episodes`` by user."""
    client = Jellyfin.__new__(Jellyfin)
    client._cfg = {}
    client.name = "jellyfin"
    client._kind = "tv"
    client._user_list = {"anna": "u1", "bob": "u2"}
    client._collect = Mock(return_value=[{"title": "Dark", "year": "2017", "tmdbid": 7, "jellyfinid": "s7"}])
    client._handler = Mock()
    client._handler.get.side_effect = lambda endpoint, params: SimpleNamespace(
        status=200, data={"Items": episodes[params["UserId"]]})
    return client


def episode(season: int, number: int, played: bool = False, **extra) -> dict:
    return {"ParentIndexNumber": season, "IndexNumber": number, "UserData": {"Played": played}, **extra}


def test_jellyfin_next_season_reads_episodes_and_anyones_watched_state() -> None:
    season_one = [episode(1, n) for n in range(1, 5)]
    client = jellyfin_tv({
        "u1": season_one[:2] + [episode(1, 3, True), episode(1, 4, True), episode(1, 5, True, LocationType="Virtual")],
        "u2": [episode(1, 1, True), episode(1, 2), *season_one[2:], episode(0, 1, True)],
    })
    items = [
        {"title": "Dark", "year": "2017", "tmdbid": 7, "seasons_aired": {1: 4, 2: 4}, "episode": 3},
        {"title": "New Show", "tmdbid": 9, "seasons_aired": {1: 6}},
    ]

    result = client.next_season(items, {"parentLibrary": ["Trending Sorozatok"], "isInverse": True})

    # 3 of the 4 episodes in the library were watched by someone (75%)
    assert [(item["title"], item["season"]) for item in result] == [("Dark", 2), ("New Show", 1)]
    assert "episode" not in result[0]
    client._collect.assert_called_once_with(
        query={"parentLibrary": ["Trending Sorozatok"], "isInverse": True, "allUsers": True})
    client._cfg = {"watched_percent": 100}
    assert [item["title"] for item in client.next_season(items, None)] == ["New Show"]


def test_jellyfin_next_season_fails_closed_and_leaves_movies_alone() -> None:
    client = jellyfin_tv({"u1": [], "u2": []})
    client._collect = Mock(return_value=None)
    with pytest.raises(ValueError, match="Failed to query the Jellyfin series"):
        client.next_season([{"title": "Dark"}])

    client = jellyfin_tv({})
    client._handler.get.side_effect = lambda endpoint, params: SimpleNamespace(status=500, data=None)
    with pytest.raises(ValueError, match="episodes of Jellyfin series s7"):
        client.next_season([{"title": "Dark", "year": "2017", "tmdbid": 7}])

    assert client.next_season([]) == []
    client._kind = "movie"
    assert client.next_season([{"title": "Arrival"}]) == [{"title": "Arrival"}]


def season_releases(*names: str) -> Jackett:
    consumer = Jackett(config={"url": "https://jackett.invalid", "token": "t", "kind": "tv"})
    consumer._handler = SimpleNamespace(get=lambda endpoint, params: SimpleNamespace(status=200, data={"Results": [
        {"Title": name, "Link": f"https://t/{name}", "Size": 1024 ** 3, "Seeders": 10} for name in names]}))
    return consumer


@pytest.mark.parametrize(("season", "torrent"), [
    (2, "Dark.S02.1080p"),                 # the single season wins over packs
    (3, "Dark.S03-S04.1080p"),             # no single season: the narrowest pack
    (1, "Dark.S01-S03.1080p"),
    (5, "Dark.Complete.Series.1080p"),     # the whole series as the last resort
])
def test_jackett_picks_one_season_before_multi_season_packs(season: int, torrent: str) -> None:
    consumer = season_releases("Dark.Complete.Series.1080p", "Dark.S01-S03.1080p", "Dark.S03-S04.1080p",
                               "Dark.S02E01.1080p", "Dark.S02.1080p", "Other.S03.1080p")

    assert consumer.search({"title": "Dark", "season": season})["torrent"] == torrent


def test_jackett_season_search_without_a_covering_release() -> None:
    consumer = season_releases("Dark.S01.1080p", "Dark.S03E05.1080p")

    assert consumer.search({"title": "Dark", "season": 2}) is None
    # without a season a series release is matched as before; episodes stay out of it
    assert consumer.search({"title": "Dark"})["torrent"] == "Dark.S01.1080p"


def torrents(result) -> list[str]:
    return [item["torrent"] for item in (result if isinstance(result, list) else [result])]


def test_season_without_pack_uses_its_episode_releases_before_multi_season_packs() -> None:
    consumer = season_releases("Dark.S01-S03.1080p", "Dark.S02E01.1080p", "Dark.S02E02-E03.1080p",
                               "Dark.S02E03.720p", "Dark.S02E04.1080p", "Dark.S03E01.1080p")
    media = {"title": "Dark", "season": 2, "seasons_aired": {1: 4, 2: 4}}

    # one release per episode; a single-episode release wins over a range covering it
    assert torrents(consumer.search(media)) == [
        "Dark.S02E01.1080p", "Dark.S02E02-E03.1080p", "Dark.S02E04.1080p"]
    # only the missing episodes of an airing season; never a pack for them
    assert torrents(consumer.search({**media, "wanted_episodes": [3, 4]})) == ["Dark.S02E03.720p", "Dark.S02E04.1080p"]
    assert consumer.search({**media, "season": 3, "wanted_episodes": [2]}) is None
    # a season pack still wins over episodes, and a multi-season pack is the last resort
    assert torrents(season_releases("Dark.S02.1080p", "Dark.S02E01.1080p").search(media)) == ["Dark.S02.1080p"]
    assert torrents(season_releases("Dark.S01-S03.1080p").search(media)) == ["Dark.S01-S03.1080p"]


def test_enrich_turns_a_season_into_one_item_per_episode_release() -> None:
    consumer = season_releases("Dark.S02E01.1080p", "Dark.S02E02.1080p")
    item = {"title": "Dark", "season": 2, "seasons_aired": {2: 2}, "tmdbid": 7}

    result = consumer.enrich([item])

    assert [(entry["season"], entry["episode"], entry["torrent"]) for entry in result] == [
        (2, 1, "Dark.S02E01.1080p"), (2, 2, "Dark.S02E02.1080p")]
    assert result[0]["tmdbid"] == 7 and result[0] is not result[1]


def test_jellyfin_next_season_lists_the_missing_episodes_of_an_airing_season() -> None:
    client = jellyfin_tv({"u1": [episode(1, 1), episode(1, 2)], "u2": []})
    item = {"title": "Dark", "year": "2017", "tmdbid": 7, "seasons_aired": {1: 4}, "wanted_episodes": [9]}

    result = client.next_season([item])

    # nobody watched anything, yet the aired episodes 3 and 4 of season 1 are missing
    assert [(entry["season"], entry["wanted_episodes"]) for entry in result] == [(1, [3, 4])]
    # nothing missing and nothing watched: no season to download yet
    assert client.next_season([{**item, "seasons_aired": {1: 2}}]) == []
