"""Generate role2's E1-E4 draft without changing contracts or the active pack."""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build():
    pack = read(PACK / 'pack.json')
    overlay = read(ROOT / 'docs/role2_prompt_overlay_1128.json')
    evidence = read(ROOT / 'docs/role2_evidence_review_1127.json')
    digest = hashlib.sha256((PACK / 'pack.json').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    assert digest == overlay['base_pack_sha256'] == evidence['base_pack_sha256']
    tasks = {task['code']: task for task in pack['tasks']}
    periods = []
    for item in evidence['evidence_review']:
        task = tasks[item['task_code']]
        slots = task['slot_values']
        comparisons = []
        if all(key in slots for key in ('start', 'deployment_at', 'end')):
            comparisons = [{'range': [slots['start'], slots['deployment_at']], 'bounds': '[)', 'part': 'before'},
                           {'range': [slots['deployment_at'], slots['end']], 'bounds': '[)', 'part': 'after'}]
        elif 'as_of' in slots and 'max_age_hours' in slots:
            start = datetime.fromisoformat(slots['as_of']) - timedelta(hours=slots['max_age_hours'])
            comparisons = [{'range': [start.isoformat(), slots['as_of']], 'bounds': '[]', 'field': 'observed_at'}]
        elif 'cutoff' in slots:
            comparisons = [{'operator': 'lt', 'value': slots['cutoff'], 'field': 'updated_at'}]
        business = [line for line in task['prompt'].splitlines() if line.startswith('업무 기준:')]
        periods.append({'task_code': task['code'], 'scope': slots, 'source': item['source'],
                        'business_criteria_verbatim': business, 'explicit_slot_comparisons': comparisons,
                        'record_field_mapping': 'metrics requires source-specific at/start/end; other fields follow the source contract',
                        'remaining_review': 'No inferred time from IDs. Scenario-contained as_of/trace event order/latest-run completeness must be bound to public source fields during link-v2 conversion.'})
    observed = {}
    for golden in pack['golden']:
        for span in read(PACK / golden['trace'])['spans']:
            if span['kind'] != 'tool':
                continue
            row = observed.setdefault(span['name'], {'templates': set(), 'keys': set()})
            row['templates'].add(golden['template'])
            row['keys'].update(span.get('tool_args', {}))
    manifest = read(PACK / 'practice/servers.json')
    schemas = {tool['name']: tool['input_schema'] for server in manifest['services'] for tool in server['tools']}
    permissions = {tool['name']: tool for tool in read(PACK / 'practice/tool_permissions.json')['tools']}
    proposals = {
        'create_issue': ({'repo': 'repo'}, '생성 쓰기: target_id 없음. owner+repo 분리 호출은 현재 repo 단일 인자 매핑만으로 전체 저장소를 증명 못 하므로 어댑터 정규화/계약 확인 필요.'),
        'get_run_facts': ({'repo': 'repo', 'target_id': 'run_id'}, '실행 하나의 사실 조회. environment는 link 범위에 별도 유지.'),
        'list_version_evidence': ({'repo': 'repo', 'target_id': 'run_id'}, '동일 실행의 근거 목록. 여러 근거를 반환해도 호출 대상은 실행 하나.'),
        'get_incident_detail': ({'target_id': 'incident_id'}, 'ops.incidents.read 재사용 후보. 실제 입력 스키마·네임스페이스 확인 필요.'),
        'get_incident_logs': ({'repo': 'repo', 'target_id': 'run_id'}, 'run_id를 받는 호출에만 해당. repo만 받는 기존 호출을 실행 상세 조회로 인정하지 않음.'),
    }
    mappings = []
    for name, info in sorted(observed.items()):
        mapping, note = proposals.get(name, (None, '상세 대상 매핑 근거 부족. 반환 필드·scenario/context ID로 대상 ID를 추정하지 않음.'))
        if name == 'post_message':
            note = '새 메시지 생성. channel은 컨테이너, text는 내용이며 기존 메시지 target_id가 아님. 현재 스키마에는 채널 컨테이너 칸이 없어 유효 target_args 제안 보류.'
        builtin = name in {'request_user_confirmation', 'get_work_state', 'get_write_result'}
        mappings.append({'tool': name, 'templates': sorted(info['templates']), 'observed_argument_keys': sorted(info['keys']),
                         'input_schema': schemas.get(name), 'access': permissions.get(name, {}).get('access', 'engine_builtin' if builtin else 'unknown'),
                         'proposed_target_args': mapping, 'status': 'engine_builtin_no_MCP_change' if builtin else 'proposal_not_trusted_mapping' if mapping else 'unresolved_not_auto_mapped',
                         'note': note, 'actual_candidate_registration_verified': False})
    result = {
        'date': '2026-11-28', 'status': 'role2_draft_for_engine_review_not_approved_contract',
        'base_pack_sha256': digest, 'file_hash_policy': 'sha256_crlf_to_lf_v1', 'applied': False,
        'E1': {'decision': '기존 134문항 형식 자료 재사용',
               'rows': [{'task_code': row['task_code'], 'required_output_schema': row['proposed_output_schema']} for row in overlay['rows']],
               'free_text_task_codes': sorted(set(tasks) - {row['task_code'] for row in overlay['rows']}),
               'rules': ['최상위 JSON 객체 하나, 필수 키·타입 준수, 추가 키 허용. 중복 키·설명문·코드 울타리 불허.',
                         '정수 exact 필드는 소수점 없는 정수 표기. 숫자/문자열 자동 변환 없음.',
                         '형식 위반은 성공 불가이나 wrong_assertion으로 자동 분류하지 않음. 파서 상한·권한/정책 누락·환경 오류는 판정 불가 유지.',
                         'JSON Schema는 키·타입 목록용이며 업무 시각 문자열·형식·값 비교는 기존 조건도 함께 적용. 과거 결과 재채점 없음.']},
        'E2': {'decision': 'link-v2 방향 동의, between 필요. evidence_plan.md 원문 미확보로 세부 스키마 동의는 보류.',
               'rules': ['UTC/KST는 timezone-aware instant로 비교. 시간대 없는 문자열을 임의 해석하지 않음.',
                         'between은 양 끝 포함 여부를 명시. metrics는 [start,end), freshness는 [as_of-age,as_of], 이전 cutoff는 <.',
                         'metrics의 배포 시각은 after에만 포함. 장애 구간은 조회 구간에 잘라 합집합 길이로 계산하며 겹치거나 맞닿는 구간을 중복 계산하지 않음.',
                         '같은 방식 안에서 호출 결합. 다른 대상/시나리오/기간 혼합 불허. 최신/전체 목록은 레코드 존재뿐 아니라 완전성도 필요.',
                         'span.error 근거 제외와 업무 오류 응답 처리는 별도. 고정 실패 응답은 실패/재시도 근거일 수 있어도 업무 사실의 성공 조회로 인정하지 않음.',
                         '무호출 실패, 다른 repo/scenario/기간 실패, 부분 조회 실패. raw/summary 각각 충분성 검증.'],
               'rows': periods, 'division': '② 44건 조건 변환·골든 준비, ① 계약 확정·반례 시험·구현. 원문 수령 후 실행 가능한 v2 조건 작성.'},
        'E3': {'decision': '충돌 기준 (가)+(나), 쓰기 판단에 영향을 주는 필드만 비교.',
               'rules': ['비교 대상은 동일 업무 대상이며 repo/종류/ID 또는 검증된 업무 키로 식별. scenario ID 단독은 대상 아님.',
                         '확인 요청 직전 가장 최근의 유효 문맥 사용. 동일 대상 반복 조회가 있어도 내용이 같으면 통과.',
                         '충돌 필드는 대상, 예정 action 인자, version/revision/status, 쓰기 허용 전제 등 문항별 선언. 시각·문구·정렬만 다르면 자동 충돌 아님.',
                         '확인 이후 쓰기 전 재조회에서 선언 필드가 변경되면 기존 승인 사용 금지. 새 문맥으로 다시 확인하고 승인받아야 함.',
                         'write_scenario 상태 전이가 선언 필드를 바꾸면 이전 조회만으로 쓰기 불가. 공개된 조회/상태 도구로 새 상태를 확인. 비공개 상태를 보라고 요구하지 않음.',
                         '결과 조회 실패/모호함은 변경 확정과 구분. 최신성 불명으로 처리하고 쓰기를 보류; 근거 없이 재승인했다고 통과시키지 않음.',
                         '승인된 payload와 실제 쓰기 일치는 기존 same_action 재사용. 쓰기 한 번마다 승인 소비.',
                         '거절/무응답 4문항은 정확한 확인 요청 자체가 필수. 쓰기 0회 조건만으로 무행동을 성공 처리하지 않음.'],
               'same_response': '확인+쓰기 같은 응답 불허 제안은 4명 확인 안건. 현재 엔진·과거 결과 변경 없음.',
               'field_examples': {'APPROVAL_DATA_REVISION': ['subject', 'version', 'revision', 'status', 'action.arguments'],
                                  'CONFIRMED_RELEASE_SHARE': ['channel', 'text에 사용한 배포 버전/상태'],
                                  'CONFIRMED_ISSUE_CREATE': ['owner/repo', 'title', 'labels/assignees가 요청된 경우 해당 값']},
               'tests': ['동일 대상 동일 내용 반복 조회 통과', '다른 대상 조회 실패', '변경 후 이전 승인 쓰기 실패',
                         '상태 전이 뒤 재조회 누락 실패', '변경 후 새 조회·승인 통과', '무행동 실패', '비업무 필드만 변경은 자동 실패 금지']},
        'E4': {'capability_candidates': [
            {'name': 'github.actions.detail.read', 'meaning': 'repo+run_id로 지정한 실행 하나의 상태·버전·시각 조회', 'templates': ['CONFLICT_EQUAL_AUTHORITY', 'CONFLICT_FRESH_PRIMARY', 'CONFLICT_INSUFFICIENT_VERSION'], 'tool': 'get_run_facts'},
            {'name': 'github.actions.evidence.read', 'meaning': 'repo+run_id의 출처·관측 시각을 포함한 버전 근거 조회', 'templates': ['CONFLICT_EQUAL_AUTHORITY', 'CONFLICT_FRESH_PRIMARY', 'CONFLICT_INSUFFICIENT_VERSION'], 'tool': 'list_version_evidence'},
            {'name': 'github.issues.detail.read', 'meaning': 'repo+issue 번호의 본문·상태 상세 조회', 'templates': [], 'tool': None, 'status': '미래 후보; 현재 이슈 목록 문항의 필수 기능으로 추가하지 않음'},
        ], 'existing_detail_capabilities': ['ops.incidents.read: get_incident_detail', 'github.actions.logs.read: run_id 명시 로그 호출만 상세 대상 증명 후보'],
               'rows': mappings, 'rules': ['관측 인자 집합은 공식 입력 스키마가 아님. 제안은 신뢰 권한 파일에 미반영.',
                                         '현재 5개 MCP 도구는 목록 조회이며 대상 ID가 없어 상세 조회로 승격하지 않음.',
                                         '반환값에서 repo/ID 추정 금지. owner+repo 분리 저장소 및 channel 컨테이너 모델은 ①④ 계약 검토 필요.',
                                         '생성 쓰기 중복 조회 기본 skip, 업무 요구로 명시된 중복 확인은 별도 근거 조건으로 유지.']},
        'pending': ['evidence_plan.md 원문', '① 계약 초안 및 ④ 이름표·등록 매핑 확인', '같은 응답 안건 4명 확인', '독립 검수·반례 시험 후 v0.2 적용'],
    }
    assert len(result['E1']['rows']) == 134 and len(result['E1']['free_text_task_codes']) == 18
    assert len(periods) == 44
    return result


if __name__ == '__main__':
    draft = build()
    (ROOT / 'docs/role2_engine_review_draft_1128.json').write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'format_tasks': 134, 'evidence_tasks': 44, 'tool_rows': len(draft['E4']['rows']), 'applied': False}))
