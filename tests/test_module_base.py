"""Module base mapping and identity behavior tests."""

import pytest

from cineflow.core.bases.module import ModuleBase


class SampleModule(ModuleBase):
    """Concrete module base for mapping behavior."""

    def __init__(self, config=None) -> None:
        super().__init__(config=config)
        self.mappings = {"title": ["name"], "year": ["release_year"], "imdbid": ["imdb"]}
        self.transforms = {"imdbid": lambda value: int(value.removeprefix("tt"))}


def test_module_maps_aliases_and_transforms() -> None:
    module = SampleModule()
    assert module.map({"name": "Film", "release_year": 2024, "imdb": "tt42"}) == {
        "title": "Film", "year": 2024, "imdbid": 42,
    }


def test_module_rejects_invalid_and_incomplete_items() -> None:
    module = SampleModule()
    assert module.map("not-a-dict") == {}
    assert module.map({"name": "Film"}) == {}
    assert module.map({"name": "Film", "release_year": 2024}) == {"title": "Film", "year": 2024}
    module.empty_property_allowed = True
    assert module.map({"name": "Film", "release_year": 2024}) == {"title": "Film", "year": 2024}


def test_module_configuration_and_properties(monkeypatch) -> None:
    monkeypatch.setenv("SAMPLEMODULE_SETTING", "environment")
    supplied_config = {"setting": "file", "nested": {"value": 3}}
    global_config = {"setting": "global", "retained": 50}
    monkeypatch.setattr("cineflow.core.bases.module.cfg", lambda key: global_config)
    module = SampleModule(supplied_config)
    assert module.cfg("setting") == "environment"
    assert module.cfg("nested.value") == 3
    assert module.cfg("retained") == 50
    module.mappings = {"title": ["title"], "year": ["year"]}
    module.transforms = {}
    assert module.mappings == {"title": ["title"], "year": ["year"]}
    assert module.transforms == {}
    assert supplied_config == {"setting": "file", "nested": {"value": 3}}
    assert global_config == {"setting": "global", "retained": 50}


def test_module_step_configuration_overrides_global(monkeypatch) -> None:
    monkeypatch.setattr(
        "cineflow.core.bases.module.cfg",
        lambda key: {
            "global_only": "global",
            "setting": "global",
            "nested": {"retained": 1, "overridden": "global"},
        },
    )

    module = SampleModule({
        "step_only": "step",
        "setting": "step",
        "nested": {"overridden": "step"},
    })

    assert module.cfg("global_only") == "global"
    assert module.cfg("step_only") == "step"
    assert module.cfg("setting") == "step"
    assert module.cfg("nested.retained") == 1
    assert module.cfg("nested.overridden") == "step"


def test_module_required_configuration_is_enforced() -> None:
    class RequiredModule(ModuleBase):
        def __init__(self):
            super().__init__(config={}, required=["token"])

    with pytest.raises(ValueError, match="Missing required"):
        RequiredModule()
