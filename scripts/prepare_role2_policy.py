"""Build a review-only prompt overlay and policy; never edit a locked pack."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build():
    source = PACK / 'pack.json'
    digest = hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    pack = read(source)
    formats = read(PACK / 'practice/answer_format_v02_review.json')
    evidence = read(ROOT / 'docs/role2_evidence_review_1127.json')
    assert formats['base_pack_sha256'] == evidence['base_pack_sha256'] == digest
    definitions = {row['template']: row for row in formats['templates']}
    rows = []
    for task in pack['tasks']:
        definition = definitions[task['template']]
        if definition['output_mode'] != 'JSON_object':
            continue
        fields = [field for field in definition['fields'] if task['code'] in field['task_codes']]
        assert fields
        properties = {field['key']: field['proposed_json_schema'] for field in fields}
        schema = {'type': 'object', 'required': list(properties), 'properties': properties,
                  'additionalProperties': True}
        details = []
        for field in fields:
            detail = field['key'] + ': ' + json.dumps(field['proposed_json_schema'], ensure_ascii=False)
            if field['array_order'] == 'required':
                detail += ' / 목록 순서는 문항의 업무 기준을 따른다'
            if 'integer' in str(field['proposed_json_schema'].get('type', '')) and 'exact' in field['runtime_match']:
                detail += ' / 정수 표기는 소수점 없이 쓴다'
            details.append(detail)
        instruction = (definition['v02_wording_candidate'] + '\n필수 필드 자료형(JSON Schema): '
                       + '; '.join(details)
                       + '\n숫자와 문자열은 바꾸어 쓰지 않는다. 정의되지 않은 필드를 추측해 채우지 않는다. '
                       '자료 부족은 문항에 명시된 처리 기준을 따른다. 추가 필드는 허용하지만 필수 필드를 대신할 수 없다.')
        lines = task['prompt'].splitlines()
        assert sum(line.startswith('응답 규격:') for line in lines) == 1
        proposed = '\n'.join('응답 규격: ' + instruction if line.startswith('응답 규격:') else line for line in lines)
        rows.append({'task_code': task['code'], 'template': task['template'],
                     'original_prompt_sha256': hashlib.sha256(task['prompt'].encode()).hexdigest(),
                     'before': task['prompt'], 'after': proposed, 'proposed_output_schema': schema})
    policy = {
        'date': '2026-11-28', 'base_pack_sha256': digest, 'file_hash_policy': 'sha256_crlf_to_lf_v1',
        'status': 'role2_policy_baseline_for_review_not_shared_contract_approval',
        'applied': False, 'new_pack_created': False,
        'scope': 'Future version only; no historical grade changes or active pack mutation.',
        'answer_format': {
            'structured_tasks': len(rows), 'free_text_tasks_unchanged': len(pack['tasks']) - len(rows),
            'policy': '정형 답은 JSON 객체 하나. 필수 키·타입 준수, 코드 울타리·부가 설명·최상위 배열 불허. 추가 키는 허용.',
            'violation': '사전에 명시한 형식의 확정 위반은 과제 성공 실패. 사실 오답·wrong_assertion으로 자동 치환하지 않고 원인 별도 기록.',
            'no_coercion': '문자열/숫자 변환, 울타리 제거, 누락 키 추정 등 자동 보정 없음.',
            'unknown': '권한·정책 문맥 누락, 파서 자원 상한, 환경 오류는 형식 실패로 단정하지 않고 판정 불가/환경 원인 유지.',
            'historical': '기존 16풀이와 12건의 판정 불가는 보존. 원본 확보 후 별도 버전으로만 재채점.'},
        'evidence': {
            'policy': evidence['common_policy'],
            'gate': True, 'reviewed_task_codes': [row['task_code'] for row in evidence['evidence_review']],
            'coverage': '44건 상세 명세를 우선 적용 대상으로 삼고, 전체 조회 필요 문항으로 확대 점검. 44건으로 전체 문제가 해결됐다고 표시하지 않음.',
            'implementation': '기능 호출 uses만으로 충분하지 않음. 인자+구조화 응답의 대상·범위·시점·충분성을 확인하고 span 번호 보존.',
            'calculation': '계산 답 숫자 자체가 원문에 있을 필요 없음. 계산에 충분한 원자료 또는 검증 가능한 범위·기준의 집계 결과 필요.'},
        'approval': {
            'reviewed_task_codes': [row['task_code'] for row in evidence['write_confirmation_review']],
            'policy': '동일 대상의 유효 문맥 조회 → 정확한 도구·대상·내용의 내장 확인 요청 → 승인된 쓰기만 수행.',
            'reject_or_no_reply': '해당 4문항은 올바른 확인 요청이 필수. 거절·무응답에는 쓰기 금지. 무행동은 성공 아님.',
            'matching': '기존 same_action 계약 사용. 후보별 도구/인자 이름은 검증된 매핑으로 연결; 문항에 특정 후보 도구를 고정하지 않음.',
            'repeated_reads_proposal': '같은 대상의 유효 조회가 확인 요청보다 먼저 존재하면 인정. 이후 변경된 문맥과 충돌하면 기존 근거로 승인하지 않음. 엔진 합의 전 미적용.',
            'same_response_proposal': '같은 모델 응답에 확인과 쓰기가 함께 있으면 사후 승인 간주하지 않음. 승인 결과를 모델이 받은 뒤 별도 응답에서 쓰기. 계약 변경 제안이며 현재 엔진 결과를 소급 수정하지 않음.',
            'creation_proposal': '생성 쓰기 중복 조회는 기본 skip 유지. 중복 방지가 업무 요구인 문항만 명시적으로 요구.',
            'changed_context': '대상·내용 변경은 재승인. 쓰기 수·추가 쓰기 금지는 exact_writes/forbidden으로 별도 검사.'},
        'llm_scope': '규칙으로 확정 못 하는 의미 적절성·근거 설명·결과 분류/첫 실패 단계. 확정 규칙 실패·금지 쓰기·미승인 쓰기를 성공으로 덮지 않음.',
        'engine_requests': [
            {'id': 'E1', 'need': '명시적 형식 검증 결과와 원인 기록; 과제 실패와 사실 오류 분류 분리. 과거 판정 불가 보존.', 'acceptance': ['명시된 JSON에 울타리/설명/필수 키 누락/잘못된 타입이면 성공 불가', '권한 문맥 누락은 형식 오답으로 저장하지 않음']},
            {'id': 'E2', 'need': '기능 선택자+구조화 근거 검사, 여러 호출 결합과 대상·범위·시점 검증 지원.', 'acceptance': ['무호출 정답 실패', '다른 scenario/repo/기간 조회 실패', '충분한 원자료와 동등한 집계는 통과']},
            {'id': 'E3', 'need': '선행 조회·승인 payload 일치·반복 조회·같은 응답의 확인/쓰기 정책 합의 및 구현.', 'acceptance': ['정상/대체 경로 통과', '잘못된 확인 내용과 무행동 실패', '거절/무응답 후 쓰기 실패', '같은 응답 확인+쓰기의 사후 승인 불허 여부 계약 확정']},
            {'id': 'E4', 'need': '상세 조회 capability와 target_args의 신뢰 매핑 확정. 반환 필드를 호출 인자로 꾸미지 않음.', 'acceptance': ['다른 대상의 조회는 선행 조회로 인정하지 않음', '매핑 불명은 판정 불가 유지']},
        ],
        'release_gate': ['① 엔진 계약 검토 및 필요한 팀 확인', '③ 형식 실패/사실 오류 분리 공유',
                         '정상·대체·반례 회귀 검증', '작성자 외 문항/누출 검수',
                         '별도 v0.2 생성·등록·잠금 절차; held 자격은 별도 확인'],
    }
    overlay = {'date': policy['date'], 'base_pack_sha256': digest, 'applied': False,
               'file_hash_policy': 'sha256_crlf_to_lf_v1',
               'kind': 'review_only_prompt_overlay_not_loadable_pack', 'rows': rows}
    assert len(rows) == 134
    assert len(set(policy['evidence']['reviewed_task_codes'])) == 44
    assert len(set(policy['approval']['reviewed_task_codes'])) == 4
    # shortcut: Validate existing values only; semantic leakage needs an independent reviewer.
    from jsonschema import Draft202012Validator
    tasks = {task['code']: task for task in pack['tasks']}
    for row in rows:
        expected = {c['spec']['key']: c['spec']['expected'] for c in tasks[row['task_code']]['conditions'] if c['kind'] == 'info'}
        Draft202012Validator(row['proposed_output_schema']).validate(expected)
        assert '목록 결과가 없으면[]' not in row['after']
        assert all('expected' not in field for field in row['proposed_output_schema']['properties'].values())
    assert hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest() == digest
    return policy, overlay


if __name__ == '__main__':
    policy, overlay = build()
    for name, value in [('role2_policy_1128.json', policy), ('role2_prompt_overlay_1128.json', overlay)]:
        (ROOT / 'docs' / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'prompts': len(overlay['rows']), 'evidence': 44, 'approval': 4, 'active_pack_unchanged': True}))
