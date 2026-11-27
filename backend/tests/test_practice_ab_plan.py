import importlib.util
import json
from pathlib import Path

from slotagent.workers.eng_serve import load_stdio

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('practice_ab',ROOT/'scripts/prepare_practice_ab.py')
plan=importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


def test_ab_equal_data_capabilities_and_no_write_tools():
    result=plan.build()
    a,b=(result['candidate_specs'][label] for label in ['A','B'])
    assert len(a['tools'])==5 and len(b['tools'])==3
    assert {cap for t in a['tools'] for cap in t['capabilities']}=={cap for t in b['tools'] for cap in t['capabilities']}
    assert a['runtime']==b['runtime'] and a['mcp_servers']==b['mcp_servers']
    assert all(t['access']=='read' for value in [a,b] for t in value['tools'])
    assert len(result['tasks'])==26 and len({t['template'] for t in result['tasks']})==8


def test_worker_docker_config_uses_image_entrypoint_without_duplicate_command(tmp_path):
    result=plan.build()
    path=tmp_path/'stdio.json'
    path.write_text(json.dumps(result['worker_stdio']),encoding='utf-8')
    server=load_stdio(path).servers['github']
    assert server.arguments==() and server.entrypoint is None
    assert len(server.mounts)==3 and server.allowed_data_roots
