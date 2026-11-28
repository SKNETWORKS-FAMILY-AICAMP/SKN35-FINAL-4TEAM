"""Inspect local simulator responses; this does not verify a real MCP deployment."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'
sys.path[:0] = [str(ROOT / 'backend/src'), str(PACK / 'reference')]
from run_pack import evaluator
from slotagent.common.hashing import canonical_hash

PRIVATE_FIELDS = {'answer', 'expected', 'answer_conditions', 'conditions', 'golden',
                  'confirmation', 'write_scenario', 'calls', 'receipt', 'responses'}


def private_paths(value, path='$'):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            current = path + '.' + key
            if key in PRIVATE_FIELDS:
                found.append(current)
            found.extend(private_paths(item, current))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(private_paths(item, f'{path}[{index}]'))
    return found


def build():
    pack = json.loads((PACK / 'pack.json').read_text(encoding='utf-8'))
    groups = json.loads((PACK / 'groups.json').read_text(encoding='utf-8'))['groups']
    permission = json.loads((PACK / 'practice/tool_permissions.json').read_text(encoding='utf-8'))['tools']
    read_tools = {t['name'] for t in permission if t['access'] == 'read'}
    template_group = {template: name for name, group in groups.items() for template in group['template_codes']}
    tasks = []
    for task in pack['tasks']:
        group = template_group[task['template']]
        if group == 'lookup':
            continue
        trace = evaluator(group).simulate(task, 'success')
        observations = []
        for span in trace['spans']:
            if span['kind'] != 'tool' or span.get('name') not in read_tools:
                continue
            try:
                value = json.loads(span['tool_result'])
            except (ValueError, TypeError):
                observations.append({'tool':span['name'], 'seq':span['seq'], 'json_decodable':False,
                                     'private_paths':[], 'requires_manual_review':True})
                continue
            observations.append({'tool':span['name'], 'seq':span['seq'], 'json_decodable':True,
                                 'private_paths':private_paths(value), 'requires_manual_review':False})
        assert observations, task['code']
        tasks.append({'code':task['code'], 'template':task['template'], 'group':group,
                      'scope':'local_simulator_only_not_actual_MCP', 'observations':observations})
    assert len(tasks) == 126 and len({t['template'] for t in tasks}) == 42
    return {'schema_version':1, 'date':'2026-11-27', 'pack_content_hash':canonical_hash(pack),
            'task_count':len(tasks), 'template_count':42,
            'read_responses':sum(len(t['observations']) for t in tasks),
            'flagged_responses':sum(bool(o['private_paths']) or o['requires_manual_review'] for t in tasks for o in t['observations']),
            'tasks':tasks, 'approval':False,
            'limits':['Normal local simulator responses only; no deployed MCP/DB/runner verification.',
                      'A forbidden-key scan is not proof against semantic answer leakage.',
                      'Observed prior receipts and facts may be legitimate; future receipt fixtures, policies and canned final answers must remain private.',
                      'Real candidate authority and fake write protection are separate engine checks.']}


if __name__ == '__main__':
    report=build()
    path=PACK/'practice/local_boundary_review.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['task_count','template_count','read_responses','flagged_responses','approval']}))
