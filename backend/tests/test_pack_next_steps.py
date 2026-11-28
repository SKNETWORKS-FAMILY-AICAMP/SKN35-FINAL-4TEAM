import hashlib
import importlib.util
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('pack_next_steps',ROOT/'scripts/prepare_pack_next_steps.py')
review=importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_all_held_candidates_have_scoped_adapter_inventory():
    adapter,_,_=review.build()
    split=review.read(review.PACK/'practice/split_review_v02.json')
    expected={r['template'] for r in split['rows'] if r['proposed_split']=='held_candidate'}
    assert {r['template'] for r in adapter['rows']}==expected
    assert adapter['summary']['templates']==35 and adapter['summary']['tasks']==105
    assert adapter['summary']['actual_mcp_ready']==0
    assert sum(adapter['summary']['waves'].values())==35
    assert all(r['tools'] and r['held_eligibility']=='pending_DB_and_team_exposure_review' for r in adapter['rows'])
    assert all(t['implementation']=='engine_builtin' for r in adapter['rows'] for t in r['tools'] if t['name'] in review.BUILTINS)


def test_type_review_covers_all_information_and_keeps_free_text_separate():
    _,formatting,_=review.build()
    assert formatting['summary']=={'structured_tasks':134,'free_text_tasks':18,'info_conditions':333,
                                   'list_fields':36,'mixed_type_fields':3,'generic_empty_list_instruction_tasks':134}
    assert formatting['applied'] is False
    templates={t['template']:t for t in formatting['templates']}
    field=next(f for f in templates['RETRY_EXHAUSTED_READ']['fields'] if f['key']=='items')
    assert field['proposed_json_schema']['items']=={'type':'string'}
    assert field['item_type_basis']=='source_issue_id_or_version_field_contract'
    assert templates['MULTI_TARGET_APPROVAL']['output_mode']=='brief_free_text_with_action_trace'


def test_proposed_types_accept_current_answers_but_no_unrestricted_string_fallback():
    _,formatting,_=review.build()
    definitions={t['template']:{f['key']:f for f in t['fields']} for t in formatting['templates']}
    pack=review.read(review.PACK/'pack.json')
    for task in pack['tasks']:
        for condition in task['conditions']:
            if condition['kind']=='info':
                field=definitions[task['template']][condition['spec']['key']]
                Draft202012Validator.check_schema(field['proposed_json_schema'])
                Draft202012Validator(field['proposed_json_schema']).validate(condition['spec']['expected'])
    schema=definitions['ERROR_RATE_TRAFFIC_NORMALIZED']['before_rate_bp']['proposed_json_schema']
    assert Draft202012Validator(schema).is_valid('UNDEFINED')
    assert not Draft202012Validator(schema).is_valid('anything')


def test_common_design_and_all_outputs_preserve_legacy_data():
    paths=[review.PACK/'pack.json',*(review.PACK/'data').glob('*.json')]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    _,_,design=review.build()
    assert len(design['current_sources'])==13
    assert design['status']=='design_only_no_generator_or_data_migration'
    assert all(s['sha256']==hashlib.sha256((review.PACK/s['location']).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for s in design['current_sources'])
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert 'no v0.2 pack created' in design['not_done'][0]
