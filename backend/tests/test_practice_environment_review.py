import importlib.util
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('environment_review', ROOT / 'scripts/check_practice_environment.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def task(prompt, expected='v9.8.7', slots=None):
    return {'code': 'TEST-001', 'template': 'TEST', 'prompt': prompt, 'slot_values': slots or {},
            'conditions': [{'kind': 'info', 'spec': {'expected': expected}}]}


def test_literal_scan_flags_answer_and_excludes_request_inputs():
    assert review.scan_prompt(task('정답은 v9.8.7'))['answer_literal_candidates'] == ['v9.8.7']
    assert review.scan_prompt(task('v9.8.7를 조회', slots={'version':'v9.8.7'}))['answer_literal_candidates'] == []


def test_format_vocabulary_and_numeric_substrings_are_not_literal_hits():
    assert review.scan_prompt(task('응답 규격: status:correct/wrong', expected='correct'))['answer_literal_candidates'] == []
    assert review.scan_prompt(task('번호 91459', expected='145'))['answer_literal_candidates'] == []


def test_literal_roles_do_not_silently_clear_unknown_answer_values():
    assert review.scan_prompt(task('정답은 v9.8.7'))['literal_roles'] == {'v9.8.7':'needs_semantic_review'}
    assert review.scan_prompt(task('실패 시 UNRESOLVED 표시',expected='UNRESOLVED'))['literal_roles'] == {'UNRESOLVED':'declared_fallback_or_error_vocabulary'}


def test_outcome_cues_are_separate_from_response_vocabulary():
    result = review.scan_prompt(task('업무 자료 insufficient-1 응답 규격: insufficient', expected='insufficient', slots={'scenario_id':'insufficient-1'}))
    assert result['findings'][0]['kind'] == 'outcome_cue_in_scenario_name'
    assert review.scan_prompt(task('응답은 성공하는 고정 fake 환경'))['findings'][0]['kind'] == 'future_tool_outcome_disclosed'


def test_scope_and_approval_are_not_overstated():
    report = review.build()
    assert report['scope'] == {'templates':50,'tasks':152,'snapshots':13,'actual_mcp_templates':8,'actual_mcp_tasks':26}
    assert len(report['tool_shape']['not_served_templates']) == 42
    assert not any(report['approval'][key] for key in ['whole_pack_pass','independent_human_review_done','database_env_checks_written'])
    assert report['prompt_leak']['tasks_with_outcome_cues'] == 0
    assert report['prompt_leak']['supported_tasks_with_outcome_cues'] == 0
    assert report['prompt_leak']['procedure_review_tasks'] == 15
    assert report['data_design']['local_adapter_boundary']['flagged_responses'] == 0


def test_prompt_revision_preserves_conditions_and_golden_files():
    pack_dir = ROOT / 'packs/it_ops/v0.1'
    revision = json.loads((pack_dir / 'practice/prompt_revision_1127.json').read_text(encoding='utf-8'))
    pack = json.loads((pack_dir / 'pack.json').read_text(encoding='utf-8'))
    assert len(revision['changed_prompt_tasks']) == 18
    assert len(revision['scenario_id_changes']) == 15
    assert hashlib.sha256((pack_dir / 'pack.json').read_bytes()).hexdigest() == revision['pack_sha256_after']
    tasks = {t['code']:t for t in pack['tasks']}
    cases = {c['id'] for name in ['scenarios.json','evidence.json']
             for c in json.loads((pack_dir / 'data' / name).read_text(encoding='utf-8'))['cases']}
    for change in revision['scenario_id_changes']:
        task = tasks[change['task_code']]
        assert re.fullmatch(r'case-[a-f0-9]{8}', change['new_id'])
        assert task['slot_values']['scenario_id'] == change['new_id']
        assert change['new_id'] in task['prompt'] and change['new_id'] in cases
        assert change['old_id'] not in task['prompt'] and change['old_id'] not in cases
    for filename, expected_hash in revision['golden_file_sha256'].items():
        assert hashlib.sha256((pack_dir / filename).read_bytes()).hexdigest() == expected_hash
