import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('split_review',ROOT/'scripts/prepare_pack_split_review.py')
review=importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_proposal_covers_all_types_and_keeps_pack_unchanged():
    path=review.PACK/'pack.json'
    before=path.read_bytes()
    report=review.build()
    assert len(report['rows'])==50 and len({r['template'] for r in report['rows']})==50
    assert report['summary']['dev_types']==15
    assert report['summary']['held_candidate_types']==35
    assert report['summary']['dev_tasks']+report['summary']['held_candidate_tasks']==152
    assert path.read_bytes()==before
    assert report['database_modified'] is False and report['v02_created'] is False


def test_supported_real_pilot_types_remain_dev():
    rows=review.build()['rows']
    actual=[r for r in rows if r['actual_mcp_supported']]
    assert len(actual)==8
    assert all(r['decision']=='keep_dev' and r['proposed_split']=='dev' for r in actual)
    assert all(r['evidence'][0]['raw_trials_verified'] is False for r in actual)


def test_no_unverified_candidate_is_promoted_to_held():
    report=review.build()
    candidates=[r for r in report['rows'] if r['proposed_split']=='held_candidate']
    assert len(candidates)==35
    assert all(r['held_eligible'] is None and r['database_exposure_history']=='not_checked' for r in candidates)
    assert report['summary']['confirmed_held_types']==0
    assert report['summary']['held_candidate_actual_mcp_supported']==0
    assert all('held_candidate' in counts for group,counts in report['groups'].items() if group!='lookup')


def test_summary_table_contains_all_rows_and_pending_notice():
    text=review.render(review.build())
    assert text.count('| `')==50
    assert '미노출이 확인된 유형이 아니다' in text
    assert '<!-- split-review:begin -->' in text and '<!-- split-review:end -->' in text
