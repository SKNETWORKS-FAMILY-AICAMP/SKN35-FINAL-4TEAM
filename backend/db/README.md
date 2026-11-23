# DB (① 담당)

## 이름 규칙 (11/23, 6차 — 칸 이름에서 `sa_<테이블>_` 을 뺌)

| 무엇 | 규칙 | 예 |
|------|------|----|
| 테이블·뷰 | `sa_<테이블>` | `sa_users`, `sa_effective_trials` |
| PK | `<테이블 단수>_id` | `sa_users.user_id`, `sa_analyses.analysis_id` |
| FK | **가리키는 PK 이름 그대로** | `sa_trials.experiment_id` → `sa_experiments.experiment_id` |
| FK (같은 테이블을 두 번·역할 이름) | 그 역할 이름 | `sa_comparisons.baseline_id`, `sa_agents.owner_id`, `sa_experiments.created_by` |
| 나머지 칸 | 짧은 이름 (ERD v1.2 이름 그대로) | `email`, `status`, `created_at` |
| 이름 붙인 인덱스·제약 | `sa_` 로 시작 | `sa_candidates_label_per_slot`, `sa_jobs_kind_matches_payload` |

- 예외 하나: `sa_domains` 의 PK 는 자연 키 `domain_code`(it_ops 등). FK 도 `domain_code`
- PK 단수 이름은 `common/db_names.py` 의 `PK` 표 (`answer_conditions` → `answer_condition_id`, `experiment_candidates` → `experiment_candidate_id`, `golden_trajectories` → `golden_trajectory_id`, `cost_ledger` → `cost_ledger_id`)
- 역할 이름 FK 9개: `sa_agents.owner_id`, `sa_experiments.derived_from`·`created_by`, `sa_labels.labeler_id`, `sa_env_checks.checked_by`, `sa_task_exposures.seen_by`,
  `sa_comparisons.exp_candidate_id`·`baseline_id`, `sa_cost_ledger.price_setting_id`
- FK 를 PK 이름과 같게 둔 덕에 `JOIN sa_experiments e USING (experiment_id)` 가 됨.
  `trg_pack_child_locked` 처럼 여러 테이블에 붙는 트리거도 `r.pack_version_id` 하나로 씀
- **여러 테이블을 잇는 SQL 에서는 칸 앞에 별칭을 붙일 것** (`t.status`, `e.status`) — `status`·`created_at`·`name` 같은 이름이 여러 테이블에 있음
- 함수·트리거 이름(`lock_experiment`, `analysis_units`, `trg_*`)은 그대로. 함수가 돌려주는 칸 이름(`task_id` 등)은 이제 테이블 칸 이름과 같음
- **JSON 계약(contracts)의 칸 이름과 거의 같음**. 다른 것은 PK(계약 `id` ↔ DB `<단수>_id`)와 4개뿐:
  `domains.code`→`domain_code`, `trials·grader_checks.exp_candidate_id`→`experiment_candidate_id`, `condition_results.condition_id`→`answer_condition_id`.
  DB 에 넣고 꺼낼 때 `slotagent.common.db_names` 로 맞춤 (`col("trials", "exp_candidate_id")` = `experiment_candidate_id`, `plain("candidates", 행)` = 짧은 이름 dict)
- **연습 DB(practice/)는 바꾸지 않음** — 에이전트가 시험 중에 보는 업무 데이터라, 이름에 우리 접두사가 보이면 안 됨
- 문서·스키마 설명에서는 테이블의 `sa_` 를 빼고 `experiments.prereg` 처럼 씀. 실제 이름은 `sa_experiments.prereg`
- ERD v1.2 이름 ↔ 지금 이름 전체 표: `backend/db/NAMES.md` (33개 테이블)
- `backend/tests/test_handoff_e2e.py::test_0_naming` 이 이 규칙을 DB 에서 직접 확인 (테이블·PK·FK·모든 칸이 db_names 표에 있는지)

## 파일

- `migrations/0001_product.sql`, `0002_comments.sql` = `erd_v1.2/product_db.sql`, `comments.sql` (11/22판)에서 **이름만 위 규칙으로 바꾼 것** (내용·제약은 같음). 두 파일로 나뉨
- `migrations/0003_review_1122.sql` = 11/22 뼈대 검토 반영 (templates.split, agents.expected_monthly_calls, spans.output,
  trials.harness_version, 값 목록 CHECK, 채점 실행·분석·리포트 중복 방지, write_intents 펜싱, 오류 HINT). 자세히: `docs/review_1122.md`
- `practice/0001_practice.sql` = 연습 DB (이름 규칙 밖)
- `seeds/` = 기본값 settings (`0001_settings_defaults.sql` 전체, `0002_pack_it_ops_judge.sql` 도메인 it_ops 판정기(② — 파일 이름 접두사 pack_) — domains 행이 먼저 있어야 함)
- `tests_constraints.sql` = 제약 테스트 (erd_v1.2/test_constraints.sql 사본). **새 이름으로 바꿈(11/22). 0001·0002 기준** — 0003 의 outcome_reason 값 목록과 맞지 않는 자유 문구가 있어 0003 뒤에는 돌리지 않음. `erd_v1.2/run_tests.py` 에서 150개 통과.
  지금 규칙은 `backend/tests/test_handoff_e2e.py` 가 확인
- 새 저장소에 합치기 전까지는 0001~0003 을 고침. 합친 뒤부터는 새 번호 파일(`0004_...sql`)을 더하고, 이미 합친 파일은 고치지 않음

## 오류 HINT (0003)

DB 가 막을 때 `RAISE ... USING HINT = '<code>'` 로 api.error code 를 붙임. `api/eng_errors.py` 는 HINT → 제약 이름 순으로 고르고, 문구로는 고르지 않음.
새 규칙을 더할 때도 HINT 를 붙일 것 (값은 `contracts/schemas/api.schema.json` `$defs/error` 의 code).
