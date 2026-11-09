"""Action stages and the funnel model of the simple flow editor (web/static/funnel.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from cineflow.core import catalog
from cineflow.core.schema import INPUT_BOTH, INPUT_DATA, INPUT_QUERY, STAGES, ActionDefinition

ROOT = Path(__file__).resolve().parent.parent
FUNNEL_JS = ROOT / 'cineflow' / 'web' / 'static' / 'funnel.js'
EXAMPLES = ROOT / 'tests' / 'data'
NODE = shutil.which('node')


def test_action_stage_is_derived_from_input_and_side_effects() -> None:
    assert ActionDefinition('get', 'Get', input=INPUT_QUERY).effective_stage == 'source'
    assert ActionDefinition('enrich', 'Enrich', input=INPUT_DATA).effective_stage == 'enrich'
    assert ActionDefinition('unique', 'Unique', input=INPUT_BOTH).effective_stage == 'filter'
    assert ActionDefinition('put', 'Put', input=INPUT_DATA, side_effects=True).effective_stage == 'output'
    assert ActionDefinition('remove', 'Remove', input=INPUT_DATA, destructive=True).effective_stage == 'output'
    declared = ActionDefinition('merge', 'Merge', input=INPUT_DATA, stage='combine')
    assert declared.effective_stage == 'combine'
    assert declared.to_dict()['stage'] == 'combine'
    assert declared.to_dict()['local'] is False


def test_action_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match='Unknown stage'):
        ActionDefinition('x', 'X', stage='sideways')


def test_published_actions_have_the_expected_stages() -> None:
    stages = {(module_id, action.id): action.effective_stage
              for module_id, definition in catalog.definitions().items() for action in definition.actions}
    assert set(stages.values()) <= set(STAGES)
    assert stages[('tmdb', 'get')] == 'source'
    assert stages[('tools', 'data_import')] == 'source'
    assert stages[('jackett', 'enrich')] == 'enrich'
    assert stages[('tools', 'remove_duplicates')] == 'combine'
    assert stages[('jellyfin', 'unique')] == 'filter'
    assert stages[('tmdb', 'exclude')] == 'filter'
    assert stages[('tools', 'filter_items')] == 'filter'
    assert stages[('transmission', 'put')] == 'output'
    assert stages[('library', 'remove')] == 'output'
    assert stages[('tools', 'data_export')] == 'output'
    # exactly one combine action, so several sources can always be merged
    assert list(stages.values()).count('combine') == 1


def test_only_service_free_actions_are_local() -> None:
    local = {(module_id, action.id)
             for module_id, definition in catalog.definitions().items()
             for action in definition.actions if action.to_dict()['local']}
    assert local == {(module_id, 'exclude') for module_id in ('tmdb', 'jackett', 'jellyfin', 'plex')} | {
        ('tools', 'filter_items')}


# ------------------------------------------------------------ funnel model

STAGE_MAP = {f'{module_id}.{action.id}': action.effective_stage
             for module_id, definition in catalog.definitions().items() for action in definition.actions}

HARNESS = """
const F = require(process.argv[1]);
const { stages, script } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const stageOf = (step) => stages[`${step.module}.${step.action}`] || null;
const names = (funnel) => funnel && {
  lanes: funnel.lanes.map((lane) => [lane.source.name, ...lane.enrich.map((step) => step.name)]),
  combine: funnel.combine && funnel.combine.name,
  filters: funnel.filters.map((step) => step.name),
  outputs: funnel.outputs.map((step) => step.name),
};
const out = new Function('F', 'stageOf', 'names', script)(F, stageOf, names);
process.stdout.write(JSON.stringify(out === undefined ? null : out));
"""


def run_funnel(script: str, **values) -> object:
    """Run a JavaScript snippet against funnel.js; ``values`` become constants."""
    if NODE is None:
        pytest.skip('Node.js is not installed')
    prelude = ''.join(f'const {key} = {json.dumps(value)};\n' for key, value in values.items())
    result = subprocess.run(
        [NODE, '-e', HARNESS, str(FUNNEL_JS)],
        input=json.dumps({'stages': STAGE_MAP, 'script': prelude + script}),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def example_steps(name: str) -> list:
    return yaml.safe_load((EXAMPLES / name).read_text(encoding='utf-8'))['steps']


def test_single_source_flow_reads_as_funnel_and_writes_back_unchanged() -> None:
    steps = example_steps('from_lib.yaml')
    result = run_funnel("""
        const read = F.toFunnel(steps, stageOf);
        const before = JSON.stringify(steps);
        return { funnel: names(read.funnel), same: JSON.stringify(F.fromFunnel(read.funnel)) === before };
    """, steps=steps)
    assert result['funnel'] == {
        'lanes': [['Collect Jellyfin favorites', 'Normalize titles with TMDb', 'Add Jackett data']],
        'combine': None, 'filters': [], 'outputs': ['Add to Transmission'],
    }
    assert result['same'] is True


def test_merged_sources_read_as_lanes_and_keep_the_written_merge_order() -> None:
    steps = example_steps('to_lib.yaml')[:8]
    result = run_funnel("""
        const read = F.toFunnel(steps, stageOf);
        const before = JSON.stringify(steps);
        return { funnel: names(read.funnel), same: JSON.stringify(F.fromFunnel(read.funnel)) === before };
    """, steps=steps)
    assert result['funnel'] == {
        'lanes': [['Collect from Jackett', 'Extend with TMDB data'], ['Collect from TMDB', 'Extend with Jackett data']],
        'combine': 'Merge data Jackett and TMDb data',
        'filters': ['Filter out Jellyfin existing media from online source', 'Exclude items by ID'],
        'outputs': ['Export to library'],
    }
    assert result['same'] is True


@pytest.mark.parametrize(('steps', 'reason'), [
    (example_steps('to_lib.yaml'), 'starts a second pipeline'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'}, {'name': 'b', 'module': 'tmdb', 'action': 'nope'}],
     'does not know'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get', 'input': {'data': 42}}], 'custom input'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'}, {'module': 'tools', 'action': 'remove_duplicates'}],
     'has no name'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'}, {'name': 'a', 'module': 'tmdb', 'action': 'get'}],
     'used twice'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'}, {'name': 'b', 'module': 'jackett', 'action': 'get'},
      {'name': 'c', 'module': 'jellyfin', 'action': 'unique', 'input': 'previous'}],
     'only one of several sources'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'}, {'name': 'b', 'module': 'jackett', 'action': 'get'},
      {'name': 'c', 'module': 'tools', 'action': 'remove_duplicates', 'input': ['b']}],
     'does not merge exactly'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'}, {'name': 'b', 'module': 'tmdb', 'action': 'get'},
      {'name': 'c', 'module': 'jackett', 'action': 'enrich', 'input': '{{a}}'}],
     'step before it'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get', 'input': 'previous'}], 'also takes the items'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'},
      {'name': 'b', 'module': 'library', 'action': 'put', 'input': 'previous'},
      {'name': 'c', 'module': 'jellyfin', 'action': 'unique', 'input': 'previous'}],
     'filters after an action'),
    ([{'name': 'a', 'module': 'tmdb', 'action': 'get'},
      {'name': 'b', 'module': 'library', 'action': 'put', 'input': 'previous'},
      {'name': 'c', 'module': 'transmission', 'action': 'put', 'input': 'previous'}],
     'result of the filters'),
])
def test_flows_outside_the_funnel_shape_explain_why(steps: list, reason: str) -> None:
    result = run_funnel('return F.toFunnel(steps, stageOf);', steps=steps)
    assert result['funnel'] is None
    assert reason in result['reason']


def test_empty_flow_is_an_empty_funnel() -> None:
    assert run_funnel('return names(F.toFunnel([], stageOf).funnel);') == {
        'lanes': [], 'combine': None, 'filters': [], 'outputs': []}
    assert run_funnel('return names(F.toFunnel(undefined, stageOf).funnel);')['lanes'] == []
    assert run_funnel('return F.toFunnel({}, stageOf).reason;') == 'The flow has no step list.'


def test_writing_a_funnel_wires_inputs_and_adds_or_drops_the_merge() -> None:
    result = run_funnel("""
        const tmdb = { name: 'TMDb', module: 'tmdb', action: 'get', input: { data: 'previous', query: 'x' } };
        const jackett = { name: 'Jackett', module: 'jackett', action: 'get' };
        const enrich = { name: 'Releases', module: 'jackett', action: 'enrich', config: { must_match: true } };
        const filter = { name: 'Not in Jellyfin', module: 'jellyfin', action: 'unique',
                         input: { data: '{{gone}}', query: { parentLibrary: 'Movies' } } };
        const library = { name: 'Library', module: 'library', action: 'put' };
        const torrents = { name: 'Torrents', module: 'transmission', action: 'put', input: 'previous' };
        const funnel = { lanes: [{ source: tmdb, enrich: [enrich] }, { source: jackett, enrich: [] }],
                         combine: null, filters: [filter], outputs: [library, torrents] };
        const newCombine = () => ({ name: 'Merge sources', module: 'tools', action: 'remove_duplicates' });
        const merged = JSON.parse(JSON.stringify(F.fromFunnel(funnel, newCombine)));
        const back = names(F.toFunnel(merged, stageOf).funnel);
        funnel.lanes.pop();
        const single = JSON.parse(JSON.stringify(F.fromFunnel(funnel, newCombine)));
        return { merged, back, single };
    """)
    assert result['merged'] == [
        {'name': 'TMDb', 'module': 'tmdb', 'action': 'get', 'input': {'query': 'x'}},
        {'name': 'Releases', 'module': 'jackett', 'action': 'enrich', 'config': {'must_match': True},
         'input': 'previous'},
        {'name': 'Jackett', 'module': 'jackett', 'action': 'get'},
        {'name': 'Merge sources', 'module': 'tools', 'action': 'remove_duplicates', 'input': ['Releases', 'Jackett']},
        {'name': 'Not in Jellyfin', 'module': 'jellyfin', 'action': 'unique',
         'input': {'data': 'previous', 'query': {'parentLibrary': 'Movies'}}},
        {'name': 'Library', 'module': 'library', 'action': 'put', 'input': 'previous'},
        {'name': 'Torrents', 'module': 'transmission', 'action': 'put', 'input': '{{Not in Jellyfin}}'},
    ]
    assert result['back'] == {
        'lanes': [['TMDb', 'Releases'], ['Jackett']], 'combine': 'Merge sources',
        'filters': ['Not in Jellyfin'], 'outputs': ['Library', 'Torrents'],
    }
    assert [step['name'] for step in result['single']] == ['TMDb', 'Releases', 'Not in Jellyfin', 'Library', 'Torrents']
    assert result['single'][2]['input'] == {'data': 'previous', 'query': {'parentLibrary': 'Movies'}}


def test_input_helpers_keep_queries_and_arguments() -> None:
    result = run_funnel("""
        return {
          data: [F.dataOf(undefined), F.dataOf('none'), F.dataOf('previous'), F.dataOf('{{a}}'),
                 F.dataOf(['a', '{{b}}']), F.dataOf('text'), F.dataOf({ query: {} }), F.dataOf([1]), F.dataOf(5)],
          withData: [F.withData('text', 'previous'), F.withData({ data: 'x', filename: 'f' }, 'previous'),
                     F.withData({ data: 'x' }, 'previous'), F.withData('{{a}}', 'previous')],
          withoutData: [F.withoutData({ data: 'x', query: 'q' }), F.withoutData({ data: 'x' }),
                        F.withoutData('text'), F.withoutData('previous')],
        };
    """)
    assert result['data'] == [None, None, 'previous', {'ref': 'a'}, {'list': ['a', 'b']}, None, None, None, None]
    assert result['withData'] == [{'data': 'previous', 'query': 'text'}, {'data': 'previous', 'filename': 'f'},
                                  'previous', 'previous']
    assert result['withoutData'] == [{'query': 'q'}, None, 'text', None]


def test_data_steps_after_a_filter_belong_to_the_filtered_items() -> None:
    steps = [
        {'name': 'Favorites', 'module': 'jellyfin', 'action': 'get'},
        {'name': 'Titles', 'module': 'tmdb', 'action': 'enrich', 'input': 'previous'},
        {'name': 'Next season', 'module': 'jellyfin', 'action': 'next_season',
         'input': {'data': 'previous', 'query': {'parentLibrary': 'Trending', 'isInverse': True}}},
        {'name': 'Releases', 'module': 'jackett', 'action': 'enrich', 'input': 'previous'},
        {'name': 'Download', 'module': 'transmission', 'action': 'put', 'input': 'previous'},
    ]
    result = run_funnel("""
        const read = F.toFunnel(steps, stageOf);
        const before = JSON.stringify(steps);
        return { funnel: names(read.funnel), same: JSON.stringify(F.fromFunnel(read.funnel)) === before };
    """, steps=steps)

    assert result['funnel'] == {'lanes': [['Favorites', 'Titles']], 'combine': None,
                                'filters': ['Next season', 'Releases'], 'outputs': ['Download']}
    assert result['same'] is True
    two_sources = [{'name': 'a', 'module': 'tmdb', 'action': 'get'},
                   {'name': 'b', 'module': 'jackett', 'action': 'get'},
                   {'name': 'c', 'module': 'tmdb', 'action': 'enrich', 'input': '{{a}}'}]
    assert 'step before it' in run_funnel('return F.toFunnel(steps, stageOf).reason;', steps=two_sources)
