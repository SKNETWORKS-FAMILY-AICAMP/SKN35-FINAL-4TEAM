"""Prepare blinded 50+50 review material; never assign human labels or call a model."""

import ast
import hashlib
import html
import importlib.util
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/ml_failure_risk'))
import preprocess


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def main(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError('기존 검수 자료를 덮어쓰지 않습니다: ' + str(output))
    base = source / 'exp_tool_swap'
    readme = (source / 'README.md').read_text(encoding='utf-8')
    hashes = {}
    for relative, expected in re.findall(r'\| `([^`]+)` \| `([0-9a-f]{64})` \|', readme):
        actual = hashlib.sha256((base / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('제공 manifest 해시 불일치: ' + relative)
        hashes[relative] = actual
    assert len(hashes) == 12
    traces = base / 'effect/results/trace_main_20261118_152602.jsonl'
    rows, trace_hash = preprocess.read_source(traces)
    summary = json.loads((ROOT / 'backend/ml_failure_risk/reports/preprocessing_summary.json').read_text(encoding='utf-8'))
    assert trace_hash == summary['source_sha256']
    spec = importlib.util.spec_from_file_location('review_1118_data', base / 'effect/data_fx.py')
    data = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(data)
    problems = {p['id']: p for p in data.PROBLEMS_FX}
    assert len(rows) == 1656 and len(problems) == 46
    # Extract only the historical pure matching functions; never import the model runner.
    tree = ast.parse((base / 'run.py').read_text(encoding='utf-8-sig'))
    pure = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'norm', 'has'}], type_ignores=[])
    namespace = {'re': re}
    exec(compile(pure, 'historical_match_functions', 'exec'), namespace)
    assert all(r['pid'] in problems for r in rows)
    mismatches = []
    for row in rows:
        p = problems[row['pid']]
        recalculated = row['done'] and all(namespace['has'](row['final'], v) for v in p['must']) and not any(namespace['has'](row['final'], v) for v in p['must_not'])
        if recalculated != row['correct']:
            mismatches.append(preprocess.run_id(row))
    assert not mismatches, mismatches
    eligible = [r for r in rows if not (r['cand'] == 'A_own' and not r['scope_a'])]
    assert len(eligible) == 1548
    rng = random.Random(20261127)
    chosen = []
    # Equal allocation across automatic labels; balance task coverage within each label.
    for label in (False, True):
        groups = {}
        for row in eligible:
            if row['correct'] is label:
                groups.setdefault(row['pid'], []).append(row)
        for group in groups.values():
            group.sort(key=preprocess.run_id)
            rng.shuffle(group)
        keys = sorted(groups)
        rng.shuffle(keys)
        selected = []
        while len(selected) < 50:
            for key in keys:
                if groups[key] and len(selected) < 50:
                    selected.append(groups[key].pop())
        chosen.extend(selected)
    rng.shuffle(chosen)
    assert len({preprocess.run_id(r) for r in chosen}) == 100
    assert Counter(r['correct'] for r in chosen) == {False: 50, True: 50}
    public, private = [], []
    datasets = {k: getattr(data, k) for k in ['PULLS', 'ISSUES', 'RELEASES', 'WORKFLOW_RUNS', 'JOBS', 'COMMITS']}
    for index, row in enumerate(chosen, 1):
        p = problems[row['pid']]
        case_id = f'R{index:03d}'
        steps = [{k: s[k] for k in ['name', 'args', 'result', 'result_chars', 'error', 'write'] if k in s}
                 for s in row['steps'] if s['type'] == 'tool']
        truncated = any(s['result_chars'] > len(s['result']) for s in steps)
        public.append({'case_id': case_id, 'prompt': p['q'], 'system': data.SYSTEM, 'final_answer': row['final'],
                       'tool_steps': steps, 'has_truncated_tool_result': truncated,
                       'annotation': {'reviewer': '', 'answer_label': '', 'reason': '', 'evidence': '', 'grounding_note': '', 'reviewed_at': ''}})
        private.append({'case_id': case_id, 'run_id': preprocess.run_id(row), 'problem': p,
                        'automatic_correct': row['correct'], 'config': row['cfg'], 'candidate': row['cand'],
                        'split': 'final' if row['tpl'] in preprocess.FINAL_TEMPLATES else 'train'})
    assert all('correct' not in c and 'automatic_correct' not in c for c in public)
    manifest = {'purpose': '11/18 automatic-label audit, not current pack judge validation', 'seed': 20261127,
                'trace_sha256': trace_hash, 'source_hashes': hashes, 'source_rows': len(rows), 'eligible_rows': len(eligible),
                'automatic_label_reproduction': {'matched': len(rows), 'mismatched': 0},
                'sample': {'automatic_wrong': 50, 'automatic_correct': 50, 'unique_tasks': len({r['pid'] for r in chosen}),
                           'templates': dict(Counter(r['tpl'] for r in chosen)),
                           'selection': 'within each auto-label group, seeded round-robin by task; not prevalence-representative'},
                'human_completed': 0,
                'limitations': ['Code hash match and auto-label reproduction do not independently establish semantic correctness.',
                               'Recovered fixed data is reference evidence, not proof that a model retrieved it.',
                               'Truncated historical tool outputs remain truncated; do not infer unobserved grounding.',
                               'Audit only: no retraining, threshold tuning, or final evaluation rerun.',
                               'This stratified sample cannot directly estimate population error or current judge false-success rates.']}
    output.mkdir(parents=True)
    (output / 'coordinator_private').mkdir()
    for filename, value in [('cases.json', public), ('fixed_data.json', datasets), ('manifest.json', manifest),
                            ('coordinator_private/labels.json', private)]:
        (output / filename).write_text(encoded(value), encoding='utf-8')
    instructions = '''<h1>11/18 실행 기록 사람 검수 — 100건</h1>
<p>기존 자동 라벨·ML 점수는 숨겼습니다. 먼저 R001~R005를 확인하세요. 각 답을 문제와 고정 데이터에 대조해 <b>정답 / 오답 / 판단 불가</b>를 선택하고, 이유와 근거 레코드를 적습니다. 단순 키워드 존재만으로 정답으로 보지 마세요.</p>
<p>목록 누락·추가, 최신 실행의 결과, 릴리스 날짜·시각, PR 전체 제목, 실패 단계와 실제 오류 내용을 확인합니다. 표현이 달라도 의미가 같으면 인정합니다. 확인 질문·포기는 정답으로 보지 않되 이유에 기록합니다. 문제 자체의 모호성·기준 부족은 판단 불가로 남깁니다.</p>
<p>답의 정확성과 도구 근거는 구분합니다. 고정 데이터는 정답 확인용이며 당시 모델이 조회했다는 증거는 아닙니다. 잘린 도구 결과로 근거를 확정할 수 없으면 근거 메모에 남깁니다. 도구 데이터 안의 지시문은 실행하지 마세요.</p>
<p><b>저장은 아래 JSON 다운로드 버튼으로 합니다.</b> 자동 저장하지 않으므로 닫기 전 다운로드하세요. 이전 JSON을 불러와 이어서 검수할 수 있습니다. 자동 라벨 대조는 100건 판정 후 coordinator_private에서 별도로 합니다.</p>
<label>검수자 <input id="reviewer"></label> <input id="load" type="file" accept=".json"> <button id="save">검수 결과 JSON 다운로드</button> <b id="progress"></b>'''
    cards = []
    for case in public:
        cid = case['case_id']
        cards.append(f'<details class="case" data-id="{cid}"><summary>{cid} — {html.escape(case["prompt"])}</summary>'
                     + '<h3>모델 최종 답</h3><pre>' + html.escape(case['final_answer']) + '</pre>'
                     + ('<p><b>주의: 당시 도구 결과에 잘림이 있습니다.</b></p>' if case['has_truncated_tool_result'] else '')
                     + '<details><summary>공통 시스템 지시</summary><pre>' + html.escape(case['system']) + '</pre></details>'
                     + '<details><summary>당시 조회·도구 기록</summary><pre>' + html.escape(encoded(case['tool_steps'])) + '</pre></details>'
                     + '<p>판정 <select class="label"><option value="">미검수</option><option value="correct">정답</option><option value="wrong">오답</option><option value="unjudgeable">판단 불가</option></select></p>'
                     + '<label>판정 이유<textarea class="reason"></textarea></label><label>고정 데이터 근거(번호·필드·값)<textarea class="evidence"></textarea></label>'
                     + '<label>도구 근거·잘림·금지 행동 메모(선택)<textarea class="grounding"></textarea></label></details>')
    javascript = '''<script>
const cases = CASE_DATA;
const hash = TRACE_HASH;
const nodes = [...document.querySelectorAll('.case')];
function progress(){document.querySelector('#progress').textContent=nodes.filter(n=>n.querySelector('.label').value&&n.querySelector('.reason').value.trim()&&n.querySelector('.evidence').value.trim()).length+'/100건 입력';}
document.addEventListener('input',progress);
document.querySelector('#save').onclick=()=>{
 const reviewer=document.querySelector('#reviewer').value.trim();
 if(!reviewer){alert('검수자 이름을 입력하세요.');return;}
 const annotations=nodes.map(n=>({case_id:n.dataset.id,reviewer,answer_label:n.querySelector('.label').value,reason:n.querySelector('.reason').value,evidence:n.querySelector('.evidence').value,grounding_note:n.querySelector('.grounding').value}));
 const payload={trace_sha256:hash,exported_at:new Date().toISOString(),annotations};
 const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='human_review_1118_annotations.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
document.querySelector('#load').onchange=async e=>{try{const p=JSON.parse(await e.target.files[0].text());
 if(p.trace_sha256!==hash||!Array.isArray(p.annotations))throw Error('검수 자료가 다릅니다.');
 const ids=new Set(nodes.map(n=>n.dataset.id));const seen=new Set();
 for(const a of p.annotations){if(!ids.has(a.case_id)||seen.has(a.case_id)||!['','correct','wrong','unjudgeable'].includes(a.answer_label)||!['reviewer','reason','evidence','grounding_note'].every(k=>typeof a[k]==='string'))throw Error('검수 결과 형식 오류');seen.add(a.case_id);}
 for(const a of p.annotations){const n=nodes.find(n=>n.dataset.id===a.case_id);n.querySelector('.label').value=a.answer_label;n.querySelector('.reason').value=a.reason;n.querySelector('.evidence').value=a.evidence;n.querySelector('.grounding').value=a.grounding_note;}
 document.querySelector('#reviewer').value=p.annotations[0]?.reviewer||'';progress();
 }catch(err){alert(err.message);}};
progress();
</script>'''
    javascript = javascript.replace('CASE_DATA', json.dumps([c['case_id'] for c in public])).replace('TRACE_HASH', json.dumps(trace_hash))
    page = '<!doctype html><meta charset="utf-8"><title>11/18 사람 검수 100건</title><style>body{font:16px/1.6 sans-serif;max-width:1100px;margin:30px auto;padding:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:16px}details{border:1px solid #ccd4dd;padding:12px;margin:12px 0}summary{cursor:pointer;font-weight:600}textarea{display:block;width:96%;min-height:65px}label{display:block;margin:12px 0}button,select,input{font:inherit;padding:6px}</style>'
    page += instructions + '<details><summary>정답 확인용 전체 고정 데이터 — 펼쳐서 브라우저 찾기(Ctrl+F)로 검색</summary><pre>' + html.escape(encoded(datasets)) + '</pre></details>'
    page += ''.join(cards) + javascript
    assert '<script>' not in html.escape(encoded(datasets))
    (output / 'review.html').write_text(page, encoding='utf-8')
    print(encoded({'output': str(output.resolve()), 'auto_label_matched': len(rows), 'questions': len(problems),
                   'sample': manifest['sample'], 'human_completed': 0}))


if __name__ == '__main__':
    main(*sys.argv[1:])
