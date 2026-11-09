"""Module definitions, field validation and flow/config preflight validation."""

import pytest

from cineflow.core import catalog, validation
from cineflow.core.schema import (
    ActionDefinition, Field, Issue, ModuleDefinition, get_path, is_secret_key,
    mask_secrets, validate_fields, validate_value,
)


def codes(issues: list[Issue]) -> list[tuple[str, str]]:
    return [('.'.join(str(part) for part in issue.path), issue.code) for issue in issues]


# ---------------------------------------------------------------- schema

def test_every_module_declares_a_definition_with_existing_actions() -> None:
    definitions = catalog.definitions()

    assert set(definitions) == set(catalog.module_ids())
    for module_id, definition in definitions.items():
        assert definition.id == module_id
        cls = catalog.module_class(module_id)
        for action in definition.actions:
            assert callable(getattr(cls, action.id, None)), f"{module_id}.{action.id}"
        assert definition.to_dict()['actions']


def test_catalog_rejects_unknown_modules() -> None:
    assert catalog.module_class('nope') is None
    assert catalog.module_class(None) is None
    assert catalog.definition('nope') is None


@pytest.mark.parametrize(('spec', 'value', 'code'), [
    (Field('a', 'boolean'), 'yes', 'type'),
    (Field('a', 'integer'), True, 'type'),
    (Field('a', 'integer'), 1.5, 'type'),
    (Field('a', 'number'), 'x', 'type'),
    (Field('a', 'string'), {'x': 1}, 'type'),
    (Field('a', 'list'), 'x', 'type'),
    (Field('a', 'object'), [], 'type'),
    (Field('a', 'select', options=('x', 'y')), 'z', 'choice'),
    (Field('a', 'url'), 'jellyfin:8096', 'format'),
    (Field('a', 'path'), '/abs', 'format'),
    (Field('a', 'path'), 'a/../../b', 'format'),
    (Field('a', 'integer', minimum=10), 5, 'range'),
    (Field('a', 'number', maximum=1), 2.5, 'range'),
])
def test_validate_value_rejects_bad_values(spec: Field, value, code: str) -> None:
    assert [issue.code for issue in validate_value(spec, value, ('a',))] == [code]


@pytest.mark.parametrize(('spec', 'value'), [
    (Field('a', 'boolean'), False),
    (Field('a', 'integer', minimum=1), 3),
    (Field('a', 'number'), 2.5),
    (Field('a', 'url'), 'https://x.example:9117/path'),
    (Field('a', 'path'), 'movies/trending'),
    (Field('a', 'select', options=('x',)), 'x'),
    (Field('a', 'secret'), 'token'),
])
def test_validate_value_accepts_good_values(spec: Field, value) -> None:
    assert validate_value(spec, value, ('a',)) == []


def test_field_definitions_reject_bad_declarations() -> None:
    with pytest.raises(ValueError):
        Field('a', 'color')
    with pytest.raises(ValueError):
        Field('a', 'select')
    with pytest.raises(ValueError):
        ActionDefinition('x', 'X', input='stream')


def test_validate_fields_handles_required_env_dotted_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    specs = (Field('token', 'secret', required=True), Field('ignore.users', 'list'))

    assert codes(validate_fields(specs, {})) == [('token', 'required')]
    assert codes(validate_fields(specs, 'x')) == [('', 'type')]
    assert codes(validate_fields(specs, {'token': 't', 'ignore': {'users': 'x'}})) == [('ignore.users', 'type')]
    assert codes(validate_fields(specs, {'token': 't', 'other': 1}, allow_unknown=False)) == [('other', 'unknown')]
    monkeypatch.setenv('MOD_TOKEN', 'x')
    assert validate_fields(specs, {}, env_prefix='mod') == []


def test_secret_helpers() -> None:
    definition = ModuleDefinition('m', 'M', fields=(Field('token', 'secret'), Field('url', 'url')))

    assert mask_secrets(definition, {'token': 't', 'url': 'u'}) == ({'url': 'u'}, ['token'])
    assert mask_secrets(definition, 'x') == ({}, [])
    assert is_secret_key('api_key') and is_secret_key('Password') and not is_secret_key('url')
    assert get_path({'a': {'b': 1}}, 'a.b') == 1 and get_path({'a': 1}, 'a.b', 'd') == 'd'
    assert str(Issue('error', ('a', 0), 'bad')) == 'ERROR a.0: bad'
    assert str(Issue('warning', (), 'bad')) == 'WARNING <root>: bad'


# ---------------------------------------------------------------- config

def test_validate_config_reports_modes_sections_and_instances() -> None:
    config = {
        'execution': 'turbo',
        'unknown': {},
        'tmdb': 'not a mapping',
        'jackett': {'url': 'nope'},
        'instances': {
            'jellyfin': {'module': 'jellyfin'},
            'Bad ID': {'module': 'jellyfin', 'config': {'url': 'http://j', 'token': 't'}},
            'home': {'module': 'jellyfin', 'name': 'Home', 'config': {'url': 'http://j'}},
            'ghost': {'module': 'ghost'},
            'broken': {'module': 'plex', 'config': 'x'},
        },
    }

    assert codes(validation.validate_config(config)) == [
        ('execution', 'choice'),
        ('unknown', 'unknown'),
        ('tmdb', 'type'),
        ('jackett.url', 'format'),
        ('instances.jellyfin', 'conflict'),
        ('instances.Bad ID', 'format'),
        ('instances.home.config.token', 'required'),
        ('instances.ghost.module', 'unknown_module'),
        ('instances.broken.config', 'type'),
    ]
    assert codes(validation.validate_config('x')) == [('', 'type')]
    assert codes(validation.validate_config({'instances': []})) == [('instances', 'type')]
    assert validation.validate_config(None) == []


def test_instance_inherits_module_defaults_and_reports_status() -> None:
    config = {
        'jellyfin': {'url': 'http://j', 'token': 'default-token', 'limit': 5},
        'instances': {'home': {'module': 'jellyfin', 'config': {'limit': 7}}},
    }

    assert validation.instance_config(config, 'home') == {'url': 'http://j', 'token': 'default-token', 'limit': 7}
    assert validation.instance_config(config, 'jellyfin')['limit'] == 5
    assert validation.instance_config(config, 'missing') == {}
    assert validation.status_of(validation.validate_instance(config, 'home')) == 'valid'
    assert validation.status_of(validation.validate_instance({}, 'jellyfin')) == 'incomplete'
    assert validation.status_of(validation.validate_instance(
        {'jellyfin': {'url': 'bad', 'token': 't'}}, 'jellyfin')) == 'invalid'
    assert codes(validation.validate_instance(config, 'missing')) == [('instances.missing', 'unknown_instance')]


# ---------------------------------------------------------------- flows

CONFIG = {
    'tmdb': {'token': 't'},
    'jackett': {'url': 'http://jackett', 'token': 't'},
    'jellyfin': {'url': 'http://jf', 'token': 't'},
    'transmission': {'url': 'http://tr'},
    'library': {'directory': 'movies'},
    'instances': {
        'home': {'module': 'jellyfin', 'name': 'Home', 'config': {}},
        'half': {'module': 'plex', 'name': 'Half', 'config': {'url': 'http://plex'}},
    },
}


def flow(*steps, **root) -> dict:
    return {'name': 'F', 'steps': list(steps), **root}


def test_flow_root_validation() -> None:
    issues = validation.validate_flow(
        {'name': '', 'enabled': 'yes', 'delay': 0, 'priority': 'high', 'description': 3, 'extra': 1, 'steps': []},
    )

    assert codes(issues) == [
        ('extra', 'unknown'), ('name', 'required'), ('enabled', 'type'), ('delay', 'range'),
        ('priority', 'type'), ('description', 'type'), ('steps', 'required'),
    ]
    assert codes(validation.validate_flow('x')) == [('', 'type')]


def test_step_structure_validation() -> None:
    issues = validation.validate_flow(flow(
        'not a step',
        {'module': 'tmdb', 'action': 'get', 'color': 'red'},
        {'name': 'a', 'action': 'get'},
        {'name': 'b', 'module': 'tmdb'},
        {'name': 'c', 'module': 'nope', 'action': 'get'},
        {'name': 'd', 'module': 'tmdb', 'action': '_results'},
        {'name': 'e', 'module': 'tmdb', 'action': 'search'},
        {'name': 'e', 'module': 'tmdb', 'action': 'get', 'config': 'x'},
        {'name': 7, 'module': 'tools', 'action': 'remove_duplicates', 'input': 'previous'},
    ), CONFIG)

    assert codes(issues) == [
        ('steps.0', 'type'),
        ('steps.1.color', 'unknown'), ('steps.1.name', 'required'),
        ('steps.2.module', 'required'),
        ('steps.3.action', 'required'),
        ('steps.4.module', 'unknown_module'),
        ('steps.5.action', 'unknown_action'),
        ('steps.6.action', 'undocumented'),
        ('steps.7.name', 'duplicate'), ('steps.7.config', 'type'),
        ('steps.8.name', 'type'),
    ]


def test_step_settings_and_required_values() -> None:
    issues = validation.validate_flow(flow(
        {'name': 'a', 'module': 'plex', 'action': 'get'},
        {'name': 'b', 'module': 'jackett', 'action': 'enrich', 'input': 'previous',
         'config': {'must_match': 'yes', 'kind': 'anime', 'token': '', 'mystery': 1}},
        {'name': 'c', 'module': 'tmdb', 'action': 'get', 'config': {'token': 'override'}},
    ), CONFIG)

    assert codes(issues) == [
        ('steps.0.config.url', 'required'), ('steps.0.config.token', 'required'),
        ('steps.1.config.must_match', 'type'),
        ('steps.1.config.token', 'required'),
        ('steps.1.config.kind', 'unknown'),
        ('steps.1.config.mystery', 'unknown'),
    ]


def test_step_instances_must_exist_match_and_be_valid() -> None:
    issues = validation.validate_flow(flow(
        {'name': 'a', 'module': 'jellyfin', 'instance': 'home', 'action': 'get'},
        {'name': 'b', 'module': 'jellyfin', 'instance': 'missing', 'action': 'get'},
        {'name': 'c', 'module': 'jellyfin', 'instance': 'half', 'action': 'get'},
        {'name': 'd', 'module': 'plex', 'instance': 'half', 'action': 'get'},
    ), CONFIG)

    assert codes(issues) == [
        ('steps.1.instance', 'unknown_instance'),
        ('steps.2.instance', 'conflict'),
        ('steps.3.instance', 'instance_status'),
    ]


def test_input_references_and_shapes() -> None:
    issues = validation.validate_flow(flow(
        {'name': 'first', 'module': 'tmdb', 'action': 'enrich', 'input': 'previous'},
        {'name': 'second', 'module': 'tmdb', 'action': 'get', 'input': '{{later}}'},
        {'name': 'third', 'module': 'tools', 'action': 'remove_duplicates', 'input': ['first', 'later', 3]},
        {'name': 'fourth', 'module': 'tmdb', 'action': 'enrich'},
        {'name': 'fifth', 'module': 'tmdb', 'action': 'enrich', 'input': 'Batman'},
        {'name': 'sixth', 'module': 'jackett', 'action': 'get', 'input': 42},
        {'name': 'seventh', 'module': 'jellyfin', 'action': 'unique', 'input': {
            'data': '{{first}}', 'query': {'isFavorite': 'yes', 'custom': 1}, 'other': 1}},
        {'name': 'eighth', 'module': 'tmdb', 'action': 'enrich', 'input': {'data': 5, 'query': {}}},
        {'name': 'ninth', 'module': 'jellyfin', 'action': 'get', 'input': {'query': 5}},
        {'name': 'tenth', 'module': 'tools', 'action': 'data_import', 'input': {'filename': {'a': 1}}},
        {'name': 'eleventh', 'module': 'library', 'action': 'get', 'input': 'previous'},
    ), CONFIG)

    assert codes(issues) == [
        ('steps.0.input', 'reference'),
        ('steps.1.input', 'reference'),
        ('steps.2.input.1', 'reference'), ('steps.2.input.2', 'reference'),
        ('steps.3.input', 'input'),
        ('steps.4.input', 'input'),
        ('steps.5.input', 'type'),
        ('steps.6.input.query.isFavorite', 'type'), ('steps.6.input.other', 'unknown'),
        ('steps.7.input.data', 'type'), ('steps.7.input.query', 'input'),
        ('steps.8.input.query', 'type'),
        ('steps.9.input.filename', 'type'),
        ('steps.10.input', 'input'),
    ]


def test_valid_structured_flow_has_no_issues() -> None:
    data = flow(
        {'name': 'trending', 'module': 'tmdb', 'action': 'get'},
        {'name': 'releases', 'module': 'jackett', 'action': 'enrich', 'input': 'previous',
         'config': {'must_match': True, 'season_pack_only': False}},
        {'name': 'missing', 'module': 'jellyfin', 'instance': 'home', 'action': 'unique',
         'input': {'data': 'previous', 'query': {'parentLibrary': 'Shows', 'isInverse': True}}},
        {'name': 'merge', 'module': 'tools', 'action': 'remove_duplicates', 'input': ['trending', '{{missing}}']},
        {'name': 'save', 'module': 'tools', 'action': 'data_export',
         'input': {'data': 'previous', 'filename': 'x.json'}},
        {'name': 'download', 'module': 'transmission', 'action': 'put', 'input': '{{merge}}'},
        enabled=True, delay=30, priority=1, description='TV', version=3, kind='tv',
    )

    assert validation.validate_flow(data, CONFIG) == []
    assert validation.flow_is_runnable(data, CONFIG)


def test_media_kind_is_a_flow_setting() -> None:
    tmdb_step = {'name': 'a', 'module': 'tmdb', 'action': 'get'}

    assert validation.validate_flow(flow(tmdb_step, kind='tv'), CONFIG) == []
    assert codes(validation.validate_flow(flow(tmdb_step, kind='anime'), CONFIG)) == [('kind', 'choice')]
    # a kind on a step is not a step setting
    assert codes(validation.validate_flow(flow({**tmdb_step, 'config': {'kind': 'tv'}}), CONFIG)) == [
        ('steps.0.config.kind', 'unknown')]


@pytest.mark.parametrize(('data', 'expected'), [
    ({'steps': []}, 'movie'),
    ({'kind': None, 'steps': []}, 'movie'),
    ({'kind': 'tv', 'steps': []}, 'tv'),
    ({'kind': 'both', 'steps': []}, 'both'),
    ({'steps': [{'config': {'kind': 'tv'}}]}, 'movie'),
    ({'kind': 'anime', 'steps': []}, None),
    ('x', None),
])
def test_flow_media_kind(data, expected) -> None:
    from cineflow.core.schema import flow_media_kind

    assert flow_media_kind(data) == expected


def test_limit_is_hidden_and_only_declared_where_it_is_used() -> None:
    definitions = catalog.definitions()
    with_limit = {mid for mid, item in definitions.items() if any(f.key == 'limit' for f in item.fields)}

    # every service with a collecting 'get' has the hidden limit; the library's 'limit' is its size
    assert with_limit == {'tmdb', 'jackett', 'jellyfin', 'plex', 'transmission', 'qbittorrent', 'library'}
    for module_id in ('tmdb', 'jackett', 'jellyfin', 'plex', 'transmission', 'qbittorrent'):
        spec = next(f for f in definitions[module_id].fields if f.key == 'limit')
        assert spec.to_dict()['hidden'] is True
        assert spec.default == 200
    # a value written in YAML is still accepted without warnings
    assert validation.validate_flow(flow(
        {'name': 'a', 'module': 'tmdb', 'action': 'get', 'config': {'limit': 50}},
    ), CONFIG) == []


def test_list_fields_declare_their_item_type() -> None:
    rules = catalog.definitions()['library'].action('put').fields[0]
    assert rules.key == 'poster_rules' and rules.to_dict()['item_type'] == 'object'
    assert Field('words', 'list').to_dict()['item_type'] == 'text'
    with pytest.raises(ValueError):
        Field('words', 'list', item_type='number')


def test_library_folder_and_release_preference_are_flow_settings() -> None:
    definitions = catalog.definitions()
    assert all(f.key != 'directory' for f in definitions['library'].fields)
    assert all(f.key != 'search_preference' for name in ('library', 'jackett') for f in definitions[name].fields)
    good = flow({'name': 'a', 'module': 'library', 'action': 'get'})
    good.update({'library_directory': 'films/new', 'search_preference': ['HUN']})
    assert validation.validate_flow(good, CONFIG) == []
    bad = flow({'name': 'a', 'module': 'library', 'action': 'get'})
    bad.update({'library_directory': '../x', 'search_preference': 'HUN'})
    assert codes(validation.validate_flow(bad, CONFIG)) == [('library_directory', 'format'),
                                                            ('search_preference', 'type')]


def test_run_kinds_of_a_flow() -> None:
    from cineflow.core.schema import run_kinds

    assert run_kinds('movie') == ('movie',)
    assert run_kinds('tv') == ('tv',)
    assert run_kinds('both') == ('movie', 'tv')


def test_flow_kind_accepts_both_and_rejects_others() -> None:
    steps = [{'name': 'a', 'module': 'tools', 'action': 'data_import'}]

    def kind_issues(kind):
        flow = {'name': 'x', 'kind': kind, 'steps': steps}
        return [issue for issue in validation.validate_flow(flow) if issue.path == ('kind',)]

    assert not kind_issues('both')
    assert 'both' in kind_issues('anime')[0].message


def test_library_query_takes_one_name_or_a_list() -> None:
    def library_issues(value):
        flow = {'name': 'x', 'steps': [{'name': 'a', 'module': 'jellyfin', 'action': 'get',
                                        'input': {'query': {'parentLibrary': value, 'isInverse': True}}}]}
        return [issue for issue in validation.validate_flow(flow) if 'parentLibrary' in issue.path]

    assert library_issues('Filmek') == []
    assert library_issues(['Trending Filmek', 'Trending Sorozatok']) == []
    assert [issue.path for issue in library_issues(['Filmek', {'x': 1}])] == [
        ('steps', 0, 'input', 'query', 'parentLibrary', 1)]


def test_unknown_settings_are_warned_about_as_having_no_effect() -> None:
    config = {
        'jackett': {'url': 'http://j', 'token': 't', 'search_preference': ['HUN']},
        'library': {'directory': 'film'},
        'instances': {'other': {'module': 'library', 'name': 'Other', 'config': {'directory': 'x'}}},
    }
    issues = validation.validate_config(config)

    assert {('.'.join(map(str, issue.path)), issue.code) for issue in issues} >= {
        ('jackett.search_preference', 'unknown'), ('library.directory', 'unknown'),
        ('instances.other.config.directory', 'unknown')}
    assert all(issue.level == 'warning' for issue in issues)
    assert "Unknown setting 'directory': it has no effect." in {issue.message for issue in issues}
    # the Modules page shows the same warning for the module settings
    assert [issue.code for issue in validation.validate_instance(config, 'library')
            if issue.path == ('library', 'directory')] == ['unknown']

    step = {'name': 'a', 'module': 'library', 'action': 'get', 'config': {'search_preference': ['HUN']}}
    step_issues = [(issue.path, issue.code) for issue in validation.validate_flow({'name': 'x', 'steps': [step]})]
    assert step_issues.count((('steps', 0, 'config', 'search_preference'), 'unknown')) == 1
