-- 과정 채점 (2026-11-26, 중간발표 Q1·Q4). 세부 모양은 contracts 검사가 맡습니다.
-- 1) 정답 조건 uses: 필수 기능을 호출했는지 (gate 기본 false, 과정 진단용)
ALTER TABLE sa_answer_conditions DROP CONSTRAINT sa_answer_conditions_kind_check;
ALTER TABLE sa_answer_conditions ADD CONSTRAINT sa_answer_conditions_kind_check
  CHECK (kind IN ('info', 'link', 'order', 'forbidden', 'uses', 'end_state', 'exact_writes'));
COMMENT ON COLUMN sa_answer_conditions.kind IS '조건 종류: info 필요 정보 / link 연결 근거 / order 순서 / forbidden 금지 행동 / uses 필수 기능 호출 / end_state 종료 상태 / exact_writes 정확한 쓰기';

-- 2) 실험 사전 등록(prereg.process_policy) 규칙별 판정. 판정 불가는 condition_results 처럼 행을 만들지 않습니다.
CREATE TABLE sa_policy_results (
  policy_result_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grading_run_id   bigint NOT NULL REFERENCES sa_grading_runs(grading_run_id),
  trial_id         bigint NOT NULL REFERENCES sa_trials(trial_id),
  rule             text NOT NULL CHECK (rule IN ('approved_tools', 'read_before_write')),
  passed           boolean NOT NULL,
  evidence         jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(evidence) = 'object'),
  UNIQUE (grading_run_id, trial_id, rule)
);
CREATE TRIGGER policy_results_append_only BEFORE UPDATE OR DELETE ON sa_policy_results
  FOR EACH ROW EXECUTE FUNCTION trg_forbid_change('추가만');
COMMENT ON TABLE sa_policy_results IS '정책 규칙별 채점 결과 [추가만]: 풀이 하나가 실험 사전 등록의 과정 정책(승인 도구, 쓰기 전 같은 대상 조회)을 지켰는지와 근거';
COMMENT ON COLUMN sa_policy_results.policy_result_id IS '행 번호. 자동으로 1씩 늘어나는 내부 ID';
COMMENT ON COLUMN sa_policy_results.grading_run_id IS '어느 채점 실행의 결과인지';
COMMENT ON COLUMN sa_policy_results.trial_id IS '어느 풀이를 채점했는지';
COMMENT ON COLUMN sa_policy_results.rule IS '정책 규칙: approved_tools 승인 목록 밖 도구 호출 없음 / read_before_write 쓰기 전에 같은 대상 조회';
COMMENT ON COLUMN sa_policy_results.passed IS '규칙을 지켰는지 (판정 불가는 행을 만들지 않음)';
COMMENT ON COLUMN sa_policy_results.evidence IS '근거 = grading.condition_evidence 스키마: span_seqs(위반한 호출 번호), found';
