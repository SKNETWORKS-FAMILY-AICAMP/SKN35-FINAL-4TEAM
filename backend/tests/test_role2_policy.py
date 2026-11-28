import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('role2_policy', ROOT / 'scripts/prepare_role2_policy.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_overlay_only_changes_response_instruction_without_answers():
    policy, overlay = review.build()
    assert policy['applied'] is False and policy['new_pack_created'] is False
    assert len(overlay['rows']) == 134
    assert policy['answer_format']['free_text_tasks_unchanged'] == 18
    for row in overlay['rows']:
        old = [line for line in row['before'].splitlines() if not line.startswith('응답 규격:')]
        assert all(line in row['after'].splitlines() for line in old)
        assert row['original_prompt_sha256'] == hashlib.sha256(row['before'].encode()).hexdigest()
        assert row['proposed_output_schema']['additionalProperties'] is True


def test_policy_retains_engine_blockers_and_review_scopes():
    policy, _ = review.build()
    assert len(policy['evidence']['reviewed_task_codes']) == 44
    assert len(policy['approval']['reviewed_task_codes']) == 4
    assert policy['evidence']['gate'] is True
    assert {item['id'] for item in policy['engine_requests']} == {'E1', 'E2', 'E3', 'E4'}
    assert '과거' in policy['engine_requests'][0]['need']
    assert '계약 변경 제안' in policy['approval']['same_response_proposal']


def test_build_does_not_modify_pack_data_or_goldens():
    paths = [review.PACK / 'pack.json', *(review.PACK / 'data').glob('*.json'),
             *(review.PACK / 'golden').rglob('*.json')]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    review.build()
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
