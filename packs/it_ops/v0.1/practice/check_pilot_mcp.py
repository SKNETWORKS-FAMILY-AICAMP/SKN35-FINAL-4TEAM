"""Run scripted goldens through real MCP reads and the engine fake-write proxy; no model API or DB."""

import argparse
import copy
import json
import sys
from pathlib import Path

from server import PracticeData
from slotagent.common import contracts
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine.eng_stdio import LocalStdioConfig
from slotagent.engine.loop import Dependencies, run_agent
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_pipeline import check_conditions

HERE = Path(__file__).resolve().parent
PACK = HERE.parent
ROOT = PACK.parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def snapshot():
    examples = ROOT / 'contracts/examples'
    source = read(examples / 'slot_and_candidates.json')
    result = merge_snapshot(read(examples / 'agent_version.json'), source['slot'], source['candidates'][0])
    manifest = read(HERE / 'pilot_manifest.json')
    result['tools'] = [
        {'name': tool['name'], 'description': tool['semantics'], 'parameters': tool['input_schema'],
         'service': 'slack' if tool['name'] == 'post_message' else 'github', 'access': tool['access'],
         'origin': 'mcp:github', 'capabilities': tool['capabilities'],
         **({'call_capabilities': tool['call_capabilities']} if tool.get('call_capabilities') else {}),
         **({'write_mode': 'fake'} if tool['access'] == 'write' else {})}
        for tool in manifest['services'][0]['tools']]
    result['runtime'].update(max_steps=60, timeout_sec=120)
    return contracts.validate('config_snapshot', result)


def check(docker_image=None):
    pack = read(PACK / 'pack.json')
    tasks = {task['code']: task for task in pack['tasks']}
    manifest = read(HERE / 'pilot_manifest.json')
    selected = [entry for entry in pack['golden'] if entry['template'] in manifest['template_codes']
                and entry['kind'] in {'success', 'alt_success'}]
    snap = snapshot()
    prereg = read(ROOT / 'contracts/examples/experiment.json')['prereg']
    results = []
    base_names = set(PracticeData(HERE / 'servers.json', PACK / 'data').tools)
    for entry in selected:
        task = tasks[entry['task_code']]
        trace = read(PACK / entry['trace'])
        calls = [span for span in trace['spans'] if span['kind'] == 'tool']
        replies = [Reply(tool_calls=(ToolCall(str(index), span['name'], json.dumps(span['tool_args'])),),
                         in_tokens=1, out_tokens=1) for index, span in enumerate(calls)]
        model = FakeModel([*replies, Reply(text=trace['final_answer'], in_tokens=1, out_tokens=1)])
        if docker_image:
            command = ['docker', 'run', '--rm', '-i', '--network=none', '--read-only', '--cap-drop=ALL',
                       '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m']
            for filename in ['deployments.json', 'issues.json', 'operations.json']:
                command += ['--mount', f'type=bind,source={(PACK / "data" / filename).resolve()},target=/data/{filename},readonly']
            command += [docker_image, '--task-code', task['code']]
        else:
            command = [sys.executable, '-u', str(HERE / 'pilot_server.py'), '--task-code', task['code']]
        stdio = LocalStdioConfig({'github': command}, timeout_sec=30, startup_timeout_sec=30)
        with stdio.open(snap) as call_tool:
            result = run_agent(snap, task['prompt'], task['seed'], Dependencies(model, call_tool), prereg=prereg,
                               confirmation=task.get('confirmation'), write_scenario=task.get('write_scenario')).trace
        assert result['run_outcome'] == 'completed', (entry['trace'], result['run_outcome'])
        conditions = [{**copy.deepcopy(condition), 'answer_condition_id': condition['seq']} for condition in task['conditions']]
        observed = {str(row.seq): row.passed for row in check_conditions(conditions, result, from_snapshot(snap, task.get('confirmation')))}
        assert observed == entry['expected']['conditions'], (entry['trace'], observed, entry['expected']['conditions'])
        actual_reads = [span for span in result['spans'] if span['kind'] == 'tool' and span['name'] not in {'post_message', 'create_issue', 'request_user_confirmation'}]
        for old, actual in zip([span for span in calls if span['name'] in {r['name'] for r in actual_reads}], actual_reads, strict=True):
            if old['name'] not in base_names:
                assert json.loads(old['tool_result']) == json.loads(actual['tool_result']), (entry['trace'], old['name'])
        results.append({'template': entry['template'], 'task_code': task['code'], 'kind': entry['kind'],
                        'read_calls': len(actual_reads), 'conditions': observed, 'passed': True})
        print(f"PASS {entry['template']} {entry['kind']}", flush=True)
    return {'kind': 'scripted_model_real_MCP_and_engine_rules_not_model_performance', 'passed': True,
            'transport': 'docker_stdio' if docker_image else 'local_stdio', 'image': docker_image,
            'templates': len({row['template'] for row in results}), 'traces': len(results),
            'actual_mcp_read_calls': sum(row['read_calls'] for row in results), 'external_model_calls': 0,
            'database_or_worker_verified': False, 'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-image')
    parser.add_argument('--report', type=Path, default=ROOT / 'tmp/pilot-mcp-1128.json')
    options = parser.parse_args()
    report = check(options.docker_image)
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}))
