"""Regression tests for bundled workflow examples."""

from pathlib import Path

import yaml


def test_from_lib_normalizes_jellyfin_titles_before_jackett_search() -> None:
    """Localized Jellyfin titles must be resolved before the torrent lookup."""
    flow_path = Path(__file__).parents[1] / "docker" / "examples" / "from_lib.yaml"

    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    steps = flow["steps"]
    names = [step["name"] for step in steps]
    normalize = steps[names.index("Normalize titles with TMDb")]

    assert names.index("Collect Jellyfin favorites") < names.index("Normalize titles with TMDb")
    assert names.index("Normalize titles with TMDb") < names.index("Add Jackett data")
    assert normalize == {
        "name": "Normalize titles with TMDb",
        "module": "tmdb",
        "action": "enrich",
        "input": "previous",
        "config": {"must_match": True},
    }
