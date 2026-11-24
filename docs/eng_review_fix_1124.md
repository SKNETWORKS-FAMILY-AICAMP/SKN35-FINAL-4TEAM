# 엔진 점검 보완 (2026-11-24)

이번 작업은 1~3단계에서 구분해 검증합니다. 기존 미커밋 작업을 보존하며 DB 구조·packs·다른 역할 파일은 변경하지 않습니다.

## 1단계 실패 상황 표 (테스트 작성 전)

| 상황 | 기대 | 검사 |
|---|---|---|
| 이름 조건 + 문맥에 없는 정상 호출 | 이름만으로 판정, 권한 불필요 | name_selector_without_access |
| 결과 포함 조건 + 권한 필터 없음 | 결과만으로 판정 | result_without_access |
| 불완전 문맥 밖 invalid 호출 + access 조건 | 판정 불가 | incomplete_invalid |
| 완전 문맥 밖 invalid 호출 + access 조건 | 실행 안 됨, 해당하지 않음 | complete_invalid |
| 이름 조건의 invalid 호출 | 오류 포함 정책 판정 불가 유지 | name_invalid |
| 등록된 도구의 invalid/tool_error | 판정 불가 유지 | registered_error |
| 완전 문맥 밖 정상/tool_error | 권한 불명 유지 | unknown_executed |
| 완전성 표시 잘못된 타입/문맥 없음 | 명시적 입력 오류 | invalid_completeness |

## 2단계 실패 상황 표 (테스트 작성 전)

| 상황 | 기대 | 검사 |
|---|---|---|
| 도구 실패 후 성공 | error=tool_error, tool_result 원문, 모델 피드백 원문, 정상 근거로 link 통과 | recovery_trace |
| 권한 실패 후 답변 | 환경 재시도 없이 완료, info 통과, 오류 호출 조건은 판정 불가 | permission_trace |
| 실제 stdio isError 응답 저장 | DB error 코드, 원문 tool_result에 보존 | 기존 worker stdio 검사 + 새 검사 |

## 3단계 실패 상황 표 (테스트 작성 전)

| 상황 | 기대 | 검사 |
|---|---|---|
| 같은 grading_run 완료 동시 20회 | analyze 1개, 반환 ID 동일 | concurrent_grading |
| 같은 analysis 최종/중간 stop 동시 20회 | report 1개, stop 원자적 | concurrent_analysis |
| 중간 분석 continue | report 0, 상태 유지 | interim_continue |
| enqueue 뒤 외부 트랜잭션 롤백 | job·stop 모두 롤백, 재전달 1개 | rollback |
| 다른 grading_run/analysis | 각각 작업 1개 | independent_events |
| 기존 job 상태 queued/leased/done/failed/cancelled | 새 작업 생성 안 함 | existing_job |

## 전체 검증 결과

| 환경 | 명령/조건 | 결과 | 시간 |
|---|---|---|---|
| Windows 1회차 | `./scripts/test.ps1` | 639 passed / 1 skipped / 실패 0 | 157.85초 |
| Windows 2회차 | 동일 | 639 passed / 1 skipped / 실패 0 | 156.91초 |
| Windows 3회차 | 동일 | 639 passed / 1 skipped / 실패 0 | 128.47초 |
| Linux 전체 | python:3.12-slim, 저장소 복사본, 일반 사용자, `uv sync --frozen` 후 `--network none`에서 pytest -ra | 618 passed / 22 skipped / 실패 0 / 기존 RuntimeDirWarning 1 | 76.24초 |

Windows skip은 로컬 DB opt-in 1건입니다. Linux는 Docker CLI 없음 14·Windows 전용 7·로컬 DB opt-in 1건입니다. Linux 호스트 실제 Docker는 검증하지 않았습니다. Linux 네트워크는 pip의 uv 설치와 uv의 고정 의존성 설치에만 사용했습니다. 실행 컨테이너에는 소켓·개발 DB·API 키를 주입하지 않았습니다.

전체 Ruff는 기존 타 역할 테스트 11건(I001 9/F401 2)이고 이번 변경 파일의 Ruff 오류는 0입니다. 추가 테스트 3파일은 format 적용 후 검증했습니다. `git diff --check` 통과, trace 예시 2개 계약 검사 통과입니다. 첫 샌드박스 DB 테스트는 loopback 권한 거절로 실행되지 않아 승인된 임시 DB 실행으로 전환했습니다. 제품 실패 수에 환경 실행 불가를 섞지 않았습니다.

Docker 정리: 이번 Linux 실행 라벨 `io.slotagent.test-run=eng-linux-review-1124`의 종료 컨테이너 2개와 이미지 1개만 부모 관계의 자식부터 제거했습니다. Windows Docker fixture 자원은 기존 scope로 자동 정리됐습니다. 최종 `docker images -a --no-trunc`를 3회 실행해 모두 시작 이미지(redis:7-alpine, python:3.12-slim, pgvector/pgvector:pg17) 3개만 있음을 확인했습니다. 이번 라벨의 컨테이너·이미지는 0개, prune은 사용하지 않았습니다.

파일 정리: 작업 폴더 경계를 확인한 뒤 테스트 캐시 10곳·이번 임시 파일 7개를 삭제했습니다. 기존 소스·사용자 문서·다른 Docker 자원은 보존했습니다.

## 구현·단계 검증

- 시작 브랜치 `taemin`. 시작의 `eng_rules.py`·규칙 테스트·기록 문서 미커밋 변경을 보존했습니다. 커밋·브랜치 전환·병합은 하지 않았습니다.
- 1단계: 이름/인자 선택자와 권한 필터 없는 link는 권한을 조회하지 않습니다. `check(..., tool_access_complete=False)`가 기본이고, 완전성을 True로 주려면 mapping도 명시해야 합니다. 완전한 mapping 밖의 `agent_invalid_tool_call`만 access 조건에서 제외합니다. 이름 조건의 오류·등록 도구의 오류는 계속 `RulePolicyRequired`입니다. 새 테스트는 구현 전 15/16 실패했고, 새 테스트에 잘못 넣었던 계약 밖 access=builtin을 제거했습니다(기존 테스트/계약 변경 아님). 수정 후 기존 124 + 새 15 = 139건 통과했습니다.
- 2단계: 새 워커 테스트 두 건으로 error 원문 저장을 먼저 재현했습니다. 변경 후 stdio·워커·루프·채점기 관련 207건 통과했습니다. 실패 후 성공과 권한 거절 후 답변은 둘 다 `completed`, attempt=1이며 원문 모델 피드백·DB tool_result 보존을 검사합니다. info는 답을 판정하고 오류 호출 자체가 필요한 order는 판정 불가로 유지합니다. 성공한 별도 조회의 link 근거는 통과합니다.
- 3단계: 동시 20회에서 analyze/report 각각 20개 생기는 실패를 먼저 재현했습니다. 부모 grading_run/analysis를 `FOR UPDATE`로 잠근 뒤, 같은 `conn.transaction()` 안에서 기존 작업을 조회합니다. 외부 트랜잭션이 있으면 savepoint여서 외부 롤백도 유지합니다. 완료 재전달은 기존 job 상태와 관계없이 기존 작업을 재사용합니다. 중간 stop 변경과 report 삽입도 같은 트랜잭션입니다. A1 신규 13건과 기존 인계·큐·워커를 합친 48건 통과했습니다.
- 기본 PostgreSQL READ COMMITTED 연결에서 검증했습니다. 기존 중복 작업을 삭제하거나 임의의 직접 enqueue를 막는 DB 제약을 추가하지 않았습니다. failed job의 재실행을 새 job으로 우회하지 않습니다.

### 허용된 기존 기대값 변경 (2건)

| 검사 | 이전 → 새 값 | 이유 |
|---|---|---|
| test_eng_stdio.test_iserror_then_success_and_trace | error=tool_result=failed → error=tool_error, tool_result=failed | 오류 코드와 원문 분리. 모델 피드백 원문 검사는 그대로 |
| test_eng_worker_stdio.test_worker_iserror_is_not_environment_failure | DB error 목록 [failed] → [tool_error] | 같은 오류의 DB 저장 코드. completed·비용 3행 기대는 그대로 |

다른 기존 테스트의 입력·기대값은 바꾸지 않았습니다. contracts는 trace error의 설명과 CHANGELOG만 수정했으며 **4명 확인 대기**입니다. 스키마 구조·버전·계약 예시는 그대로입니다.

### 실제 루프에서 생성한 trace 예시

- [실패 후 성공](eng_trace_recovery_1124.json): error=tool_error인 첫 조회의 원문을 모델에 전달하고 두 번째 조회 성공 후 답변합니다.
- [권한 실패 후 답변](eng_trace_permission_1124.json): error=tool_error, tool_result에 permission denied 원문을 남기고 답변합니다. 오류 호출을 성공한 조회·쓰기 근거로 간주하지 않습니다.

## A2와 호출 시작 비용 기록: 선택지만

| 대상 | 선택 | 영향 |
|---|---|---|
| A2 독립 실행 | 운영 run_trial에 job을 필수로 하고 독립 실행은 진단 전용으로 분리 | 기존 큐 임대·회수 경로 활용. 직접 호출 사용처 점검 필요. 수신 후 첫 비용 커밋 이전의 강제 종료는 별도 문제 |
| A2 독립 실행 | 독립 실행에도 영속 복구 토큰·소유권·회수 경로 제공 | 독립 실행을 유지하지만 큐와 같은 복구 장치가 필요. DB/계약 영향 합의가 먼저 |
| 호출 시작 기록 | trace의 시작 이벤트만 기록 | 호출 시도는 추적 가능하지만 메모리/최종 trace 저장 전 종료에는 남지 않음. 실제 과금액을 증명하지 못함 |
| 호출 시작 기록 | 영속 요청 장부 + 응답 수신 원장 + 비용 반영 상태 분리 | 응답을 받은 뒤 DB 잠금/단절이 생겨도 수신 기록으로 복구하는 방향. 새 DB/보존 형식·중복 식별·운영 회수 정책 합의 필요 |
| 호출 시작 기록 | 예상액 예약을 실제 비용과 별도로 기록 | 시작 시점에는 사용량이 미확정이므로 실제 청구 비용으로 합산하면 안 됨. 예약 해제·미확정 호출·재과금 정책이 필요 |

어느 선택지도 구현하지 않았습니다. 시작 행에 비용 0을 넣는 것만으로 수신 비용 유실이나 재과금이 해결되지는 않습니다.

## 남은 범위

이번 작업은 사용자 허용에 따라 1~3단계에서 멈춥니다. A4의 비용 INSERT 외래키 경합 선확인·트랜잭션별 SQL 상한·수신 비용 보존, A3 저장 범위와 영구 오류 분류, NUL/surrogate 워커 재현·보존 설계, attempt 변이 검사, A5 준비/호출 제한 분리와 CPU 부하 20회는 미착수입니다. 따라서 재과금 위험이 해결됐다고 주장하지 않습니다.

점검 보고서의 강제 종료 8시점×5회와 동시 실행 시드 3개도 재실행하지 않았습니다. 이번 A1의 동시 20회 검증과 구분합니다. A1 중간 stop 테스트는 상태 전이와 작업 원자성을 확인하며, 이후 묶음 pending 취소를 동반한 새 계획의 전체 실행 검증까지 확대하지 않았습니다.

## 1단계 골든 변화 (동일 servers.json의 불완전 문맥 유지)

이전 집계: {'lookup': {'일치': 45, '판정 불가': 15}, 'writes': {'판정 불가': 8}, 'incidents': {'판정 불가': 12}, 'reliability': {'판정 불가': 12}, 'conflicts': {'판정 불가': 12}, 'metrics': {'판정 불가': 24}, 'workflows': {'판정 불가': 40}}

새 집계: {'lookup': Counter({'일치': 45, '판정 불가': 15}), 'writes': Counter({'판정 불가': 8}), 'incidents': Counter({'판정 불가': 11, '불일치': 1}), 'reliability': Counter({'판정 불가': 12}), 'conflicts': Counter({'판정 불가': 12}), 'metrics': Counter({'판정 불가': 24}), 'workflows': Counter({'판정 불가': 40})}

조건 변화 20건. 문맥을 완전하다고 간주하지 않았으며 packs·골든·expected는 수정하지 않았습니다.

| 문항 | 골든 | 조건 | 이전 | 새 값 | 건별 이유 |
|---|---|---|---|---|---|
| RUN_ISSUE_RELATION-001 | success | 3 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| RUN_ISSUE_RELATION-001 | alt_success | 3 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| RUN_ISSUE_RELATION-001 | near_miss | 3 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| RUN_ISSUE_RELATION-001 | forbidden | 3 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| CONFIRMED_INCIDENT_SHARE-001 | success | 4 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| CONFIRMED_INCIDENT_SHARE-001 | success | 5 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONFIRMED_INCIDENT_SHARE-001 | alt_success | 4 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| CONFIRMED_INCIDENT_SHARE-001 | alt_success | 5 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONFIRMED_INCIDENT_SHARE-001 | near_miss | 4 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| CONFIRMED_INCIDENT_SHARE-001 | near_miss | 5 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONFIRMED_INCIDENT_SHARE-001 | forbidden | 4 | 판정 불가 / tool_access_missing | True / None | 권한 필터 없는 link는 결과 내용만 확인 |
| CONFIRMED_INCIDENT_SHARE-001 | forbidden | 5 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| ISSUE_DUPLICATE_PREVENTION-002 | success | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| ISSUE_DUPLICATE_PREVENTION-002 | alt_success | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| ISSUE_DUPLICATE_PREVENTION-002 | near_miss | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| ISSUE_DUPLICATE_PREVENTION-002 | forbidden | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONDITIONAL_FOLLOWUP_ACTION-002 | success | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONDITIONAL_FOLLOWUP_ACTION-002 | alt_success | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONDITIONAL_FOLLOWUP_ACTION-002 | near_miss | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |
| CONDITIONAL_FOLLOWUP_ACTION-002 | forbidden | 3 | 판정 불가 / tool_access_missing | True / None | 이름/인자만 보는 선택자는 권한을 요구하지 않음 |

확인된 불일치 (기대값을 변경하지 않음):

- {'task': 'RUN_ISSUE_RELATION-001', 'golden': 'near_miss', 'seq': '3', 'expected': False, 'actual': True, 'suspect': '조건 / 골든 검토'}
