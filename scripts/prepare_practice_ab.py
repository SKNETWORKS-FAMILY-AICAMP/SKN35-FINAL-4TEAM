"""Prepare equal-coverage A/B inputs; never create an experiment or call a model."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PACK=ROOT/'packs/it_ops/v0.1'
sys.path.insert(0,str(ROOT/'backend/src'))
from slotagent.common import contracts
from slotagent.common.hashing import canonical_hash


def build():
    manifest=json.loads((PACK/'practice/servers.json').read_text(encoding='utf-8'))
    pack=json.loads((PACK/'pack.json').read_text(encoding='utf-8'))
    example=json.loads((ROOT/'contracts/examples/agent_version.json').read_text(encoding='utf-8'))
    service=manifest['services'][0]
    spec=importlib.util.spec_from_file_location('ab_practice',PACK/'practice/server.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data=module.PracticeData(PACK/'practice/servers.json',PACK/'data')
    definitions={t['name']:{'name':t['name'],'description':t['semantics'],'service':'github','access':'read',
                           'origin':'mcp:github','capabilities':t['capabilities'],'parameters':t['input_schema']}
                 for t in service['tools']}
    shared={'schema_version':1,'services':[{'code':'github','name':'GitHub'}],
            'mcp_servers':[{'name':'github','package':'slotagent-it-ops-practice','version':service['version'],
                            'transport':'stdio','image_digest':service['image']}],
            'tools':[], 'runtime':copy.deepcopy(example['spec']['runtime'])}
    candidates={}
    names={'A':list(definitions),'B':['list_deployments','list_issues','list_operation_releases']}
    for label,selected in names.items():
        value=copy.deepcopy(shared)
        value['tools']=[definitions[n] for n in selected]
        contracts.validate('agent_spec',value)
        candidates[label]=value
    # Verify exact records under ID-field normalization, not only capability names.
    for a,b,key in [('list_deployments','list_operation_runs','run_id'),('list_issues','list_operation_issues','number')]:
        rows_a=[{**{k:v for k,v in r.items() if k!=key},'id':str(r[key])} for r in data.call(a,{})]
        rows_b=data.call(b,{})
        assert sorted(rows_a,key=lambda r:(r['repo'],r['id']))==sorted(rows_b,key=lambda r:(r['repo'],r['id']))
    supported=set(manifest['template_codes'])
    selected=[t for t in pack['tasks'] if t['template'] in supported]
    assert len(selected)==26
    stdio={'kind':'docker','scope':'role2-ab-local','servers':{'github':{'image':service['image'],
           'arguments':[], 'mounts':[{'source':str((PACK/s['path']).resolve()),'target':s['container_path']}
                                    for s in manifest['snapshots']],
           'allowed_data_roots':[str((PACK/'data').resolve())]}}}
    return {'schema_version':1,'status':'prepared_not_executed','pack_content_hash':canonical_hash(pack),
            'comparison':'5 read tools vs 3 read tools; equal source-record coverage, fixed descriptions and runtime',
            'model':{'provider':'openai','name':'gpt-4.1-mini','temperature':0},
            'instructions':'업무에 필요한 사실은 도구로 확인하고 각 문항의 응답 규격을 따르세요. 조회만 수행하고 변경·외부 공유하지 마세요.',
            'candidate_specs':candidates,'worker_stdio':stdio,
            'tasks':[{'code':t['code'],'template':t['template'],'seed':t['seed']} for t in selected],
            'actual_supported_templates':8,'tasks_count':26,'reps_1_trials':52,
            'blocked_before_real_execution':['Answer-format policy and source historical12 review pending.',
                                             'Evidence gates remain unchanged; use only a demo, not validated success-rate claims.',
                                             'No DB pack lock/environment approval or real model/judge run performed.',
                                             'Fix and record resolved model version, prereg, reps, seed, prices and budget before execution.'],
            'model_input_boundary':'Send only task.prompt, fixed instructions and candidate tool definitions; no task codes, expected conditions, golden traces or environment-review artifacts.'}


if __name__=='__main__':
    report=build()
    path=PACK/'practice/ab_plan.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'path':str(path),'A_tools':5,'B_tools':3,'templates':8,'tasks':26,'executed':False}))
