import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('local_boundary_review', ROOT/'scripts/check_local_practice_boundaries.py')
review=importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_nested_private_fixture_fields_are_detected():
    assert review.private_paths({'context':{'rows':[{'receipt':{'number':'future'}}]},'answer':42}) == [
        '$.context.rows[0].receipt','$.answer']


def test_legitimate_observed_work_receipts_are_not_future_fixture_fields():
    assert review.private_paths({'receipts':[{'status':'success','number':42}], 'raw_log':'answer is data'}) == []


def test_all_unserved_templates_have_scoped_local_evidence():
    report=review.build()
    assert report['task_count']==126 and report['template_count']==42
    assert report['read_responses']>126
    assert report['flagged_responses']==0
    assert report['approval'] is False
