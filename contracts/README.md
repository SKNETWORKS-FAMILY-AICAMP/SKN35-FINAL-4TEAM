# 데이터 전송 스키마 (contracts)

역할 사이에 오가는 모든 JSON의 모양. **역할 사이를 오가는 jsonb 칸은 모두 스키마가 있음** (3차 2). 형식은 JSON Schema 2020-12.
파일은 16개 = 전송 스키마 15개 + `common.schema.json`(여럿이 함께 쓰는 공통 정의, 직접 저장하지 않음).

**스키마 없이 두는 jsonb 칸** (한 역할 안에서만 쓰고 넘기지 않음 — 넘기게 되면 그때 스키마부터):
`env_checks.detail`(②) · `grader_checks.value`(②③) · `validation_runs.params·result`(②③) · `templates.value_rule`(②) · `tasks.slot_values`(②) · `experiment_candidates.variant`(확장) · `agent_versions.connection`(④, 비밀 값 금지는 DB CHECK)

## 한눈에

| 스키마 | 들어가는 곳 | 쓰는 역할 → 읽는 역할 | 핵심 |
|--------|-------------|------------------------|------|
| `agent_spec` | agent_versions.spec | ④ → ① | 서비스, MCP 서버(5개까지), 켜진 도구 전부(50개까지), 실행 한도 |
| `component_spec` | candidates.component_spec | ④ → ① | 자리 하나에서 무엇으로 바꾸는지. `kind` 로 갈래: tool_bundle / custom_tool / prompt / model |
| `config_snapshot` | experiment_candidates.config_snapshot | ①의 함수로 ④가 저장 → ① 워커 | 후보 구성 완성본. 워커는 후보 구성을 이것만 봄 (문항·연습 환경은 평가팩, 엔진 버전·seed 는 실행 때 trials·spans 에) |
| `prereg` | experiments.prereg | plan-proposal(settings·③) → ④ 저장 → ①③ | 1차 지표·검정(ni_then_sup)·마진·α, **outcome_rules**(env_error_reasons 필수), **max_env_retries** |
| `plan` | experiments.plan | plan-proposal(②문항·③수) → ④ 저장 → ① | **tasks = [{task_id, batch_no}]**, 예상 비용. **proposal** 은 서버가 채움(요청·제안 시각·해시·고쳤는지·고친 칸) — 요청·응답은 `$defs/body`(proposal 없음), 저장 행은 `$defs/stored`. 문항 수·풀이 수는 계산값이라 안 둠 |
| `answer_condition` | answer_conditions.spec | ② → ① | kind 칸별 모양 5개: info / link / order / forbidden / end_state. `gate` = 성공 판정에 쓰는지 (forbidden 은 칸 없음 = 항상 관문) |
| `pack` | pack_versions.premises, data_snapshots.design, golden_trajectories.expected | ② → 리포트·①·① 채점 테스트 | 전제 문장·시간대 / 연습 데이터 설계 / 골든 궤적의 기대 판정 |
| `settings` | settings.value (key 마다) | ②③(+①) → ①·plan-proposal | 마진·α·회귀율 한도·env_error_reasons·판정기 설정·가격표 … `validate('settings', v, part=key)` |
| `chat` | chat_messages.function_args | ④ chatbot | 함수 5개 인자. create_experiment·calc_sample_size 는 api 요청 모양 그대로 |
| `trace` | spans·write_intents 행, golden_trajectories.trace | ① → ①②③ | 단계(llm/tool/plan), **LLM 이 낸 글·계획(output)**, 도구 인자·결과 전문, 가짜 쓰기, 사용량, 실패 원인(값 목록) |
| `job_payload` | jobs.payload | ①(engine/advance.py)만 넣음 → 워커 | 번호만: run_trial / grade / analyze / report / validation. kind = jobs.kind (DB CHECK) |
| `grading` | grading_runs.judge_settings, condition_results.evidence, trial_grades.metrics | ①② → ③ | 판정기 설정(← settings judge.settings), 근거 span seq, 진단 지표. `{}` = 해당 없음 |
| `analysis` | analyses.method, comparisons.exclusions·extra_needed | ③ → 공동·④ | 신뢰구간·Holm·seed, 중간 분석 stop 판정, 뺀 단위 사유별 수 |
| `report_content` | reports.content | 공동(1차 ③) → 화면·④ | 신호등, 판정, 한 줄 이유, 근거(comparison_id 또는 trial_id), detail(유형별·실패 유형·도구 시간 상위 10) |
| `api` | HTTP | 화면·chatbot ↔ 백엔드 | 에이전트 등록, 후보 등록, 평가팩 목록, plan-proposal, 실험 만들기, run·stop, status, results, report, error |

## 어떻게 이어지나 (예시 한 이야기)

`examples/` 는 하나로 이어진 이야기입니다: **"GitHub 조회" 자리에서 A(지금 MCP 도구 4개) vs B(필요한 3개)**.
A 는 작업 단계 조회가 없어 T1-1 을 틀리고, B 는 `list_issues` 를 빼서 T2(이슈 질문)가 도구 범위 밖(out_of_scope) — 둘 다 4/6.
⚠ 이 숫자는 **P-01 = fail 기준**. exclude 로 정하면 T2 가 A·B 둘 다 분석에서 빠져 T1 만 남음(A 2/4 vs B 4/4). "도구를 줄이면 이 자리 질문 일부를 못 푼다"를 보여 주는 예시.

```
agent_version.json ─┐
slot_and_candidates.json ─┼─ build_config_snapshot ─→ config_snapshot.B.json
                    │
pack.json (문항 3개·정답 조건) ── experiment.json (prereg·plan = plan-proposal 응답) ── lock_experiment() → 풀이 12개
                                                                  │
trace.json (실행 기록) ── grading_analysis_report.json (채점 → 분석 → 리포트) ── api_and_jobs.json
```

`backend/tests/test_handoff_e2e.py` 가 이 순서대로 실제 DB에 넣어 봅니다.

## 규칙

0. **DB 이름은 줄여서 씀** — 스키마 설명의 `agent_versions.spec`, `trials.outcome_reason` 은 실제로 `sa_agent_versions.spec`, `sa_trials.outcome_reason`.
   JSON 의 칸 이름은 짧은 이름 그대로 (`experiment_id`·`trial_id` …). DB 이름과는 `slotagent.common.db_names` 로 맞춤 (db/README.md 이름 규칙, db/NAMES.md)

1. **버전은 JSON 안의 `schema_version` 이 기준** (지금은 모두 1). DB 에 `*_schema_version` 칸이 있는 4곳
   (agent_versions.spec, candidates.component_spec, answer_conditions.spec, experiments.prereg)은 그 칸도 같은 값.
   plan·config_snapshot·judge_settings·metrics·method·content 는 DB 칸 없이 JSON 안의 값만.
   작은 조각(condition_evidence, exclusions, extra_needed, pack 의 세 칸, settings 값, chat 인자)은 버전이 없음 — 바뀌면 그걸 담는 쪽 버전을 올림.
2. **모르는 키는 막음** (`additionalProperties: false`). 키를 더하려면 스키마부터.
3. **`{}` = 해당 없음.** DB 기본값이 `'{}'` 인 칸(judge_settings, metrics, data_snapshots.design)은 스키마도 빈 객체를 받음 (반쯤 찬 객체는 막음).
4. **번호(id)는 DB가 만듦.** 요청에 id 를 넣지 않음. 예시의 id 는 연결을 보여 주는 값일 뿐.
5. **해시**: `canonical_hash()` — 키 정렬·공백 없음·UTF-8·정수로 떨어지는 실수는 정수. `sha256:` + 64자리.
   - agent_versions.spec_hash = hash({model, temperature, instructions, spec}) — 받는 방법(파일·러너·API, 질문 사용 여부)은 spec 에 없음(connection_type·questions_used 칸)
   - candidates.spec_hash = hash(component_spec)
   - experiment_candidates.config_hash = hash(config_snapshot)
   - analyses.input_hash = hash(넣은 trial_grades 행 목록)
6. **두 곳에 같은 값을 두지 않음** — job_payload·report evidence 는 번호만 담고 내용은 DB에서 읽음. 계산되는 값(문항 수·풀이 수)은 저장하지 않음.
   예외는 기록용 복사본 하나: analyses.method 의 alpha·sequential = prereg 값 (`checks.check_method` 가 저장할 때 같은지 확인).
7. **값 목록은 한 곳** — 지표 이름(`$defs/metric`, 회귀율은 목록이 아니라 comparisons.regression_rate 칸)·실패 원인(`$defs/outcome_reason`)·멈춘 이유(`$defs/stop_reason`)·결과 3분류(`$defs/result_class`)·첫 실패 단계(`$defs/first_fail_type`)·판정 질문(`$defs/question_kind`)은 common.schema.json 에 두고, DB CHECK(0003)도 같은 목록.
   run_outcome 은 outcome_reason 으로 정함: env_error_reasons 에 있으면 env_error, `timeout_` 이면 timeout, 나머지 agent_error (`checks.run_outcome_for`).
8. **스키마로 못 하는 검사는 `common.checks`** — 도구의 service·access 가 자리와 같은지, plan 의 문항 겹침·묶음, link.supports, 기준 후보 = agent_spec, 기준 후보 1개, method = prereg.

## 실행 기록을 DB에 넣는 순서 (trace → spans·write_intents)

1. 풀이가 `running` 이고 `trace.attempt = trials.attempt` 일 때만 넣음 (DB 트리거가 spans·write_intents 둘 다 확인 — 늦게 온 옛 워커 기록을 막음)
2. **spans 를 먼저** 넣고 `seq → spans.id` 표를 만듦. `spans[].output` → `spans.output`, 나머지 속성 → `spans.attributes`
   (`model.resolved`, `model.seed` = `trial_seed(task.seed, rep)`, `mcp.server_version`)
3. `write_intents[].span_seq` 를 그 표로 `span_id` 로 바꿔 넣음 (같은 풀이·같은 시도의 단계만 — DB 확인)
4. `usage` → trials 숫자 칸, `run_outcome`·`outcome_reason` → trials, 엔진 버전 → `trials.harness_version`, 비용 → cost_ledger 1행
5. 같은 트랜잭션에서 `engine.advance.on_trial_finished(trial_id)` — 범위가 다 끝났으면 채점 실행 1개
6. 채점의 근거(condition_evidence)는 `spans.id` 가 아니라 `seq` 로 가리킴 (골든 궤적에도 같은 채점 코드를 쓰려고)

## 합치는 규칙 (build_config_snapshot)

tool_bundle / custom_tool 후보:
1. agent_spec.tools 에서 자리와 같은 (service, access) 도구를 모두 빼고
2. 후보의 tools 를 넣고
3. 이름순 정렬 (겹치면 오류)
4. `write_tools` = access 가 write 인 도구 전부 → 쓰기 가로채기 대상
5. `mcp_servers` = 남은 도구가 실제로 쓰는 서버만

6. 후보가 `mcp_server` 를 주는데, 같은 이름의 서버를 **자리 밖 도구도** 쓰고 내용(버전 등)이 다르면 거절 — 다른 자리 도구까지 바뀌어 "한 자리만 바꿈"이 깨짐. 새 서버는 다른 이름으로 (예: `github-b`)
7. 기준 후보(is_baseline)는 agent_spec 의 그 자리 도구와 같아야 함 — 등록 때 `checks.baseline_component()` 로 자동으로 만듦

tool_search 후보는 1~7 을 tool_bundle 과 똑같이 하고, 스냅숏에 `tool_search{method, top_k, deferred}` 를 붙임 — deferred 도구는 검색해야 모델에게 보임 (11/23, 고도화 D).
prompt / model 후보는 도구는 그대로, 지시문·모델만 바꿈. skill / workflow 는 확장(지금은 거절).
**기획서 1.3: Tool 자리 먼저** — 지금은 `tool_bundle`·`custom_tool`·`tool_search` 만 스냅숏을 만들고(`snapshot.PHASE1_KINDS`), 후보의 `mcp_server` 는 에이전트의 같은 이름 서버와 똑같아야 함. 프롬프트·Skill·MCP 서버 교체는 그다음 단계.
스냅숏 `model.provider` 는 `agent_versions.model_provider` 그대로. 쓰기 도구는 `tools[].write_mode` 로 실행 방식을 정함(비면 fake).
엔진 버전·풀이별 seed·모델 고정 버전은 스냅숏에 넣지 않음 (실행 때 정해짐 → trials·spans).

## 아직 정하지 않은 것 (⚠)

`docs/decisions_pending.md` 한 곳에 모음 (out_of_scope 셈, 429, 연습 환경 MCP 연결, 사용자 확인 장치, 담당 확인 등).
