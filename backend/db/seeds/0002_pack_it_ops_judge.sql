-- ② 판정기 설정 (도메인별). ①이 sa_grading_runs 를 만들 때 최신 행의 value 를 judge_settings 로 복사
-- 도메인 행(sa_domains.code = it_ops)이 먼저 있어야 함
INSERT INTO sa_settings(scope, scope_ref, key, value, note) VALUES
  ('domain', 'it_ops', 'judge.settings',
   '{"schema_version":1,"temperature":0,"votes":3,"tiebreak_model":"gpt-4.1","questions":["plan_steps","grounded","result_class"],"rubric_version":"rc-1.0"}',
   '② 판정기 설정 (grading.judge_settings 스키마)'),
  ('domain', 'it_ops', 'judge.model', '"gpt-4.1-mini"', '② 판정 모델');
