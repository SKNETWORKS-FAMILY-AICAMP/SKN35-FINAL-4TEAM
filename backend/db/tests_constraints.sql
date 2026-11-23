-- erd_v1.2/test_constraints.sql 사본 (11/22 이름 규칙판). 0001·0002 위에서 돌림 — 0003 의 outcome_reason 값 목록과 맞지 않는 자유 문구가 있어 0003 뒤에는 안 돌림. erd_v1.2/run_tests.py 로 150개 통과
-- product_db.sql 을 적용한 빈 DB 에서 실행. 규칙마다 "되어야 하는 것"과 "막혀야 하는 것"을 확인
-- 괄호 안 ID 는 요구사항 정의서 v1.2
SET client_min_messages = warning;
CREATE TEMP TABLE test_log(name text, ok boolean, detail text);

CREATE OR REPLACE FUNCTION pg_temp.expect_fail(p_name text, p_sql text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE p_sql; INSERT INTO test_log VALUES (p_name, false, '막히지 않음');
  EXCEPTION WHEN others THEN INSERT INTO test_log VALUES (p_name, true, SQLERRM); END;
END $$;
CREATE OR REPLACE FUNCTION pg_temp.expect_ok(p_name text, p_sql text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE p_sql; INSERT INTO test_log VALUES (p_name, true, 'ok');
  EXCEPTION WHEN others THEN INSERT INTO test_log VALUES (p_name, false, SQLERRM); END;
END $$;

-- ------------------------------------------------------------------
-- 기본 데이터 (연습 실험 축소판)
-- ------------------------------------------------------------------
INSERT INTO sa_users(email, name) VALUES ('dev@example.test', '개발자'), ('labeler@example.test', '라벨러');
INSERT INTO sa_domains(domain_code, name, status) VALUES ('it_ops', 'IT 운영', 'active'), ('data_analysis', '데이터 분석', 'pilot');
INSERT INTO sa_settings(scope, key, value) VALUES ('global', 'ni_margin_pp', '5'), ('global', 'regression_limit', '0.05');
INSERT INTO sa_agents(owner_id, name) VALUES (1, '배포 도우미');
INSERT INTO sa_agent_versions(agent_id, version_no, connection_type, control_level, model, instructions, spec, spec_hash)
VALUES (1, 1, 'spec_upload', 'C2', 'model-x', '너는 IT 운영 도우미다', '{"tools":[]}', 'h1');
INSERT INTO sa_slots(agent_version_id, name, service, access, comparable) VALUES (1, 'GitHub 조회', 'github', 'read', true);
INSERT INTO sa_slots(agent_version_id, name, service, access, comparable, not_comparable_reason)
VALUES (1, 'Slack 발송', 'slack', 'write', false, '쓰기 자리는 비교 대상이 아님');
INSERT INTO sa_candidates(slot_id, label, name, component_spec, spec_hash, is_baseline) VALUES
 (1, 'A', 'MCP 전체', '{"tools":["t1","t2","t3"]}', 'cA', true),
 (1, 'B', '필요한 것만', '{"tools":["t1","t2"]}', 'cB', false),
 (1, 'C', '직접 도구', '{"tools":["lookup"]}', 'cC', false),
 (1, 'D', '네 번째', '{"tools":["t9"]}', 'cD', false);
INSERT INTO sa_candidates(slot_id, label, name, component_spec, spec_hash) VALUES (2, 'X', '다른 자리', '{}', 'cX');

INSERT INTO sa_pack_versions(domain_code, pack_code, version) VALUES ('it_ops', 'it_ops', 'v1.0'), ('it_ops', 'it_ops', 'v0.9');
INSERT INTO sa_data_snapshots(pack_version_id, source_kind, location) VALUES (1, 'db_schema', 'pack_it_ops_v1_0');
INSERT INTO sa_templates(pack_version_id, code, question_pattern) VALUES (1, 'T1', '{날짜} 실패 실행'), (1, 'T2', '{사람}의 열린 이슈');
INSERT INTO sa_tasks(template_id, code, prompt, seed) VALUES (1, 'T1-0', '11월 5일 실패 실행?', 1), (1, 'T1-1', '11월 6일?', 2), (2, 'T2-0', 'sora 이슈?', 3);
INSERT INTO sa_answer_conditions(task_id, seq, kind, spec) VALUES (1, 1, 'info', '{"value":"305"}'), (1, 2, 'link', '{"rel":"closed_by"}');
INSERT INTO sa_golden_trajectories(template_id, kind, trace, expected) VALUES (1, 'success', '[]', '{"success":true}');
INSERT INTO sa_templates(pack_version_id, code, question_pattern) VALUES (2, 'Z1', '다른 팩 유형');
INSERT INTO sa_tasks(template_id, code, prompt, seed) VALUES (3, 'Z1-0', '다른 팩 문항', 9);

-- ------------------------------------------------------------------
-- 1. 연결·후보
-- ------------------------------------------------------------------
SELECT pg_temp.expect_fail('구성 명세는 불변 (agent_versions)', $q$UPDATE sa_agent_versions SET model='other' WHERE agent_version_id=1$q$);
SELECT pg_temp.expect_fail('API 연결은 C2 불가 (5.9)', $q$INSERT INTO sa_agent_versions(agent_id,version_no,connection_type,control_level,model,instructions,spec,spec_hash) VALUES (1,2,'api','C2','m','i','{}','h')$q$);
SELECT pg_temp.expect_fail('연결 정보에 API 키 저장 금지 (NFR-SEC-01)', $q$INSERT INTO sa_agent_versions(agent_id,version_no,connection_type,control_level,model,instructions,spec,spec_hash,connection) VALUES (1,3,'runner','C2','m','i','{}','h','{"api_key":"x"}')$q$);
SELECT pg_temp.expect_fail('비교 못 하는 자리는 이유 필수 (FR-CON-03)', $q$INSERT INTO sa_slots(agent_version_id,name,service,access,comparable) VALUES (1,'Jira','jira','write',false)$q$);
SELECT pg_temp.expect_fail('자리마다 기준 후보는 1개', $q$INSERT INTO sa_candidates(slot_id,label,name,component_spec,spec_hash,is_baseline) VALUES (1,'E','두 번째 기준','{}','cE',true)$q$);
SELECT pg_temp.expect_fail('후보는 불변', $q$UPDATE sa_candidates SET name='x' WHERE candidate_id=2$q$);
SELECT pg_temp.expect_ok('[확장] 도구 말고 지시문 후보도 같은 테이블', $q$INSERT INTO sa_candidates(slot_id,label,name,component_kind,component_spec,spec_hash) VALUES (1,'P','지시문 바꾸기','prompt','{"prompt":"..."}','cP')$q$);

-- ------------------------------------------------------------------
-- 2. 평가팩 잠금
-- ------------------------------------------------------------------
SELECT pg_temp.expect_fail('동결 안 된 연습 데이터가 있으면 평가팩 잠금 불가 (FR-PACK-08)', $q$UPDATE sa_pack_versions SET status='locked', locked_at=now() WHERE pack_version_id=1$q$);
SELECT pg_temp.expect_fail('연습 데이터 동결은 해시와 시각이 함께', $q$UPDATE sa_data_snapshots SET content_hash='abc' WHERE data_snapshot_id=1$q$);
SELECT pg_temp.expect_ok('연습 데이터 동결', $q$UPDATE sa_data_snapshots SET content_hash='abc', frozen_at=now() WHERE data_snapshot_id=1$q$);
SELECT pg_temp.expect_ok('평가팩 잠금', $q$UPDATE sa_pack_versions SET status='locked', locked_at=now() WHERE pack_version_id=1$q$);
SELECT pg_temp.expect_fail('잠긴 평가팩에 문항 유형 추가 금지 (FR-PACK-07)', $q$INSERT INTO sa_templates(pack_version_id,code,question_pattern) VALUES (1,'T9','x')$q$);
SELECT pg_temp.expect_fail('잠긴 평가팩의 문항 수정 금지', $q$UPDATE sa_tasks SET prompt='고침' WHERE task_id=1$q$);
SELECT pg_temp.expect_fail('잠긴 평가팩의 정답 조건 수정 금지', $q$UPDATE sa_answer_conditions SET spec='{"value":"306"}' WHERE answer_condition_id=1$q$);
SELECT pg_temp.expect_fail('잠긴 평가팩의 골든 궤적 추가 금지', $q$INSERT INTO sa_golden_trajectories(template_id,kind,trace,expected) VALUES (1,'near_miss','[]','{}')$q$);
SELECT pg_temp.expect_fail('잠긴 평가팩의 연습 데이터 바꾸기 금지', $q$UPDATE sa_data_snapshots SET location='other' WHERE data_snapshot_id=1$q$);
SELECT pg_temp.expect_fail('잠긴 평가팩을 draft 로 되돌리기 금지', $q$UPDATE sa_pack_versions SET status='draft', locked_at=NULL WHERE pack_version_id=1$q$);
SELECT pg_temp.expect_ok('잠긴 평가팩에도 점검 기록은 추가 (FR-ENV-01)', $q$INSERT INTO sa_env_checks(pack_version_id,kind,target,result) VALUES (1,'golden_test','grader-1.0','pass')$q$);
SELECT pg_temp.expect_fail('점검 기록은 추가만', $q$UPDATE sa_env_checks SET result='fail' WHERE env_check_id=1$q$);
SELECT pg_temp.expect_fail('점검 종류는 정해진 것만', $q$INSERT INTO sa_env_checks(pack_version_id,kind,target,result) VALUES (1,'random','x','pass')$q$);
SELECT pg_temp.expect_ok('문항 열람 기록 (FR-PACK-04)', $q$INSERT INTO sa_task_exposures(task_id,seen_by,reason) VALUES (1,1,'실패 기록 열람')$q$);
SELECT pg_temp.expect_ok('[확장] 새 도메인은 행 추가만 (NFR-EXT-01)', $q$INSERT INTO sa_domains(domain_code,name,status) VALUES ('customer_support','고객지원','planned')$q$);
SELECT pg_temp.expect_fail('기준 숫자는 추가만 (바꾸면 새 행)', $q$UPDATE sa_settings SET value='7' WHERE key='ni_margin_pp'$q$);
SELECT pg_temp.expect_ok('기준 숫자 바꾸기 = 새 행', $q$INSERT INTO sa_settings(scope,key,value,valid_from) VALUES ('global','ni_margin_pp','7', now() + interval '1 day')$q$);

-- ------------------------------------------------------------------
-- 3. 실험·사전 등록
-- ------------------------------------------------------------------
-- 실험 데이터는 먼저 다 넣음 (막힌 INSERT 도 번호를 쓰므로)
INSERT INTO sa_experiments(agent_version_id, slot_id, pack_version_id, reps, prereg, plan, created_by) VALUES
 (1, 1, 1, 1, '{"primary":"success_rate","margin_pp":5,"alpha":0.05,"outcome_rules":{"out_of_scope":"fail"},"max_env_retries":1}', '{"tasks":[{"task_id":1,"batch_no":1},{"task_id":2,"batch_no":1},{"task_id":3,"batch_no":2}]}', 1),   -- 1: 본 실험
 (1, 1, 2, 2, '{"outcome_rules":{"out_of_scope":"fail"},"max_env_retries":1}', '{"tasks":[{"task_id":1,"batch_no":1},{"task_id":2,"batch_no":1},{"task_id":3,"batch_no":2}]}', 1),                                                       -- 2: 잠기지 않은 평가팩
 (1, 1, 1, 2, '{"outcome_rules":{"out_of_scope":"fail"},"max_env_retries":1}', '{"tasks":[{"task_id":1,"batch_no":1},{"task_id":2,"batch_no":1},{"task_id":3,"batch_no":2}]}', 1);                                                       -- 3: 후보 4개
INSERT INTO sa_experiment_candidates(experiment_id, candidate_id, label, role, config_snapshot, config_hash) VALUES
 (1, 1, 'A', 'baseline', '{"model":"model-x"}', 'kA'), (1, 2, 'B', 'candidate', '{"model":"model-x"}', 'kB'),   -- 1, 2
 (2, 1, 'A', 'baseline', '{}', 'k1'), (2, 2, 'B', 'candidate', '{}', 'k2'),                                     -- 3, 4
 (3, 1, 'A', 'baseline', '{}', 'k1'), (3, 2, 'B', 'candidate', '{}', 'k2'), (3, 3, 'C', 'candidate', '{}', 'k3'), (3, 4, 'D', 'candidate', '{}', 'k4');
SELECT pg_temp.expect_fail('비교 실험은 자리 필수', $q$INSERT INTO sa_experiments(kind,agent_version_id,pack_version_id,reps,created_by) VALUES ('compare',1,1,2,1)$q$);
SELECT pg_temp.expect_ok('진단은 자리 없이', $q$INSERT INTO sa_experiments(kind,agent_version_id,pack_version_id,reps,created_by) VALUES ('diagnose',1,1,2,1)$q$);
SELECT pg_temp.expect_fail('다른 자리의 후보는 넣을 수 없음 (한 번에 한 자리)', $q$INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash) VALUES (1,5,'X','candidate','{}','x')$q$);
SELECT pg_temp.expect_fail('실험마다 기준은 1개', $q$INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash) VALUES (1,3,'C','baseline','{}','kC')$q$);
SELECT pg_temp.expect_fail('잠기지 않은 평가팩으로는 실험 잠금 불가', $q$SELECT lock_experiment(2)$q$);
SELECT pg_temp.expect_fail('후보는 3개까지 (FR-EXP-05)', $q$SELECT lock_experiment(3)$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 잠금은 lock_experiment 로만 (직접 UPDATE 금지)', $q$UPDATE sa_experiments SET status='locked', locked_at=now() WHERE experiment_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 사전 등록에 오류 처리 규칙이 없으면 잠금 불가', $q$SELECT lock_experiment((SELECT experiment_id FROM sa_experiments WHERE kind='diagnose'))$q$);
SELECT pg_temp.expect_ok('[1.2 수정] 실험 잠금 = 풀이 행 생성까지 한 번에', $q$SELECT lock_experiment(1)$q$);
SELECT pg_temp.expect_ok('[1.2 수정] 잠금이 만든 풀이 = 후보 2 × 문항 3 × 반복 1', $q$DO $d$ BEGIN IF (SELECT count(*) FROM sa_trials WHERE experiment_id=1 AND run_no=1 AND status='pending') <> 6 THEN RAISE EXCEPTION 'count'; END IF; END $d$$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 이미 잠긴 실험을 다시 잠글 수 없음', $q$SELECT lock_experiment(1)$q$);
SELECT pg_temp.expect_fail('잠긴 실험에 후보 추가 금지', $q$INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash) VALUES (1,3,'C','candidate','{}','kC')$q$);
SELECT pg_temp.expect_fail('잠긴 실험의 반복 수 변경 금지', $q$UPDATE sa_experiments SET reps=5 WHERE experiment_id=1$q$);
SELECT pg_temp.expect_fail('잠근 뒤 사전 등록 변경은 탐색적 표시 없이 불가', $q$UPDATE sa_experiments SET prereg='{"margin_pp":7}' WHERE experiment_id=1$q$);
SELECT pg_temp.expect_ok('상태 변경(실행 중)은 됨', $q$UPDATE sa_experiments SET status='running' WHERE experiment_id=1$q$);
SELECT pg_temp.expect_fail('멈춤은 이유 필수 (FR-RUN-08)', $q$UPDATE sa_experiments SET status='stopped' WHERE experiment_id=1$q$);

-- ------------------------------------------------------------------
-- 4. 실행: 풀이·실행 기록·가짜 쓰기
-- ------------------------------------------------------------------
-- 잠금이 만든 풀이 1~6: 후보 A(1)의 문항 1·2·3 = 1·2·3, 후보 B(2)의 문항 1·2·3 = 4·5·6. 문항 3은 묶음 2
SELECT pg_temp.expect_fail('잠기지 않은 실험은 실행 불가 (FR-EXP-02)', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep) VALUES (2,3,1,0)$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 계획 밖 첫 실행 풀이 금지 (잠금이 만든 것만)', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep) VALUES (1,1,1,1)$q$);
SELECT pg_temp.expect_fail('실험의 평가팩에 없는 문항 금지', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep) VALUES (1,1,4,0)$q$);
SELECT pg_temp.expect_fail('다른 실험의 후보 금지', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep) VALUES (1,3,1,1)$q$);
SELECT pg_temp.expect_fail('끝났는데 결과 상태가 없으면 금지', $q$UPDATE sa_trials SET status='finished' WHERE trial_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 실행 결과는 4종만 (정답·오답은 채점이 정함)', $q$UPDATE sa_trials SET status='finished', run_outcome='correct', outcome_reason='x' WHERE trial_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 오류로 끝나면 원인 필수', $q$UPDATE sa_trials SET status='error', run_outcome='timeout' WHERE trial_id=1$q$);
SELECT pg_temp.expect_fail('실행 중이 아닌 풀이에는 실행 기록 금지', $q$INSERT INTO sa_spans(trial_id,seq,kind,name,started_at,duration_sec) VALUES (1,1,'llm','model-x',now(),1)$q$);
UPDATE sa_trials SET status='running', started_at=now() WHERE trial_id IN (1,2,3,4,5,6);
INSERT INTO sa_spans(trial_id, seq, kind, name, started_at, duration_sec, tool_args, tool_result)
VALUES (1, 1, 'llm', 'model-x', now(), 1.2, NULL, NULL), (1, 2, 'tool', 'list_runs', now(), 0.3, '{"date":"11-05"}', '[{"id":305}]');
-- 워커가 죽어 다시 실행: 시도 번호를 올리면 같은 순서 번호로 새 기록을 쌓을 수 있고, 옛 시도 기록은 막힘
SELECT pg_temp.expect_ok('다시 실행: 시도 번호 올리기', $q$UPDATE sa_trials SET attempt=2 WHERE trial_id=3$q$);
SELECT pg_temp.expect_ok('다시 실행: 같은 순서 번호로 새 시도 기록', $q$INSERT INTO sa_spans(trial_id,attempt,seq,kind,name,started_at,duration_sec) VALUES (3,2,1,'llm','model-x',now(),1)$q$);
SELECT pg_temp.expect_fail('옛 시도의 늦은 기록 금지 (펜싱)', $q$INSERT INTO sa_spans(trial_id,attempt,seq,kind,name,started_at,duration_sec) VALUES (3,1,2,'llm','model-x',now(),1)$q$);
SELECT pg_temp.expect_fail('시도 번호는 줄일 수 없음', $q$UPDATE sa_trials SET attempt=1 WHERE trial_id=3$q$);
SELECT pg_temp.expect_fail('실행 기록은 추가만 (FR-RUN-06)', $q$UPDATE sa_spans SET tool_result='[]' WHERE trial_id=1 AND seq=2$q$);
SELECT pg_temp.expect_fail('실행 기록 삭제 금지', $q$DELETE FROM sa_spans WHERE trial_id=1 AND seq=1$q$);
SELECT pg_temp.expect_fail('도구 단계는 도구 이름 필수', $q$INSERT INTO sa_spans(trial_id,seq,kind,started_at,duration_sec) VALUES (1,3,'tool',now(),0.1)$q$);
SELECT pg_temp.expect_ok('가짜 쓰기 기록 (FR-RUN-03)', $q$INSERT INTO sa_write_intents(trial_id,span_id,tool_name,payload,in_rule_list) VALUES (1,(SELECT span_id FROM sa_spans WHERE trial_id=1 AND seq=2),'slack.send','{"text":"..."}',true)$q$);
SELECT pg_temp.expect_fail('가짜 쓰기 기록은 추가만', $q$UPDATE sa_write_intents SET user_confirmed=true WHERE write_intent_id=1$q$);
SELECT pg_temp.expect_fail('러너 기록은 서명 없이 끝낼 수 없음 (NFR-SEC-03)', $q$UPDATE sa_trials SET record_source='runner', status='finished', run_outcome='completed' WHERE trial_id=6$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 실행 중 풀이는 취소 불가 (취소는 대기 중인 것만)', $q$UPDATE sa_trials SET status='cancelled' WHERE trial_id=6$q$);
SELECT pg_temp.expect_ok('풀이 끝내기', $q$UPDATE sa_trials SET status='finished', run_outcome='completed', finished_at=now() WHERE trial_id IN (1,2,3,4,5,6)$q$);
SELECT pg_temp.expect_fail('끝난 풀이는 수정 금지', $q$UPDATE sa_trials SET run_outcome='timeout', outcome_reason='x' WHERE trial_id=1$q$);
SELECT pg_temp.expect_fail('풀이 삭제 금지', $q$DELETE FROM sa_trials WHERE trial_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 정상 종료 풀이는 다시 실행 불가', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,run_no) VALUES (1,1,1,0,2)$q$);
SELECT pg_temp.expect_fail('작업 큐: 임대 중이면 임대 시간 필수', $q$INSERT INTO sa_jobs(kind,payload,status) VALUES ('run_trial','{}','leased')$q$);
SELECT pg_temp.expect_ok('작업 큐: 넣기', $q$INSERT INTO sa_jobs(kind,payload) VALUES ('run_trial','{"trial_id":1}')$q$);

-- ------------------------------------------------------------------
-- 5. 채점
-- ------------------------------------------------------------------
INSERT INTO sa_grading_runs(experiment_id, pack_version_id, grader_version, purpose) VALUES (1, 1, 'grader-1.0', 'initial');
SELECT pg_temp.expect_ok('조건별 결과', $q$INSERT INTO sa_condition_results(grading_run_id,trial_id,answer_condition_id,passed,evidence) VALUES (1,1,1,true,'{"span":2}'),(1,1,2,true,'{}')$q$);
SELECT pg_temp.expect_fail('같은 채점에서 같은 조건은 한 번만', $q$INSERT INTO sa_condition_results(grading_run_id,trial_id,answer_condition_id,passed) VALUES (1,1,1,false)$q$);
SELECT pg_temp.expect_ok('LLM 투표 3번 + 상위 모델', $q$INSERT INTO sa_llm_votes(grading_run_id,trial_id,question_kind,vote_no,model,answer) VALUES (1,1,'grounded',1,'j','yes'),(1,1,'grounded',2,'j','no'),(1,1,'grounded',3,'j','yes'),(1,1,'grounded',4,'j-big','yes')$q$);
SELECT pg_temp.expect_fail('투표 번호는 4까지', $q$INSERT INTO sa_llm_votes(grading_run_id,trial_id,question_kind,vote_no,model) VALUES (1,1,'grounded',5,'j')$q$);
SELECT pg_temp.expect_ok('성공 채점', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (1,1,true,'correct')$q$);
SELECT pg_temp.expect_fail('실패면 첫 실패 단계 필수 (FR-SCR-06)', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (1,2,false,'wrong_assertion')$q$);
SELECT pg_temp.expect_ok('실패 + 빈 결과를 믿고 단정 태그', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,first_fail_type,fail_tags) VALUES (1,2,false,'wrong_assertion','argument','{empty_result_assertion}')$q$);
SELECT pg_temp.expect_ok('도구 범위 밖은 실패 유형 없이 (FR-SCR-10)', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,out_of_scope) VALUES (1,3,false,'ask_or_giveup',true)$q$);
SELECT pg_temp.expect_fail('실패 유형은 9가지만', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,first_fail_type) VALUES (1,4,false,'wrong_assertion','out_of_scope')$q$);
SELECT pg_temp.expect_fail('성공인데 결과 분류가 정답이 아니면 금지', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (1,4,true,'ask_or_giveup')$q$);
SELECT pg_temp.expect_fail('금지 행동이 있으면 성공 불가', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,forbidden_action) VALUES (1,5,true,'correct',true)$q$);
SELECT pg_temp.expect_fail('채점 결과는 추가만 (재채점은 새 grading_run)', $q$UPDATE sa_trial_grades SET success=false WHERE trial_grade_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 채점이 빠진 풀이가 있으면 채점을 끝낼 수 없음', $q$UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 채점 행은 성공 여부 필수 (graded)', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,result_class) VALUES (1,4,'correct')$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 채점기 오류 행은 다른 칸을 비워야 함', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,grade_status,success,result_class) VALUES (1,4,'grader_error',false,'ask_or_giveup')$q$);
SELECT pg_temp.expect_ok('[1.2 수정] 채점기 오류는 채점 결과에 남김', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,grade_status) VALUES (1,4,'grader_error')$q$);
SELECT pg_temp.expect_ok('나머지 채점', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (1,5,true,'correct'),(1,6,true,'correct')$q$);
SELECT pg_temp.expect_ok('[1.2 수정] 범위 안 유효 풀이를 다 채점하면 끝내기', $q$UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 끝난 채점 실행에 채점 추가 금지', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (1,1,true,'correct')$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 채점 실행은 finished_at 말고 수정 금지', $q$UPDATE sa_grading_runs SET grader_version='x' WHERE grading_run_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 채점 실행 삭제 금지', $q$DELETE FROM sa_grading_runs WHERE grading_run_id=1$q$);
SELECT pg_temp.expect_ok('재채점 = 새 채점 실행 (FR-SCR-08)', $q$INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose) VALUES (1,1,'grader-1.1','regrade')$q$);
SELECT pg_temp.expect_ok('재채점 결과는 따로 쌓임', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (2,1,true,'correct')$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 다른 실험의 풀이 채점 금지', $q$INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose) VALUES ((SELECT experiment_id FROM sa_experiments WHERE kind='diagnose'),1,'g','calibration'); INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES (currval(pg_get_serial_sequence('sa_grading_runs','grading_run_id')),2,true,'correct')$q$);

-- ------------------------------------------------------------------
-- 6. 채점 검증
-- ------------------------------------------------------------------
SELECT pg_temp.expect_ok('블라인드 라벨 (FR-VAL-01)', $q$INSERT INTO sa_labels(grading_run_id,trial_id,labeler_id,sampled_as,human_success) VALUES (1,1,2,'llm_judged',true)$q$);
SELECT pg_temp.expect_ok('이중 라벨은 다른 사람이 (FR-VAL-04)', $q$INSERT INTO sa_labels(grading_run_id,trial_id,labeler_id,sampled_as,human_success) VALUES (1,1,1,'llm_judged',true)$q$);
SELECT pg_temp.expect_fail('같은 사람이 같은 풀이를 두 번 라벨 금지', $q$INSERT INTO sa_labels(grading_run_id,trial_id,labeler_id,sampled_as,human_success) VALUES (1,1,2,'random',false)$q$);
SELECT pg_temp.expect_fail('블라인드가 아닌 라벨 금지', $q$INSERT INTO sa_labels(grading_run_id,trial_id,labeler_id,sampled_as,human_success,blind) VALUES (1,2,2,'random',false,false)$q$);
SELECT pg_temp.expect_fail('채점 오류율은 후보별 (FR-VAL-02)', $q$INSERT INTO sa_grader_checks(grading_run_id,kind,n,value,passed) VALUES (1,'error_rate',350,'{}',true)$q$);
SELECT pg_temp.expect_ok('후보별 채점 오류율', $q$INSERT INTO sa_grader_checks(grading_run_id,kind,experiment_candidate_id,n,value,passed) VALUES (1,'error_rate',1,350,'{"fs":0.02,"fs_upper":0.045}',true)$q$);
SELECT pg_temp.expect_fail('판정기 사전 확인은 질문 유형별 (FR-VAL-03)', $q$INSERT INTO sa_grader_checks(grading_run_id,kind,n,value,passed) VALUES (1,'judge_calibration',100,'{"kappa":0.75}',true)$q$);

-- ------------------------------------------------------------------
-- 7. 판정
-- ------------------------------------------------------------------
INSERT INTO sa_analyses(experiment_id, grading_run_id, method, code_version, input_hash)
VALUES (1, 1, '{"ci":"bootstrap_template_task_trial","correction":{"method":"holm","family":["B:success_rate"],"alpha":0.05},"seed":7}', 'git:abc1234 scipy-1.18', 'h-in-1');
SELECT pg_temp.expect_fail('[1.2 수정] 끝나지 않은 채점으로 분석 금지', $q$INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash) VALUES (1,2,'{"ci":"x","correction":{},"seed":1}','v','h')$q$);
SELECT pg_temp.expect_fail('중간 분석은 묶음 번호 필수', $q$INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash,is_interim) VALUES (1,1,'{"ci":"x","correction":{},"seed":1}','v','h',true)$q$);
SELECT pg_temp.expect_fail('분석은 신뢰구간·보정군·난수가 있어야 함 (재현성)', $q$INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash) VALUES (1,1,'{"ci":"x","seed":1}','v','h')$q$);
SELECT pg_temp.expect_fail('분석은 코드 버전·입력 해시 필수', $q$INSERT INTO sa_analyses(experiment_id,grading_run_id,method) VALUES (1,1,'{"ci":"x","correction":{},"seed":1}')$q$);
SELECT pg_temp.expect_ok('비교·판정', $q$INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,n_tasks,n_templates,regression_rate,verdict,reason,exclusions) VALUES (1,2,1,'success_rate',0.163,-0.012,0.402,0.975,46,11,0.022,'conditional','비용 개선','{"by_reason":{"grader_error":1},"by_candidate":{"B":1},"templates_left":11,"coverage":{"A":1,"B":1}}')$q$);
SELECT pg_temp.expect_fail('차이는 구간 안에 있어야 함', $q$INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,n_tasks,n_templates,exclusions) VALUES (1,2,1,'success_rate',0.5,0,0.4,0.95,46,11,'{"by_reason":{},"by_candidate":{},"templates_left":11,"coverage":{}}')$q$);
SELECT pg_temp.expect_fail('판단 보류면 추가 문항 수 필수 (FR-STA-05)', $q$INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,n_tasks,n_templates,exclusions,verdict) VALUES (1,2,1,'success_rate',0.02,-0.1,0.1,0.95,46,11,'hold','{"by_reason":{},"by_candidate":{},"templates_left":11,"coverage":{}}')$q$);
SELECT pg_temp.expect_fail('판정은 1차 지표에만', $q$INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,n_tasks,n_templates,exclusions,verdict) VALUES (1,2,1,'cost_per_success',-1,-2,0,0.95,46,11,'adopt','{"by_reason":{},"by_candidate":{},"templates_left":11,"coverage":{}}')$q$);
SELECT pg_temp.expect_fail('판정 4종 밖 금지', $q$INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,n_tasks,n_templates,exclusions,verdict) VALUES (1,2,1,'success_rate',0,-0.1,0.1,0.95,46,11,'maybe','{"by_reason":{},"by_candidate":{},"templates_left":11,"coverage":{}}')$q$);
SELECT pg_temp.expect_fail('판정은 불변', $q$UPDATE sa_comparisons SET verdict='adopt' WHERE comparison_id=1$q$);
SELECT pg_temp.expect_fail('[1.2 수정] 비교에는 제외 기록 필수', $q$INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,n_tasks,n_templates,exclusions) VALUES (1,2,1,'success_rate',0.1,0,0.2,0.95,46,11,'{"by_reason":{}}')$q$);

-- ------------------------------------------------------------------
-- 8. 결과 전달·운영
-- ------------------------------------------------------------------
SELECT pg_temp.expect_ok('한 장 요약서', $q$INSERT INTO sa_reports(experiment_id,analysis_id,kind,content,share_token_hash) VALUES (1,1,'one_pager','{}','tok1')$q$);
SELECT pg_temp.expect_fail('공유 토큰은 겹치지 않음', $q$INSERT INTO sa_reports(experiment_id,analysis_id,kind,content,share_token_hash) VALUES (1,1,'detail','{}','tok1')$q$);
SELECT pg_temp.expect_ok('공유 링크 만료 시각', $q$INSERT INTO sa_reports(experiment_id,analysis_id,kind,content,share_token_hash,share_expires_at) VALUES (1,1,'detail','{}','tok2',now()+interval '30 days')$q$);
SELECT pg_temp.expect_fail('공유 토큰 없이 만료 시각만은 금지', $q$INSERT INTO sa_reports(experiment_id,analysis_id,kind,content,share_expires_at) VALUES (1,1,'detail','{}',now())$q$);
SELECT pg_temp.expect_fail('chatbot 은 정해진 함수만 (FR-BOT-01)', $q$INSERT INTO sa_chat_messages(conversation_id,user_id,role,function_name) VALUES (gen_random_uuid(),1,'function','run_sql')$q$);
SELECT pg_temp.expect_fail('실행 함수는 사용자 확인 뒤에만 (FR-BOT-03)', $q$INSERT INTO sa_chat_messages(conversation_id,user_id,role,function_name,function_args) VALUES (gen_random_uuid(),1,'function','start_run','{}')$q$);
SELECT pg_temp.expect_ok('확인 받은 실행 함수', $q$INSERT INTO sa_chat_messages(conversation_id,user_id,role,function_name,user_confirmed) VALUES (gen_random_uuid(),1,'function','start_run',true)$q$);
SELECT pg_temp.expect_fail('대화 기록은 추가만', $q$DELETE FROM sa_chat_messages$q$);
SELECT pg_temp.expect_fail('검증 실험 종류는 E1~E6·카나리아만', $q$INSERT INTO sa_validation_runs(domain_code,kind) VALUES ('it_ops','E7')$q$);
SELECT pg_temp.expect_fail('끝난 검증 실험은 통과 여부 필수', $q$INSERT INTO sa_validation_runs(domain_code,kind,finished_at) VALUES ('it_ops','E3',now())$q$);
SELECT pg_temp.expect_ok('비용 장부', $q$INSERT INTO sa_cost_ledger(source,ref_id,experiment_id,model,in_tokens,out_tokens,cost_krw,price_setting_id) VALUES ('trial',1,1,'model-x',800,40,0.54,1)$q$);
SELECT pg_temp.expect_fail('비용 장부는 추가만', $q$UPDATE sa_cost_ledger SET cost_krw=0$q$);

-- ------------------------------------------------------------------
-- 9. 확장 지점: 8주 뒤 기능이 새 테이블 없이 들어올 수 있는지
-- ------------------------------------------------------------------
INSERT INTO sa_experiments(kind, agent_version_id, slot_id, pack_version_id, reps, prereg, plan, created_by) VALUES ('fix_effect', 1, 1, 1, 2, '{"tag":"fx","outcome_rules":{"out_of_scope":"fail"},"max_env_retries":1}', '{"tasks":[{"task_id":1}]}', 1);
SELECT pg_temp.expect_ok('[확장] 수정 효과 실험: 하나씩 뺀 구성을 variant 로 (OOS-07)', $q$INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,variant,config_snapshot,config_hash) VALUES ((SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='fx'),3,'C','baseline','{"fixes":["H","P","N"]}','{}','f0'),((SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='fx'),3,'C-noH','variant','{"fixes":["P","N"]}','{}','f1'),((SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='fx'),3,'C-noP','variant','{"fixes":["H","N"]}','{}','f2'),((SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='fx'),3,'C-noN','variant','{"fixes":["H","P"]}','{}','f3')$q$);
SELECT pg_temp.expect_ok('[확장] 변형이 많은 수정 효과 실험은 후보 수 제한 없이 잠금', $q$SELECT lock_experiment((SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='fx'))$q$);
SELECT pg_temp.expect_ok('[확장] 새 작업 종류는 kind 값만', $q$INSERT INTO sa_jobs(kind,payload) VALUES ('fix_recommend','{}')$q$);
SELECT pg_temp.expect_ok('[확장] 새 진단 지표는 metrics 키로', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,metrics) VALUES (2,2,true,'correct','{"plan_inclusion":null,"new_metric":0.3}')$q$);

-- ------------------------------------------------------------------
-- 10. [1.2 수정] 오류 풀이, 다시 실행, 채점 범위, 분석 단위
-- ------------------------------------------------------------------
-- 실험 X: 후보 A(기준)·B, 문항 1·2(묶음 1)·3(묶음 2), 반복 1, 환경 오류 다시 실행 2번까지
INSERT INTO sa_experiments(agent_version_id, slot_id, pack_version_id, reps, prereg, plan, created_by) VALUES
 (1, 1, 1, 1, '{"tag":"err","outcome_rules":{"out_of_scope":"fail"},"max_env_retries":2}',
  '{"tasks":[{"task_id":1,"batch_no":1},{"task_id":2,"batch_no":1},{"task_id":3,"batch_no":2}]}', 1);
CREATE TEMP VIEW x AS SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='err';
INSERT INTO sa_experiment_candidates(experiment_id, candidate_id, label, role, config_snapshot, config_hash)
SELECT experiment_id, 1, 'A', 'baseline', '{}'::jsonb, 'xA' FROM x UNION ALL SELECT experiment_id, 2, 'B', 'candidate', '{}', 'xB' FROM x;
SELECT lock_experiment((SELECT experiment_id FROM x));
-- 풀이 번호를 이름으로: a1 = 후보 A 문항 1 ...
CREATE TEMP VIEW xt AS
SELECT t.trial_id, ec.label || t.task_id AS k, t.run_no FROM sa_trials t JOIN sa_experiment_candidates ec ON ec.experiment_candidate_id = t.experiment_candidate_id
 WHERE t.experiment_id = (SELECT experiment_id FROM x);
UPDATE sa_trials SET status='running' WHERE experiment_id = (SELECT experiment_id FROM x) AND task_id IN (1, 2);
UPDATE sa_trials SET status='finished', run_outcome='completed' WHERE trial_id IN (SELECT trial_id FROM xt WHERE k IN ('A1','A2','B1'));
SELECT pg_temp.expect_ok('에이전트 시간 초과는 원인과 함께 오류로 끝냄', $q$UPDATE sa_trials SET status='error', run_outcome='timeout', outcome_reason='에이전트가 같은 조회를 반복' WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B2')$q$);
SELECT pg_temp.expect_fail('채점 범위 안에 대기 풀이가 있으면 채점 시작 불가', $q$INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose) VALUES ((SELECT experiment_id FROM x),1,'g','initial')$q$);
-- 문항 3 은 B 만 환경 오류, A 는 끝남
UPDATE sa_trials SET status='running' WHERE trial_id IN (SELECT trial_id FROM xt WHERE k IN ('A3','B3'));
UPDATE sa_trials SET status='finished', run_outcome='completed' WHERE trial_id=(SELECT trial_id FROM xt WHERE k='A3');
UPDATE sa_trials SET status='error', run_outcome='env_error', outcome_reason='연습 DB 연결 불가' WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3');
SELECT pg_temp.expect_fail('다시 실행은 바로 앞 번호가 있어야 함', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,batch_no,run_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,batch_no,3 FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3')$q$);
SELECT pg_temp.expect_fail('다시 실행해도 묶음 번호는 같아야 함', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,batch_no,run_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,1,2 FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3')$q$);
SELECT pg_temp.expect_ok('환경 오류 풀이는 새 행으로 다시 실행', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,batch_no,run_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,batch_no,2 FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=1)$q$);
SELECT pg_temp.expect_fail('같은 후보·문항·반복·실행 번호는 한 번만', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,batch_no,run_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,batch_no,2 FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=1)$q$);
SELECT pg_temp.expect_fail('실행 번호는 바꿀 수 없음', $q$UPDATE sa_trials SET run_no=5 WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=2)$q$);
UPDATE sa_trials SET status='running' WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=2);
UPDATE sa_trials SET status='error', run_outcome='env_error', outcome_reason='연습 DB 연결 불가' WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=2);
SELECT pg_temp.expect_ok('유효 풀이 뷰는 (후보, 문항, 반복)마다 마지막 실행 하나', $q$DO $d$ BEGIN IF (SELECT count(*) FROM sa_effective_trials WHERE experiment_id=(SELECT experiment_id FROM x)) <> 6 OR (SELECT run_no FROM sa_effective_trials WHERE experiment_id=(SELECT experiment_id FROM x) AND task_id=3 AND experiment_candidate_id=(SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=1))) <> 2 THEN RAISE EXCEPTION 'view'; END IF; END $d$$q$);

-- 채점: 묶음 1까지 먼저 (순차 검정 중간)
INSERT INTO sa_grading_runs(experiment_id, pack_version_id, grader_version, purpose, upto_batch_no) VALUES ((SELECT experiment_id FROM x), 1, 'g', 'initial', 1);
CREATE TEMP VIEW xg AS SELECT max(grading_run_id) AS grading_run_id FROM sa_grading_runs WHERE experiment_id = (SELECT experiment_id FROM x);
SELECT pg_temp.expect_fail('채점 범위 밖 풀이 채점 금지', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES ((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='A3'),true,'correct')$q$);
SELECT pg_temp.expect_fail('시간 초과 풀이는 성공 불가', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES ((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='B2'),true,'correct')$q$);
SELECT pg_temp.expect_ok('시간 초과 풀이는 첫 실패 유형 없이 실패로', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES ((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='B2'),false,'ask_or_giveup')$q$);
SELECT pg_temp.expect_fail('끝까지 실행한 풀이의 실패는 첫 실패 유형 필수', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES ((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='A1'),false,'wrong_assertion')$q$);
SELECT pg_temp.expect_ok('묶음 1 채점', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,judge_status) VALUES ((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='A1'),true,'correct','ok'),((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='B1'),true,'correct','undecidable'),((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='A2'),true,'correct','ok')$q$);
UPDATE sa_grading_runs SET finished_at = now() WHERE grading_run_id = (SELECT grading_run_id FROM xg);
SELECT pg_temp.expect_fail('중간 분석 묶음은 채점 범위 안만', $q$INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash,is_interim,batch_no) VALUES ((SELECT experiment_id FROM x),(SELECT grading_run_id FROM xg),'{"ci":"x","correction":{},"seed":1}','v','h',true,2)$q$);
SELECT pg_temp.expect_ok('중간 분석 (묶음 1)', $q$INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash,is_interim,batch_no) VALUES ((SELECT experiment_id FROM x),(SELECT grading_run_id FROM xg),'{"ci":"x","correction":{},"seed":1}','v','h',true,1)$q$);
-- 분석 단위 (묶음 1): 문항 1 = B 판정 불가로 제외, 문항 2 = 포함 (B 시간 초과는 실패로 셈)
SELECT pg_temp.expect_ok('분석 단위: 판정 불가는 쌍에서 함께 제외, 시간 초과는 포함', $q$DO $d$ DECLARE r text; BEGIN
  SELECT string_agg(task_id || ':' || coalesce(exclude_reason, 'in'), ',' ORDER BY task_id) INTO r
    FROM analysis_units((SELECT grading_run_id FROM xg), (SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B1')));
  IF r <> '1:undecidable,2:in' THEN RAISE EXCEPTION '%', r; END IF; END $d$$q$);

-- 전체 채점: 묶음 2 의 B3 은 끝까지 환경 오류 → 채점 행 없음, 분석에서 쌍째 제외
INSERT INTO sa_grading_runs(experiment_id, pack_version_id, grader_version, purpose) VALUES ((SELECT experiment_id FROM x), 1, 'g', 'regrade');
SELECT pg_temp.expect_fail('채점 범위에 든 묶음은 다시 실행 불가 (횟수가 남아도)', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,batch_no,run_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,batch_no,3 FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B3' AND run_no=2)$q$);
SELECT pg_temp.expect_fail('환경 오류 풀이는 채점 행 금지', $q$INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class) VALUES ((SELECT grading_run_id FROM xg),(SELECT trial_id FROM xt WHERE k='B3' AND run_no=2),false,'ask_or_giveup')$q$);
INSERT INTO sa_trial_grades(grading_run_id, trial_id, success, result_class)
SELECT (SELECT grading_run_id FROM xg), trial_id, true, 'correct' FROM xt WHERE k IN ('A1','B1','A2','A3');
INSERT INTO sa_trial_grades(grading_run_id, trial_id, success, result_class) VALUES ((SELECT grading_run_id FROM xg), (SELECT trial_id FROM xt WHERE k='B2'), false, 'ask_or_giveup');
SELECT pg_temp.expect_ok('환경 오류만 남으면 채점을 끝낼 수 있음', $q$UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=(SELECT grading_run_id FROM xg)$q$);
SELECT pg_temp.expect_ok('분석 단위: 환경 오류는 쌍에서 함께 제외', $q$DO $d$ DECLARE r text; BEGIN
  SELECT string_agg(task_id || ':' || coalesce(exclude_reason, 'in'), ',' ORDER BY task_id) INTO r
    FROM analysis_units((SELECT grading_run_id FROM xg), (SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xt WHERE k='B1')));
  IF r <> '1:in,2:in,3:env_error' THEN RAISE EXCEPTION '%', r; END IF; END $d$$q$);
SELECT pg_temp.expect_fail('판정기 맞춰 보기 채점으로는 분석 금지', $q$INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose) VALUES ((SELECT experiment_id FROM x),1,'g','calibration'); UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=currval(pg_get_serial_sequence('sa_grading_runs','grading_run_id')); INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash) VALUES ((SELECT experiment_id FROM x),currval(pg_get_serial_sequence('sa_grading_runs','grading_run_id')),'{"ci":"x","correction":{},"seed":1}','v','h')$q$);

-- 일찍 멈춘 실험: 남은 대기 풀이는 취소, 채점은 끝난 묶음까지
INSERT INTO sa_experiments(agent_version_id, slot_id, pack_version_id, reps, prereg, plan, created_by) VALUES
 (1, 1, 1, 1, '{"tag":"stop","outcome_rules":{},"max_env_retries":0}',
  '{"tasks":[{"task_id":1,"batch_no":1},{"task_id":3,"batch_no":2}]}', 1);
CREATE TEMP VIEW xs AS SELECT experiment_id FROM sa_experiments WHERE prereg->>'tag'='stop';
INSERT INTO sa_experiment_candidates(experiment_id, candidate_id, label, role, config_snapshot, config_hash)
SELECT experiment_id, 1, 'A', 'baseline', '{}'::jsonb, 'sA' FROM xs UNION ALL SELECT experiment_id, 2, 'B', 'candidate', '{}', 'sB' FROM xs;
SELECT lock_experiment((SELECT experiment_id FROM xs));
UPDATE sa_trials SET status='running' WHERE experiment_id=(SELECT experiment_id FROM xs) AND batch_no=1;
CREATE TEMP VIEW xst AS SELECT t.trial_id, ec.label || t.task_id AS k FROM sa_trials t JOIN sa_experiment_candidates ec ON ec.experiment_candidate_id = t.experiment_candidate_id WHERE t.experiment_id = (SELECT experiment_id FROM xs);
UPDATE sa_trials SET status='finished', run_outcome='completed' WHERE trial_id=(SELECT trial_id FROM xst WHERE k='A1');
UPDATE sa_trials SET status='error', run_outcome='env_error', outcome_reason='가짜 도구 서버 장애' WHERE trial_id=(SELECT trial_id FROM xst WHERE k='B1');
SELECT pg_temp.expect_fail('다시 실행은 max_env_retries 까지 (0 이면 다시 실행 없음)', $q$INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,batch_no,run_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,batch_no,2 FROM sa_trials WHERE trial_id=(SELECT trial_id FROM xst WHERE k='B1')$q$);
SELECT pg_temp.expect_fail('실행 중인 실험의 풀이는 취소 불가', $q$UPDATE sa_trials SET status='cancelled' WHERE experiment_id=(SELECT experiment_id FROM xs) AND batch_no=2$q$);
UPDATE sa_experiments SET status='stopped', stop_reason='일찍 멈춤: 묶음 1에서 경계 넘음' WHERE experiment_id=(SELECT experiment_id FROM xs);
SELECT pg_temp.expect_ok('멈춘 실험의 대기 풀이는 취소', $q$UPDATE sa_trials SET status='cancelled' WHERE experiment_id=(SELECT experiment_id FROM xs) AND batch_no=2$q$);
SELECT pg_temp.expect_fail('취소한 풀이가 범위에 있으면 전체 채점 불가', $q$INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose) VALUES ((SELECT experiment_id FROM xs),1,'g','initial')$q$);
SELECT pg_temp.expect_ok('멈춘 실험은 끝난 묶음까지 채점', $q$INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose,upto_batch_no) VALUES ((SELECT experiment_id FROM xs),1,'g','initial',1)$q$);
SELECT pg_temp.expect_fail('취소한 풀이는 바꿀 수 없음', $q$UPDATE sa_trials SET status='running' WHERE experiment_id=(SELECT experiment_id FROM xs) AND batch_no=2$q$);
