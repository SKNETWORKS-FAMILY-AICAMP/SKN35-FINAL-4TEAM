import hashlib
import importlib.util
import shutil
from pathlib import Path

import pytest

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


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_all_review_builders_accept_either_checkout_newline(tmp_path, monkeypatch, newline):
    copied_pack = tmp_path / 'packs/it_ops/v0.1'
    shutil.copytree(review.PACK, copied_pack, ignore=shutil.ignore_patterns('reference', '__pycache__'))
    (tmp_path / 'docs').mkdir()
    shutil.copy2(ROOT / 'docs/role2_evidence_review_1127.json', tmp_path / 'docs')
    for path in tmp_path.rglob('*.json'):
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', newline))
    original = (copied_pack / 'pack.json').read_bytes()
    for name in ['prepare_pack_split_review', 'prepare_pack_next_steps', 'prepare_role2_policy']:
        module_spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        expected = module.build()
        monkeypatch.setattr(module, 'ROOT', tmp_path)
        monkeypatch.setattr(module, 'PACK', copied_pack)
        assert module.build() == expected
        if name == 'prepare_role2_policy':
            (copied_pack / 'pack.json').write_bytes(original.replace(b'production', b'wrongscope', 1))
            with pytest.raises(AssertionError):
                module.build()
            (copied_pack / 'pack.json').write_bytes(original)
    assert (copied_pack / 'pack.json').read_bytes() == original
