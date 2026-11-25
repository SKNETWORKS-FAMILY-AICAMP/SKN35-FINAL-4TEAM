-- 문항별 가짜 쓰기 시나리오와 정확한 쓰기 조건 (2026-11-25). 세부 모양은 contracts 검사가 맡습니다.
ALTER TABLE sa_tasks ADD COLUMN write_scenario jsonb
  CONSTRAINT sa_tasks_write_scenario_object CHECK (jsonb_typeof(write_scenario) = 'object');
COMMENT ON COLUMN sa_tasks.write_scenario IS '문항별 가짜 쓰기·상태 시나리오. 엔진 전용이며 모델 입력에 넣지 않음. SQL NULL은 시나리오 없음';

ALTER TABLE sa_answer_conditions DROP CONSTRAINT sa_answer_conditions_kind_check;
ALTER TABLE sa_answer_conditions ADD CONSTRAINT sa_answer_conditions_kind_check
  CHECK (kind IN ('info', 'link', 'order', 'forbidden', 'end_state', 'exact_writes'));
COMMENT ON COLUMN sa_answer_conditions.kind IS '조건 종류: info 필요 정보 / link 연결 근거 / order 순서 / forbidden 금지 행동 / end_state 종료 상태 / exact_writes 정확한 쓰기';
