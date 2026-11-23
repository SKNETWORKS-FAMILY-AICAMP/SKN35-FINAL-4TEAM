-- =====================================================================
-- SlotAgent 1.2 제품 DB (PostgreSQL 16)
-- 기준: SlotAgent 1.2 기획서, 요구사항 정의서 v1.2 (82개), 설계로 넘긴 결정 D-01~D-14
-- 1.1 ERD(73개)를 8주 범위에 맞춰 33개로 줄이고, 8주 뒤 기능은 "확장 지점"으로 자리만 둠
--
-- 표시 (테이블 주석에도 같은 표시)
--   [불변]   저장 후 UPDATE/DELETE 금지. 바꾸려면 새 행(새 버전)
--   [잠금]   부모의 locked_at 이 찍힌 뒤 수정 금지
--   [추가만] INSERT 만 허용 (기록·이력)
--   [큐]     상태 컬럼만 바뀜
--   [확장]   8주 뒤 기능이 들어올 자리 (지금은 값 하나만 씀)
-- 용어: sa_templates = 문항 유형, sa_tasks = 문항, sa_trials = 풀이
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. 공통 트리거 함수
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% 은(는) %: 수정·삭제할 수 없습니다 (새 행을 만드세요)',
    TG_TABLE_NAME, TG_ARGV[0] USING ERRCODE = 'P0001';
END $$;

-- 평가팩 버전이 잠겼으면 자식 행 INSERT/UPDATE/DELETE 금지
-- TG_ARGV[0]: 'direct'(pack_version_id 컬럼) / 'template'(template_id) / 'task'(task_id)
CREATE OR REPLACE FUNCTION trg_pack_child_locked() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r record; pv bigint; locked timestamptz;
BEGIN
  r := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  IF TG_ARGV[0] = 'direct' THEN pv := r.pack_version_id;
  ELSIF TG_ARGV[0] = 'template' THEN SELECT pack_version_id INTO pv FROM sa_templates WHERE template_id = r.template_id;
  ELSIF TG_ARGV[0] = 'task' THEN
    SELECT t.pack_version_id INTO pv FROM sa_tasks k JOIN sa_templates t ON t.template_id = k.template_id WHERE k.task_id = r.task_id;
  END IF;
  SELECT locked_at INTO locked FROM sa_pack_versions WHERE pack_version_id = pv;
  IF locked IS NOT NULL THEN
    RAISE EXCEPTION '평가팩 버전 % 은(는) 잠겼습니다: % 를 바꿀 수 없습니다 (다음 버전에서 고치세요)', pv, TG_TABLE_NAME
      USING ERRCODE = 'P0001';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

-- ---------------------------------------------------------------------
-- 1. 공통: 사용자, 도메인, 설정
-- ---------------------------------------------------------------------
CREATE TABLE sa_users (
  user_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email       text NOT NULL UNIQUE,
  name        text NOT NULL,
  org_id      bigint,                                   -- [확장] 팀·요금제(OOS-01)가 생기면 orgs 테이블 FK
  created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE sa_users IS '사용자. [확장] org_id: 팀·요금제 자리';

CREATE TABLE sa_domains (
  domain_code        text PRIMARY KEY,                         -- it_ops, data_analysis, customer_support
  name        text NOT NULL,
  status      text NOT NULL CHECK (status IN ('active', 'pilot', 'planned')),
  validated_at timestamptz,                             -- E1~E6 모두 통과한 때 (NFR-VER-07). NULL 이면 "검증 전"
  created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE sa_domains IS '도메인. [확장] 새 도메인은 행 추가 + 연습 DB 스키마만 (NFR-EXT-01)';

-- 기준 숫자·가격표·비용 한도. 값을 바꾸면 새 행(valid_from)으로 쌓음
CREATE TABLE sa_settings (
  setting_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope       text NOT NULL CHECK (scope IN ('global', 'domain', 'experiment')),
  scope_ref   text NOT NULL DEFAULT '',                 -- domain code 또는 experiment id. global 이면 ''
  key         text NOT NULL,                            -- ni_margin_pp, regression_limit, label_success_min, price.gpt-x, cost_limit_month ...
  value       jsonb NOT NULL,
  valid_from  timestamptz NOT NULL DEFAULT now(),
  note        text,
  UNIQUE (scope, scope_ref, key, valid_from),
  CHECK ((scope = 'global') = (scope_ref = ''))
);
COMMENT ON TABLE sa_settings IS '[추가만] 기준 숫자(마진 5%p, 회귀율 5% 등)·가격표·비용 한도. 수치 조정은 새 행';
CREATE TRIGGER settings_append_only BEFORE UPDATE OR DELETE ON sa_settings
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 2. 연결: 에이전트, 버전, 자리, 후보
-- ---------------------------------------------------------------------
CREATE TABLE sa_agents (
  agent_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_id    bigint NOT NULL REFERENCES sa_users(user_id),
  name        text NOT NULL,
  purpose     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sa_agent_versions (
  agent_version_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_id        bigint NOT NULL REFERENCES sa_agents(agent_id),
  version_no      int NOT NULL,
  connection_type text NOT NULL CHECK (connection_type IN ('spec_upload', 'questions', 'runner', 'api')),
  control_level   text NOT NULL CHECK (control_level IN ('C0', 'C1', 'C2')),   -- 평가 가능성 프로파일 (5.9)
  model           text NOT NULL,
  temperature     numeric NOT NULL DEFAULT 0,
  instructions    text NOT NULL,
  spec            jsonb NOT NULL,                       -- 구성 명세 (도구 목록, 서비스, 쓰기 도구 표시)
  spec_schema_version int NOT NULL DEFAULT 1,           -- [확장] 구성 명세 형식이 바뀌면 숫자만 올림
  spec_hash       text NOT NULL,
  connection      jsonb NOT NULL DEFAULT '{}',          -- 러너 ID·API 주소·드라이런 여부 (비밀 값은 저장 안 함)
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (agent_id, version_no),
  CHECK (connection_type <> 'api' OR control_level IN ('C0', 'C1')),
  CHECK (NOT (connection ? 'api_key') AND NOT (connection ? 'password'))       -- NFR-SEC-01
);
COMMENT ON TABLE sa_agent_versions IS '[불변] 구성 명세. 바꾸면 새 version_no';
CREATE TRIGGER agent_versions_immutable BEFORE UPDATE OR DELETE ON sa_agent_versions
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('불변');

CREATE TABLE sa_slots (
  slot_id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_version_id  bigint NOT NULL REFERENCES sa_agent_versions(agent_version_id),
  name              text NOT NULL,                      -- GitHub 조회
  service           text NOT NULL,
  access            text NOT NULL CHECK (access IN ('read', 'write')),
  comparable        boolean NOT NULL,
  not_comparable_reason text,                           -- 쓰기 자리, 코드 없는 자체 도구 (FR-CON-03, FR-RUN-10)
  UNIQUE (agent_version_id, name),
  CHECK (comparable OR not_comparable_reason IS NOT NULL)
);

CREATE TABLE sa_candidates (
  candidate_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slot_id         bigint NOT NULL REFERENCES sa_slots(slot_id),
  label           text NOT NULL,                        -- A, B, C
  name            text NOT NULL,
  component_kind  text NOT NULL DEFAULT 'tool_bundle'
                  CHECK (component_kind IN ('tool_bundle', 'custom_tool', 'prompt', 'model', 'skill', 'workflow')),
  component_spec  jsonb NOT NULL,
  spec_schema_version int NOT NULL DEFAULT 1,
  spec_hash       text NOT NULL,
  is_baseline     boolean NOT NULL DEFAULT false,       -- 지금 구성
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT sa_candidates_label_per_slot UNIQUE (slot_id, label)
);
COMMENT ON TABLE sa_candidates IS '[불변] 후보. [확장] component_kind: 도구 묶음 말고 지시문·모델·Skill·Workflow 교체도 같은 테이블';
CREATE UNIQUE INDEX sa_candidates_one_baseline ON sa_candidates(slot_id) WHERE is_baseline;
CREATE TRIGGER candidates_immutable BEFORE UPDATE OR DELETE ON sa_candidates
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('불변');

-- ---------------------------------------------------------------------
-- 3. 평가팩: 버전, 연습 데이터, 문항 유형, 문항, 정답 조건, 골든 궤적, 점검, 열람
-- ---------------------------------------------------------------------
CREATE TABLE sa_pack_versions (
  pack_version_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  domain_code text NOT NULL REFERENCES sa_domains(domain_code),
  pack_code   text NOT NULL,                            -- it_ops
  version     text NOT NULL,                            -- v1.0
  status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'locked', 'retired')),
  premises    jsonb NOT NULL DEFAULT '{}',              -- 요약서 전제 조건 (데이터 설계 등)
  locked_at   timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pack_code, version),
  CHECK ((status = 'draft') = (locked_at IS NULL))
);
COMMENT ON TABLE sa_pack_versions IS '[잠금] 평가팩 버전. 잠근 뒤에는 status 를 retired 로만 바꿀 수 있음';

CREATE OR REPLACE FUNCTION trg_pack_versions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.locked_at IS NOT NULL THEN RAISE EXCEPTION '잠긴 평가팩 버전은 지울 수 없습니다' USING ERRCODE = 'P0001'; END IF;
    RETURN OLD;
  END IF;
  IF OLD.locked_at IS NOT NULL THEN
    IF NEW.locked_at IS DISTINCT FROM OLD.locked_at OR NEW.premises <> OLD.premises OR NEW.version <> OLD.version
       OR NEW.pack_code <> OLD.pack_code OR NEW.domain_code <> OLD.domain_code OR NEW.status = 'draft' THEN
      RAISE EXCEPTION '잠긴 평가팩 버전은 retired 로 바꾸는 것만 됩니다' USING ERRCODE = 'P0001';
    END IF;
  ELSIF NEW.locked_at IS NOT NULL THEN
    -- 잠그는 순간: 연습 데이터가 하나 이상 있고 모두 동결(content_hash)돼 있어야 함 (FR-PACK-08)
    IF NOT EXISTS (SELECT 1 FROM sa_data_snapshots WHERE pack_version_id = NEW.pack_version_id) THEN
      RAISE EXCEPTION '연습 데이터 없이 평가팩을 잠글 수 없습니다' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM sa_data_snapshots WHERE pack_version_id = NEW.pack_version_id AND content_hash IS NULL) THEN
      RAISE EXCEPTION '동결되지 않은 연습 데이터가 있습니다' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- 연습 데이터 버전. 읽기 도구 실행 방식(D-05)이 무엇이든 같은 모양
CREATE TABLE sa_data_snapshots (
  data_snapshot_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pack_version_id bigint NOT NULL REFERENCES sa_pack_versions(pack_version_id),
  source_kind     text NOT NULL CHECK (source_kind IN ('db_schema', 'repo', 'practice_tool', 'fixed_response')),
  location        text NOT NULL,                        -- 연습 DB 스키마 이름, 저장소 주소, 연습 도구 이름
  design          jsonb NOT NULL DEFAULT '{}',          -- 로그인 형식, 봇 이름, 열린·닫힌 비율 (FR-ENV-02)
  content_hash    text,                                 -- 동결할 때 계산 (내용 비교 방법은 D-07)
  frozen_at       timestamptz,
  UNIQUE (pack_version_id, source_kind, location),
  CHECK ((frozen_at IS NULL) = (content_hash IS NULL))
);
COMMENT ON TABLE sa_data_snapshots IS '[잠금] 연습 데이터 버전. [확장] source_kind: D-05 결정에 따라 db_schema/repo/practice_tool 중 쓰는 것만';
CREATE TRIGGER pack_versions_rules BEFORE UPDATE OR DELETE ON sa_pack_versions
  FOR EACH ROW EXECUTE FUNCTION trg_pack_versions();
CREATE TRIGGER data_snapshots_locked BEFORE INSERT OR UPDATE OR DELETE ON sa_data_snapshots
  FOR EACH ROW EXECUTE FUNCTION trg_pack_child_locked('direct');

CREATE TABLE sa_templates (
  template_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pack_version_id bigint NOT NULL REFERENCES sa_pack_versions(pack_version_id),
  code            text NOT NULL,                        -- T1
  question_pattern text NOT NULL,                       -- "{사람}에게 배정된 열린 이슈"
  value_rule      jsonb NOT NULL DEFAULT '{}',
  is_representative boolean NOT NULL DEFAULT false,     -- 골든 궤적 4종을 두는 대표 유형 (15~20개)
  UNIQUE (pack_version_id, code)
);
COMMENT ON TABLE sa_templates IS '[잠금] 문항 유형. 통계의 묶음 단위';
CREATE TRIGGER templates_locked BEFORE INSERT OR UPDATE OR DELETE ON sa_templates
  FOR EACH ROW EXECUTE FUNCTION trg_pack_child_locked('direct');

CREATE TABLE sa_tasks (
  task_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  template_id bigint NOT NULL REFERENCES sa_templates(template_id),
  code        text NOT NULL,                            -- T1-0
  prompt      text NOT NULL,
  slot_values jsonb NOT NULL DEFAULT '{}',
  seed        int NOT NULL,
  UNIQUE (template_id, code)
);
COMMENT ON TABLE sa_tasks IS '[잠금] 문항';
CREATE TRIGGER tasks_locked BEFORE INSERT OR UPDATE OR DELETE ON sa_tasks
  FOR EACH ROW EXECUTE FUNCTION trg_pack_child_locked('template');

CREATE TABLE sa_answer_conditions (
  answer_condition_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id     bigint NOT NULL REFERENCES sa_tasks(task_id),
  seq         int NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('info', 'link', 'order', 'forbidden', 'end_state')),
  spec        jsonb NOT NULL,                           -- 값·비교 방법 / 관계 / 순서 / 금지 / 종료 상태 (표현 방식은 D-06)
  spec_schema_version int NOT NULL DEFAULT 1,
  UNIQUE (task_id, seq)
);
COMMENT ON TABLE sa_answer_conditions IS '[잠금] 정답 조건 4종 + 연결 근거 (FR-PACK-03)';
CREATE TRIGGER answer_conditions_locked BEFORE INSERT OR UPDATE OR DELETE ON sa_answer_conditions
  FOR EACH ROW EXECUTE FUNCTION trg_pack_child_locked('task');

CREATE TABLE sa_golden_trajectories (
  golden_trajectory_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  template_id bigint NOT NULL REFERENCES sa_templates(template_id),
  kind        text NOT NULL CHECK (kind IN ('success', 'alt_success', 'near_miss', 'forbidden')),
  trace       jsonb NOT NULL,                           -- 실행 기록 형식과 같은 모양
  expected    jsonb NOT NULL,                           -- 기대 판정
  UNIQUE (template_id, kind)
);
COMMENT ON TABLE sa_golden_trajectories IS '[잠금] 골든 궤적 (FR-PACK-05)';
CREATE TRIGGER golden_trajectories_locked BEFORE INSERT OR UPDATE OR DELETE ON sa_golden_trajectories
  FOR EACH ROW EXECUTE FUNCTION trg_pack_child_locked('template');

-- 평가팩 점검 기록: 연습 환경 검증 3가지, 대체 도구, 서버 버전 변경, 골든 궤적 테스트
CREATE TABLE sa_env_checks (
  env_check_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pack_version_id bigint NOT NULL REFERENCES sa_pack_versions(pack_version_id),
  kind            text NOT NULL CHECK (kind IN ('tool_shape', 'data_design', 'prompt_leak',
                                                 'substitute_tool', 'version_change', 'golden_test')),
  target          text NOT NULL,                        -- 점검 대상 (도구 이름, 문항 유형, 채점기 버전)
  result          text NOT NULL CHECK (result IN ('pass', 'fail', 'note')),
  detail          jsonb NOT NULL DEFAULT '{}',
  checked_by      bigint REFERENCES sa_users(user_id),
  checked_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE sa_env_checks IS '[추가만] 연습 환경 검증 (FR-ENV-01~03), 골든 궤적 테스트 결과. 잠근 뒤에도 기록 추가 가능';
CREATE TRIGGER env_checks_append_only BEFORE UPDATE OR DELETE ON sa_env_checks
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- 새 문항 관리: 고칠 때 실패 내용을 들여다본 문항 (FR-PACK-04)
CREATE TABLE sa_task_exposures (
  task_exposure_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id     bigint NOT NULL REFERENCES sa_tasks(task_id),
  seen_by     bigint NOT NULL REFERENCES sa_users(user_id),
  reason      text NOT NULL,                            -- 실패 기록 열람, 수정 작업
  seen_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE sa_task_exposures IS '[추가만] 열람한 문항은 효과 판정의 "새 문항"에서 빠짐';
CREATE TRIGGER task_exposures_append_only BEFORE UPDATE OR DELETE ON sa_task_exposures
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 4. 실험: 실험(사전 등록 포함), 실험 후보
-- ---------------------------------------------------------------------
CREATE TABLE sa_experiments (
  experiment_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind            text NOT NULL DEFAULT 'compare'
                  CHECK (kind IN ('compare', 'diagnose', 'validation', 'fix_effect')),  -- [확장] fix_effect = OOS-07
  agent_version_id bigint NOT NULL REFERENCES sa_agent_versions(agent_version_id),
  slot_id         bigint REFERENCES sa_slots(slot_id),
  pack_version_id bigint NOT NULL REFERENCES sa_pack_versions(pack_version_id),
  reps            int NOT NULL CHECK (reps BETWEEN 1 AND 10),
  prereg          jsonb NOT NULL DEFAULT '{}',          -- 1차 지표, 마진, 유의수준, 2차 지표, 예산, 예상 방향, outcome_rules(오류 처리 규칙), max_env_retries
  prereg_schema_version int NOT NULL DEFAULT 1,
  plan            jsonb NOT NULL DEFAULT '{}',          -- 필요 문항 유형·문항 수, 최소 차이, 예상 비용 (FR-EXP-03), sa_tasks=[{task_id, batch_no}] 풀 문항과 묶음
  budget_krw      numeric CONSTRAINT sa_experiments_budget_positive CHECK (budget_krw > 0),
  status          text NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft', 'locked', 'running', 'stopped', 'done', 'failed')),
  stop_reason     text,                                 -- 예산 도달, 일찍 멈춤 (FR-RUN-08)
  exploratory     boolean NOT NULL DEFAULT false,       -- 잠근 뒤 기준을 바꾸면 true ("탐색적 결과")
  locked_at       timestamptz,
  created_by      bigint NOT NULL REFERENCES sa_users(user_id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (kind <> 'compare' OR slot_id IS NOT NULL),
  CHECK ((status = 'draft') = (locked_at IS NULL)),
  CHECK (status <> 'stopped' OR stop_reason IS NOT NULL)
);
COMMENT ON TABLE sa_experiments IS '[잠금] 실험과 사전 등록. 잠근 뒤 prereg 를 바꾸면 exploratory=true 여야 함 (FR-EXP-02)';

CREATE TABLE sa_experiment_candidates (
  experiment_candidate_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id   bigint NOT NULL REFERENCES sa_experiments(experiment_id),
  candidate_id    bigint NOT NULL REFERENCES sa_candidates(candidate_id),
  label           text NOT NULL,                        -- A, B, C (변형이면 C+no_H 등)
  role            text NOT NULL CHECK (role IN ('baseline', 'candidate', 'variant')),   -- [확장] variant = 하나씩 빼 보기
  variant         jsonb NOT NULL DEFAULT '{}',          -- 켜고 끈 수정 (OOS-07 자리)
  config_snapshot jsonb NOT NULL,                       -- 모델 버전, 프롬프트, 도구 스키마, 서버 버전, 시드, 온도 (NFR-REP-01)
  config_hash     text NOT NULL,
  CONSTRAINT sa_experiment_candidates_label_per_experiment UNIQUE (experiment_id, label)
);
COMMENT ON TABLE sa_experiment_candidates IS '[잠금] 실험에 넣은 후보와 버전 묶음';
CREATE UNIQUE INDEX sa_experiment_one_baseline ON sa_experiment_candidates(experiment_id) WHERE role = 'baseline';

CREATE OR REPLACE FUNCTION trg_experiments() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE n_base int; n_other int;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.locked_at IS NOT NULL THEN RAISE EXCEPTION '잠긴 실험은 지울 수 없습니다' USING ERRCODE = 'P0001'; END IF;
    RETURN OLD;
  END IF;
  IF OLD.locked_at IS NOT NULL THEN
    IF NEW.kind <> OLD.kind OR NEW.agent_version_id <> OLD.agent_version_id OR NEW.slot_id IS DISTINCT FROM OLD.slot_id
       OR NEW.pack_version_id <> OLD.pack_version_id OR NEW.reps <> OLD.reps OR NEW.plan <> OLD.plan
       OR NEW.locked_at IS DISTINCT FROM OLD.locked_at OR NEW.budget_krw IS DISTINCT FROM OLD.budget_krw THEN
      RAISE EXCEPTION '잠긴 실험의 설계는 바꿀 수 없습니다' USING ERRCODE = 'P0001';
    END IF;
    IF NEW.prereg <> OLD.prereg AND NOT NEW.exploratory THEN
      RAISE EXCEPTION '잠근 뒤 사전 등록을 바꾸려면 exploratory=true 로 표시해야 합니다' USING ERRCODE = 'P0001';
    END IF;
    IF OLD.exploratory AND NOT NEW.exploratory THEN
      RAISE EXCEPTION '탐색적 결과 표시는 되돌릴 수 없습니다' USING ERRCODE = 'P0001';
    END IF;
  ELSIF NEW.locked_at IS NOT NULL THEN
    -- 잠그는 순간: lock_experiment 로만, 오류 처리 규칙이 사전 등록에 있어야 함
    IF coalesce(current_setting('slotagent.locking', true), '') <> 'on' THEN
      RAISE EXCEPTION '실험 잠금은 lock_experiment() 로만 합니다 (잠금과 풀이 행 생성을 한 번에)' USING ERRCODE = 'P0001';
    END IF;
    IF NOT (NEW.prereg ? 'outcome_rules') OR jsonb_typeof(NEW.prereg->'max_env_retries') IS DISTINCT FROM 'number'
       OR (NEW.prereg->>'max_env_retries')::numeric < 0 THEN
      RAISE EXCEPTION '사전 등록에 outcome_rules 와 max_env_retries(0 이상)가 있어야 잠글 수 있습니다' USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(NEW.plan->'tasks') IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.plan->'tasks') = 0 THEN
      RAISE EXCEPTION 'plan.tasks(풀 문항 목록)가 있어야 잠글 수 있습니다' USING ERRCODE = 'P0001';
    END IF;
    -- 평가팩이 잠겨 있고, 기준 1개 + 다른 후보가 있어야 함
    IF NOT EXISTS (SELECT 1 FROM sa_pack_versions WHERE pack_version_id = NEW.pack_version_id AND locked_at IS NOT NULL) THEN
      RAISE EXCEPTION '잠기지 않은 평가팩으로는 실험을 잠글 수 없습니다' USING ERRCODE = 'P0001';
    END IF;
    SELECT count(*) FILTER (WHERE role = 'baseline'), count(*) FILTER (WHERE role <> 'baseline')
      INTO n_base, n_other FROM sa_experiment_candidates WHERE experiment_id = NEW.experiment_id;
    IF n_base <> 1 OR (NEW.kind = 'compare' AND n_other < 1) THEN
      RAISE EXCEPTION '기준 1개와 비교할 후보가 있어야 잠글 수 있습니다' USING ERRCODE = 'P0001';
    END IF;
    IF NEW.kind = 'compare' AND (SELECT count(*) FROM sa_experiment_candidates WHERE experiment_id = NEW.experiment_id) > 3
       AND NOT EXISTS (SELECT 1 FROM sa_experiment_candidates WHERE experiment_id = NEW.experiment_id AND role = 'variant') THEN
      RAISE EXCEPTION '한 비교의 후보는 3개까지입니다 (FR-EXP-05)' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER experiments_rules BEFORE UPDATE OR DELETE ON sa_experiments
  FOR EACH ROW EXECUTE FUNCTION trg_experiments();

CREATE OR REPLACE FUNCTION trg_experiment_candidates() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r record; e record; c_slot bigint;
BEGIN
  r := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  SELECT * INTO e FROM sa_experiments WHERE experiment_id = r.experiment_id;
  IF e.locked_at IS NOT NULL THEN
    RAISE EXCEPTION '잠긴 실험의 후보는 바꿀 수 없습니다' USING ERRCODE = 'P0001';
  END IF;
  IF TG_OP <> 'DELETE' AND e.slot_id IS NOT NULL THEN
    SELECT slot_id INTO c_slot FROM sa_candidates WHERE candidate_id = NEW.candidate_id;
    IF c_slot <> e.slot_id THEN
      RAISE EXCEPTION '실험의 자리와 다른 자리의 후보입니다 (한 번에 한 자리만)' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN r;
END $$;
CREATE TRIGGER experiment_candidates_rules BEFORE INSERT OR UPDATE OR DELETE ON sa_experiment_candidates
  FOR EACH ROW EXECUTE FUNCTION trg_experiment_candidates();

-- ---------------------------------------------------------------------
-- 5. 실행: 작업 큐, 풀이, 실행 기록, 가짜 쓰기 기록
-- ---------------------------------------------------------------------
CREATE TABLE sa_jobs (
  job_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind        text NOT NULL,                            -- [확장] run_trial, grade, analyze, report, validation ... 새 작업은 kind 추가
  payload     jsonb NOT NULL,
  status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'leased', 'done', 'failed', 'cancelled')),
  priority    int NOT NULL DEFAULT 0,
  attempts    int NOT NULL DEFAULT 0,
  leased_by   text,
  lease_until timestamptz,
  last_error  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'leased') = (lease_until IS NOT NULL))
);
COMMENT ON TABLE sa_jobs IS '[큐] DB 작업 큐. SELECT ... FOR UPDATE SKIP LOCKED 로 가져감. 임대 10분(settings queue.lease_sec), 1분마다 연장. attempts = 임대 토큰: 연장·완료·실패는 attempts 가 가져갈 때 값과 같을 때만';
CREATE INDEX sa_jobs_ready ON sa_jobs(priority DESC, job_id) WHERE status = 'queued';

CREATE TABLE sa_trials (
  trial_id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id     bigint NOT NULL REFERENCES sa_experiments(experiment_id),
  experiment_candidate_id  bigint NOT NULL REFERENCES sa_experiment_candidates(experiment_candidate_id),
  task_id           bigint NOT NULL REFERENCES sa_tasks(task_id),
  rep               int NOT NULL CHECK (rep >= 0),
  batch_no          int NOT NULL DEFAULT 1,             -- 순차 검정 묶음 (문항 유형 15~20개 단위)
  status            text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'finished', 'error', 'cancelled')),
  run_outcome       text CHECK (run_outcome IN ('completed', 'agent_error', 'timeout', 'env_error')),   -- 실행 결과만. 맞았는지는 sa_trial_grades
  outcome_reason    text,                               -- completed 가 아니면 필수. 무엇이 일으켰는지 (outcome_rules 기준표)
  run_no            int NOT NULL DEFAULT 1 CHECK (run_no >= 1),   -- 환경 오류 뒤 다시 실행하면 새 행으로 +1
  api_retries       int NOT NULL DEFAULT 0,
  attempt           int NOT NULL DEFAULT 1 CHECK (attempt >= 1),   -- 워커가 죽어 처음부터 다시 실행하면 +1. 실행 기록은 이 번호로만 추가
  record_source     text NOT NULL DEFAULT 'platform' CHECK (record_source IN ('platform', 'runner', 'customer')),
  signature         text,                               -- 러너 기록 서명 (NFR-SEC-03)
  started_at        timestamptz,
  finished_at       timestamptz,
  in_tokens         int, out_tokens int, tool_desc_tokens int,
  cost_krw          numeric,
  llm_sec           numeric, tool_sec numeric, wait_sec numeric,
  final_answer      text,
  UNIQUE (experiment_candidate_id, task_id, rep, run_no),
  CHECK ((status IN ('finished', 'error')) = (run_outcome IS NOT NULL)),
  CHECK (run_outcome IS NULL OR run_outcome = 'completed' OR outcome_reason IS NOT NULL),
  CHECK (record_source <> 'runner' OR status <> 'finished' OR signature IS NOT NULL)
);
COMMENT ON TABLE sa_trials IS '[큐→불변] 풀이. 잠글 때 lock_experiment 가 run_no=1 행을 모두 만듦. 끝나면(finished/error/cancelled) 수정 금지';
CREATE INDEX sa_trials_by_experiment ON sa_trials(experiment_id, experiment_candidate_id);

CREATE OR REPLACE FUNCTION trg_trials() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e record; c_exp bigint; t_pack bigint; prev record;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT * INTO e FROM sa_experiments WHERE experiment_id = NEW.experiment_id;
    IF e.locked_at IS NULL THEN RAISE EXCEPTION '잠기지 않은 실험은 실행할 수 없습니다 (사전 등록 먼저)' USING ERRCODE = 'P0001'; END IF;
    SELECT experiment_id INTO c_exp FROM sa_experiment_candidates WHERE experiment_candidate_id = NEW.experiment_candidate_id;
    IF c_exp <> NEW.experiment_id THEN RAISE EXCEPTION '다른 실험의 후보입니다' USING ERRCODE = 'P0001'; END IF;
    SELECT t.pack_version_id INTO t_pack FROM sa_tasks k JOIN sa_templates t ON t.template_id = k.template_id WHERE k.task_id = NEW.task_id;
    IF t_pack <> e.pack_version_id THEN RAISE EXCEPTION '실험의 평가팩에 없는 문항입니다' USING ERRCODE = 'P0001'; END IF;
    IF NEW.status <> 'pending' THEN RAISE EXCEPTION '풀이는 pending 으로 만들어야 합니다' USING ERRCODE = 'P0001'; END IF;
    IF NEW.run_no = 1 THEN
      -- 계획한 풀이는 잠글 때 한 번에 만듦 (계획 밖 풀이 금지)
      IF coalesce(current_setting('slotagent.locking', true), '') <> 'on' THEN
        RAISE EXCEPTION '첫 실행 풀이는 lock_experiment() 가 만듭니다' USING ERRCODE = 'P0001';
      END IF;
      RETURN NEW;
    END IF;
    -- 다시 실행(run_no > 1): 바로 앞 실행이 환경 오류로 끝났고, 횟수 안이고, 아직 채점 범위에 안 들어갔을 때만
    SELECT * INTO prev FROM sa_trials
     WHERE experiment_candidate_id = NEW.experiment_candidate_id AND task_id = NEW.task_id AND rep = NEW.rep AND run_no = NEW.run_no - 1
       FOR SHARE;
    IF NOT FOUND OR prev.status NOT IN ('finished', 'error') OR prev.run_outcome <> 'env_error' THEN
      RAISE EXCEPTION '다시 실행은 바로 앞 실행(run_no %)이 환경 오류로 끝났을 때만 됩니다', NEW.run_no - 1 USING ERRCODE = 'P0001';
    END IF;
    IF NEW.batch_no <> prev.batch_no THEN RAISE EXCEPTION '다시 실행해도 묶음 번호는 같아야 합니다' USING ERRCODE = 'P0001'; END IF;
    IF NEW.run_no > (e.prereg->>'max_env_retries')::int + 1 THEN
      RAISE EXCEPTION '환경 오류 다시 실행은 %번까지입니다 (max_env_retries)', e.prereg->>'max_env_retries' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM sa_grading_runs g WHERE g.experiment_id = NEW.experiment_id AND g.purpose IN ('initial', 'regrade')
                AND (g.upto_batch_no IS NULL OR NEW.batch_no <= g.upto_batch_no)) THEN
      RAISE EXCEPTION '이미 채점 범위에 든 묶음(%)은 다시 실행할 수 없습니다', NEW.batch_no USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION '풀이는 지울 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF OLD.status IN ('finished', 'error', 'cancelled') THEN RAISE EXCEPTION '끝난 풀이는 바꿀 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF NEW.experiment_id <> OLD.experiment_id OR NEW.experiment_candidate_id <> OLD.experiment_candidate_id
     OR NEW.task_id <> OLD.task_id OR NEW.rep <> OLD.rep OR NEW.run_no <> OLD.run_no OR NEW.batch_no <> OLD.batch_no THEN
    RAISE EXCEPTION '풀이의 식별 정보(후보·문항·반복·실행 번호·묶음)는 바꿀 수 없습니다' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.status = 'cancelled' THEN
    -- 일찍 멈춤·예산 도달로 안 돌린 풀이. 대기 중인 것만, 멈춘 실험에서만
    IF OLD.status <> 'pending' THEN RAISE EXCEPTION '실행 취소는 대기 중인 풀이만 됩니다' USING ERRCODE = 'P0001'; END IF;
    IF NOT EXISTS (SELECT 1 FROM sa_experiments WHERE experiment_id = NEW.experiment_id AND status IN ('stopped', 'failed')) THEN
      RAISE EXCEPTION '실행 취소는 멈춘 실험(stopped/failed)에서만 됩니다' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  IF NEW.attempt < OLD.attempt THEN
    RAISE EXCEPTION '시도 번호는 줄일 수 없습니다' USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trials_rules BEFORE INSERT OR UPDATE OR DELETE ON sa_trials
  FOR EACH ROW EXECUTE FUNCTION trg_trials();

-- 실험 잠금: locked_at 기록과 (후보 × 문항 × 반복) 풀이 행 생성(pending, run_no=1, 묶음 배정)을 한 트랜잭션으로
CREATE OR REPLACE FUNCTION lock_experiment(p_experiment_id bigint) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE e record; n_cand int; n_task int; n_made int;
BEGIN
  PERFORM set_config('slotagent.locking', 'on', true);
  UPDATE sa_experiments SET status = 'locked', locked_at = now() WHERE experiment_id = p_experiment_id AND locked_at IS NULL
  RETURNING * INTO e;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 실험이거나 이미 잠긴 실험입니다 (%)', p_experiment_id USING ERRCODE = 'P0001'; END IF;
  SELECT count(*) INTO n_cand FROM sa_experiment_candidates WHERE experiment_id = p_experiment_id;
  n_task := jsonb_array_length(e.plan->'tasks');
  INSERT INTO sa_trials(experiment_id, experiment_candidate_id, task_id, rep, batch_no, run_no)
  SELECT p_experiment_id, ec.experiment_candidate_id, (t->>'task_id')::bigint, r, coalesce((t->>'batch_no')::int, 1), 1
    FROM sa_experiment_candidates ec
   CROSS JOIN jsonb_array_elements(e.plan->'tasks') WITH ORDINALITY AS pt(t, ord)
   CROSS JOIN generate_series(0, e.reps - 1) r
   WHERE ec.experiment_id = p_experiment_id
   ORDER BY ec.experiment_candidate_id, pt.ord, r;
  GET DIAGNOSTICS n_made = ROW_COUNT;
  IF n_made <> n_cand * n_task * e.reps THEN
    RAISE EXCEPTION '풀이 행 수(%)가 계획(후보 % × 문항 % × 반복 %)과 다릅니다', n_made, n_cand, n_task, e.reps USING ERRCODE = 'P0001';
  END IF;
  PERFORM set_config('slotagent.locking', 'off', true);
  RETURN n_made;
END $$;

-- 유효 풀이: (후보, 문항, 반복)마다 마지막으로 끝난 실행 (환경 오류 뒤 다시 실행했으면 그 결과)
CREATE VIEW sa_effective_trials AS
SELECT DISTINCT ON (experiment_candidate_id, task_id, rep) *
  FROM sa_trials
 WHERE status IN ('finished', 'error')
 ORDER BY experiment_candidate_id, task_id, rep, run_no DESC;
COMMENT ON VIEW sa_effective_trials IS '(후보, 문항, 반복)마다 run_no 가 가장 큰 끝난 풀이 하나';

CREATE TABLE sa_spans (
  span_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  trial_id      bigint NOT NULL REFERENCES sa_trials(trial_id),
  attempt       int NOT NULL DEFAULT 1,                 -- 풀이의 몇 번째 시도 기록인지. 채점은 sa_trials.attempt 와 같은 것만 씀
  seq           int NOT NULL,
  kind          text NOT NULL CHECK (kind IN ('llm', 'tool', 'plan')),   -- [확장] 새 단계 종류는 값 추가
  name          text,                                   -- 모델 이름 또는 도구 이름
  started_at    timestamptz NOT NULL,
  duration_sec  numeric NOT NULL CHECK (duration_sec >= 0),
  wait_sec      numeric NOT NULL DEFAULT 0,
  in_tokens     int, out_tokens int,
  tool_args     jsonb,
  tool_result   text,                                   -- 모델이 받은 그대로 전문 저장 (출처 추적·재채점)
  error         text,
  attributes    jsonb NOT NULL DEFAULT '{}',            -- 표준 추적 형식의 나머지 속성 (D-02)
  UNIQUE (trial_id, attempt, seq),
  CHECK (kind <> 'tool' OR name IS NOT NULL)
);
COMMENT ON TABLE sa_spans IS '[추가만] 실행 기록. [확장] 커지면 trial_id 기준 파티션, tool_result 는 객체 저장소로 옮기고 위치만 attributes 에';
CREATE TRIGGER spans_append_only BEFORE UPDATE OR DELETE ON sa_spans
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- 실행 중인 풀이의 지금 시도에만 기록을 붙임. 임대가 끝난 옛 워커가 늦게 쓰는 기록을 막음 (작업 큐 펜싱)
CREATE OR REPLACE FUNCTION trg_spans_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE t record;
BEGIN
  SELECT status, attempt INTO t FROM sa_trials WHERE trial_id = NEW.trial_id;
  IF t.status <> 'running' THEN
    RAISE EXCEPTION '실행 중인 풀이에만 실행 기록을 붙일 수 있습니다' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.attempt <> t.attempt THEN
    RAISE EXCEPTION '지난 시도(%)의 기록입니다. 지금 시도는 %', NEW.attempt, t.attempt USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER spans_current_attempt BEFORE INSERT ON sa_spans
  FOR EACH ROW EXECUTE FUNCTION trg_spans_insert();

CREATE TABLE sa_write_intents (
  write_intent_id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  trial_id          bigint NOT NULL REFERENCES sa_trials(trial_id),
  span_id           bigint NOT NULL REFERENCES sa_spans(span_id),
  tool_name         text NOT NULL,
  payload           jsonb NOT NULL,                     -- 보내려던 내용
  in_rule_list      boolean NOT NULL,                   -- 쓰기 도구 목록에 있던 도구인지
  user_confirmed    boolean NOT NULL DEFAULT false,     -- 사용자 확인 뒤 시도인지 (금지 행동 판정)
  created_at        timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE sa_write_intents IS '[추가만] 가짜 쓰기 도구가 남긴 기록 (FR-RUN-03). 종료 상태·금지 행동 채점의 근거';
CREATE TRIGGER write_intents_append_only BEFORE UPDATE OR DELETE ON sa_write_intents
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 6. 채점: 채점 실행, 조건별 결과, LLM 투표, 풀이별 채점
-- ---------------------------------------------------------------------
CREATE TABLE sa_grading_runs (
  grading_run_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id   bigint NOT NULL REFERENCES sa_experiments(experiment_id),
  pack_version_id bigint NOT NULL REFERENCES sa_pack_versions(pack_version_id),   -- 재채점 때 새 평가팩 버전 가능
  grader_version  text NOT NULL,
  judge_model     text,
  judge_settings  jsonb NOT NULL DEFAULT '{}',          -- 온도, 질문 목록, 3번 판정
  purpose         text NOT NULL CHECK (purpose IN ('initial', 'regrade', 'calibration')),
  upto_batch_no   int CHECK (upto_batch_no IS NULL OR upto_batch_no >= 1),   -- 채점 범위: 이 묶음까지 (비어 있으면 전체)
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz
);
COMMENT ON TABLE sa_grading_runs IS '[불변] 채점 한 번 (finished_at 만 한 번 기록). 같은 실행 기록을 여러 번 채점 (FR-SCR-08)';

-- 범위 안 계획 단위(후보, 문항, 반복) 중 마지막 실행이 아직 안 끝난 수
CREATE OR REPLACE FUNCTION grading_scope_unfinished(p_experiment_id bigint, p_upto int) RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT count(*) FROM (
    SELECT DISTINCT ON (experiment_candidate_id, task_id, rep) status
      FROM sa_trials
     WHERE experiment_id = p_experiment_id AND (p_upto IS NULL OR batch_no <= p_upto)
     ORDER BY experiment_candidate_id, task_id, rep, run_no DESC
  ) last_run WHERE status NOT IN ('finished', 'error');
$$;

CREATE OR REPLACE FUNCTION trg_grading_runs() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE n_missing bigint;
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION '채점 실행은 지울 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.finished_at IS NOT NULL THEN RAISE EXCEPTION '채점 실행은 끝나지 않은 상태로 만듭니다' USING ERRCODE = 'P0001'; END IF;
    IF NEW.purpose IN ('initial', 'regrade') AND grading_scope_unfinished(NEW.experiment_id, NEW.upto_batch_no) > 0 THEN
      RAISE EXCEPTION '채점 범위 안에 안 끝난(대기·실행 중·취소) 풀이가 있습니다. 멈춘 실험이면 upto_batch_no 로 범위를 줄이세요'
        USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
  END IF;
  IF ROW(NEW.experiment_id, NEW.pack_version_id, NEW.grader_version, NEW.judge_model, NEW.judge_settings, NEW.purpose,
         NEW.upto_batch_no, NEW.started_at)
     IS DISTINCT FROM ROW(OLD.experiment_id, OLD.pack_version_id, OLD.grader_version, OLD.judge_model, OLD.judge_settings,
         OLD.purpose, OLD.upto_batch_no, OLD.started_at)
     OR OLD.finished_at IS NOT NULL THEN
    RAISE EXCEPTION '채점 실행은 finished_at 을 한 번 기록하는 것 말고는 바꿀 수 없습니다' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.finished_at IS NOT NULL AND NEW.purpose IN ('initial', 'regrade') THEN
    -- 범위 안 유효 풀이(환경 오류 제외)마다 채점 행이 정확히 1개 (UNIQUE 가 2개 이상을 막으므로 빠진 것만 셈)
    SELECT count(*) INTO n_missing
      FROM sa_effective_trials t
     WHERE t.experiment_id = NEW.experiment_id AND (NEW.upto_batch_no IS NULL OR t.batch_no <= NEW.upto_batch_no)
       AND t.run_outcome <> 'env_error'
       AND NOT EXISTS (SELECT 1 FROM sa_trial_grades g WHERE g.grading_run_id = NEW.grading_run_id AND g.trial_id = t.trial_id);
    IF n_missing > 0 THEN
      RAISE EXCEPTION '채점이 빠진 풀이가 %건 있어 채점을 끝낼 수 없습니다', n_missing USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER grading_runs_rules BEFORE INSERT OR UPDATE OR DELETE ON sa_grading_runs
  FOR EACH ROW EXECUTE FUNCTION trg_grading_runs();

CREATE TABLE sa_condition_results (
  condition_result_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grading_run_id  bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  trial_id        bigint NOT NULL REFERENCES sa_trials(trial_id),
  answer_condition_id    bigint NOT NULL REFERENCES sa_answer_conditions(answer_condition_id),
  passed          boolean NOT NULL,
  evidence        jsonb NOT NULL DEFAULT '{}',          -- 근거 span id, 찾은 값과 관계
  UNIQUE (grading_run_id, trial_id, answer_condition_id)
);
COMMENT ON TABLE sa_condition_results IS '[추가만] 정답 조건별 규칙 채점 결과';
CREATE TRIGGER condition_results_append_only BEFORE UPDATE OR DELETE ON sa_condition_results
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

CREATE TABLE sa_llm_votes (
  llm_vote_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grading_run_id  bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  trial_id        bigint NOT NULL REFERENCES sa_trials(trial_id),
  question_kind   text NOT NULL,                        -- plan_steps, grounded, appropriate, result_class
  vote_no         int NOT NULL CHECK (vote_no BETWEEN 1 AND 4),   -- 1~3번 + 상위 모델 1번
  model           text NOT NULL,
  answer          text,                                 -- yes / no / 분류 값
  quote           text,                                 -- 근거 인용
  UNIQUE (grading_run_id, trial_id, question_kind, vote_no)
);
COMMENT ON TABLE sa_llm_votes IS '[추가만] LLM 판정기 투표. 엇갈리면 vote_no=4 (상위 모델)';
CREATE TRIGGER llm_votes_append_only BEFORE UPDATE OR DELETE ON sa_llm_votes
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

CREATE TABLE sa_trial_grades (
  trial_grade_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grading_run_id  bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  trial_id        bigint NOT NULL REFERENCES sa_trials(trial_id),
  grade_status    text NOT NULL DEFAULT 'graded' CHECK (grade_status IN ('graded', 'grader_error')),   -- 채점기 오류면 grader_error
  success         boolean,                              -- graded 면 필수, grader_error 면 비움
  result_class    text CHECK (result_class IN ('correct', 'wrong_assertion', 'ask_or_giveup')),
  first_fail_type text CHECK (first_fail_type IN ('intent', 'plan_missing', 'tool_choice', 'argument', 'tool_error',
                                                  'info_missing', 'order', 'forbidden', 'final_answer')),
  fail_tags       text[] NOT NULL DEFAULT '{}',         -- empty_result_assertion (빈 결과를 믿고 단정) ... [확장] 태그 추가
  out_of_scope    boolean NOT NULL DEFAULT false,       -- 도구 범위 밖 (FR-SCR-10). 성공률에서 어떻게 셀지는 outcome_rules
  forbidden_action boolean NOT NULL DEFAULT false,
  judge_status    text NOT NULL DEFAULT 'ok' CHECK (judge_status IN ('ok', 'undecidable')),
  unmeasurable    text[] NOT NULL DEFAULT '{}',         -- 측정 불가 지표 (예: plan_inclusion)
  metrics         jsonb NOT NULL DEFAULT '{}',          -- 진단 지표 [확장] 새 지표는 키 추가
  UNIQUE (grading_run_id, trial_id),
  CHECK ((grade_status = 'graded') = (success IS NOT NULL)),
  CHECK ((grade_status = 'graded') = (result_class IS NOT NULL)),
  CHECK (grade_status = 'graded' OR (
         first_fail_type IS NULL AND NOT forbidden_action AND NOT out_of_scope AND judge_status = 'ok'
         AND fail_tags = '{}' AND unmeasurable = '{}' AND metrics = '{}'::jsonb)),
  CHECK (success = (result_class = 'correct')),
  CHECK (NOT success OR first_fail_type IS NULL),
  CHECK (NOT forbidden_action OR NOT success)
  -- "실패면 첫 실패 유형 필수"는 실행 결과에 따라 달라 트리거(trg_trial_grades)가 검사
);
COMMENT ON TABLE sa_trial_grades IS '[추가만] 풀이별 최종 채점. 환경 오류 풀이는 채점 행 없음';

CREATE OR REPLACE FUNCTION trg_trial_grades() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE t record; g record;
BEGIN
  SELECT * INTO t FROM sa_trials WHERE trial_id = NEW.trial_id;
  SELECT * INTO g FROM sa_grading_runs WHERE grading_run_id = NEW.grading_run_id;
  IF t.experiment_id <> g.experiment_id THEN RAISE EXCEPTION '다른 실험의 풀이는 채점할 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF g.finished_at IS NOT NULL THEN RAISE EXCEPTION '끝난 채점 실행에는 채점을 더할 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF g.upto_batch_no IS NOT NULL AND t.batch_no > g.upto_batch_no THEN
    RAISE EXCEPTION '채점 범위(묶음 %까지) 밖 풀이입니다', g.upto_batch_no USING ERRCODE = 'P0001';
  END IF;
  IF t.status NOT IN ('finished', 'error') THEN RAISE EXCEPTION '끝난 풀이만 채점합니다' USING ERRCODE = 'P0001'; END IF;
  IF t.run_outcome = 'env_error' THEN
    RAISE EXCEPTION '환경 오류 풀이는 채점하지 않습니다 (다시 실행하거나 분석 단위에서 제외)' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.grade_status = 'graded' THEN
    IF t.run_outcome IN ('agent_error', 'timeout') AND NEW.success THEN
      RAISE EXCEPTION '에이전트 오류·시간 초과 풀이는 성공일 수 없습니다' USING ERRCODE = 'P0001';
    END IF;
    IF t.run_outcome = 'completed' AND NOT NEW.success AND NOT NEW.out_of_scope AND NEW.first_fail_type IS NULL THEN
      RAISE EXCEPTION '끝까지 실행한 풀이가 실패면 첫 실패 유형이 필요합니다 (FR-SCR-06)' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trial_grades_rules BEFORE INSERT ON sa_trial_grades
  FOR EACH ROW EXECUTE FUNCTION trg_trial_grades();
CREATE TRIGGER trial_grades_append_only BEFORE UPDATE OR DELETE ON sa_trial_grades
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 7. 채점 검증: 사람 라벨, 채점기 점검
-- ---------------------------------------------------------------------
CREATE TABLE sa_labels (
  label_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grading_run_id  bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  trial_id        bigint NOT NULL REFERENCES sa_trials(trial_id),
  labeler_id      bigint NOT NULL REFERENCES sa_users(user_id),
  sampled_as      text NOT NULL CHECK (sampled_as IN ('llm_judged', 'boundary', 'random')),
  human_success   boolean NOT NULL,
  human_result_class text CHECK (human_result_class IN ('correct', 'wrong_assertion', 'ask_or_giveup')),
  blind           boolean NOT NULL DEFAULT true,        -- 후보 이름·채점 결과를 숨겼는지
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (grading_run_id, trial_id, labeler_id),
  CHECK (blind)                                         -- 블라인드가 아닌 라벨은 받지 않음 (FR-VAL-01)
);
COMMENT ON TABLE sa_labels IS '[추가만] 사람 라벨. 같은 풀이를 2명이 라벨하면 이중 라벨';
CREATE TRIGGER labels_append_only BEFORE UPDATE OR DELETE ON sa_labels
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

CREATE TABLE sa_grader_checks (
  grader_check_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grading_run_id  bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  kind            text NOT NULL CHECK (kind IN ('error_rate', 'judge_calibration', 'label_agreement')),
  experiment_candidate_id bigint REFERENCES sa_experiment_candidates(experiment_candidate_id),   -- error_rate 는 후보별
  question_kind   text,                                 -- judge_calibration 은 질문 유형별
  n               int NOT NULL CHECK (n > 0),
  value           jsonb NOT NULL,                       -- 거짓 성공·실패율과 95% 상한, κ
  passed          boolean NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (kind <> 'error_rate' OR experiment_candidate_id IS NOT NULL),
  CHECK (kind <> 'judge_calibration' OR question_kind IS NOT NULL)
);
COMMENT ON TABLE sa_grader_checks IS '[추가만] 채점 오류율(FR-VAL-02), 판정기 사전 확인(FR-VAL-03), 라벨 품질(FR-VAL-04)';
CREATE TRIGGER grader_checks_append_only BEFORE UPDATE OR DELETE ON sa_grader_checks
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 8. 판정: 분석, 비교 결과
-- ---------------------------------------------------------------------
CREATE TABLE sa_analyses (
  analysis_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id   bigint NOT NULL REFERENCES sa_experiments(experiment_id),
  grading_run_id  bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  method          jsonb NOT NULL,                       -- {ci, correction:{method, family, alpha}, sequential, seed} (D-08~D-10)
  code_version    text NOT NULL,                        -- 분석 코드 버전 (커밋 해시)과 통계 라이브러리 버전
  input_hash      text NOT NULL,                        -- 분석에 넣은 sa_trial_grades 행 목록의 해시 (같은 입력인지 확인)
  is_interim      boolean NOT NULL DEFAULT false,       -- 순차 검정 중간 분석
  batch_no        int,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT is_interim OR batch_no IS NOT NULL),
  CHECK (method ?& ARRAY['ci', 'correction', 'seed'])   -- 신뢰구간·보정군·난수가 없으면 재현 불가
);
COMMENT ON TABLE sa_analyses IS '[불변] 분석 한 번. 끝난 initial·regrade 채점만, 중간 분석은 채점 범위 안 묶음만';

CREATE OR REPLACE FUNCTION trg_analyses_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE g record;
BEGIN
  SELECT * INTO g FROM sa_grading_runs WHERE grading_run_id = NEW.grading_run_id;
  IF g.experiment_id <> NEW.experiment_id THEN RAISE EXCEPTION '다른 실험의 채점으로 분석할 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF g.finished_at IS NULL THEN RAISE EXCEPTION '끝나지 않은 채점으로 분석할 수 없습니다' USING ERRCODE = 'P0001'; END IF;
  IF g.purpose NOT IN ('initial', 'regrade') THEN RAISE EXCEPTION '판정기 맞춰 보기(calibration) 채점으로는 분석하지 않습니다' USING ERRCODE = 'P0001'; END IF;
  IF NEW.is_interim AND g.upto_batch_no IS NOT NULL AND NEW.batch_no > g.upto_batch_no THEN
    RAISE EXCEPTION '중간 분석 묶음(%)이 채점 범위(%)를 넘습니다', NEW.batch_no, g.upto_batch_no USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER analyses_rules BEFORE INSERT ON sa_analyses
  FOR EACH ROW EXECUTE FUNCTION trg_analyses_insert();
CREATE TRIGGER analyses_immutable BEFORE UPDATE OR DELETE ON sa_analyses
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('불변');

CREATE TABLE sa_comparisons (
  comparison_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  analysis_id     bigint NOT NULL REFERENCES sa_analyses(analysis_id),
  exp_candidate_id bigint NOT NULL REFERENCES sa_experiment_candidates(experiment_candidate_id),
  baseline_id     bigint NOT NULL REFERENCES sa_experiment_candidates(experiment_candidate_id),
  metric          text NOT NULL,                        -- success_rate, cost_per_success, latency_p50 ... [확장]
  diff            numeric NOT NULL,                     -- 후보 − 기준
  ci_low          numeric NOT NULL,
  ci_high         numeric NOT NULL,
  ci_level        numeric NOT NULL CHECK (ci_level > 0.5 AND ci_level < 1),   -- 보정하면 0.975 등
  p_value         numeric CHECK (p_value BETWEEN 0 AND 1),
  n_tasks         int NOT NULL, n_templates int NOT NULL,
  regression_rate numeric,
  verdict         text CHECK (verdict IN ('adopt', 'conditional', 'hold', 'reject')),   -- 1차 지표 행에만
  reason          text,
  extra_needed    jsonb,                                -- 판단 보류 시 추가 문항 유형·문항 수와 비용
  exclusions      jsonb NOT NULL,                       -- 뺀 분석 단위: 사유별·후보별 수, 남은 문항 유형 수, 후보별 평가 가능 범위
  CHECK (ci_low <= diff AND diff <= ci_high),
  CHECK (exclusions ?& ARRAY['by_reason', 'by_candidate', 'templates_left', 'coverage']),
  CHECK (exp_candidate_id <> baseline_id),
  CHECK (verdict IS NULL OR metric = 'success_rate'),
  CHECK (verdict <> 'hold' OR extra_needed IS NOT NULL),
  CHECK (n_templates <= n_tasks)
);
COMMENT ON TABLE sa_comparisons IS '[불변] 지표별 비교와 판정';
CREATE TRIGGER comparisons_immutable BEFORE UPDATE OR DELETE ON sa_comparisons
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('불변');

-- ---------------------------------------------------------------------
-- 9. 결과 전달: 리포트, chatbot
-- ---------------------------------------------------------------------
CREATE TABLE sa_reports (
  report_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id   bigint NOT NULL REFERENCES sa_experiments(experiment_id),
  analysis_id     bigint NOT NULL REFERENCES sa_analyses(analysis_id),
  kind            text NOT NULL CHECK (kind IN ('one_pager', 'detail')),   -- [확장] 새 리포트 종류
  content         jsonb NOT NULL,                       -- 판정, 근거 수치, 월 비용, 위험 요인, 전제 조건
  file_path       text,
  share_token_hash text UNIQUE,                         -- 보기 전용 링크 (토큰 원문은 저장 안 함)
  share_revoked_at timestamptz,
  share_expires_at timestamptz,                         -- 링크 만료 시각 (기본: 만든 때 + 30일, 앱이 넣음)
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (share_revoked_at IS NULL OR share_token_hash IS NOT NULL),
  CHECK (share_expires_at IS NULL OR share_token_hash IS NOT NULL)
);

CREATE TABLE sa_chat_messages (
  chat_message_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id uuid NOT NULL,
  user_id         bigint NOT NULL REFERENCES sa_users(user_id),
  role            text NOT NULL CHECK (role IN ('user', 'assistant', 'function')),
  content         text,
  function_name   text CHECK (function_name IN ('get_results', 'create_experiment', 'calc_sample_size',
                                                'start_run', 'write_report')),   -- [확장] 함수 추가는 이 목록만
  function_args   jsonb,
  cited_experiment_ids bigint[] NOT NULL DEFAULT '{}',  -- 답에 쓴 수치의 근거 (FR-BOT-02)
  user_confirmed  boolean,                              -- 실행 요청은 확인 뒤에만 (FR-BOT-03)
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((role = 'function') = (function_name IS NOT NULL)),
  CHECK (function_name IS NULL OR function_name NOT IN ('start_run', 'create_experiment') OR coalesce(user_confirmed, false))
);
COMMENT ON TABLE sa_chat_messages IS '[추가만] chatbot 대화와 함수 호출';
CREATE INDEX sa_chat_by_conversation ON sa_chat_messages(conversation_id, chat_message_id);
CREATE TRIGGER chat_messages_append_only BEFORE UPDATE OR DELETE ON sa_chat_messages
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 10. 운영: 검증 실험·감시, 비용 장부
-- ---------------------------------------------------------------------
CREATE TABLE sa_validation_runs (
  validation_run_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  domain_code     text NOT NULL REFERENCES sa_domains(domain_code),
  kind            text NOT NULL CHECK (kind IN ('E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'canary')),
  experiment_id   bigint REFERENCES sa_experiments(experiment_id),
  pack_version_id bigint REFERENCES sa_pack_versions(pack_version_id),
  params          jsonb NOT NULL DEFAULT '{}',
  result          jsonb,
  passed          boolean,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  CHECK ((finished_at IS NULL) = (passed IS NULL))
);
COMMENT ON TABLE sa_validation_runs IS '검증 실험 E1~E6, 카나리아 감시. 도메인별로 따로';

CREATE TABLE sa_cost_ledger (
  cost_ledger_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  source          text NOT NULL CHECK (source IN ('trial', 'judge', 'chat', 'validation')),
  ref_id          bigint,                               -- sa_trials.trial_id 등
  experiment_id   bigint REFERENCES sa_experiments(experiment_id),
  model           text NOT NULL,
  in_tokens       int NOT NULL CHECK (in_tokens >= 0),
  out_tokens      int NOT NULL CHECK (out_tokens >= 0),
  cost_krw        numeric NOT NULL CHECK (cost_krw >= 0),
  price_setting_id bigint REFERENCES sa_settings(setting_id)       -- 어떤 가격표로 계산했는지
);
COMMENT ON TABLE sa_cost_ledger IS '[추가만] LLM 비용 장부. 예산·비용 한도 판단에 씀 (FR-RUN-07, NFR-OPS-01)';
CREATE INDEX sa_cost_by_month ON sa_cost_ledger(occurred_at);
CREATE TRIGGER cost_ledger_append_only BEFORE UPDATE OR DELETE ON sa_cost_ledger
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');

-- ---------------------------------------------------------------------
-- 11. 분석 단위: 기준과 후보 한 쌍이 함께 유효한 (문항, 반복)만 씀
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analysis_units(p_grading_run_id bigint, p_exp_candidate_id bigint)
RETURNS TABLE (task_id bigint, rep int, included boolean, exclude_reason text)
LANGUAGE sql STABLE AS $$
  WITH gr AS (
    SELECT experiment_id, upto_batch_no FROM sa_grading_runs WHERE grading_run_id = p_grading_run_id
  ), pair AS (                                   -- 기준 + 비교할 후보 하나
    SELECT ec.experiment_candidate_id FROM sa_experiment_candidates ec
     WHERE ec.experiment_id = (SELECT experiment_id FROM gr)
       AND (ec.role = 'baseline' OR ec.experiment_candidate_id = p_exp_candidate_id)
  ), et AS (                                     -- 계획 목록(run_no = 1)에서 시작해 마지막 실행과 채점을 붙임
    SELECT p.task_id AS t_id, p.rep AS t_rep, e.run_outcome, g.grade_status,
           coalesce(g.judge_status = 'undecidable', false) AS undecidable
      FROM sa_trials p
      JOIN gr ON gr.experiment_id = p.experiment_id
      LEFT JOIN sa_effective_trials e
        ON e.experiment_candidate_id = p.experiment_candidate_id AND e.task_id = p.task_id AND e.rep = p.rep
      LEFT JOIN sa_trial_grades g ON g.trial_id = e.trial_id AND g.grading_run_id = p_grading_run_id
     WHERE p.run_no = 1
       AND (gr.upto_batch_no IS NULL OR p.batch_no <= gr.upto_batch_no)
       AND p.experiment_candidate_id IN (SELECT experiment_candidate_id FROM pair)
  ), u AS (
    SELECT t_id, t_rep,
           CASE WHEN count(*) < (SELECT count(*) FROM pair)        THEN 'missing_candidate'
                WHEN bool_or(run_outcome IS NULL)                 THEN 'not_finished'
                WHEN bool_or(run_outcome = 'env_error')           THEN 'env_error'
                WHEN bool_or(grade_status IS NULL)                THEN 'ungraded'
                WHEN bool_or(grade_status = 'grader_error')       THEN 'grader_error'
                WHEN bool_or(undecidable)                         THEN 'undecidable'
           END AS reason
      FROM et GROUP BY t_id, t_rep
  )
  SELECT t_id, t_rep, reason IS NULL, reason FROM u ORDER BY t_id, t_rep;
$$;
COMMENT ON FUNCTION analysis_units(bigint, bigint) IS '채점 범위 안 (문항, 반복)마다 기준·후보 한 쌍의 포함 여부와 제외 사유. out_of_scope 는 제외 사유가 아님';
