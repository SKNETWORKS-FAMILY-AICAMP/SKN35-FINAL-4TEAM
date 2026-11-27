"""Prepare adapter coverage, response-type review and a non-destructive data-design proposal."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/it_ops/v0.1'
BUILTINS = {'request_user_confirmation', 'get_write_result', 'get_work_state'}
EMPTY_ITEMS = {
    ('RETRY_EXHAUSTED_READ', 'items'): 'string',
    ('CONFLICT_FRESH_PRIMARY', 'missing_fields'): 'string',
    ('CONFLICT_INSUFFICIENT_VERSION', 'primary_versions'): 'string',
    ('CONFLICT_INSUFFICIENT_VERSION', 'evidence_ids'): 'string',
}
SENTINELS = {'UNDEFINED', 'UNAVAILABLE', 'UNRESOLVED'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def type_of(value):
    return {str: 'string', int: 'integer', float: 'number', bool: 'boolean', list: 'array',
            dict: 'object', type(None): 'null'}[type(value)]


def build():
    pack = read(PACK / 'pack.json')
    digest = hashlib.sha256((PACK / 'pack.json').read_bytes()).hexdigest()
    split = read(PACK / 'practice/split_review_v02.json')
    assert split['source_pack_sha256'] == digest
    groups = read(PACK / 'groups.json')['groups']
    permissions = {t['name']: t for t in read(PACK / 'practice/tool_permissions.json')['tools']}
    observed = defaultdict(lambda: defaultdict(set))
    for entry in pack['golden']:
        if entry['kind'] not in {'success', 'alt_success'}:
            continue
        for span in read(PACK / entry['trace'])['spans']:
            if span['kind'] == 'tool':
                observed[entry['template']][span['name']].add(tuple(sorted(span.get('tool_args', {}))))
    adapter_rows = []
    for row in split['rows']:
        if row['proposed_split'] != 'held_candidate':
            continue
        tools = []
        for name, signatures in sorted(observed[row['template']].items()):
            builtin = name in BUILTINS
            definition = permissions.get(name)
            tools.append({'name': name, 'implementation': 'engine_builtin' if builtin else 'local_simulator_only',
                          'access': 'builtin' if builtin else definition['access'] if definition else 'unverified',
                          'observed_argument_key_sets': [list(s) for s in sorted(signatures)],
                          'registration_schema_verified': False,
                          'capabilities': definition.get('capabilities', []) if definition else []})
        assert tools
        writing = any(t['access'] == 'write' for t in tools)
        stateful = row['group'] == 'reliability'
        wave = '3_fake_write_integration' if writing else '2_isolated_stateful_reads' if stateful else '1_read_only_adapters'
        adapter_rows.append({'template': row['template'], 'group': row['group'], 'task_count': row['task_count'],
                             'task_codes': row['task_codes'], 'source_files': groups[row['group']]['snapshot_paths'],
                             'tools': tools, 'suggested_wave': wave, 'actual_mcp_ready': False,
                             'held_eligibility': 'pending_DB_and_team_exposure_review',
                             'required_work': ['Define and validate candidate tool input/output schemas; observed key sets are not a schema.',
                                               'Implement MCP/adapter public projections; never return a whole private scenario fixture.',
                                               'Use isolated trial/attempt state and the current frozen-data hashes.',
                                               'Validate with actual engine calls and record environment evidence.']
                             + (['Keep writes fake and use builtin confirmation/result/state tools; do not implement a second approval proxy.'] if writing else [])
                             + (['Reset response counters and pagination state for every trial/attempt.'] if stateful else [])})
    assert len(adapter_rows) == 35 and sum(r['task_count'] for r in adapter_rows) == 105
    adapter = {'schema_version': 1, 'date': '2026-11-27', 'base_pack_sha256': digest,
               'status': 'implementation_inventory_not_connected_not_held_approval',
               'summary': {'templates': 35, 'tasks': 105, 'actual_mcp_ready': 0,
                           'waves': dict(Counter(r['suggested_wave'] for r in adapter_rows))},
               'evidence_limit': 'Success/alternate representative goldens identify example paths, not every valid tool or every variant path.',
               'engine_builtins_are_not_missing_MCP_tools': sorted(BUILTINS), 'rows': adapter_rows}

    by_template = defaultdict(list)
    for task in pack['tasks']:
        by_template[task['template']].append(task)
    templates = []
    for template in pack['templates']:
        code = template['code']
        tasks = by_template[code]
        conditions = defaultdict(list)
        for task in tasks:
            for condition in task['conditions']:
                if condition['kind'] == 'info':
                    conditions[condition['spec']['key']].append((task, condition['spec']))
        fields = []
        for key, examples in conditions.items():
            types = sorted({type_of(spec['expected']) for _, spec in examples})
            item_types = sorted({type_of(item) for _, spec in examples if isinstance(spec['expected'], list)
                                 for item in spec['expected']})
            provenance = 'observed_across_template_variants'
            if 'array' in types and not item_types:
                declared = EMPTY_ITEMS.get((code, key))
                item_types = [declared] if declared else []
                provenance = 'source_issue_id_or_version_field_contract' if declared else 'unknown_not_inferred_from_empty_list'
            schema = {'type': types[0] if len(types) == 1 else types}
            if 'array' in types and item_types:
                schema['items'] = {'type': item_types[0] if len(item_types) == 1 else item_types}
            matches = sorted({spec['match'] for _, spec in examples})
            flags = []
            if 'array' in types:
                flags.append('prompt_lists_container_but_not_item_JSON_type')
            if len(types) > 1:
                flags.append('conditional_number_or_reserved_string_requires_explicit_rule')
            if 'exact' in matches and 'integer' in types:
                flags.append('JSON_Schema_integer_does_not_enforce_runtime_exact_numeric_encoding')
            reserved = sorted({spec['expected'] for _, spec in examples
                               if isinstance(spec['expected'], str) and spec['expected'] in SENTINELS})
            numeric = [kind for kind in types if kind in {'integer', 'number'}]
            if numeric and 'string' in types and reserved:
                schema['anyOf'] = [{'type': numeric[0] if len(numeric) == 1 else numeric}, {'enum': reserved}]
            fields.append({'key': key, 'proposed_json_schema': schema, 'item_type_basis': provenance,
                           'runtime_match': matches, 'reserved_fallback_strings': reserved,
                           'array_order': 'required' if 'array' in types and 'exact' in matches else 'set_comparison' if 'set_equal' in matches else None,
                           'review_flags': flags, 'task_codes': [t['code'] for t, _ in examples]})
        templates.append({'template': code, 'task_codes': [t['code'] for t in tasks],
                          'output_mode': 'JSON_object' if fields else 'brief_free_text_with_action_trace',
                          'fields': fields,
                          'v02_wording_candidate': ('JSON 객체 하나만 출력하고 필수 필드명·자료형을 지킨다. 설명문·코드 울타리를 붙이지 않는다. 빈 목록은 해당 필드의 값으로 []를 사용하며, 최상위 답을 []로 바꾸지 않는다.'
                                                   if fields else '실행 결과를 간단히 요약하며 실제 수행·승인 여부는 도구 기록으로 판정한다.')})
    info_tasks = [t for t in pack['tasks'] if any(c['kind'] == 'info' for c in t['conditions'])]
    format_review = {'schema_version': 1, 'date': '2026-11-27', 'base_pack_sha256': digest, 'applied': False,
                     'status': 'v02_wording_and_type_proposal_not_new_grading_policy',
                     'summary': {'structured_tasks': len(info_tasks), 'free_text_tasks': len(pack['tasks']) - len(info_tasks),
                                 'info_conditions': sum(c['kind'] == 'info' for t in pack['tasks'] for c in t['conditions']),
                                 'list_fields': sum('array' in (f['proposed_json_schema']['type'] if isinstance(f['proposed_json_schema']['type'], list) else [f['proposed_json_schema']['type']]) for t in templates for f in t['fields']),
                                 'mixed_type_fields': sum(isinstance(f['proposed_json_schema']['type'], list) for t in templates for f in t['fields']),
                                 'generic_empty_list_instruction_tasks': sum('목록 결과가 없으면[]' in t['prompt'] for t in info_tasks)},
                     'rules': ['Types are proposed per template across variants, not leaked from an individual expected answer.',
                               'Keep numeric IDs as strings where the existing condition contract uses strings; do not coerce silently.',
                               'JSON Schema integer can accept 3.0 while runtime exact may distinguish 3 and 3.0. Runtime grading remains authoritative.',
                               'Only explicitly defined fallback strings are allowed in a numeric/string union; arbitrary strings are not accepted.',
                               'Do not require JSON for the 18 free-text action-summary tasks without a separate decision.',
                               'Adopt in a new pack only after policy approval; do not retroactively fail historical model outputs.'],
                     'templates': templates}

    design = {'schema_version': 1, 'date': '2026-11-27', 'status': 'design_only_no_generator_or_data_migration',
              'base_pack_sha256': digest,
              'core': {'entities': ['synthetic_company', 'synthetic_person', 'team', 'membership'],
                       'shared_rules': ['Namespaced stable IDs; preserve source IDs and explicit composite keys.',
                                        'Timezone-aware instants plus Asia/Seoul business-date rules. Preserve historical raw timestamps.',
                                        'Use immutable generator/data versions and canonical content hashes.',
                                        'Record root seed and deterministic per-module seeds; do not use Python hash().']},
              'modules': {'it_ops': ['repository', 'deployment_run', 'issue', 'release', 'incident', 'oncall_assignment'],
                          'analytics_future': ['order', 'sales_record']},
              'interface': {'shape': 'generate(core, seed) -> domain_data; oracle(domain_data, task) -> expected_conditions',
                            'seed_derivation': 'int(SHA256(root_seed + module_name + generator_version), 16); independent RNG per module',
                            'model_view': 'Explicit public projections only; no oracle outputs, expected conditions, approval policies or future response schedule.'},
              'compatibility': ['Keep all 13 current snapshots unchanged and reference them from a versioned manifest first.',
                                'Repository issue/run numbers are composite with repo; never treat number alone as globally unique.',
                                'Do not invent company/team/person links for old rows lacking that information; mark unmapped until supplied.',
                                'Adapters translate legacy id/run_id/number while preserving original values and types.',
                                'A new dataset/version does not clear exposure of the same or equivalent template.'],
              'generation_policy': ['Compute answer-bearing values deterministically in code.',
                                    'If LLM prose is needed, generate once, review, freeze and hash; never regenerate during candidate runs.',
                                    'Do not embed raw private reconciliation/scenario files in a public common dataset.'],
              'phases': ['1: metadata manifest for current frozen sources; no data rewrites.',
                         '2: core and one IT module on a separate development dataset with deterministic checks.',
                         '3: validate relationships, answer/negative cases and public projections before a new pack version.',
                         '4: add analytics module only when its evaluation tasks exist.'],
              'current_sources': [{'location': s['location'], 'sha256': hashlib.sha256((PACK/s['location']).read_bytes()).hexdigest(),
                                   'snapshot_version': read(PACK/s['location']).get('snapshot_version')} for s in pack['data_snapshots']],
              'not_done': ['No shared-core data generated, no new relations fabricated, no v0.2 pack created, no DB or API changes.']}
    return adapter, format_review, design


def render(adapter, formatting):
    lines = ['<!-- next-steps-review:begin -->', '## held 연결·답 형식·공통 데이터 준비 — 11/27', '',
             '**적용 전 준비 자료다. v0.1·원본13개·정답·골든은 변경하지 않았다.**', '',
             '### held 후보 연결 범위', '',
             '[상세 어댑터 목록](it_ops/v0.1/practice/held_adapter_plan.json). 35유형105문항 모두 로컬 구현/예시 호출은 있으나 실제 MCP 연결은0유형이다. 아래 도구명은 대표 성공 경로이며 필수 도구 이름으로 고정하지 않는다. 내장 승인·결과/상태 조회는 새 MCP로 중복 구현하지 않는다.', '',
             '| 후보 유형 | 그룹 | 필요 업무 도구 예시 | 준비 단계 |', '|---|---|---|---|']
    for row in adapter['rows']:
        names = ', '.join(t['name'] for t in row['tools'] if t['implementation'] != 'engine_builtin')
        lines.append(f"| `{row['template']}` | {row['group']} | {names} | {row['suggested_wave']} |")
    counts = formatting['summary']
    lines += ['', '### 답 형식 세부 점검', '',
              f"[필드별 형식 후보](it_ops/v0.1/practice/answer_format_v02_review.json): JSON응답{counts['structured_tasks']}문항·자유 요약{counts['free_text_tasks']}문항, 정보 조건{counts['info_conditions']}개를 점검했다. 유형별 목록 필드{counts['list_fields']}개는 원소 타입까지 정리했고 혼합 타입 필드{counts['mixed_type_fields']}개는 조건부 특수 문자열을 구분했다. 공통 빈목록 지시{counts['generic_empty_list_instruction_tasks']}문항은 최상위[]로 오해하지 않도록 필드 안의[]로 명확히 할 후보를 작성했다.",
              '숫자형exact는3과3.0의 처리와 JSON Schema integer의 의미가 다를 수 있어 형식 스키마만으로 채점 규칙을 바꾸지 않는다. 과거12풀이 형식 정책도 여전히 미확정이다.', '',
              '### 공통 데이터 최소 설계', '',
              '[설계안](it_ops/v0.1/practice/common_data_design.json): 회사·사람·팀·ID·시간대·시드 규칙과 도메인 모듈의경계를 정리했다. 먼저 현재13개 원본의 메타데이터 manifest만 묶고 원본·정답을 재생성하지 않는다. 기존에 없는 소속 관계는 추정하지 않는다. generate(core, seed)와 oracle을 분리하고 긴 문장만 필요 시1회 생성·검수·고정한다. 실제 생성기·공통 데이터·DB 변경은 미구현이다.',
              '<!-- next-steps-review:end -->']
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    before = {str(p): p.read_bytes() for p in [PACK/'pack.json', *(PACK/'data').glob('*.json')]}
    adapter, formatting, design = build()
    for name, value in [('held_adapter_plan.json', adapter), ('answer_format_v02_review.json', formatting), ('common_data_design.json', design)]:
        (PACK/'practice'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=ROOT/'packs/README.md'
    text=path.read_text(encoding='utf-8')
    start,end='<!-- next-steps-review:begin -->','<!-- next-steps-review:end -->'
    if start in text:
        a,b=text.index(start),text.index(end)+len(end)
        text=text[:a]+render(adapter,formatting).rstrip()+text[b:]
    else:
        text=text.rstrip()+'\n\n'+render(adapter,formatting)
    path.write_text(text,encoding='utf-8')
    assert all(Path(p).read_bytes()==blob for p,blob in before.items())
    print(json.dumps({'adapter':adapter['summary'],'format':formatting['summary'],'sources_unchanged':len(before)},ensure_ascii=False))
