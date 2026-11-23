# 11/22 뼈대 검토 39개 — 처리 기록

**고침** = 뼈대에 반영하고 테스트로 확인 · **임시** = 임시 값을 넣고 결정 목록(`decisions_pending.md`)에 올림 · **문서** = 설명만 고침

테스트: `scripts\test.ps1` → 25개 통과 (계약 17 + DB e2e 8). 처음 16개에서 늘어남.

## A. 폴더 구조와 역할 흐름

| # | 지적 | 처리 | 어디 |
|---|------|------|------|
| 1 | 채점 실행을 만드는 주체가 없음, 중복 가능 | 고침 — ①의 `engine/advance.py on_trial_finished` 가 범위가 다 끝났을 때만 만듦. DB 유일 인덱스 `grading_runs_one_initial`(실험·범위당 initial 1개) + `ON CONFLICT DO NOTHING`. e2e 가 두 번 불러 1개인지 확인 | advance.py, 0003 |
| 2 | judge_settings 가 어디서 오는지 없음 | 고침 — `settings(scope=domain, key=judge.settings)` 최신 행을 ①이 복사. 시드 추가 | seeds/0002, advance.py |
| 3 | ④가 ③·②의 기본값을 받는 길이 없음 | 고침 — `POST /api/experiments/plan-proposal` (요청·응답 스키마). 고정값은 settings 시드, 계산은 `stats.sample_size`(③)·`packs.select.select_tasks`(②) 자리 | api 스키마, packs/select.py |
| 4 | dev/held 구분이 DB 에 없음 | 고침 — `templates.split` (문항 유형 단위, 기본 held) | 0003, pack.json |
| 5 | 순차 검정 중간 멈춤 주체 없음 | 고침 — ③은 `analyses.method.sequential.stop` 에 판정만, ①이 `on_analysis_done` 에서 멈춤·대기 풀이 취소 | analysis 스키마, advance.py |
| 6 | 실험 상태 전환·예산 멈춤 주체 없음 | 고침 — 상태는 ①만 바꿈(advance.py 머리말에 전환 그림). `check_budget` 이 cost_ledger 합으로 멈춤. e2e 8 이 확인. failed 조건은 임시(P-08) | advance.py |
| 7 | 흐름표에 빠진 테이블, FR-VAL 담당 없음 | 고침(담당은 임시) — README 에 "흐름표 밖 테이블" 표, `grading/validate.py` + job `validation` 처리 함수 | README, registry.py, P-04 |

## 문서와 소유권

| # | 지적 | 처리 | 어디 |
|---|------|------|------|
| 8 | "한 줄로" 순서에 실험 초안이 빠짐 | 문서 | README |
| 9 | README 두 곳의 0001 설명이 다름 | 문서 — 0001·0002·0003 으로 맞춤 | README, db/README |
| 10 | CODEOWNERS 로 4명 합의 강제 불가 | 정함 — 4명 모두 admin 이라 승인 수로 막지 않고 CHANGELOG + 4명 확인 약속 (P-06) | CODEOWNERS, README |
| 11 | CODEOWNERS 빈칸 | 고침 — api 파일별 담당(results = ③), grading/ 전체(①②), 공동 칸 1차 담당(reports ③, api·web ①). ①·④ 겹침은 ① (팀장 결정) | CODEOWNERS |

## B. 스키마 ↔ DB 칸·제약

| # | 지적 | 처리 | 어디 |
|---|------|------|------|
| 12 | "모든 JSON 에 schema_version = DB 칸" 규칙이 사실과 다름 | 문서 — JSON 안 값이 기준, DB 칸은 4곳만, 작은 조각 3개는 버전 없음 | contracts/README 규칙 1 |
| 13 | 2차 지표 이름 불일치 | 고침 — `$defs/metric` 한 목록 + DB CHECK `comparisons_metric_known` | common 스키마, 0003 |
| 14 | budget 0 이 스키마는 통과, DB 는 거절 | 고침 — `$defs/krw_positive` | api 스키마 |
| 15 | `{}` 처리 불일치 | 고침 — judge_settings·trial_metrics 가 `{}` 또는 완전한 모양만 받음 (규칙만 쓰는 채점은 questions 없이 `{}`) | grading 스키마 |
| 16 | agent_spec.source 가 DB 칸과 겹치고 해시를 바꿈 | 고침 — 뺌 (connection_type 칸만) | agent_spec 스키마 |
| 17 | condition_evidence span id vs seq | 고침 — seq 로 통일(골든 궤적에도 같은 코드), DB 주석 바로잡음 | grading 스키마, 0003 |
| 18 | jobs.kind 와 payload.kind 확인 안 함 | 고침 — CHECK `jobs_kind_matches_payload` | 0003 |
| 19 | trace → DB 변환 규칙 없음, write_intents 펜싱 없음 | 고침 — "실행 기록을 DB에 넣는 순서" 절 + 트리거 `write_intents_current_attempt` (같은 풀이·실행 중·지금 시도) | contracts/README, 0003 |
| 20 | 오류 문구로 오류 분류 | 고침 — 트리거 오류에 `HINT = <code>`, errors.py 는 HINT → 제약 이름 순. e2e 가 baseline_exists·label_taken·immutable·experiment_locked 확인 | 0003, api/errors.py |

## C. 칸이 모자라거나 과한 곳

| # | 지적 | 처리 | 어디 |
|---|------|------|------|
| 21 | trace 에 LLM 이 낸 글 없음 | 고침 — `spans[].output`, DB `spans.output` | trace 스키마, 0003 |
| 22 | "워커는 config_snapshot 만 봄"이 사실과 다름, MCP 연결 계약 없음 | 문서 + 임시(P-03) — "후보 구성은 이것만, 문항·환경은 평가팩" | config_snapshot 스키마, engine/ |
| 23 | 정답 조건의 역할(필수/진단) 없음 | 고침 — `gate`, 기본값 info·order·forbidden·end_state = true, link = false. `checks.condition_gate()` 한 곳 | answer_condition 스키마, checks.py |
| 24 | env_error_reasons 선택 칸, outcome_reason 값 목록 없음 | 고침 — env_error_reasons 필수(env_ 값만), `$defs/outcome_reason` + DB CHECK, 기본값 settings. 목록 자체는 임시(P-07) | prereg·trace·common 스키마, 0003, seeds |
| 25 | "사용자 확인 뒤"를 누가 판단하나 | 임시(P-05) — 결정 전까지 user_confirmed 는 항상 false | answer_condition·trace 스키마 설명 |
| 26 | 리포트 근거가 비교만 가리킴 | 고침 — evidence 는 comparison_id 또는 trial_id 중 하나 | report_content 스키마 |
| 27 | monthly_cost_krw 입력 없음 | 고침 — `agents.expected_monthly_calls` (구성이 아니라 해시 밖), 등록 요청에 칸. 필수 여부는 임시(P-09) | 0003, api 스키마 |
| 28 | detail 리포트 모양 없음 | 고침 — `detail`: by_template, fail_types, tool_time_top(10개) | report_content 스키마 |
| 29 | api 에 ④의 1단계 요청 없음 | 고침 — register_agent(자리·기준 A 자동), pack_list, plan_proposal, create_experiment_response, stop, results, report | api 스키마 |
| 30 | 잘못된 후보를 막는 검사 없음 | 고침 — `common/checks.py`: (a) check_component (b)(c) check_plan (d) check_task_conditions (e) baseline_component·check_baseline (f) 는 스키마로 표현 가능해서 tool_def 에 if/then | checks.py, snapshot.py, common 스키마 |
| 31 | status 풀이 수가 trials_total 보다 커짐 | 고침 — 계획 단위마다 마지막 실행으로 셈, `trials_total` 필수, 다시 실행 횟수는 `env_reruns` | api 스키마, e2e 7 |
| 32 | 실험 요청과 예시의 후보 모양 다름, role ↔ is_baseline | 고침 — 요청은 candidate id 목록만, role·label 은 후보 행에서. DB 트리거 `experiment_candidates_role` 이 확인 | api 스키마, experiment.json, 0003 |
| 33 | 같은 값이 두 곳 | 고침 — plan.n_templates·estimate.trials, analyze.experiment_id 뺌. method 의 alpha·looks 는 기록용 복사본으로 남기고 `check_method` 로 확인 | plan·job_payload 스키마, checks.py |
| 34 | prereg.test 값 하나 | 고침 — `ni_then_sup` / noninferiority / superiority, 필수 | prereg 스키마 |
| 35 | custom_tool 개수 설명 불일치 | 문서 — "직접 만든 도구(1~10개)" (자리 하나의 도구 묶음이 여러 개일 수 있음) | component_spec 스키마 |
| 36 | config_snapshot 에 실행 시점 아닌 값 | 고침 — harness_version → `trials.harness_version`, seed → `trial_seed(task.seed, rep)`(spans.attributes), max_output_tokens → runtime | config_snapshot 스키마, snapshot.py, 0003 |
| 37 | MCP 서버를 바꾸면 다른 자리도 바뀜 | 고침 — 같은 이름·다른 내용의 서버를 자리 밖 도구가 쓰면 거절 ("다른 이름으로") | snapshot.py |

## D. 예시 이야기

| # | 지적 | 처리 | 어디 |
|---|------|------|------|
| 38 | B 가 T2 를 풀 수 없는데 6/6 | 고침 — B 의 T2 를 out_of_scope 예시로. A 는 T1-1 을 틀림. 둘 다 4/6, 판단 보류, 위험에 "뺀 도구가 필요한 질문" | grading_analysis_report.json, e2e 5 |
| 39 | 후보 이름 "필요한 3개만"인데 도구 1개 | 고침 — api 예시는 C "릴리스 조회만 (도구 1개)" | api_and_jobs.json |

## 2차 검토 (11/22 저녁, 8개)

팀장 결정: 4명 모두 저장소 admin 이라 PR 승인 수는 상관없음. ①·④가 겹치는 담당은 무조건 ①.

| # | 지적 | 처리 |
|---|------|------|
| 1 | P-06 "승인 수 4"면 PR 이 안 합쳐짐 | 정함 — 승인 수로 막지 않음 (모두 admin). CHANGELOG + 4명 확인 약속 |
| 2 | P-07 의 "0004 CHECK" 가 사실과 다름 | 문서 — CHECK 는 지금 0003 에 있음, 값을 바꿀 때 0004 |
| 3 | 리포트 담당 표기 두 가지 | 문서 — 리포트 공동(1차 ③) · 대화 ④ chatbot 으로 통일 |
| 4 | plan-proposal 주인 없음, 제안을 고쳤는지 모름 | 고침 — 응답 모양 ① 1차(`api/plan_proposal.py`), `plan.proposal = {hash, edited, edited_fields}` + `checks.check_proposal`. 같은 규칙으로 api/·web 1차도 ① |
| 5 | stop_reason 자유 글 | 고침 — `budget / interim / user / job_failed` ($defs/stop_reason + DB CHECK `experiments_stop_reason_known`), stop 요청은 본문 없음 |
| 6 | 예산이 조금 넘을 수 있음 | 문서 — 풀이·판정기 비용을 같은 예산에서 셈, 시작 전에만 확인하므로 돌고 있는 만큼 넘을 수 있음 (advance.py, README) |
| 7 | 예시 4/6 은 P-01 = fail 기준 | 문서 — 예시 옆에 적음 (exclude 면 A 2/4 vs B 4/4) |
| 8 | 스키마 "12개"인데 파일 13개 | 문서 — 12개 + common(공통 정의) |

## 3차 검토 (11/22 밤, 설계 9개 + 문서 3개 + 폴더 접두사)

2차 4번(plan-proposal)의 처리 방식을 바꿈: ④가 "고쳤는지"를 적던 것을 **서버가 제안을 다시 만들어 비교**하는 방식으로.
DB 변경(3·4·8)은 아직 새 저장소에 합치기 전이라 0004 를 만들지 않고 0003 에 넣음.

| # | 지적 | 처리 |
|---|------|------|
| 1 | forbidden 에 `gate: false` 를 넣으면 DB 가 채점 행을 거절 | 고침 — forbidden 에서 `gate` 칸을 뺌 (항상 관문). `checks.condition_gate("forbidden", …)` 는 항상 true |
| 2 | 역할 사이를 오가는데 스키마가 없는 jsonb | 고침 — 원칙을 "역할 사이를 오가는 jsonb 만 스키마"로. 새 스키마 3개: `pack`(premises·data_design·golden_expected), `settings`(key 마다), `chat`(함수 5개 인자). 스키마 없이 두는 칸은 contracts/README 에 목록 |
| 3 | 값 목록이 DB 에만 있는 것 3개 | 고침 — common 에 `result_class`·`first_fail_type`·`question_kind`. judge_settings.questions·report detail.fail_types 키가 이걸 씀. DB CHECK `llm_votes_question_kind_known` (0003) |
| 4 | 분석·리포트를 두 번 만들 수 있음 | 고침 — 유일 인덱스 `analyses_one_per_scope`(채점 실행 + 중간 여부 + 묶음), `reports_one_per_kind`(분석 + 종류). 같은 채점으로 다시 분석하려면 재채점(regrade) |
| 5 | `plan.proposal` 을 ④가 적어서 확인이 안 됨 | 고침 — create 요청에 `proposal: {request, as_of}`, 요청의 plan 엔 proposal 없음(`plan#/$defs/body`). 서버가 `common.proposal.verify` 로 다시 만들어 비교 → 저장 행 `plan.proposal = {request, as_of, hash, edited, edited_fields}`(`plan#/$defs/stored`). plan-proposal 응답에 `as_of`. 24시간 넘은 제안은 `proposal_stale`. 본체는 `common/proposal.py`, 라우터는 `api/eng_plan_proposal.py`. `checks.check_proposal` 은 지움 |
| 6 | run_outcome 과 outcome_reason 관계 없음 | 고침 — 규칙: env_error_reasons 에 있으면 env_error, `timeout_` 이면 timeout, 나머지 agent_error. `checks.run_outcome_for()` 한 곳. trace 스키마는 prereg 없이 알 수 있는 것만 확인 (timeout_ ↔ timeout, agent_ → agent_error, env_error 는 env_·429 이유만) |
| 7 | 채점 검증 담당 표기 두 가지 | 문서 — job_payload validation 갈래를 "② 1차, ③ 계산" 으로 |
| 8 | 회귀율이 두 곳 | 고침 — metric 목록에서 `regression_rate` 를 빼고 `comparisons.regression_rate` 칸에만. DB CHECK `comparisons_metric_known` 도 같게 |
| 9 | trace "러너 업로드는 이 모양 그대로" | 문서 — 뺌. 러너 업로드 모양(시작·끝 시각, 서명)은 뒷반에 따로 (runner/README) |
| 문서 | 예산 초과 상한 | README·advance.py — "최대 (동시 워커 수 × 풀이 1번 예상 비용) + 진행 중인 채점 비용까지 넘을 수 있음". 예약 장부는 두지 않음 |
| 문서 | 먼저 정할 것 | decisions_pending — P-01·P-05 ★우선, P-08 그대로 |
| 폴더 | 여러 역할이 쓰는 폴더 | 파일 이름 앞에 역할 접두사 `eng_ ① · pack_ ② · stats_ ③ · intake_ ④` — grading/(eng_pipeline·eng_rules·pack_judge·pack_classify·pack_validate), api/(eng_errors·eng_plan_proposal), db/seeds/(0002_pack_it_ops_judge), backend/tests/(새 테스트부터). CODEOWNERS 는 접두사로 담당 |

구현 단계로 넘김 (지금은 하지 않음): 장애 주입·복구 테스트, 동시 워커 검증, 실제 에이전트·LLM 실행 검증, 실행 환경 격리.

## 아직 안 한 것

- `db/tests_constraints.sql` 은 0001·0002 기준이라 0003 뒤에는 돌리지 않음 (outcome_reason 자유 문구)
- 함수 몸통은 아직 stub: `common.proposal.propose`, select_tasks, sample_size, pack_validate, register_agent
- 맨 위 `packs/`(평가팩 원본)와 `backend/src/slotagent/packs/`(코드)는 폴더 이름이 같음 — 접두사로는 못 풀어서 그대로 둠

## 4차 (11/22 밤): DB 이름 규칙

사용자 결정: DB 도 파일 이름처럼 앞에 접두사. 테이블 `sa_users`, PK `sa_users_id` 꼴.

| 무엇 | 처리 |
|------|------|
| 테이블·뷰 33+1개 | `sa_` 로 시작 (`sa_effective_trials` 포함). 0001~0003·seeds 를 고침 (아직 합치기 전이라 0004 를 만들지 않음) |
| PK | `sa_<테이블>_id`. 예외: `sa_domains` 는 자연 키 `code` 그대로 |
| FK 칸 | 이름 그대로 (`experiment_id` 등) — contracts 의 번호 칸 이름과 맞추려고. 바꾸면 api·job_payload·trace 등 계약이 함께 바뀜 |
| 이름 붙인 인덱스·제약 | `sa_` 로 시작 (api/eng_errors.py 의 제약 이름 표도 같이) |
| 함수·트리거 | 그대로 |
| 연습 DB | 바꾸지 않음 — 에이전트가 시험 중에 보는 이름이라 |
| 코드 | engine/advance.py, common/snapshot.py(행의 PK 를 `id` 로 맞춰 merge_snapshot 에 넘김), common/proposal.py, e2e 테스트의 SQL |
| 확인 | `test_0_naming`: public 의 모든 테이블·뷰가 `sa_`, PK 가 `sa_<테이블>_id` (테이블 33개). 29 passed |
| 문서 | README·contracts/README·db/README 에 규칙. 설명 글에서는 `sa_` 를 빼고 줄여 씀 |

남은 것: `erd_v1.2` 문서들(ERD·테이블 정의서·DB 설계서)은 아직 옛 이름. `db/tests_constraints.sql` 도 옛 이름(돌리지 않음).

## 5차 (11/22 밤): 모든 칸 이름도 sa_ 규칙

사용자 결정: PK 만이 아니라 모든 칸을 같은 규칙으로. FK 는 가리키는 PK 이름 그대로, JSON 계약의 칸 이름은 그대로.

| 무엇 | 처리 |
|------|------|
| 칸 310개 | `sa_<테이블>_<칸>` (예: `sa_users_email`). 0001~0003·seeds·0002 주석을 고침 |
| FK | 가리키는 PK 이름 (`sa_trials.sa_experiments_id`). 같은 테이블을 두 번·역할 이름은 자기 접두사: `sa_comparisons_exp_candidate_id`·`sa_comparisons_baseline_id`, `sa_agents_owner_id`, `sa_env_checks_checked_by`, `sa_task_exposures_seen_by`, `sa_experiments_created_by`, `sa_labels_labeler_id`, `sa_cost_ledger_price_setting_id` |
| sa_domains | PK 를 `sa_domains_code` 로 (4차에선 `code` 그대로였음). FK 도 `sa_domains_code` |
| 제약 이름 | 자동 이름이 길어져서 오류 표가 쓰는 것은 이름을 붙임: `sa_candidates_label_per_slot`, `sa_experiment_candidates_label_per_experiment`, `sa_experiments_budget_positive` |
| 코드 | 이름표 한 곳 `common/db_names.py` (`col`, `plain`). snapshot 은 `plain()` 으로 짧은 이름 행을 만들어 merge_snapshot 에 넘김. advance·proposal·e2e 테스트의 SQL |
| 확인 | `test_0_naming` 이 테이블·PK·FK·모든 칸을 DB 에서 직접 확인. 29 passed. 남은 옛 칸 이름 검사: 함수 결과 칸(`analysis_units` 의 task_id 등)만 남음 — 테이블 칸이 아니라 그대로 |
| 대응표 | `db/NAMES.md` — ERD v1.2 이름 → 지금 이름 (ERD·테이블 정의서 고칠 때 씀) |

ERD 문서(11/22 밤): `erd_v1.2` 의 원본(product_db.sql = 0001, dictionary.py, design_text.py, ERD.md, 빌드 스크립트)을 새 이름으로 바꾸고 문서 7종(ERD·테이블 정의서·DB 설계서·쉬운 설명서·draw.io)을 다시 만듦. 제약 테스트 150개 + 연습 DB 10개 통과(바꾸기 전과 같은 수). 바꾸기 전 판은 `D:\final_test\이전 버전\erd_v1.2_칸이름바꾸기전_1122`. `db/tests_constraints.sql` 도 새 이름 사본으로 바꿈.

남은 것: 함수 결과 칸 이름(`analysis_units` 의 task_id 등)을 바꿀지는 미정. 문서 파일 이름은 v1.2 그대로.

## 6차 (11/23): 칸 이름에서 `sa_<테이블>_` 접두사를 뺌

사용자 결정: 칸 이름이 너무 길어짐 (가장 긴 것 `sa_experiment_candidates_label_per_experiment` 45자 — 길이 대부분은 `sa_` 가 아니라 칸마다 붙는 테이블 이름).
테이블의 `sa_` 는 그대로 두고(다른 스키마·연습 DB 와 안 겹치게), 칸만 짧게.

| 무엇 | 처리 |
|------|------|
| PK | `sa_<테이블>_id` → `<테이블 단수>_id` (`user_id`, `analysis_id`, `experiment_candidate_id` …). 표는 `common/db_names.py` 의 `PK` |
| FK | 가리키는 PK 이름 그대로 (규칙은 같음, 이름만 짧아짐). 역할 이름 FK 9개는 그 이름 (`owner_id`, `baseline_id`, `checked_by` …) |
| 나머지 칸 | ERD v1.2 이름 그대로 (`email`, `status`) |
| 제약·인덱스 이름 | 그대로 (`sa_` 로 시작) |
| 바꾼 이름 | 318개, 16개 파일 1717곳. 0001~0003·seeds·tests_constraints·NAMES.md·코드·e2e 테스트. NAMES.md 의 옛 이름 → 새 이름으로 기계적으로 바꿈 |
| JSON 계약 | 안 바뀜. DB 이름과 다른 것은 PK(`id`)와 4개뿐 (`domains.code`, trials·grader_checks `exp_candidate_id`, `condition_id`) |
| 확인 | `scripts/test.ps1` 30 passed (`test_0_naming` 을 새 규칙으로 고침). `erd_v1.2/run_tests.py` 제약 150/150, 연습 DB 10/10, 설명 없는 칸 없음 |
| ERD 문서 | `erd_v1.2` 원본을 같은 표로 바꾸고 문서 7종을 다시 만듦 (`build_dictionary.py` 의 PK 판단을 DB 에서 읽도록 고침). 재생성한 comments.sql = 0002 와 같음 |
| 바꾸기 전 판 | `D:\final_test\이전 버전\slotagent_skeleton_sa접두사_1123`, `erd_v1.2_sa접두사_1123` |

5차의 "남은 것: 함수 결과 칸 이름(`analysis_units` 의 task_id 등)" 은 이제 테이블 칸 이름과 같아져서 풀림.
주의: 여러 테이블을 잇는 SQL 은 칸 앞에 별칭을 붙일 것 (`status`·`created_at` 이 여러 테이블에 있음).

## 7차 (11/23): 등록 질문 · 도메인 · 도구 검색 후보 (계약 변경 한 번에 묶음)

| 무엇 | 처리 |
|------|------|
| 질문 | 연결 방식이 아님 (사용자). `connection_type` = spec_upload·runner·api, 질문을 썼는지는 `sa_agent_versions.questions_used`. spec 에 안 넣음(spec_hash 유지) |
| 도메인 | 등록 질문 1번(드롭다운) → `sa_agents.domain_code` (FK, 비면 평가팩 전부 보여 줌). 버전마다 안 바뀌므로 agents 에 |
| 도구 검색 | 고도화 D. `component_kind`·component_spec 에 `tool_search`, 스냅숏에 `tool_search` 칸. `checks.check_component` 가 always_loaded ⊂ tools, 검색할 도구 1개 이상 확인 |
| DB | 0003 끝에 더함 (합치기 전 규칙). tests_constraints.sql 은 0001·0002 기준이라 안 건드림 |
| 예시 | agent_version·api_and_jobs = spec_upload + questions_used, it_ops. slot_and_candidates 에 후보 C(도구 검색) |
| 확인 | `scripts/test.ps1` 33 passed (도구 검색 스냅숏·거절, 질문 연결 방식 거절 3개 더함. e2e 예산 테스트는 후보 수로 셈) |
| 남은 것 | ④ 확인. ERD v1.2 문서(erd_v1.2)에는 아직 반영 안 함 |

## 8차 (11/23): 기획서 1.3 반영

| 무엇 | 처리 |
|------|------|
| P-01 | **확정: 범위 밖은 실패로 셈** (1.3 5.4). prereg·settings 는 `fail` 만. 실행 전 판정: 도구 `capabilities` × 문항 유형 `required_capabilities` → `checks.template_scope` (in_scope / out_of_scope / excluded_write / needs_review). 리포트 `detail.in_scope` |
| 쓰기 도구 | 1.3 5.8·8.1: 사용자가 실행 방식을 고름 → `tool_def.write_mode`. 업로드 fake·exclude_tasks, 러너 fake·test_space, API dry_run 만(필수). 쓰기 도구 10개까지. `checks.check_write_modes` |
| 모델 | 회사 4종 `model_provider` (DB 칸 + 등록 요청 필수 + 스냅숏). 같은 회사 안에서 버전만 바꿈 |
| 도구 개수 | 50개 한도 뺌 (1.3 8.2). 설명 토큰 합계 상한은 값 미정(P-11) |
| Tool 먼저 | `snapshot.PHASE1_KINDS` = tool_bundle·custom_tool·tool_search. 새 MCP 서버 후보 거절 |
| DB | 0003 끝에 `sa_agent_versions.model_provider`, `sa_templates.required_capabilities` |
| 예시 | 도구에 capabilities, 쓰기 도구 write_mode=fake, pack 문항 유형에 required_capabilities, 리포트 in_scope (A 2/4 vs B 4/4, B 범위 밖 2) |
| 확인 | `scripts/test.ps1` 38 passed (P-01·범위 판정·쓰기 방식·모델 회사·도구 개수·Tool 먼저 5개 더함) |
| DB 추가 (8차 뒤) | `sa_experiment_candidates.template_scope` — 실행 전 범위 판정을 후보 넣을 때 저장, 잠금 뒤 못 바꿈, needs_review 는 CHECK 로 막음. `sa_agents.runner_token_hash`(UNIQUE)·`runner_token_revoked_at` — 러너 연결 토큰은 해시만. 테스트 38 passed (e2e 에 저장·거절 확인 더함) |
