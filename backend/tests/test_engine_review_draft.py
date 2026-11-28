import hashlib
import importlib.util
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('engine_review_draft', ROOT / 'scripts/prepare_engine_review_draft.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_draft_covers_formats_and_accepts_existing_expected_types():
    draft = review.build()
    pack = review.read(review.PACK / 'pack.json')
    tasks = {task['code']: task for task in pack['tasks']}
    assert draft['applied'] is False
    assert len(draft['E1']['rows']) == 134
    assert len(draft['E1']['free_text_task_codes']) == 18
    for row in draft['E1']['rows']:
        values = {c['spec']['key']: c['spec']['expected'] for c in tasks[row['task_code']]['conditions'] if c['kind'] == 'info'}
        Draft202012Validator(row['required_output_schema']).validate(values)


def test_period_boundaries_and_target_mapping_do_not_guess_business_ids():
    draft = review.build()
    periods = {row['task_code']: row for row in draft['E2']['rows']}
    assert len(periods) == 44
    metric = periods['ERROR_COUNTS_BEFORE_AFTER-001']['explicit_slot_comparisons']
    assert [row['bounds'] for row in metric] == ['[)', '[)']
    assert metric[0]['range'][1] == metric[1]['range'][0]
    assert periods['CONFLICT_INSUFFICIENT_VERSION-001']['explicit_slot_comparisons'][0]['bounds'] == '[]'
    assert periods['ISSUES_STALE_UNASSIGNED-003']['explicit_slot_comparisons'][0]['operator'] == 'lt'
    tools = {row['tool']: row for row in draft['E4']['rows']}
    assert tools['post_message']['proposed_target_args'] is None
    assert tools['create_issue']['proposed_target_args'] == {'repo': 'repo'}
    assert tools['get_write_case']['proposed_target_args'] is None
    for row in tools.values():
        assert row['actual_candidate_registration_verified'] is False
        if row['proposed_target_args']:
            assert set(row['proposed_target_args'].values()) <= set(row['observed_argument_keys'])


def test_draft_keeps_pack_data_goldens_and_trusted_mapping_unchanged():
    paths = [review.PACK / 'pack.json', review.PACK / 'practice/tool_permissions.json',
             *(review.PACK / 'data').glob('*.json'), *(review.PACK / 'golden').rglob('*.json')]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    review.build()
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
