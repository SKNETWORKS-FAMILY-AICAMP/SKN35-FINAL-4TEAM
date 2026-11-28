import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from slotagent.common.hashing import canonical_hash

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'packs/it_ops/v0.1'
HERE = PACK / 'practice'
sys.path.insert(0, str(HERE))
PilotData = importlib.import_module('pilot_server').PilotData


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


MANIFEST = read(HERE / 'pilot_manifest.json')
PACK_DATA = read(PACK / 'pack.json')
TASKS = {task['code']: task for task in PACK_DATA['tasks']}


def data(code):
    return PilotData(HERE / 'pilot_manifest.json', PACK / 'data', code)


def assert_public(value):
    if isinstance(value, dict):
        assert not set(value) & {'expected', 'conditions', 'confirmation', 'responses', 'calls', 'receipt', 'answer'}
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


@pytest.mark.parametrize('code', MANIFEST['task_codes'])
def test_every_pilot_task_has_scoped_public_read_results(code):
    task = TASKS[code]
    scope = task['slot_values']
    server = data(code)
    name = task['template']
    if name == 'DEPLOY_LATEST_SUCCESS':
        result = server.call('list_deployments', {'repo': scope['repo']})
    elif name == 'ISSUES_UNASSIGNED_OPEN':
        result = server.call('list_issues', {'repo': scope['repo']})
    elif name == 'DEPLOY_RELEASE_LINK':
        result = [server.call(tool, {'repo': scope['repo']}) for tool in ['list_operation_runs', 'list_operation_releases']]
    elif name in {'CONFIRMED_RELEASE_SHARE', 'CONFIRMED_ISSUE_CREATE'}:
        result = server.call('get_write_context', {'context_id': scope['context_id']})
    elif name == 'LOG_FIRST_ERROR':
        result = server.call('get_incident_logs', {'repo': scope['repo']})
    elif name.startswith('RETRY_'):
        result = [server.call('query_issue_ids', {'repo': scope['repo']}) for _ in range(scope['max_calls'])]
    elif name == 'CONFLICT_EQUAL_AUTHORITY':
        args = {key: scope[key] for key in ['repo', 'run_id', 'environment']}
        result = [server.call(tool, args) for tool in ['get_run_facts', 'list_version_evidence']]
    elif name == 'ERROR_COUNTS_BEFORE_AFTER':
        result = server.call('query_metric_errors', {'service': scope['service']})
    else:
        tool = ('read_workflow_context' if name in {'CONFIG_OVERRIDE_PRECEDENCE', 'UNTRUSTED_ISSUE_INSTRUCTIONS'}
                else 'get_write_case' if name == 'LATEST_CONFIRMATION_SCOPE' else 'get_incident_case')
        result = server.call(tool, {'scenario_id': scope['scenario_id']})
    assert result
    assert_public(result)
    assert_public(server.metadata())


GOLDENS = [row for row in PACK_DATA['golden'] if row['template'] in MANIFEST['template_codes']
           and row['kind'] in {'success', 'alt_success'}]


@pytest.mark.parametrize('entry', GOLDENS, ids=lambda row: row['template'] + ':' + row['kind'])
def test_new_read_paths_match_existing_normal_and_alternate_golden_responses(entry):
    server = data(entry['task_code'])
    for span in read(PACK / entry['trace'])['spans']:
        if span['kind'] == 'tool' and span['name'] in server.tools and span['name'] not in server.base.tools and server.tools[span['name']]['access'] == 'read':
            assert server.call(span['name'], span['tool_args']) == json.loads(span['tool_result'])


def test_retry_state_is_isolated_and_invalid_requests_do_not_advance_it():
    code = next(task['code'] for task in TASKS.values() if task['template'] == 'RETRY_TRANSIENT_READ')
    left, right = data(code), data(code)
    args = {'repo': TASKS[code]['slot_values']['repo']}
    with pytest.raises(ValueError):
        left.call('query_issue_ids', {'repo': 'acme/wrong'})
    with pytest.raises(ValidationError):
        left.call('query_issue_ids', {**args, 'scenario_id': 'forged'})
    assert left.call('query_issue_ids', args)['ok'] is False
    assert left.call('query_issue_ids', args)['ok'] is True
    assert right.call('query_issue_ids', args)['ok'] is False


def test_fake_write_tools_cannot_be_used_directly_and_no_builtin_is_duplicated():
    server = data(MANIFEST['task_codes'][0])
    assert not {'request_user_confirmation', 'get_work_state', 'get_write_result'} & server.tools.keys()
    for name, args in [('post_message', {'channel': 'ops', 'text': 'blocked'}),
                       ('create_issue', {'repo': 'acme/ops', 'title': 'blocked'})]:
        with pytest.raises(ValueError, match='Writes require engine proxy'):
            server.call(name, args)


def test_frozen_fixture_drift_is_rejected(tmp_path):
    manifest = copy.deepcopy(MANIFEST)
    fixture = read(HERE / 'pilot_fixture.json')
    fixture['contexts'][0]['version'] = 'tampered'
    (tmp_path / 'pilot_fixture.json').write_text(json.dumps(fixture), encoding='utf-8')
    (tmp_path / 'pilot_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Frozen pilot fixture mismatch'):
        PilotData(tmp_path / 'pilot_manifest.json', PACK / 'data', MANIFEST['task_codes'][0])


def test_generated_fixture_is_current_and_sources_are_unchanged():
    spec = importlib.util.spec_from_file_location('prepare_pilot_server', ROOT / 'scripts/prepare_pilot_server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = [PACK / 'pack.json', *(PACK / 'data').glob('*.json'), *(PACK / 'golden').rglob('*.json')]
    before = {path: path.read_bytes() for path in paths}
    fixture, manifest = module.build()
    assert fixture == read(HERE / 'pilot_fixture.json')
    assert manifest == MANIFEST
    assert canonical_hash(fixture) == manifest['fixture']['content_hash']
    assert before == {path: path.read_bytes() for path in paths}
