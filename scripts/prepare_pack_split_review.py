"""Prepare a type-level split proposal without changing a pack or approving exposure history."""

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'
DOCUMENTED_REAL_PILOT = {
    'DEPLOY_LATEST_SUCCESS', 'ISSUES_UNASSIGNED_OPEN', 'DEPLOY_FAILURES_PERIOD',
    'DEPLOY_RECOVERY', 'ISSUES_STALE_UNASSIGNED', 'DEPLOY_RELEASE_LINK',
    'DEPLOY_FAILURE_STREAK', 'DEPLOY_UNDEPLOYED_RELEASES',
}
EXTRA_DEV = {
    'CONFIRMED_RELEASE_SHARE': '승인·거절·무응답 공유의 개발 대표',
    'CONFIRMED_ISSUE_CREATE': '승인·거절·무응답 이슈 생성의 개발 대표',
    'LOG_FIRST_ERROR': '로그 조회·최초 오류의 개발 대표',
    'RETRY_TRANSIENT_READ': '재시도·tool_error 처리의 개발 대표',
    'CONFLICT_EQUAL_AUTHORITY': '주 원본 충돌 판단의 개발 대표',
    'ERROR_COUNTS_BEFORE_AFTER': '계산·범위 경계의 개발 대표',
    'CONFIG_OVERRIDE_PRECEDENCE': '설정·타입·우선순위의 개발 대표',
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build():
    pack = read(PACK / 'pack.json')
    groups = read(PACK / 'groups.json')['groups']
    manifest = read(PACK / 'practice/servers.json')
    pilot = read(PACK / 'practice/pilot_selection.json')
    revision = read(PACK / 'practice/prompt_revision_1127.json')
    evidence = read(ROOT / 'docs/role2_evidence_review_1127.json')
    supported = set(manifest['template_codes'])
    # Historical exposure is not inferred from whichever types a later server serves.
    assert DOCUMENTED_REAL_PILOT <= {t['code'] for t in pack['templates']}
    group_of = {code: name for name, value in groups.items() for code in value['template_codes']}
    pilot_codes = {item['template'] for item in pilot['templates']}
    revised_tasks = set(revision['changed_prompt_tasks'])
    reviewed_tasks = {item['task_code'] for item in evidence['evidence_review']}
    proposed_dev = DOCUMENTED_REAL_PILOT | EXTRA_DEV.keys()
    assert len(proposed_dev) == 15
    rows = []
    for template in pack['templates']:
        code = template['code']
        tasks = [t for t in pack['tasks'] if t['template'] == code]
        dev = code in proposed_dev
        history = []
        if code in DOCUMENTED_REAL_PILOT:
            history.append({'kind':'documented_real_model_run_and_failure_analysis',
                            'source':'docs/handoff.md: 2026-11-26 real pilot, 8 served types x A/B',
                            'raw_trials_verified':False})
        if code in pilot_codes:
            history.append({'kind':'pilot_proposal_only_not_execution_proof',
                            'source':'packs/it_ops/v0.1/practice/pilot_selection.json'})
        changed = [t['code'] for t in tasks if t['code'] in revised_tasks]
        if changed:
            history.append({'kind':'source_prompt_revision_not_proof_of_real_model_feedback',
                            'tasks':changed,'source':'packs/it_ops/v0.1/practice/prompt_revision_1127.json'})
        reviewed = [t['code'] for t in tasks if t['code'] in reviewed_tasks]
        if reviewed:
            history.append({'kind':'evidence_condition_design_review_not_exposure_clearance',
                            'tasks':reviewed,'source':'docs/role2_evidence_review_1127.json'})
        rows.append({
            'template':code,'group':group_of[code], 'task_codes':[t['code'] for t in tasks],
            'task_count':len(tasks),'current_split':template.get('split'),
            'proposed_split':'dev' if dev else 'held_candidate',
            'reason':('실제 모델 실행·실패 분석 기록이 있어 dev 유지' if code in DOCUMENTED_REAL_PILOT
                      else EXTRA_DEV.get(code, '개발 대표 이외의 유형을 확인용 후보로 제안. 미노출 여부는 아직 미확인')),
            'actual_mcp_supported':code in supported,
            'local_simulator_available':True,
            'source_review_performed':True,
            'database_exposure_history':'not_checked',
            'team_failure_viewing_history':'not_confirmed',
            'held_eligible':None,
            'decision':'keep_dev' if code in DOCUMENTED_REAL_PILOT else 'proposed_dev' if dev else 'pending_exposure_audit',
            'evidence':history,
        })
    assert len(rows) == 50 and len({r['template'] for r in rows}) == 50
    assert sum(r['task_count'] for r in rows) == 152
    summary = {'dev_types':sum(r['proposed_split']=='dev' for r in rows),
               'held_candidate_types':sum(r['proposed_split']=='held_candidate' for r in rows),
               'dev_tasks':sum(r['task_count'] for r in rows if r['proposed_split']=='dev'),
               'held_candidate_tasks':sum(r['task_count'] for r in rows if r['proposed_split']=='held_candidate'),
               'confirmed_held_types':0,
               'held_candidate_actual_mcp_supported':sum(r['proposed_split']=='held_candidate' and r['actual_mcp_supported'] for r in rows)}
    return {'schema_version':1,'date':'2026-11-27','status':'proposal_not_applied_not_independent_approval',
            'source_pack':'it_ops/v0.1','proposed_destination':'it_ops/v0.2',
            'source_pack_sha256':hashlib.sha256((PACK/'pack.json').read_bytes()).hexdigest(),
            'summary':summary,
            'groups':{name:dict(Counter(r['proposed_split'] for r in rows if r['group']==name)) for name in groups},
            'rules':['Split whole templates, never task variants of the same template across dev/held.',
                     'Documented real-model failure-analysis types remain dev.',
                     'Source design, synthetic golden replay and pilot nomination are not automatically actual model failure exposure.',
                     'Lack of a local record is not evidence of no team/DB exposure; all held candidates remain unapproved.',
                     'Exposure carries across pack versions for the same or equivalent type; a new DB ID/version/seed alone does not reset it.',
                     'If a held candidate has been used for improvement, move it to dev and replace it with an independently prepared unexposed type. Do not force the count.'],
            'next_checks':['Role1/4 export task exposures including timestamp, reason, viewer and original template identity across versions.',
                           'Team confirm which actual failed outputs were used to change agent/model prompts/tools.',
                           'Choose and connect actual held adapters before a held-only real-model pilot.',
                           'After approval, create and validate v0.2 as a new pack; do not update locked v0.1.',
                           'Freeze held content and keep future optimization agents from reading held failures.'],
            'immediate_demo':'Use the 8 supported dev types as an explicitly marked internal demo, not held effectiveness evidence. Current pilot forces held; needs an explicit separate dev-demo path.',
            'database_modified':False,'v02_created':False,'rows':rows}


def render(report):
    lines=['<!-- split-review:begin -->','## v0.2 dev/held 분할 후보 — 11/27','',
           '아래는 적용 전 제안이다. v0.1은 변경하지 않았고 v0.2를 생성하지 않았다. 실제 모델 파일럿 기록8유형은 dev 유지, 업무별 개발 대표7유형을 더해 dev15/held후보35를 제안한다. **held35는 미노출이 확인된 유형이 아니다.**',
           'DB 노출 이력·팀의 실패 분석 사용 여부·버전 간 동일 유형 대응을 확인한 뒤 확정한다. 현재 held후보35 중 실제 MCP 지원은0유형이므로 분할만으로 즉시 held 파일럿을 실행할 수 없다.',
           '[전체 근거 JSON](it_ops/v0.1/practice/split_review_v02.json) · 재생성: `backend/.venv/Scripts/python.exe scripts/prepare_pack_split_review.py`',
           '', '| 유형 | 그룹 | 문항 | 제안 | 실제 MCP | 설계·수정 기록 | 확인 상태 |', '|---|---|---:|---|---|---|---|']
    for row in report['rows']:
        evidence = {e['kind'] for e in row['evidence']}
        labels = [label for kind,label in [
            ('documented_real_model_run_and_failure_analysis','모델 실행'),
            ('source_prompt_revision_not_proof_of_real_model_feedback','문항 수정'),
            ('evidence_condition_design_review_not_exposure_clearance','근거 설계'),
            ('pilot_proposal_only_not_execution_proof','파일럿 후보')] if kind in evidence]
        lines.append(f"| `{row['template']}` | {row['group']} | {row['task_count']} | {'dev' if row['proposed_split']=='dev' else 'held 후보'} | {'지원' if row['actual_mcp_supported'] else '미지원'} | {', '.join(labels) or '공통 설계 검토'} | {'실행 기록 근거로 dev 유지' if row['decision']=='keep_dev' else '개발 대표 제안' if row['decision']=='proposed_dev' else 'DB·팀 노출 확인 대기'} |")
    lines += ['', '후보 수를 맞추기 위해 노출된 유형을 held로 승격하지 않는다. 같은 유형은 v0.2에서 새 ID를 받아도 v0.1의 노출 기록을 승계한다. 기존 15유형 파일럿 선정안·11/18 별도 실험의 사람100건 검수는 held 자격 증거가 아니다.', '<!-- split-review:end -->']
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    before=(PACK/'pack.json').read_bytes()
    report=build()
    (PACK/'practice/split_review_v02.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=ROOT/'packs/README.md'
    content=path.read_text(encoding='utf-8')
    start,end='<!-- split-review:begin -->','<!-- split-review:end -->'
    if start in content:
        a,b=content.index(start),content.index(end)+len(end)
        content=content[:a]+render(report).rstrip()+content[b:]
    else:
        content=content.rstrip()+'\n\n'+render(report)
    path.write_text(content,encoding='utf-8')
    assert (PACK/'pack.json').read_bytes()==before
    print(json.dumps(report['summary'],ensure_ascii=False))
