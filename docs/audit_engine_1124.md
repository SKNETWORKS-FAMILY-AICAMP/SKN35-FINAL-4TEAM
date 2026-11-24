# ① 실행 엔진 점검 — 2026-11-24

## 1. 결론 3줄

1. 다음 기능 개발은 이어갈 수 있지만 배포 가능한 상태로 판정하지 않습니다. 같은 완료 통지로 분석·리포트 작업이 각각 두 벌 생성되는 경로를 각각 5/5회 재현했습니다.
2. Windows 전체 5회 중 1회에서 결과가 달랐고 최종 attempt 비교 제거도 검출되지 않았습니다. Linux 전체·Linux 호스트 Docker는 못 했으며, 외부 병합 후 Ruff 11건/형식 28개가 걸렸습니다.
3. 제품 코드·계약·마이그레이션·기존 테스트는 고치지 않았습니다. 이 점검의 저장소 쓰기는 이 보고서 하나이며 커밋하지 않았습니다. 아래 숫자는 지정한 입력·횟수의 관찰이며 안전성 보장이 아닙니다.

### 시작 기준·실행 방식


시작 HEAD: e1fcd32438efae601721d78573f8fb502720a2a0 / taemin. 시작 미커밋 9개:


```text
 M backend/src/slotagent/common/queue.py
 M backend/src/slotagent/engine/eng_stdio.py
 M backend/src/slotagent/engine/worker.py
 M backend/src/slotagent/workers/eng_main.py
 M backend/tests/eng_stdio_server.py
 M docs/checklist.md
 M docs/handoff.md
?? backend/src/slotagent/engine/eng_docker.py
?? backend/tests/test_eng_docker.py
```


시작 작업 트리를 저장소 밖 임시 복사본으로 동결했습니다. 그 뒤 외부 작업에서 dev → taemin 병합 커밋 8d296d6ed540703eaef46b1b87a669351c821f7f가 생겼습니다. 이 점검은 commit/merge/checkout/fetch를 실행하지 않았습니다. 시작 스냅샷의 반복·변이 결과와 병합 후 추가 회귀를 구분합니다. 기록 시 HEAD: 8d296d6ed540703eaef46b1b87a669351c821f7f.

기존 backend .venv의 Python 3.12를 사용하고 모든 pytest를 복사본에서 실행했습니다. 임시 PostgreSQL(pgserver), FakeModel/SDK mock만 사용했습니다. 개발 DB 및 final_project_postgres_data는 접속·수정하지 않았습니다. 변이·전체 반복의 Python socket.connect는 loopback 외 차단했고 Docker는 로컬 python:3.12-slim 캐시로만 시험 이미지를 만들었습니다. 소켓 마운트·prune·실제 모델 API·패키지 다운로드를 하지 않았습니다.

전체 명령 형태: 복사본 backend에서 python -m pytest <전체 test_*.py 목록> -p audit_network_guard -p no:cacheprovider --basetemp <전용 임시 경로> --junitxml <임시 로그> -ra --tb=short. audit_network_guard는 외부 연결만 차단합니다. 파일 순서는 1~3회 정렬, 4~5회 random.Random(1124), random.Random(20261124) shuffle입니다. 다른 점검 부하도 있어 순서와 부하의 영향을 분리한 실험은 아닙니다.


| Windows 전체 회차 | 결과 | 실행기 경과 초 | 순서 |
|---|---|---|---|
| baseline1 | 367 passed / 0 failed / 0 skipped | 138.45 | 정렬 |
| baseline2 | 367 passed / 0 failed / 0 skipped | 112.58 | 정렬 |
| baseline3 | 367 passed / 0 failed / 0 skipped | 149.95 | 정렬 |
| baseline4 | 367 passed / 0 failed / 0 skipped | 121.97 | shuffle 1124 |
| baseline5 | 366 passed / 1 failed / 0 skipped | 156.77 | shuffle 20261124 |


5회차 실패는 호출 전에 session(timeout_sec=0.5)의 초기화 tools/list가 deadline을 넘긴 것입니다. 원본 함수를 바꾸지 않고 추가 20회 반복해 1 failed/19 passed(48.51초), index=18에서 같은 지점을 재현했습니다. 원문:


```text
FAILED tests/test_eng_stdio.py::test_call_failure_is_saved[call_timeout-env_mcp_server_down]
1 failed, 366 passed in 142.79s (0:02:22)
```


병합 후 새 복사본의 전체 회귀: 486개 수집, 483 passed / 2 failed / 1 skipped (309.49초). 두 실패는 같은 함수 exit/call_timeout 매개변수의 초기화 시간 초과입니다. skip 1건은 test_pack_loader.py:68의 Explicit local DB opt-in required이며 개발 DB 사용 금지에 따라 켜지 않았습니다. 새 계약에 전체 변이를 다시 적용한 결과는 아닙니다.

시작 스냅샷 전체 Ruff check: 오류 0. format --check: exit 1, 13 files would be reformatted, 49 files already formatted. --check만 실행했습니다.

Linux 전체: 못 했음. 네트워크 없는 로컬 python:3.12-slim에서 python -m pytest --version → /usr/local/bin/python: No module named pytest(exit 1). 테스트 수·skip 수를 산출하지 못했습니다. 외부 네트워크 금지에 따라 의존성을 설치하지 않았으며 이전 작업의 Linux 346 passed를 이번 결과로 재사용하지 않습니다.

병합 후 추가 검사: Ruff check 11건(exit 1), format --check 28 files would be reformatted / 51 files already formatted(exit 1). 아래는 새 스냅샷에서 나온 지적이며 시작 스냅샷의 Ruff 0건·형식 13개와 구분합니다.

| 코드 | 새 스냅샷 파일:줄 | 메시지 |
|---|---|---|
| I001 | tests\test_confirmation.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_conflicts.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_deployment.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_incidents.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_independent.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_loader.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_metrics.py:3 | Import block is un-sorted or un-formatted |
| F401 | tests\test_pack_metrics.py:5 | `json` imported but unused |
| I001 | tests\test_pack_reliability.py:3 | Import block is un-sorted or un-formatted |
| I001 | tests\test_pack_workflows.py:3 | Import block is un-sorted or un-formatted |
| F401 | tests\test_pack_workflows.py:5 | `json` imported but unused |




## 2. 문제 표

### 직접 재현한 것

| ID | 심각도 | 무엇 | 재현 방법 | 횟수 | 시작 스냅샷 위치 | 고칠 방향 |
|---|---|---|---|---|---|---|
| A1 | 심각 — 작업 중복 생성 | 완료 통지 재전달 시 analyze/report 작업이 각각 2개 | 임시 실험 두 trial을 env_error로 완료 → initial grading_run.finished_at 기록 → 같은 gr로 on_grading_finished 두 번. finished gr로 analysis 생성 후 on_analysis_done 두 번. 같은 참조의 sa_jobs count 확인 | analyze 5/5, report 5/5, 매번 2개. downstream 실제 중복 실행·이중 과금은 안 함 | backend/src/slotagent/engine/advance.py:221, :232, enqueue :143 | 완료 이벤트별 멱등 키·원자적 enqueue/상태 검사. 필요한 DB·계약 합의는 별도. initial grade 중복 방지와는 다른 문제 |
| A2 | 심각 — 독립 실행 경로 갇힘 | job 없는 run_trial에서 DB 단절 후 running(1), 비용 0, 회수 job 없음 | 가짜 chat이 Reply를 만든 뒤 conn.close()하고 반환. 비용 저장 및 _release_attempt가 닫힌 연결로 실패 | 1/1, CostPersistenceError. 큐를 쓰는 run_once 경로와 구분 | engine/worker.py:30, :101, :122; engine/costs.py:16 | 운영 실행 job 필수화 또는 독립 실행용 복구 토큰/정리 경로. 비용 첫 커밋 전 유실은 별도 영속 수신 정책 |
| A3 | 보통 — 입력·분류 | 2**63 토큰이 어댑터/trace에서 허용되어 비용 DB 오류로 재시도 | _tokens(2**63) 허용 직접 확인. FakeModel Reply(in_tokens=2**63,out_tokens=1)로 같은 job을 run_once 3회 | 시나리오 1개/3시도 모두 CostPersistenceError. job failed/3, trial pending/4, 비용 0행 | common/llm.py:159, engine/tracing.py:39, engine/costs.py:16 | 저장 가능한 사용량 범위 검사, 비정상 사용량의 영구 오류 분류 검토. 미매핑 소진 pending 정책 자체는 기존 미완료 항목 |
| A4 | 보통 — 대기 상한 | 기본 lock_timeout/statement_timeout이 0/0, 외부 잠금에서 대기 | 다른 연결의 experiment FOR UPDATE 유지 → 워커 → pg_stat_clear_snapshot 후 Lock/transactionid 확인, 이후 1.2초 유지 → kill/해제/reclaim | 5/5. 시작 포함 2.77~3.27초 관찰. 무기한 실측 아님 | engine/worker.py:53, :193; common/queue.py:55; common/db.py:52 | 워커 세션의 SQL lock/statement 상한, 오류 후 기존 회수 경로 검토 |
| A5 | 낮음 — 검사 불안정 | 0.5초 초기화 제한의 기존 검사 간헐 실패 | 전체 5회, 동일 함수 20회 추가 | 전체 1/5, 함수 1/20. 병합 후 전체도 동일 함수 2매개변수 실패 | tests/test_eng_stdio.py:252; engine/eng_stdio.py:325, :446 | 준비 시간과 호출 실패 검사를 분리할지 검토. 이번에 기대값·상한을 바꾸지 않음 |
| A6 | 낮음 — 형식 | 기존 파일 13개가 format --check 불일치 | 기존 Ruff의 전체 format --check | 1/1 | 아래 목록 | 별도 정리. 다른 역할 파일 포함이므로 이번에 수정 안 함 |

형식 불일치 파일:


- src\slotagent\api\eng_errors.py:9:1
- src\slotagent\api\eng_plan_proposal.py:6:1
- src\slotagent\common\checks.py:18:1
- src\slotagent\common\contracts.py:9:1
- src\slotagent\common\hashing.py:9:1
- src\slotagent\common\proposal.py:12:1
- src\slotagent\common\snapshot.py:22:1
- src\slotagent\engine\advance.py:28:1
- src\slotagent\intake\service.py:2:1
- src\slotagent\workers\registry.py:2:1
- tests\test_contracts.py:2:1
- tests\test_eng_stdio.py:553:23
- tests\test_handoff_e2e.py:9:1


### 코드만 보고 의심한 것

| 심각도 | 의심·근거 | 재현 여부 | 위치·고칠 방향 |
|---|---|---|---|
| 심각 가능 — 장기 갇힘 | 외부 잠금을 계속 잡으면 main이 job 잠금을 가진 채 experiment를 기다리고 heartbeat도 job 잠금을 기다릴 수 있음. reclaim은 잠긴 job을 SKIP LOCKED로 건너뜀 | A4의 짧은 대기는 관찰. 무기한 상태는 재현 안 함 | queue.py:55/:74/:138, worker.py:53. SQL 상한·취소·회수 순서와 실제 운영 DB 설정 확인 |
| 보통 가능 — bind TOCTOU | start 직전 검사와 daemon bind 사이의 호스트 경로 교체 | 새 공격 재현 안 함. 사용자가 이미 허용한 한계이며 신규 문제에 포함 안 함 | eng_docker.py:52/:350. 신뢰한 관리자만 바꾸는 데이터 전용 루트 사용 |

### 이미 아는 문제 — AGENTS.md 9번, 신규 문제로 세지 않음

1. span.error 도구 실패 코드 계약 합의: 시작 스냅샷은 원문을 error/tool_result에 저장. 이번에 변경 안 함.
2. ② servers.json/팩 로더 연계 대기: 시작 기록 기준. 외부 병합으로 pack 파일이 들어왔으나 이 점검이 병합·연계하지 않음.
3. ② 실제 P-03 서버·데이터 버전·sa_env_checks 연결 대기. 시험 서버로만 검사.
4. P-05 가짜 승인/거절·write_proxy 연계 대기.
5. ② trace·환경 오류·시간 초과 집계 합의. 실제 통계·채점 완료로 쓰지 않음.

checklist의 미매핑 소진 pending 정리·실험 종료 게이트·배포 반복 진입점도 이미 미완료로 적힌 항목입니다. 허용 루트 내부 내용(.env 등) 미검사, 컨테이너 워커 bind 거절/volume 필요, Linux 호스트 Docker 미검증도 기존 합의한 한계입니다.

A1 최소 재현 순서: 기존 experiment/engine_db 픽스처 사용 → dependencies(tool=ToolEnvironmentError를 내는 함수)로 두 trial을 run_trial → 생성된 gr의 finished_at=now() → advance.on_grading_finished(conn,gr)를 두 번 → sa_jobs WHERE kind=analyze AND payload.grading_run_id=gr의 count=2. 이어 method={ci:{},correction:{},seed:1124}, code_version=audit, input_hash='a'*64로 그 finished gr의 sa_analyses를 만들고 on_analysis_done 두 번 → 같은 analysis_id의 report job count=2. 실제 핸들러는 호출하지 않습니다.

## 3. 보호 장치를 망가뜨린 결과

시작 스냅샷의 별도 복사본에서 변이를 한 번에 하나만 적용하고 복원했습니다. 기존 테스트·기대값은 그대로입니다. 각 행은 전체 367개 검사입니다. retry_limit은 한 프로세스, 이후에는 파일 4묶음의 합계이며 마지막 두 재검사는 다시 단일 전체 실행입니다.

첫 임대 변이의 %s IS NOT NULL은 PostgreSQL의 파라미터 자료형을 결정할 수 없어 유효한 검출 증거에서 제외했습니다. %s::text IS NOT NULL로 보완한 재검사만 최종 근거로 씁니다. 실행기 전환 중 중단한 회차도 제외합니다. 초기화 간헐 실패만 있으면 해당 변이를 잡은 것으로 세지 않습니다.


| 망가뜨린 것 | 판정 | 잡은 테스트/빈틈 | 전체 결과 |
|---|---|---|---|
| 재시도 상한 제거 | 검출 | test_transient_error_stops_at_max_attempts | 361 passed / 6 failed / 0 skipped; 149.31s |
| 임대 attempts/leased_by 비교 제거(유효 SQL) | 검출 | test_priority_skip_locked_and_tokens | 366 passed / 1 failed / 0 skipped; 110.98s |
| 최종 current attempt 비교 제거 | 빈틈 | 전체 통과 | 367 passed / 0 failed / 0 skipped; 101.80s |
| 비용 ON CONFLICT 제거 | 검출 | test_identical_receipt_concurrently_commits_once | 328 passed / 39 failed / 0 skipped; 138.64s |
| 최종 transaction을 nullcontext로 변경 | 검출 | test_queue_completion_failure_rolls_back_results_and_keeps_costs | 343 passed / 24 failed / 0 skipped; 121.05s |
| 완료 trial 조기 반환 제거 | 검출 | test_trial_read_and_atomic_storage_and_single_grading_handoff | 363 passed / 4 failed / 0 skipped; 113.12s |
| 수동 재개 job FOR UPDATE 제거 | 검출 | test_resume_concurrently_once | 366 passed / 1 failed / 0 skipped; 88.70s |
| initial grading ON CONFLICT 제거 | 검출 | test_4_lock_and_run | 362 passed / 5 failed / 0 skipped; 95.22s |
| spent>=budget 차단 제거 | 검출 | test_budget_exhaustion_does_not_call_model | 363 passed / 4 failed / 0 skipped; 103.70s |
| MCP response id 비교 제거 | 검출 | test_bad_response_closes_session[wrong_id] | 366 passed / 1 failed / 0 skipped; 96.97s |
| MCP 스키마 완전 비교 제거 | 검출 | test_tool_inventory_rejected[schema] | 364 passed / 3 failed / 0 skipped; 79.17s |
| MCP deadline 5초 지연 | 검출 | test_initialize_timeout | 363 passed / 4 failed / 0 skipped; 93.28s |
| Job 전체 대신 직접 프로세스만 종료 | 검출 | test_process_tree_close | 360 passed / 7 failed / 0 skipped; 82.84s |
| none을 없는 네트워크로 변경 | 검출 | test_linux_docker_argv_without_docker[128-1-64] | 355 passed / 12 failed / 0 skipped; 66.48s |
| --read-only 제거 | 검출 | test_linux_docker_argv_without_docker[128-1-64] | 364 passed / 3 failed / 0 skipped; 81.23s |
| --user 제거 | 검출 | test_linux_docker_argv_without_docker[128-1-64] | 365 passed / 2 failed / 0 skipped; 82.20s |
| --cap-drop ALL 제거 | 검출 | test_linux_docker_argv_without_docker[128-1-64] | 365 passed / 2 failed / 0 skipped; 80.56s |
| pids 상한을 0으로 변경 | 검출 | test_linux_docker_argv_without_docker[128-1-64] | 364 passed / 3 failed / 0 skipped; 80.34s |
| 현재 임대 컨테이너도 삭제 | 검출 | test_docker_reclaim_preserves_current_db_lease | 366 passed / 1 failed / 0 skipped; 84.08s |
| bind 루트 포함 비교 제거 | 검출 | test_bind_sibling_prefix_rejected | 365 passed / 2 failed / 0 skipped; 80.20s |
| isError를 환경 오류로 처리 | 검출 | test_iserror_then_success_and_trace | 365 passed / 2 failed / 0 skipped; 77.19s |



network 변이는 외부 접속을 열지 않도록 존재하지 않는 네트워크로 변경했습니다. argv의 none 검사·시작 실패 검출이며 bridge로 외부 접속하는 검사는 안 했습니다. 시간 변이도 무한 대기 대신 5초 늦게 적용했습니다. 최종 attempt 비교만 없앤 상태에서 검출되지 않더라도 앞선 취소·임대 펜싱은 남아 있습니다. 실제 stale 저장 재현과 최종 저장 경계 단독 검사 부족을 구분해야 합니다.

## 4. 강제 종료·동시 실행·나쁜 입력·연속 실행

### 강제 종료

FakeModel의 두 Reply는 in/out=(100,10),(120,12), 비용 0.120/0.144원입니다. run_once heartbeat=0.1초, Docker timeout=10초. gate를 확인한 뒤 워커 kill, 해당 임시 DB lease_until을 과거로 바꿔 다음 run_once가 reclaim하게 했습니다. 운영 기본 임대 600초를 실제로 기다린 것은 아닙니다.

처음 40회에 더해 실제 worker/실행기/CLI 자손 PID를 열거·종료 확인하는 40회를 재실행했습니다. 아래는 최종 40회만입니다. 최종 pytest 40 passed, 실패/skip 0, 343.43초.


| 시점 | 횟수 | 확인 실패 | 합계 초 | 이전 커밋 비용행 | 커밋 전 잃은 응답 | 최대 job attempts | 회수 후 컨테이너/PID |
|---|---|---|---|---|---|---|---|
| leased | 5 | 0 | 26.77 | [0] | 0 | 2 | 0/0 |
| container_start | 5 | 0 | 28.22 | [0] | 0 | 2 | 0/0 |
| model_pre_cost | 5 | 0 | 35.14 | [0] | 5 | 2 | 0/0 |
| model_post_cost | 5 | 0 | 35.53 | [1] | 0 | 2 | 0/0 |
| tool | 5 | 0 | 38.59 | [1] | 0 | 2 | 0/0 |
| final_before | 5 | 0 | 46.84 | [2] | 0 | 2 | 0/0 |
| final_after | 5 | 0 | 44.16 | [2] | 0 | 2 | 0/0 |
| cleanup | 5 | 0 | 40.75 | [2] | 0 | 2 | 0/0 |



- leased: queue.lease 커밋 직후, trial 실행 전.
- container_start: initialize가 stdin에 전송된 뒤 init_timeout 서버 응답 대기. create/pull 내부 모든 단계를 탐색한 것은 아님.
- model_pre_cost: FakeModel이 Reply를 만들고 audit 이벤트를 쓴 뒤, 루프에 반환하기 전. 5회에서 응답 1건씩 총 5건 유실. 원격 API 실과금 측정 아님.
- model_post_cost: 첫 응답 비용 커밋 후 on_model_span. 보존 1행 + 새 시도 2행 = 최종 3행.
- tool: tools/call 전송 후 call_timeout 대기.
- final_before: trial_id/attempt가 들어간 trace 검사 후 최종 transaction 시작 직전.
- final_after: 결과·span 쓰기 후 queue.finish 직전. 같은 transaction의 커밋 전이므로 결과는 롤백되고 비용 2행은 보존. 결과만 커밋된 뒤 job 미완료인 독립 구간은 현재 구현에 없음.
- cleanup: 첫 docker rm 확인 후 나머지 close가 끝나기 전. 모든 정리 명령 중단 지점을 탐색한 것은 아님.

매회 이전 비용행+2=최종 비용행, span seq 중복 없음, 해당 trial finished, run_once 성공, attempts≤3, scoped container 0을 확인했습니다. 최종 40회는 kill 전 열거한 실제 PID들도 wait_dead(timeout=4)로 확인했습니다. jobs 최종 status의 시점별 별도 집계 열은 없으며 run_once 성공과 결과·queue.finish 원자성 및 기존 test_docker_worker_kill_reclaim의 done 검사도 근거입니다.

### 워커 4개 × 풀이 100개 × 시드 3개

실제 lock_experiment로 만든 계획 trial을 사용했습니다. 첫 시도 일부를 Random(seed+trial_id*71+attempt)로 약 15% 실패시키고 응답 전 0~0.01초/실패 전 0~0.03초 지연을 넣었습니다. 재현에는 DB 생성 ID·fixture 순서도 영향을 줍니다. 실패는 응답 생성 전이며 임대 상실·강제 종료 비용은 별도 실험입니다.


| 시드 | 완료/갇힌 trial | 일시 실패 | max attempts | 응답/장부 행 | Reply 비용/장부 합계 | 중복 임대키/교착 | span/initial grading_run | 초 |
|---|---|---|---|---|---|---|---|---|
| 1124 | 100/0 | 22 | 2 | 200/200 | 26.400/26.400 | 0/0 | 300/1 | 7.39 |
| 20261124 | 100/0 | 17 | 2 | 200/200 | 26.400/26.400 | 0/0 | 300/1 | 7.61 |
| 8675309 | 100/0 | 18 | 2 | 200/200 | 26.400/26.400 | 0/0 | 300/1 | 10.20 |



(trial_id, attempts) 임대키 중복 0, 최종 trace 3 span×100=300, 장부 200건/26.400원을 확인했습니다. initial grading_run은 직접 1개 집계했습니다. 이 전용 집계에는 grade sa_jobs 수를 따로 넣지 않았고 기존 test_trial_read_and_atomic_storage_and_single_grading_handoff·test_parallel_completions_create_one_grading_job의 job 1개 검증을 함께 근거로 둡니다.


| 경합 | 횟수 | 불변조건 위반 | 관찰 |
|---|---|---|---|
| 같은 trial 재개 20개 동시 호출 | 20 | 0 | resumed=1, queued job=1 |
| 회수/연장 만료 경계 | 20 | 0 | expired renew 거절, queued/failed 회수. 독립 반복을 위해 매회 임시 job attempts=0 초기화 |
| 실험 중단/최종 저장 직전 | 5 | 0 | 모두 RunCancelled, trial cancelled, span 0 |
| 마지막 두 trial 동시 완료 | 5 | 0 | initial grading_run=1, 장부 4행/0.528원 |
| 동일 완료 통지 두 번 | 5 | 5 | analyze=2 및 report=2; A1로 기록 |


모델 첫 응답 직후의 중단도 별도 5회 실행했습니다. 회수/연장 20회의 합산 attempts를 운영 재시도 상한 검증으로 쓰지 않습니다.

### 나쁜 입력


| MCP 입력 | 횟수 | 결과 | 초 |
|---|---|---|---|
| fragmented | 1 | accepted | 0.359 |
| truncated | 1 | ToolEnvironmentError | 0.203 |
| deep | 1 | ToolEnvironmentError | 0.219 |
| size1048575 | 1 | accepted | 0.188 |
| size1048576 | 1 | accepted | 0.235 |
| size1048577 | 1 | ToolEnvironmentError | 0.203 |
| utf8 | 1 | ToolEnvironmentError | 0.234 |
| notify127 | 1 | accepted | 0.266 |
| notify128 | 1 | ToolEnvironmentError | 0.187 |
| notify129 | 1 | ToolEnvironmentError | 0.219 |
| duplicate | 1 | accepted → 두 번째 ToolEnvironmentError | 0.282 |
| late | 1 | ToolEnvironmentError | 0.266 |
| slow | 1 | ToolEnvironmentError | 0.672 |


크기는 newline 포함 실제 bytes. 깊이는 2,000. 알림 127개+응답=총 128 메시지는 허용, 알림 128/129개 뒤 응답은 상한 초과. fragment는 0.001초/byte, slow는 0.1초/byte 및 호출 timeout 0.4초. duplicate는 같은 id 응답 두 개 후 다음 호출에서 옛 id를 거절하는지 확인했습니다. 모든 client close 후 직접 프로세스 종료를 확인했습니다.


실행 수·실패 수·시간 요약(스크립트 성공과 문제 미발견은 다릅니다):

| 검사 | 입력/횟수 | 스크립트 실패 | 경과 초 |
|---|---|---|---|
| 강제 종료 PID 확인 | 8시점×5회 | 0 | 343.43 |
| 4프로세스×100개 | 3시드 | 0 | 25.202 |
| 동시 재개 | 20호출 | 0 | 1.109 |
| 회수/연장 | 20회 | 0 | 2.719 |
| 중단/최종 저장 | 5회 | 0 | 1.508 |
| 마지막 두 풀이 동시 완료 | 5회 | 0 | 1.764 |
| 나쁜 MCP/모델/DB·자원·비밀값 | 25사례 | 0 | 38.51; A2/A3 발견 포함 |
| 기본 DB 대기/완료 통지 중복 | 각 5회 | 0 | 37.34; 중복 위반은 5/5 |
| 연속 실행 | 200개, Docker 20개 | 0 | 69.72 |


| 모델 입력 | 횟수 | 결과 | 모델 호출 수 |
|---|---|---|---|
| unknown | 1 | completed | 2 |
| wrong_args | 1 | completed | 2 |
| repeat | 1 | agent_error / agent_max_steps | 3 |
| empty | 1 | completed | 1 |
| negative | 1 | ContractError | 1 |
| nan | 1 | TypeError | 1 |
| huge | 1 | completed | 1 |


없는 도구·잘못된 인자는 피드백 후 두 번째 Reply로 완료, 반복은 max_steps=6, 빈 답은 completed였습니다. 빈 답 허용을 채점 성공으로 해석하지 않습니다. negative/NaN은 계약 오류. huge=2**63은 루프에서 completed여서 A3의 실제 워커 검사로 이어갔습니다.


| Docker/DB 입력 | 횟수 | 결과 |
|---|---|---|
| oom | 1 | exit=137, stdout=(없음), 1.422s |
| pids | 1 | exit=0, stdout=PIDS_BLOCKED 11, 3.062s |
| cost_disconnect | 1 | CostPersistenceError / running(1), cost 0, job 없음 |
| lock_timeout | 1 | LockNotAvailable / 0.110s, 테스트 lock_timeout=100ms |


OOM: memory/memory-swap=32MiB에 bytearray(256MiB) → exit 137. pids: 상한 12, 메모리·CPU·네트워크 제한 유지 컨테이너 안에서만 최대 fork 100회 시도 → errno 11, 자식 wait 후 exit 0. 호스트 fork 폭주는 안 했습니다. 이미지 없음·즉시 종료·초기화 무응답은 기존 Docker 전체 테스트에 포함됐습니다.

### 200개 연속 실행 — 실제 Docker 20개


| 시점(풀이 수) | RSS MiB | OS 스레드 | 핸들 | 자식 프로세스 | 해당 DB 연결 | scoped 컨테이너 |
|---|---|---|---|---|---|---|
| 0 | 86.547 | 8 | 777 | 0 | 1 | 0 |
| 100 | 85.684 | 5 | 774 | 0 | 1 | 0 |
| 200 | 86.672 | 5 | 774 | 0 | 1 | 0 |


200개 모두 finished, attempts 최대 1, 비용 400행/52.800원, span 600개, initial grading_run 1개. 69.72초. 매 10개 중 1개 Docker. 세 표본에서 스레드·핸들·자식·DB 연결·컨테이너의 지속 증가는 관찰하지 못했습니다. RSS는 중간 감소 후 끝에서 시작보다 0.125MiB 높았습니다. 이 세 표본으로 장기 누수 없음을 결론내리지 않습니다. 실행 중 peak는 측정하지 않았습니다.



점검 코드 오류도 구분합니다. 첫 준비에서 lock_experiment 밖 trial 추가로 4개 사례가 막혔습니다. 실제 잠금 경로로 바꾼 다음 실행에서는 dict/list 비교 오류 3개와 공유 로그 append 경합 1개가 있었습니다. 임시 점검 코드만 고쳐 프로세스별 로그로 바꾼 최종 9 passed/47 deselected 결과를 썼습니다. 초기 집계 실패 회차에도 100개×3과 200개는 실행됐지만 위 표는 집계까지 끝난 최종 회차만입니다.

점검 전용 실행의 원래 요약도 남깁니다: 첫 audit 4 failed/52 passed(204.39초), 대용량 픽스처 첫 재실행 4 failed/52 deselected(125.65초), 집계 수정 후 9 passed/47 deselected(117.28초). 기본 DB 대기 검사 첫 회차는 pg_stat_activity 통계 스냅샷을 갱신하지 않아 5 failed/1 passed(62.14초)였고, pg_stat_clear_snapshot을 넣은 점검 코드로 다시 관측해 10 passed/1 deselected(37.34초)였습니다. 이는 제품 수정이나 기존 테스트 기대값 변경이 아닙니다. MCP/모델/DB/자원 probe는 25 passed(38.51초), 비밀값 추가 probe는 1 passed/25 deselected(30.25초)였습니다.

### checklist 완료 항목과 코드·테스트

| 완료 항목 | 실제 코드 | 테스트 근거·범위 |
|---|---|---|
| P-03 최소 연결 | eng_stdio.StdioTools, eng_docker.DockerStdioConfig | test_trial_round_trip, test_docker_worker_round_trip. ① 시험 서버 |
| 공통 DB 연결 | common/db.py | test_eng_db.py 설정·임시 제품 테이블·commit/rollback. 개발 DB 과거 확인은 이번 재실행 안 함 |
| OpenAI/가짜 어댑터·4사 mock | common/llm.py OpenAIModel/FakeModel/ProviderModel | test_eng_llm.py. 실제 API 미검증 |
| 큐 임대·연장·토큰·회수 | common/queue.py | test_priority_skip_locked_and_tokens, test_old_worker_cannot_save_after_reclaim |
| Docker DI·회수 | eng_main.py, eng_docker.py | test_docker_worker_round_trip, test_docker_worker_kill_reclaim. Windows 실제 daemon |
| 예산·attempt·최종 저장 | engine/worker.py | test_eng_worker.py, test_queue_completion_failure_rolls_back_results_and_keeps_costs. 최종 attempt 단독 검출은 변이 표 |
| 예외 후 반환·cancel | worker._release_attempt | test_model_exceptions_release_attempt_and_allow_retry, test_stopped_experiment_still_records_inflight_response_cost. A2 예외 |
| 중간 비용·중복 방지 | engine/costs.py | test_eng_costs.py. 커밋 전 유실은 남음 |
| 풀이별 stdio·lost 연결 | worker.py, eng_main.py | test_worker_session_is_per_trial, test_worker_lost_interrupts_stdio_wait |
| 누적 3회 수동 재개 | advance.resume_failed_trial | test_resume_preserves_attempt_budget, test_resume_concurrently_once. 알려진 소진 종결은 명시 함수 호출 때 |
| 읽기 루프 단계·시간·취소 | engine/loop.py | test_eng_loop.py, 가짜 모델 |
| isError 대화·MCP timeout 분류 | eng_stdio.py, loop.py | test_iserror_then_success_and_trace, test_mcp_initialize_timeout_exhaustion_is_environment_error |
| 자식·손자 정리 | eng_stdio Job/process group | test_process_tree_close, test_process_tree_abort, test_worker_death_closes_tree. Linux 부모 사망 자동 정리는 기존 skip이므로 Windows와 동등한 보장 아님 |
| Docker 격리·상한·키 | eng_docker.py | test_docker_isolation, argv 2건, OOM/pids probe. 일부 값은 argv 검사 |
| bind 허용 데이터 루트 | validate_bind_source | test_bind_* 및 test_docker_bind_allowed_root. 내부 내용 검사 아님 |
| lock·initial grade job 1개 | engine/lock.py, advance.on_trial_finished | test_parallel_completions_create_one_grading_job, test_trial_read_and_atomic_storage_and_single_grading_handoff |
| 수동 재개 잠금 | advance.resume_failed_trial | test_resume_concurrently_once + 20개 동시 호출 |

각 완료 항목에 적어도 하나의 코드·테스트 근거는 찾았습니다. 실제 API·② 실제 서버·Linux 부모 사망·모든 후속 작업 멱등성까지 완료로 넓혀 읽을 근거는 없습니다.

### 가짜 비밀값

부모 환경 OPENAI_API_KEY와 가짜 DATABASE_URL 비밀번호에 AUDIT_FAKE_SECRET_1124_6f82를 넣었습니다. 검사한 trace JSON, 도구 응답, CLI 환경, 실제 컨테이너 Config.Env 및 stdout/stderr에서 일치 0건. Config.Env에는 OPENAI_API_KEY/DATABASE_URL 항목 자체도 없었습니다. JSON-RPC error.message 및 stderr에 같은 값을 넣은 추가 서버 1회는 호출자 오류가 ToolEnvironmentError('env_mcp_server_down')였고 원문 값은 없었습니다. 점검 메타 로그에 의도적으로 쓴 sentinel은 누출로 세지 않았습니다. 모델이 원문으로 비밀값을 생성하거나 데이터 루트의 .env를 읽는 시나리오는 검사하지 않았습니다.

## 5. 못 한 검증과 이유

- Linux 전체: 못 했음. 로컬 이미지에 pytest 없고 외부 네트워크를 쓰지 않아 의존성 설치 안 함. 이번 passed/failed/skipped 산출 불가.
- Linux 호스트 실제 Docker 검증: 못 했음. 배포 전 일회용 VM 또는 CI 러너에서 확인 필요. docker.sock 마운트 안 함.
- 실제 모델 API·외부 서비스·개발 DB는 지시대로 안 함. 실제 청구서와 비용 일치 확인 안 함.
- 가능한 모든 스케줄·create/pull 내부 시점·임의 SQL마다의 kill·모든 cleanup 중단 지점은 안 함. 기재한 gate 8종·시드 3종·경합만 실행.
- 최종 저장 후 gate는 transaction 커밋 전. 결과만 커밋되고 job만 남는 독립 구간은 없음.
- 무기한 잠금·수시간/수일 누수는 실측 안 함. 기본값 0/0 및 짧은 관찰, 200개/세 점 표만 근거.
- 전용 동시 집계에 grade sa_jobs 수, kill 시점별 jobs status를 따로 넣지 않음. 직접 측정값과 기존 원자성/단일 job 검사를 구분해 기재.
- 새 병합 계약·② 코드에 전체 변이 재적용 안 함. 시작 스냅샷 변이와 병합 후 전체 1회는 별도.

## 6. 정리 확인


시작 컨테이너:


```text
531bfe0e7821 final_project-postgres-1 pgvector/pgvector:pg17
e64d49321160 final_project-redis-1 redis:7-alpine
```


시작 이미지:


```text
c5d34a98396a redis:7-alpine
5e2bdb1b0d54 python:3.12-slim
7d0a41464797 pgvector/pgvector:pg17
```


종료 컨테이너:


```text
531bfe0e7821 final_project-postgres-1 pgvector/pgvector:pg17
e64d49321160 final_project-redis-1 redis:7-alpine
```


종료 이미지:


```text
c5d34a98396a redis:7-alpine
5e2bdb1b0d54 python:3.12-slim
7d0a41464797 pgvector/pgvector:pg17
```


최종 git status:


```text
?? docs/audit_engine_1124.md
```


시작 미커밋 9개 파일 모두 내용 해시 일치 확인: 9/9. 원본 엔진·기존 테스트에 이번 점검이 쓴 변경 0개. 시험 태그/라벨 컨테이너·이미지·볼륨 잔여 0개. 중단한 검사 PID 26252 소유(.handle_pids.json) 임시 DB slotagent_e2e_aobs0gwl만 pg_ctl로 종료하고 삭제함. 개발 PostgreSQL/Redis 컨테이너와 기존 11/22 임시 폴더는 보존함. 활성 점검 Python/PostgreSQL이 없음을 확인한 뒤 저장소 밖 점검 복사본·스크립트·로그·캐시 폴더를 삭제 완료함.

시작 manifest 대비 달라진 기존 파일(외부 병합이며 이 점검의 수정 아님):
- .gitignore
- backend/src/slotagent/packs/loader.py
- backend/src/slotagent/packs/select.py
- contracts/CHANGELOG.md
- contracts/schemas/answer_condition.schema.json
- contracts/schemas/pack.schema.json
- contracts/schemas/trace.schema.json
- docs/README.md
- docs/capabilities.md
- frontend/next-env.d.ts
- packs/README.md
