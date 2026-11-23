-- =====================================================================
-- 0003: 11/22 뼈대 검토 반영 (0001·0002 는 erd_v1.2 그대로 두고 여기서만 바꿈)
-- 괄호 안 번호 = docs/review_1122.md 의 검토 번호
-- =====================================================================

-- ---------------------------------------------------------------------
-- 칸 추가
-- ---------------------------------------------------------------------
-- (4) 고칠 때 쓰는 문항(dev)과 확인용 문항(held). 문항 유형 단위로 나눔 — 같은 유형의 문항이 양쪽에 섞이면 시험 맞춤이 샘
ALTER TABLE sa_templates ADD COLUMN split text NOT NULL DEFAULT 'held' CHECK (split IN ('dev', 'held'));
COMMENT ON COLUMN sa_templates.split IS 'dev = 고칠 때 들여다보는 문항 유형 / held = 확인용(실험 기본). plan-proposal 은 held 만 고름 (실험 ⑪)';

-- (27) 리포트 월 비용의 입력. 구성이 아니라서 sa_agent_versions.spec(해시 대상)이 아니라 sa_agents 에 둠
ALTER TABLE sa_agents ADD COLUMN expected_monthly_calls int CHECK (expected_monthly_calls IS NULL OR expected_monthly_calls > 0);
COMMENT ON COLUMN sa_agents.expected_monthly_calls IS '한 달 예상 호출 수 (등록 질문). report monthly_cost_krw = 풀이 평균 비용 × 이 값. 비면 월 비용을 안 보여 줌';

-- (21) LLM 이 낸 글과 계획 내용. ②의 판정 질문(plan_steps·grounded)과 첫 실패 단계 분류가 읽음
ALTER TABLE sa_spans ADD COLUMN output text;
COMMENT ON COLUMN sa_spans.output IS 'llm: 모델이 낸 글(중간 발화·최종 답) / plan: 계획 내용. trace 스키마 spans[].output';

-- (36) 실제로 실행한 엔진 버전. 실험 초안 때가 아니라 워커가 풀이를 시작할 때 찍음
ALTER TABLE sa_trials ADD COLUMN harness_version text;
COMMENT ON COLUMN sa_trials.harness_version IS '이 풀이를 실행한 워커의 엔진 버전 (common.snapshot.HARNESS_VERSION 또는 커밋). config_snapshot 에는 없음';

-- ---------------------------------------------------------------------
-- 값 목록·일치 검사
-- ---------------------------------------------------------------------
-- (18) sa_jobs.kind 와 payload.kind 가 같아야 함
ALTER TABLE sa_jobs ADD CONSTRAINT sa_jobs_kind_matches_payload CHECK (kind = payload->>'kind');

-- (13) 지표 이름 한 목록 (contracts common.schema.json $defs/metric 과 같음)
--      (3차 8) 회귀율은 지표 목록에서 빼고 sa_comparisons.regression_rate 칸 하나에만 둠
ALTER TABLE sa_comparisons ADD CONSTRAINT sa_comparisons_metric_known CHECK (metric IN
  ('success_rate', 'cost_per_success_krw', 'latency_p50_sec', 'tool_calls_mean', 'completion_rate'));
COMMENT ON COLUMN sa_comparisons.metric IS '지표 이름. 목록은 contracts common.schema.json $defs/metric 과 같음 (CHECK comparisons_metric_known). 회귀율은 지표가 아니라 regression_rate 칸';
COMMENT ON COLUMN sa_comparisons.regression_rate IS '회귀율 (기준은 맞혔는데 후보가 틀린 비율). 지표 목록(metric)에는 없고 이 칸에만 (3차 8). 한도는 prereg.regression_limit';

-- (3차 3) LLM 판정기 질문 종류 한 목록 (contracts common.schema.json $defs/question_kind 와 같음)
ALTER TABLE sa_llm_votes ADD CONSTRAINT sa_llm_votes_question_kind_known CHECK (question_kind IN
  ('plan_steps', 'grounded', 'appropriate', 'result_class'));

-- (24) 실행 실패 원인 값 목록 (contracts common.schema.json $defs/outcome_reason 과 같음)
--      ※ db/tests_constraints.sql(erd_v1.2 사본)은 자유 문구를 넣으므로 0001·0002 에만 돌림
ALTER TABLE sa_trials ADD CONSTRAINT sa_trials_outcome_reason_known CHECK (outcome_reason IS NULL OR outcome_reason IN
  ('env_mcp_server_down', 'env_practice_repo_unreachable', 'env_practice_db_unreachable', 'env_llm_api_5xx',
   'env_worker_lost', 'env_write_proxy_error', 'llm_api_429',
   'agent_max_steps', 'agent_invalid_tool_call', 'agent_llm_refused', 'agent_crash', 'timeout_wall_clock'));
COMMENT ON COLUMN sa_trials.outcome_reason IS 'completed 가 아니면 필수. 값 목록 = contracts $defs/outcome_reason. 환경 탓인지는 prereg.outcome_rules.env_error_reasons 로 정함';

-- (2차 5) 멈춘 이유 값 목록 (contracts common.schema.json $defs/stop_reason 과 같음)
ALTER TABLE sa_experiments ADD CONSTRAINT sa_experiments_stop_reason_known CHECK (stop_reason IS NULL OR stop_reason IN
  ('budget', 'interim', 'user', 'job_failed'));
COMMENT ON COLUMN sa_experiments.stop_reason IS 'budget 예산 도달 / interim 중간 분석 멈춤 판정 / user 사용자 멈춤 / job_failed 작업이 끝내 실패(failed). 바꾸는 곳은 engine/advance.py 만';

-- (데이터 약속 v2-1) 원본 실험 참조. 잠긴 실험의 기준을 바꾸고 싶으면 이 칸으로 원본을 가리키는 새 실험을 만든다 (원본은 그대로 남음)
ALTER TABLE sa_experiments ADD COLUMN derived_from bigint REFERENCES sa_experiments(experiment_id);
ALTER TABLE sa_experiments ADD CONSTRAINT sa_experiments_derived_is_exploratory
  CHECK (derived_from IS NULL OR exploratory);
COMMENT ON COLUMN sa_experiments.derived_from IS '원본 실험. 잠긴 실험의 기준을 바꾼 새 실험이면 채움. 이런 실험은 처음부터 탐색적(exploratory)';

-- (1) 채점 실행 중복 방지: 실험·범위마다 initial 채점은 1개. 워커 여러 개가 동시에 마지막 풀이를 끝내도 한 번만 들어감
--     넣는 쪽(engine/advance.py)은 INSERT ... ON CONFLICT DO NOTHING 으로 넣고, 넣었을 때만 grade 작업을 넣음
CREATE UNIQUE INDEX sa_grading_runs_one_initial ON sa_grading_runs(experiment_id, coalesce(upto_batch_no, 0)) WHERE purpose = 'initial';

-- (3차 4) 분석·리포트도 같은 것을 두 번 만들지 않음. 넣는 쪽은 ON CONFLICT DO NOTHING
--     분석: 채점 실행 하나 + 중간 분석 여부 + 묶음마다 1개. 같은 채점으로 다시 분석하고 싶으면 재채점(regrade)을 거침
--     리포트: 분석 하나 + 종류(one_pager / detail)마다 1개
CREATE UNIQUE INDEX sa_analyses_one_per_scope ON sa_analyses(grading_run_id, is_interim, coalesce(batch_no, 0));
CREATE UNIQUE INDEX sa_reports_one_per_kind ON sa_reports(analysis_id, kind);

-- ---------------------------------------------------------------------
-- (19) 가짜 쓰기 기록도 sa_spans 처럼 "실행 중인 풀이의 지금 시도"에만, 그리고 같은 풀이의 단계에만
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_write_intents_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE t record; s record;
BEGIN
  SELECT status, attempt INTO t FROM sa_trials WHERE trial_id = NEW.trial_id;
  SELECT trial_id, attempt INTO s FROM sa_spans WHERE span_id = NEW.span_id;
  IF s.trial_id <> NEW.trial_id THEN
    RAISE EXCEPTION '다른 풀이의 실행 단계를 가리킵니다' USING ERRCODE = 'P0001', HINT = 'invalid_trace';
  END IF;
  IF t.status <> 'running' THEN
    RAISE EXCEPTION '실행 중인 풀이에만 가짜 쓰기 기록을 붙일 수 있습니다' USING ERRCODE = 'P0001', HINT = 'invalid_trace';
  END IF;
  IF s.attempt <> t.attempt THEN
    RAISE EXCEPTION '지난 시도(%)의 단계입니다. 지금 시도는 %', s.attempt, t.attempt USING ERRCODE = 'P0001', HINT = 'invalid_trace';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER write_intents_current_attempt BEFORE INSERT ON sa_write_intents
  FOR EACH ROW EXECUTE FUNCTION trg_write_intents_insert();

-- ---------------------------------------------------------------------
-- (20) 오류 종류를 문구가 아니라 HINT 로. api/eng_errors.py 는 HINT → 제약 이름 순으로 고름
--      HINT 값 = contracts api.schema.json $defs/error code
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% 은(는) %: 수정·삭제할 수 없습니다 (새 행을 만드세요)',
    TG_TABLE_NAME, TG_ARGV[0] USING ERRCODE = 'P0001', HINT = 'immutable';
END $$;

CREATE OR REPLACE FUNCTION trg_experiment_candidates() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r record; e record; c_slot bigint;
BEGIN
  r := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  SELECT * INTO e FROM sa_experiments WHERE experiment_id = r.experiment_id;
  IF e.locked_at IS NOT NULL THEN
    RAISE EXCEPTION '잠긴 실험의 후보는 바꿀 수 없습니다' USING ERRCODE = 'P0001', HINT = 'experiment_locked';
  END IF;
  IF TG_OP <> 'DELETE' AND e.slot_id IS NOT NULL THEN
    SELECT slot_id INTO c_slot FROM sa_candidates WHERE candidate_id = NEW.candidate_id;
    IF c_slot <> e.slot_id THEN
      RAISE EXCEPTION '실험의 자리와 다른 자리의 후보입니다 (한 번에 한 자리만)' USING ERRCODE = 'P0001', HINT = 'wrong_slot';
    END IF;
  END IF;
  RETURN r;
END $$;

-- 0001 과 같은 검사, HINT 만 붙임: 잠긴 실험을 바꾸려 함 = experiment_locked / 잠글 조건이 안 됨 = not_lockable
CREATE OR REPLACE FUNCTION trg_experiments() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE n_base int; n_other int;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.locked_at IS NOT NULL THEN RAISE EXCEPTION '잠긴 실험은 지울 수 없습니다' USING ERRCODE = 'P0001', HINT = 'experiment_locked'; END IF;
    RETURN OLD;
  END IF;
  IF OLD.locked_at IS NOT NULL THEN
    IF NEW.kind <> OLD.kind OR NEW.agent_version_id <> OLD.agent_version_id OR NEW.slot_id IS DISTINCT FROM OLD.slot_id
       OR NEW.pack_version_id <> OLD.pack_version_id OR NEW.reps <> OLD.reps OR NEW.plan <> OLD.plan
       OR NEW.locked_at IS DISTINCT FROM OLD.locked_at OR NEW.budget_krw IS DISTINCT FROM OLD.budget_krw THEN
      RAISE EXCEPTION '잠긴 실험의 설계는 바꿀 수 없습니다' USING ERRCODE = 'P0001', HINT = 'experiment_locked';
    END IF;
    -- (데이터 약속 v2-1) 잠긴 실험의 사전 등록은 바꾸지 않는다. 기준을 바꾸려면 원본을 가리키는 새 실험(derived_from, 탐색적)
    IF NEW.prereg <> OLD.prereg OR NEW.derived_from IS DISTINCT FROM OLD.derived_from THEN
      RAISE EXCEPTION '잠긴 실험의 사전 등록은 바꿀 수 없습니다. 원본을 가리키는 새 실험(derived_from)을 만드세요' USING ERRCODE = 'P0001', HINT = 'experiment_locked';
    END IF;
    IF OLD.exploratory AND NOT NEW.exploratory THEN
      RAISE EXCEPTION '탐색적 결과 표시는 되돌릴 수 없습니다' USING ERRCODE = 'P0001', HINT = 'immutable';
    END IF;
  ELSIF NEW.locked_at IS NOT NULL THEN
    IF coalesce(current_setting('slotagent.locking', true), '') <> 'on' THEN
      RAISE EXCEPTION '실험 잠금은 lock_experiment() 로만 합니다 (잠금과 풀이 행 생성을 한 번에)' USING ERRCODE = 'P0001', HINT = 'not_lockable';
    END IF;
    IF NOT (NEW.prereg ? 'outcome_rules') OR jsonb_typeof(NEW.prereg->'max_env_retries') IS DISTINCT FROM 'number'
       OR (NEW.prereg->>'max_env_retries')::numeric < 0 THEN
      RAISE EXCEPTION '사전 등록에 outcome_rules 와 max_env_retries(0 이상)가 있어야 잠글 수 있습니다' USING ERRCODE = 'P0001', HINT = 'not_lockable';
    END IF;
    IF jsonb_typeof(NEW.plan->'tasks') IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.plan->'tasks') = 0 THEN
      RAISE EXCEPTION 'plan.tasks(풀 문항 목록)가 있어야 잠글 수 있습니다' USING ERRCODE = 'P0001', HINT = 'not_lockable';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM sa_pack_versions WHERE pack_version_id = NEW.pack_version_id AND locked_at IS NOT NULL) THEN
      RAISE EXCEPTION '잠기지 않은 평가팩으로는 실험을 잠글 수 없습니다' USING ERRCODE = 'P0001', HINT = 'not_lockable';
    END IF;
    SELECT count(*) FILTER (WHERE role = 'baseline'), count(*) FILTER (WHERE role <> 'baseline')
      INTO n_base, n_other FROM sa_experiment_candidates WHERE experiment_id = NEW.experiment_id;
    IF n_base <> 1 OR (NEW.kind = 'compare' AND n_other < 1) THEN
      RAISE EXCEPTION '기준 1개와 비교할 후보가 있어야 잠글 수 있습니다' USING ERRCODE = 'P0001', HINT = 'not_lockable';
    END IF;
    IF NEW.kind = 'compare' AND (SELECT count(*) FROM sa_experiment_candidates WHERE experiment_id = NEW.experiment_id) > 3
       AND NOT EXISTS (SELECT 1 FROM sa_experiment_candidates WHERE experiment_id = NEW.experiment_id AND role = 'variant') THEN
      RAISE EXCEPTION '한 비교의 후보는 3개까지입니다 (FR-EXP-05)' USING ERRCODE = 'P0001', HINT = 'limit_exceeded';
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- (32) 실험 후보의 역할은 sa_candidates.is_baseline 과 같아야 함 (기준 후보 = baseline). variant 는 확장
CREATE OR REPLACE FUNCTION trg_experiment_candidates_role() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record;
BEGIN
  SELECT is_baseline, label INTO c FROM sa_candidates WHERE candidate_id = NEW.candidate_id;
  IF (NEW.role = 'baseline') <> c.is_baseline THEN
    RAISE EXCEPTION '실험의 기준은 자리의 기준 후보(is_baseline)여야 하고, 기준 후보는 baseline 으로만 넣습니다'
      USING ERRCODE = 'P0001', HINT = 'invalid_spec';
  END IF;
  IF NEW.role <> 'variant' AND NEW.label <> c.label THEN
    RAISE EXCEPTION '실험 후보 label(%)이 후보 label(%)과 다릅니다', NEW.label, c.label USING ERRCODE = 'P0001', HINT = 'invalid_spec';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER experiment_candidates_role BEFORE INSERT ON sa_experiment_candidates
  FOR EACH ROW EXECUTE FUNCTION trg_experiment_candidates_role();

-- ---------------------------------------------------------------------
-- 주석 바로잡기
-- ---------------------------------------------------------------------
-- (17) 근거는 sa_spans.span_id 가 아니라 seq (골든 궤적에도 같은 채점 코드를 쓰려고)
COMMENT ON COLUMN sa_condition_results.evidence IS '근거 = grading.condition_evidence 스키마: span_seqs(같은 풀이·지금 시도의 sa_spans.seq), 찾은 값, 메모';
-- (2) 판정기 설정을 어디서 읽는지
COMMENT ON COLUMN sa_grading_runs.judge_settings IS '②가 정한 판정기 설정. ①이 채점 실행을 만들 때 settings(scope=domain, key=judge.settings) 최신 행을 그대로 복사. LLM 을 안 쓰면 {}';

-- =====================================================================
-- 11/23 계약 변경 (합치기 전이라 새 번호 파일 대신 여기에 더함, backend/db/README). contracts/CHANGELOG.md 2026-11-23 줄과 같은 내용
-- =====================================================================
-- (1) 질문은 연결 방식이 아님 — spec_upload·runner·api 어디서든 정보를 채우는 보조 단계
ALTER TABLE sa_agent_versions DROP CONSTRAINT sa_agent_versions_connection_type_check;
ALTER TABLE sa_agent_versions ADD CONSTRAINT sa_agent_versions_connection_type_check
  CHECK (connection_type IN ('spec_upload', 'runner', 'api'));
ALTER TABLE sa_agent_versions ADD COLUMN questions_used boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN sa_agent_versions.connection_type IS '연결 방식: spec_upload 설정 파일 / runner 러너 / api API. 질문은 연결 방식이 아님 (questions_used)';
COMMENT ON COLUMN sa_agent_versions.questions_used IS '등록 질문(도메인·지시문·도구 확인·모델)으로 정보를 채웠는지. 연결 방식과 따로 셈. spec 에 넣지 않음 (같은 구성이면 spec_hash 가 같아야 함)';

-- (2) 등록 질문 1번의 도메인. 버전마다 바뀌지 않으므로 sa_agents 에 둠. 실험 만들 때 이 도메인의 평가팩을 먼저 보여 줌
ALTER TABLE sa_agents ADD COLUMN domain_code text REFERENCES sa_domains(domain_code);
COMMENT ON COLUMN sa_agents.domain_code IS '에이전트의 도메인 (등록 질문, sa_domains 드롭다운). 비면 평가팩을 전부 보여 줌';

-- (3) 고도화 D: 도구 검색(Tool Search) 후보. 도구 설명을 처음에 다 넣지 않고 필요할 때 찾아 불러옴
ALTER TABLE sa_candidates DROP CONSTRAINT sa_candidates_component_kind_check;
ALTER TABLE sa_candidates ADD CONSTRAINT sa_candidates_component_kind_check
  CHECK (component_kind IN ('tool_bundle', 'custom_tool', 'tool_search', 'prompt', 'model', 'skill', 'workflow'));
COMMENT ON COLUMN sa_candidates.component_kind IS '[확장] 바꾸는 구성 요소 종류: tool_bundle 도구 묶음 / custom_tool 직접 만든 도구 / tool_search 도구 검색 / prompt 지시문 / model / skill / workflow. 8주 안에는 앞의 셋만';

-- =====================================================================
-- 11/23 기획서 1.3 반영 (contracts/CHANGELOG.md 2026-11-23 두 번째 줄)
-- =====================================================================
-- (4) 모델 회사 4종. 같은 회사 안에서 버전만 바꿈
ALTER TABLE sa_agent_versions ADD COLUMN model_provider text NOT NULL
  CONSTRAINT sa_agent_versions_model_provider_known CHECK (model_provider IN ('anthropic', 'openai', 'google', 'deepseek'));
COMMENT ON COLUMN sa_agent_versions.model_provider IS '모델 회사: anthropic / openai / google / deepseek (기획서 1.3 8.1). 호출은 common/llm.py 어댑터 하나로';

-- (5) 문항 유형이 필요로 하는 기능. 후보 도구의 capabilities 와 맞춰 실행 전에 도구 범위 밖을 정함 (P-01 = fail)
ALTER TABLE sa_templates ADD COLUMN required_capabilities jsonb NOT NULL DEFAULT '[]'
  CONSTRAINT sa_templates_required_capabilities_array CHECK (jsonb_typeof(required_capabilities) = 'array');
COMMENT ON COLUMN sa_templates.required_capabilities IS '필요 기능 이름표 목록 (pack 스키마 required_capabilities). 범위 밖 판정은 common.checks.template_scope. 비면 판정 안 함';
