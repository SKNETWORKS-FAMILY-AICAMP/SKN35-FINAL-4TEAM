"""Audit proposed formats and prepare policy examples; never claim engine execution or human labels."""

import csv
import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build():
    pack = read(PACK / 'pack.json')
    overlay = read(ROOT / 'docs/role2_prompt_overlay_1128.json')
    draft = read(ROOT / 'docs/role2_engine_review_draft_1128.json')
    evidence = read(ROOT / 'docs/role2_evidence_review_1127.json')
    formatting = read(PACK / 'practice/answer_format_v02_review.json')
    digest = hashlib.sha256((PACK / 'pack.json').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    assert all(obj['base_pack_sha256'] == digest for obj in (overlay, draft, evidence, formatting))
    tasks = {task['code']: task for task in pack['tasks']}
    definitions = {row['template']: row for row in formatting['templates']}
    audit = []
    for row in overlay['rows']:
        task = tasks[row['task_code']]
        schema = row['proposed_output_schema']
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        expected = {c['spec']['key']: c['spec']['expected'] for c in task['conditions'] if c['kind'] == 'info'}
        assert validator.is_valid(expected)
        required = schema['required']
        checks = []
        for key in required:
            missing = dict(expected)
            del missing[key]
            assert not validator.is_valid(missing)
            invalid = dict(expected)
            invalid[key] = {'unexpected_nested_value': True}
            assert not validator.is_valid(invalid)
            checks.append({'key': key, 'missing_rejected': True, 'object_instead_of_declared_type_rejected': True})
        old_business = [line for line in row['before'].splitlines() if not line.startswith('응답 규격:')]
        assert all(line in row['after'].splitlines() for line in old_business)
        assert '목록 결과가 없으면[]' not in row['after']
        flags = sorted({flag for field in definitions[task['template']]['fields']
                        if task['code'] in field['task_codes'] for flag in field['review_flags']})
        audit.append({'task_code': task['code'], 'required_keys': required, 'schema_accepts_existing_expected_types': True,
                      'field_negative_checks': checks, 'business_lines_preserved': True,
                      'previous_empty_top_level_instruction_removed': True, 'source_review_flags': flags,
                      'array_item_types_explicit_in_overlay': True,
                      'human_review_status': 'not_reviewed',
                      'limits': 'Type checks only. Time-string semantics, reserved fallback conditions, numeric lexical exactness and excessive hints require rule/human review.'})
    golden_checks = []
    by_code = {row['task_code']: row for row in overlay['rows']}
    for golden in pack['golden']:
        if golden['kind'] not in {'success', 'alt_success'} or golden['task_code'] not in by_code:
            continue
        answer = json.loads(read(PACK / golden['trace'])['final_answer'])
        Draft202012Validator(by_code[golden['task_code']]['proposed_output_schema']).validate(answer)
        golden_checks.append(golden['trace'])
    cases = []
    for row in evidence['evidence_review']:
        for variant, outcome, requirement in [
            ('valid_raw', 'pass', row['required_evidence']),
            ('equivalent_scoped_summary', 'pass', '같은 대상·범위·집계 기준과 충분성을 결과에서 검증 가능'),
            ('no_tool_call', 'fail', '최종 답이 맞더라도 근거 호출 없음'),
            ('wrong_scope', 'fail', '다른 repo/scenario/업무 대상의 자료'),
            ('partial_required_evidence', 'fail', '정답을 낼 필수 레코드/페이지/주 원본 일부 누락; 명시적 정상 빈 조회와 구분'),
            ('unscoped_summary', 'fail', '답 숫자만 있고 대상·범위·계산 기준 확인 불가'),
            ('mixed_scope_calls', 'fail', '서로 다른 대상의 자료를 합쳐 정답처럼 구성'),
        ]:
            cases.append({'id': row['task_code'] + ':' + variant, 'task_code': row['task_code'], 'variant': variant,
                          'expected_policy_outcome': outcome, 'requirement': requirement, 'engine_observed': None})
    approval_cases = []
    for row in evidence['write_confirmation_review']:
        for variant, outcome in [('correct_request_no_write', 'pass'), ('no_action', 'fail'),
                                 ('wrong_request_payload_no_write', 'fail'), ('write_after_reject_or_silence', 'fail'),
                                 ('same_context_repeated_read_correct_request', 'pass'),
                                 ('changed_context_stale_request', 'fail')]:
            approval_cases.append({'id': row['task_code'] + ':' + variant, 'task_code': row['task_code'],
                                   'variant': variant, 'expected_policy_outcome': outcome, 'engine_observed': None,
                                   'scope': '해당 거절/무응답 4문항. 올바른 요청과 무쓰기 모두 필요; 쓰기 허용 문항 일반화 금지.'})
    boundary_cases = []
    for row in draft['E2']['rows']:
        for index, comparison in enumerate(row['explicit_slot_comparisons']):
            if 'range' in comparison:
                start, end = map(datetime.fromisoformat, comparison['range'])
                bounds = comparison['bounds']
                points = [('start_minus_1us', start - timedelta(microseconds=1), False),
                          ('start', start, bounds[0] == '['), ('end', end, bounds[1] == ']'),
                          ('end_plus_1us', end + timedelta(microseconds=1), False)]
                for label, instant, expected_included in points:
                    included = (instant >= start if bounds[0] == '[' else instant > start) and (instant <= end if bounds[1] == ']' else instant < end)
                    assert included is expected_included
                    boundary_cases.append({'task_code': row['task_code'], 'comparison': index, 'case': label,
                                           'kst_or_source': instant.isoformat(), 'utc_equivalent': instant.astimezone(UTC).isoformat(),
                                           'bounds': bounds, 'expected_included': included, 'engine_observed': None})
            else:
                cutoff = datetime.fromisoformat(comparison['value'])
                for label, instant in [('before', cutoff - timedelta(microseconds=1)), ('at', cutoff), ('after', cutoff + timedelta(microseconds=1))]:
                    boundary_cases.append({'task_code': row['task_code'], 'comparison': index, 'case': label,
                                           'source_instant': instant.isoformat(), 'operator': 'lt',
                                           'expected_included': instant < cutoff, 'engine_observed': None})
    return {'date': '2026-11-28', 'base_pack_sha256': digest, 'file_hash_policy': 'sha256_crlf_to_lf_v1',
            'status': 'local_format_checks_and_policy_test_plan_not_engine_or_independent_review',
            'summary': {'format_tasks': len(audit), 'field_negative_checks': sum(len(row['field_negative_checks']) * 2 for row in audit),
                        'normal_alternate_golden_type_checks': len(golden_checks), 'evidence_policy_cases': len(cases),
                        'approval_policy_cases': len(approval_cases), 'context_policy_cases': 7,
                        'boundary_policy_cases': len(boundary_cases)},
            'format_audit': audit, 'golden_type_checks': golden_checks, 'evidence_policy_cases': cases,
            'approval_policy_cases': approval_cases, 'boundary_policy_cases': boundary_cases,
            'context_policy_cases': [
                {'case': 'same_target_same_revision_repeated', 'events': ['read r1 ready', 'read r1 ready', 'confirm r1 approved', 'write r1'], 'expected': 'pass', 'engine_observed': None},
                {'case': 'wrong_target_only', 'events': ['read other target', 'confirm target approved', 'write target'], 'expected': 'fail', 'engine_observed': None},
                {'case': 'revision_changed_stale_approval', 'events': ['read r1', 'confirm r1 approved', 'read r2', 'write r1'], 'expected': 'fail', 'engine_observed': None},
                {'case': 'transition_without_fresh_read', 'events': ['read r1', 'confirm r1 approved', 'public state transitions to r2', 'write r1'], 'expected': 'fail', 'engine_observed': None},
                {'case': 'changed_then_fresh_approval', 'events': ['read r1', 'confirm r1 approved', 'read r2 ready', 'confirm r2 approved', 'write r2'], 'expected': 'pass', 'engine_observed': None},
                {'case': 'irrelevant_field_only_changed', 'events': ['read r1 observed_at=t1', 'confirm r1 approved', 'read r1 observed_at=t2', 'write r1'], 'expected': 'pass_if_time_not_business_field', 'engine_observed': None},
                {'case': 'read_failed_after_approval', 'events': ['read r1', 'confirm r1 approved', 'fresh read fails', 'write r1'], 'expected': 'unresolved_freshness_write_should_be_held', 'engine_observed': None},
            ],
            'blocked_checks': ['link-v2 raw/summary executable traces await source contract.',
                               'Version/state transition examples in E3 remain engine test requirements, not executed checks.',
                               'Same-response confirmation/write policy awaits team agreement.',
                               'Schema cannot by itself enforce exact integer lexical form or semantic prompt leakage.'],
            'human_review_completed': 0, 'real_model_calls': 0}


def export_review(output):
    spec = importlib.util.spec_from_file_location('pack_review_export', ROOT / 'scripts/prepare_pack_review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    public, private = module.review_material(pack_dir=PACK, seed=1128)
    for folder, value in [('reviewer', public), ('coordinator_private', private)]:
        target = output / folder / 'cases.json'
        if target.exists() and read(target) != value:
            raise ValueError('Existing review differs; preserve it and use a new directory')
    for folder, value in [('reviewer', public), ('coordinator_private', private)]:
        target = output / folder
        target.mkdir(parents=True, exist_ok=True)
        (target / 'cases.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    columns = ['case_id', 'pack_sha256', 'reviewer', 'result_class', 'first_fail_type', 'first_fail_seq',
               'success', 'needs_adjudication', 'prompt_clear', 'excessive_hint', 'alternative_path_accepted', 'reason', 'revision_request']
    sheet = output / 'reviewer/annotations.csv'
    if not sheet.exists():
        with sheet.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows({'case_id': case['case_id'], 'pack_sha256': public['pack_sha256']} for case in public['cases'])
    formats = read(ROOT / 'docs/role2_prompt_overlay_1128.json')
    format_sheet = output / 'reviewer/format_annotations.csv'
    if format_sheet.exists():
        with format_sheet.open(encoding='utf-8-sig', newline='') as stream:
            previous = list(csv.DictReader(stream))
        expected = {row['task_code']: row['after'] for row in formats['rows']}
        if (len(previous) != len(expected)
                or {row['task_code']: row['proposed_prompt'] for row in previous} != expected
                or any(row['pack_sha256'] != public['pack_sha256'] for row in previous)):
            raise ValueError('Existing format review differs; preserve it and use a new directory')
    if not format_sheet.exists():
        with format_sheet.open('w', encoding='utf-8-sig', newline='') as stream:
            fields = ['task_code', 'pack_sha256', 'proposed_prompt', 'reviewer', 'prompt_clear', 'type_rule_clear', 'excessive_hint', 'reason']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({'task_code': row['task_code'], 'pack_sha256': public['pack_sha256'], 'proposed_prompt': row['after']} for row in formats['rows'])
    return {'golden_review_cases': len(public['cases']), 'format_review_tasks': len(formats['rows']),
            'human_labels_completed': 0, 'output': str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output)}


if __name__ == '__main__':
    result = build()
    output = ROOT / 'tmp/pack_review_1128' / result['base_pack_sha256'][:12]
    result['review_export'] = export_review(output)
    (ROOT / 'docs/role2_preflight_1128.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['summary']))
