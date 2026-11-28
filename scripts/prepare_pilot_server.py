"""Freeze allowlisted pilot fixtures and MCP definitions; do not alter the pack or original snapshots."""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'
sys.path.insert(0, str(PACK / 'practice'))
from pilot_server import VERSION, extra_tools
from slotagent.common.hashing import canonical_hash


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build():
    pack = read(PACK / 'pack.json')
    pilot = read(PACK / 'practice/pilot_selection.json')
    codes = {row['template'] for row in pilot['templates']}
    tasks = [task for task in pack['tasks'] if task['template'] in codes]
    identifiers = {task['slot_values'].get('scenario_id') for task in tasks}
    def cases(filename):
        return [row for row in read(PACK / 'data' / filename)['cases'] if row['id'] in identifiers]
    def projection(row, keys):
        return {key: copy.deepcopy(row[key]) for key in keys}
    fixture = {
        'tasks': {task['code']: copy.deepcopy(task['slot_values']) for task in tasks},
        'contexts': read(PACK / 'data/context.json')['contexts'],
        'write_cases': [projection(row, ['id', 'repo', 'version', 'labels', 'owner', 'channels']) for row in cases('write_scenarios.json')],
        'incident_cases': [projection(row, ['id', 'repo', 'run_id', 'as_of', 'logs']) for row in cases('incident_scenarios.json')],
        'logs': read(PACK / 'data/incidents.json')['logs'],
        'evidence': [projection(row, ['id', 'facts', 'evidence']) for row in cases('evidence.json')],
        'metrics': [projection(row, ['id', 'service', 'errors']) for row in cases('metrics.json')],
        'workflows': [projection(row, ['id', 'context']) for row in cases('workflows.json')],
        'retries': [projection(row, ['id', 'repo', 'responses']) for row in cases('scenarios.json')],
    }
    base = read(PACK / 'practice/servers.json')
    tools = [{key: copy.deepcopy(tool[key]) for key in ['name', 'access', 'semantics', 'input_schema', 'capabilities']}
             for tool in base['services'][0]['tools']]
    permissions = {tool['name']: tool for tool in read(PACK / 'practice/tool_permissions.json')['tools']}
    for tool in extra_tools():
        tool['capabilities'] = permissions[tool['name']]['capabilities']
        if permissions[tool['name']].get('call_capabilities'):
            tool['call_capabilities'] = permissions[tool['name']]['call_capabilities']
        tools.append(tool)
    manifest = {'schema_version': 1, 'status': 'local_pilot_development_not_environment_approval',
                'fixture': {'file': 'pilot_fixture.json', 'content_hash': canonical_hash(fixture)},
                'services': [{'service': 'github', 'server_id': 'it-ops-pilot-practice', 'version': VERSION, 'tools': tools}],
                'template_codes': sorted(codes), 'task_codes': sorted(fixture['tasks']),
                'notice': 'Private responder schedule stays inside server. No pack answers/confirmation policies/receipts served. Writes require engine fake proxy.',
                'launch_policy': 'New process per trial/attempt; trusted --task-code supplied by launcher. Shared worker config cannot vary task-code yet; do not hardcode one for all jobs.'}
    return fixture, manifest


if __name__ == '__main__':
    fixture, manifest = build()
    for filename, value in [('pilot_fixture.json', fixture), ('pilot_manifest.json', manifest)]:
        (PACK / 'practice' / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'templates': len(manifest['template_codes']), 'tasks': len(manifest['task_codes']),
                      'tools': len(manifest['services'][0]['tools'])}))
