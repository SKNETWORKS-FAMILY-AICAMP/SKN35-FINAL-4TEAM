import csv
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('role2_preflight', ROOT / 'scripts/prepare_role2_preflight.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_format_checks_and_cases_are_not_reported_as_engine_success():
    result = review.build()
    assert result['summary']['format_tasks'] == 134
    assert result['summary']['field_negative_checks'] == 666
    assert result['summary']['normal_alternate_golden_type_checks'] == 88
    assert result['summary']['evidence_policy_cases'] == 308
    assert result['summary']['approval_policy_cases'] == 24
    assert len(result['context_policy_cases']) == 7
    assert all(row['engine_observed'] is None for name in ['evidence_policy_cases', 'approval_policy_cases',
                                                         'context_policy_cases', 'boundary_policy_cases'] for row in result[name])
    assert result['human_review_completed'] == result['real_model_calls'] == 0


def test_period_boundaries_and_equivalent_instants():
    result = review.build()
    rows = result['boundary_policy_cases']
    assert len(rows) == 159
    metrics = [row for row in rows if row['task_code'] == 'ERROR_COUNTS_BEFORE_AFTER-001']
    assert next(row for row in metrics if row['comparison'] == 0 and row['case'] == 'end')['expected_included'] is False
    assert next(row for row in metrics if row['comparison'] == 1 and row['case'] == 'start')['expected_included'] is True
    for row in rows:
        if 'utc_equivalent' in row:
            assert datetime.fromisoformat(row['kst_or_source']) == datetime.fromisoformat(row['utc_equivalent'])


def test_review_export_separates_keys_keeps_blank_labels_and_preserves_annotations(tmp_path):
    result = review.export_review(tmp_path)
    assert result['golden_review_cases'] == 28
    assert result['format_review_tasks'] == 134
    public = json.loads((tmp_path / 'reviewer/cases.json').read_text(encoding='utf-8'))
    assert all(all(value is None for value in row['annotation'].values()) for row in public['cases'])
    assert all('expected' not in row and 'conditions' not in row for row in public['cases'])
    assert (tmp_path / 'coordinator_private/cases.json').exists()
    sheet = tmp_path / 'reviewer/annotations.csv'
    with sheet.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert all(not row['reviewer'] and not row['result_class'] for row in rows)
    rows[0]['reviewer'] = 'test-reviewer'
    rows[0]['reason'] = 'Preserve this existing annotation'
    with sheet.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    before = sheet.read_bytes()
    review.export_review(tmp_path)
    assert sheet.read_bytes() == before
    path = tmp_path / 'reviewer/format_annotations.csv'
    path.write_text(path.read_text(encoding='utf-8-sig').replace('업무 요청:', '오래된 요청:', 1), encoding='utf-8-sig')
    with pytest.raises(ValueError, match='Existing format review differs'):
        review.export_review(tmp_path)


def test_preflight_preserves_active_pack_data_goldens_and_permissions():
    paths = [review.PACK / 'pack.json', review.PACK / 'practice/tool_permissions.json',
             *(review.PACK / 'data').glob('*.json'), *(review.PACK / 'golden').rglob('*.json')]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    review.build()
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
