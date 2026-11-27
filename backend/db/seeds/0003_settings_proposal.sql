-- plan-proposal 이 stats.sample_size 에 넘길 값과 reps 기본값 (11/27, ① 먼저 적용, ③ 확인 전)
INSERT INTO sa_settings(scope, scope_ref, key, value, note) VALUES
  ('global', '', 'power',  '0.8', '③ 검정력 (기획서 80%)'),
  ('global', '', 'p_base', '0.7', '⚠ ③ 확인 전 임시값: 기준 후보 예상 성공률'),
  ('global', '', 'reps',   '3',   '⚠ ③ 확인 전 임시값: 문항당 반복 수 기본');
