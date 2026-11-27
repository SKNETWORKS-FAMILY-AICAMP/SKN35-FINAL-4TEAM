"""Record scoped environment evidence and prompt risks, without approving or locking a pack."""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'
sys.path.insert(0, str(ROOT / 'backend/src'))
from slotagent.common.hashing import canonical_hash

LITERAL_ROLES = {
    **dict.fromkeys(['UNRESOLVED','UNDEFINED','UNAVAILABLE','NONE','parse_error','unknown'], 'declared_fallback_or_error_vocabulary'),
    **dict.fromkeys(['runtime','environment','defaults'], 'declared_configuration_layers'),
    'boolean':'required_type_definition', 'rollback':'event_category_in_scope',
    **dict.fromkeys(['both','confirmed','redirect_not_allowed','blocked'], 'conditional_business_rule_vocabulary'),
    **dict.fromkeys(['[EMAIL]','[TOKEN]'], 'required_redaction_replacement'),
    **dict.fromkeys(['ops-alerts','ops-dev'], 'requested_write_targets_not_observed_completion'),
}


def atoms(value):
    if isinstance(value, dict):
        return [atom for item in value.values() for atom in atoms(item)]
    if isinstance(value, list):
        return [atom for item in value for atom in atoms(item)]
    return [str(value)]


def scan_prompt(task):
    prompt = task['prompt']
    body = prompt.split('응답 규격:')[0]
    inputs = set(atoms(task['slot_values']))
    overlaps = sorted({value for c in task['conditions'] if c['kind'] == 'info'
                       for value in atoms(c['spec']['expected']) if len(value) >= 3 and value not in inputs
                       and re.search(r'(?<![A-Za-z0-9_])' + re.escape(value) + r'(?![A-Za-z0-9_])', body)})
    findings = []
    scenario = task['slot_values'].get('scenario_id', '')
    if scenario.split('-')[0] in {'transient', 'persistent', 'conflict', 'fresh', 'insufficient'} and scenario in prompt:
        findings.append({'kind': 'outcome_cue_in_scenario_name', 'value': scenario,
                         'action': 'Use an opaque public ID with an explicit internal mapping; update prompt, adapter, data references and hashes together.'})
    if '응답은 성공하는 고정 fake 환경' in prompt:
        findings.append({'kind': 'future_tool_outcome_disclosed', 'value': '응답은 성공하는 고정 fake 환경',
                         'action': 'Remove the success guarantee while keeping fake execution and approval requirements.'})
    return {'code': task['code'], 'template': task['template'], 'findings': findings,
            'answer_literal_candidates': overlaps,
            'literal_roles': {v:LITERAL_ROLES.get(v,'needs_semantic_review') for v in overlaps},
            'procedure_review': ('business_constraints_and_scripted_sequence_mixed_independent_review_required'
                                 if task['template'] in {'LATEST_CONFIRMATION_SCOPE','UNCERTAIN_WRITE_RECONCILIATION',
                                                        'PARTIAL_WRITE_RECONCILIATION','APPROVAL_DATA_REVISION','EXPLICIT_URL_ALLOWLIST'} else None),
            'literal_scan_limit': 'Excludes slot inputs, response-format section and values shorter than 3 characters. Not a semantic no-leak proof.'}


def build(pack_dir=PACK):
    pack_dir = Path(pack_dir)
    pack = json.loads((pack_dir / 'pack.json').read_text(encoding='utf-8'))
    manifest = json.loads((pack_dir / 'practice/servers.json').read_text(encoding='utf-8'))
    spec = importlib.util.spec_from_file_location('environment_server', pack_dir / 'practice/server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    data = server.PracticeData(pack_dir / 'practice/servers.json', pack_dir / 'data')
    verification = json.loads((pack_dir / 'practice/verification.json').read_text(encoding='utf-8'))
    service = manifest['services'][0]
    assert verification['passed'] and verification['image'] == service['image']
    assert verification['server_version'] == service['version']
    assert verification['snapshot_hashes'] == data.hashes
    forbidden_keys = {'expected', 'answer_conditions', 'conditions', 'golden', 'confirmation', 'write_scenario'}

    def keys(value):
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}
        return set()

    shapes = []
    for name in data.tools:
        rows = data.call(name, {})
        assert not keys(rows) & forbidden_keys
        shapes.append({'name': name, 'rows': len(rows), 'repos': sorted({r['repo'] for r in rows}),
                       'result_contract': 'MCP TextContent containing a JSON array; invalid arguments => isError=true'})
    designs = []
    for snapshot in pack['data_snapshots']:
        path = (pack_dir / snapshot['location']).resolve()
        assert path.is_relative_to((pack_dir / 'data').resolve())
        content = json.loads(path.read_text(encoding='utf-8'))
        notes = snapshot.get('design', {}).get('notes', [])
        assert notes and all(isinstance(note, str) and note.strip() for note in notes)
        designs.append({'location': snapshot['location'], 'content_hash': canonical_hash(content), 'notes': notes,
                        'mounted_in_current_server': snapshot['location'] in {s['path'] for s in manifest['snapshots']}})
    prompts = [scan_prompt(task) for task in pack['tasks']]
    supported = set(manifest['template_codes'])
    risks = [p for p in prompts if p['findings']]
    local_path = pack_dir / 'practice/local_boundary_review.json'
    local_review = json.loads(local_path.read_text(encoding='utf-8')) if local_path.exists() else None
    if local_review is not None and local_review['pack_content_hash'] != canonical_hash(pack):
        local_review = None
    return {
        'schema_version': 1, 'date': '2026-11-27', 'reviewer': 'Codex assistant review, not independent human approval',
        'pack_content_hash': canonical_hash(pack), 'practice_manifest_hash': canonical_hash(manifest),
        'scope': {'templates': len(pack['templates']), 'tasks': len(pack['tasks']), 'snapshots': len(designs),
                  'actual_mcp_templates': len(supported), 'actual_mcp_tasks': sum(t['template'] in supported for t in pack['tasks'])},
        'tool_shape': {'status': 'passed_for_current_5_tools_only', 'docker_verification': verification, 'tools': shapes,
                       'not_served_templates': [t['code'] for t in pack['templates'] if t['code'] not in supported]},
        'data_design': {'status': '13_design_records_and_hashes_checked_not_all_services_verified', 'snapshots': designs,
                        'local_adapter_boundary': ({k:local_review[k] for k in ['task_count','template_count','read_responses','flagged_responses','approval']}
                                                   if local_review else 'not_checked_for_current_pack'),
                        'public_private_boundary': 'Only deployments/issues/operations are mounted. reconciliation.json contains replay/answer fields and must not be mounted whole; expose context only.'},
        'prompt_leak': {'status': 'changes_recommended_before_pack_approval' if risks else 'checked_patterns_clear_independent_review_pending', 'tasks_with_outcome_cues': len(risks),
                        'supported_tasks_with_outcome_cues': sum(p['template'] in supported for p in risks),
                        'literal_overlap_tasks': sum(bool(p['answer_literal_candidates']) for p in prompts),
                        'procedure_review_tasks': sum(bool(p['procedure_review']) for p in prompts),
                        'review_notes': ['Output vocabulary, fallback labels, masks and business rules are not automatically answer leakage.',
                                         'Scenario names that reveal likely outcomes and explicit future success guarantees are flagged separately.',
                                         'Detailed recipes in LATEST_CONFIRMATION_SCOPE, reconciliation and URL policy are already in REVIEW_CHECKLIST.md; reduce procedural guidance only together with grading/adapter review.',
                                         'Repeated same-template answers, prompt-only shortcut passing, and examples of permitted paths need independent review and real-model testing.'],
                        'tasks': prompts},
        'approval': {'whole_pack_pass': False, 'independent_human_review_done': False, 'database_env_checks_written': False,
                     'blockers': ['42 templates have no actual practice MCP service in this image.',
                                  'No current sa_env_checks approvals bound to a DB pack fingerprint were created.',
                                  'Independent review and actual 16-model-trial replay remain outstanding.']
                                 + (['Outcome cue findings need prompt/data/adapter review.'] if risks else [])}}


if __name__ == '__main__':
    report = build()
    output = PACK / 'practice/environment_review.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'scope': report['scope'],
                      'risk_tasks': report['prompt_leak']['tasks_with_outcome_cues'],
                      'supported_risk_tasks': report['prompt_leak']['supported_tasks_with_outcome_cues'],
                      'literal_overlap_tasks': report['prompt_leak']['literal_overlap_tasks'],
                      'whole_pack_pass': False}, ensure_ascii=False))
