# contracts 바뀐 기록

바꾸는 법: ① 이 파일에 한 줄 → ② 스키마·예시 같이 고침 → ③ `scripts/test.ps1` 통과 → ④ 4명 확인(CODEOWNERS) 후 합침.
형식이 호환되지 않게 바뀌면 그 스키마의 `schema_version` 을 올리고, 옛 버전 읽기는 남겨 둔다 (DB 옛 행은 안 고침).

| 날짜 | 스키마 | 버전 | 바뀐 것 | 누가 |
|------|--------|------|---------|------|
| 2026-11-22 | 전체 | 1 | 첫 판 (ERD v1.2 11/22판 기준) | 태민 |
| 2026-11-22 | 전체 | 1 | 11/22 뼈대 검토 반영 (아직 아무도 안 썼으므로 버전은 1 그대로). 바뀐 것 요약: agent_spec.source 뺌 · config_snapshot 의 harness_version·model.seed·resolved 뺌, runtime.max_output_tokens · prereg.test = ni_then_sup 등 3값·env_error_reasons 필수·지표 이름 한 목록 · plan 의 n_templates·estimate.trials 뺌 · answer_condition 에 gate · trace spans[].output, outcome_reason 값 목록 · judge_settings·trial_metrics 가 {} 받음 · analysis.method.sequential.stop · job analyze 에서 experiment_id 뺌 · report evidence 에 trial_id, detail 칸 · api 에 등록·평가팩 목록·plan-proposal·stop·results·report, 실험 요청 후보는 id 만. 자세히 docs/review_1122.md | 태민 |
| 2026-11-22 | 전체 | 1 | 3차 검토 반영 (버전 1 그대로): 새 스키마 pack·settings·chat · forbidden 에서 gate 뺌 · common 에 result_class·first_fail_type·question_kind · metric 목록에서 regression_rate 뺌 · plan.proposal 은 서버가 채움(request·as_of·hash·edited·edited_fields), plan $defs body/stored, create 요청에 proposal{request, as_of}, plan-proposal 응답에 as_of, error code proposal_stale · trace 에 run_outcome↔outcome_reason 확인. 자세히 docs/review_1122.md "3차 검토" | 태민 |
| 2026-11-22 | (모양 변경 없음) | 1 | DB 이름 규칙(테이블 sa_, PK sa_<테이블>_id) — 계약의 칸 이름은 그대로, 설명 글은 sa_ 를 빼고 줄여 씀 (contracts/README 규칙 0) | 태민 |
| 2026-11-22 | (모양 변경 없음) | 1 | DB 모든 칸 이름 규칙(sa_<테이블>_<칸>, FK = 가리키는 PK 이름) — 계약의 칸 이름은 그대로, DB 와는 common/db_names 로 맞춤 | 태민 |
| 2026-11-23 | (모양 변경 없음) | 1 | DB 칸 이름 6차 규칙(PK `<테이블 단수>_id`, 나머지 칸은 ERD 짧은 이름) — 계약 칸 이름은 그대로 | 태민 |
| 2026-11-23 | api · agent_spec · component_spec · config_snapshot | 1 | ① 등록: `connection_type` 에서 `questions` 뺌(질문은 연결 방식이 아니라 세 방식 어디서든 쓰는 보조 단계) → `version.questions_used` 추가, 등록 요청에 `domain_code` 추가 (DB `sa_agent_versions.questions_used`, `sa_agents.domain_code`). ② 고도화 D: `component_spec` 에 `tool_search` 갈래(service·access·tools·search{method=bm25, top_k, always_loaded}), `config_snapshot.tool_search{method, top_k, deferred}` (선택 칸), DB `component_kind` 에 `tool_search`. 아직 아무도 안 썼으므로 버전 1 그대로. **④ 확인함(11/23)** | 태민 |
