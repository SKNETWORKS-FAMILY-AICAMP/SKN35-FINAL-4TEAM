-- 기본값 (sa_settings 는 추가만: 값을 바꾸려면 새 행을 넣음, 최신 valid_from 이 이김)
-- 누가 정하는 값인지 note 에 적음. plan-proposal API 가 여기서 읽어 prereg·plan 을 만듦 (11/22 검토 2·3·24)
-- 숫자는 기획서 1.2 share용 그대로 (마진 5%p, 회귀율 5%)
INSERT INTO sa_settings(scope, scope_ref, key, value, note) VALUES
  ('global', '', 'ni_margin_pp',        '5',    '③ 비열등성 마진 %p (기획서 1.2)'),
  ('global', '', 'alpha',               '0.05', '③ 유의수준'),
  ('global', '', 'regression_limit',    '0.05', '③ 회귀율 한도 (기획서 1.2)'),
  ('global', '', 'max_env_retries',     '1',    '① 환경 오류 다시 실행 횟수'),
  ('global', '', 'env_error_reasons',
   '["env_mcp_server_down","env_practice_repo_unreachable","env_practice_db_unreachable","env_llm_api_5xx","env_worker_lost","env_write_proxy_error"]',
   '① 환경 탓으로 볼 outcome_reason. llm_api_429 는 팀 확정 전이라 뺌'),
  ('global', '', 'out_of_scope_rule',   '"fail"', '⚠ 팀 확정 전 (fail / exclude)'),
  ('global', '', 'queue.lease_sec',     '600',  '① 작업 임대 10분');
