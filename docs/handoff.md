# 작업 인계 기록

Codex·Claude·팀원이 같이 씁니다. **새 기록은 맨 위에** 더합니다. 한 작업에 기록 하나를 씁니다.

```
## YYYY-MM-DD · <도구 또는 사람> · <브랜치>
- 한 일:
- 안 한 일 / 남은 일:
- 의문점 (계약·미정 사항과 부딪힌 곳):
```

---

## 2026-11-25 · Claude · taemin (쓰기 계약·도구 권한을 ① 결정으로 적용)
- 한 일: 사용자 결정으로 write_scenario·exact_writes·P-05 v1을 계약에 적용(CHANGELOG), DB 0005, 워커·로더·채점기 연결, 스냅숏 채점 문맥(eng_context), 연습 도구 권한표(tool_permissions.json), 이름표 9개 사전 등록. 골든 188개: 일치 185 / 불일치 3 / 판정 불가 0
- 안 한 일 / 남은 일: ②④ 이견 확인, ②의 9문항 활성화·골든 3개, 개발 DB에 0005 적용, eng_pipeline. 커밋 없음.
- 의문점: 4명 확인이 끝난 것은 아님. loader.py(②)는 write_scenario 저장만 더함.

## 2026-11-25 · Claude · taemin (승인 재검증·② 최신 대조)
- 한 일: `eng_rules.check(confirmation=ConfirmationContext(...))`로 unless_user_confirmed 재검증(boolean은 안 믿음, 문맥 없으면 그대로 판정 불가). get_write_result에 unknown 추가. 고정 수량 테스트를 팩 기준으로 바꿈. ② 도구 목록을 임시 권한으로 넣은 골든 188개 대조: 일치 185 / 불일치 3 / 판정 불가 0. ②에게 보낼 문서: role2_reply_1125.md (저장소 밖)
- 안 한 일 / 남은 일: eng_pipeline에서 스냅숏으로 문맥 만들기, 계약·DB 칸(4명 확인), 반복 order 기준. 커밋 없음.
- 의문점: tool_inventory를 권한 근거로 쓸지 ④ 확인.

## 2026-11-25 · Claude · taemin (write_proxy·확인 도구)
- 한 일: 쓰기 가로채기·`request_user_confirmation`·가짜 쓰기 상태(`get_write_result`, `get_work_state`)를 엔진에 구현. `sa_tasks.confirmation`을 워커에서 읽고 `sa_write_intents`에 저장. 쓰기 횟수 조건의 순수 함수(`grading/eng_writes.py`, 규칙 채점기에 미연결). 모든 문항에 확인 도구가 추가되어 HARNESS_VERSION 0.1.0 → 0.2.0. 옛 "쓰기 미지원" 테스트 2개를 새 동작으로 바꿈. 자세히 docs/eng_write_contract_draft_1125.md, 실행 예시 docs/eng_write_examples_1125.json
- 안 한 일 / 남은 일: `write_scenario`·`exact_writes`의 계약·DB 칸(4명 확인 뒤), forbidden 승인 재검증, test_space·dry_run. 커밋 없음.
- 의문점: 초안 문서 6절 5개. `contracts/`·DB·packs 변경 없음.

## 2026-11-24 · Claude · taemin (최종 저장만 재시도)
- 한 일: 잠금에 막힌 최종 저장을 모델 재호출 없이 최대 5회 재시도, heartbeat의 일시 잠금 오류를 임대 상실에서 제외, 회수의 experiment 잠금 완화. Windows 780/1 skip 2회, Linux 759/22 skip, 강제 종료·3시드 43 passed. 자세히 docs/eng_remaining_1124.md 끝
- 안 한 일 / 남은 일: 실험 종료 게이트(NUL 등 영구 실패 풀이 pending), Linux 호스트 실제 Docker 검증, 채점 파이프라인. 커밋 없음.
- 의문점: 없음. 계약·DB·packs 변경 없음.

## 2026-11-24 · Codex→Claude · taemin (엔진 점검 보완 나머지 — 마지막 검증)
- 한 일: Codex가 A4 SQL 상한·비용 영수증 재시도, A3 토큰/비용 범위, NUL·surrogate 영구 오류, attempt 검사 테스트, A5 시작/호출 제한 분리를 구현하고 마지막 전체 검증 중 중단. Claude가 코드 검토와 최종 코드의 Windows(763 passed/1 skipped)·Linux(742 passed/22 skipped) 전체를 실행. 자세히 docs/eng_remaining_1124.md
- 안 한 일 / 남은 일: 최종 저장만 재시도하기(제안), 종료 게이트, Codex 임시 파일·Linux 시험 자원 정리, Linux 호스트 실제 Docker 검증. 커밋 없음.
- 의문점: 같은 문서의 남은 위험 4개.

## 2026-11-24 · Codex · taemin (엔진 점검 보완 1~3단계)
- 한 일: 이름/인자 조건과 권한 필터 없는 link의 불필요한 권한 요구를 제거했습니다. `tool_access_complete=False`가 기본이며 호출자가 명시한 완전 문맥 밖의 `agent_invalid_tool_call`만 access 조건에서 제외합니다. 이름 조건·등록 도구의 오류 판정 불가는 유지했습니다. 골든 168개는 일치 45 / 불일치 1 / 판정 불가 122이고 조건 변화 20건을 건별 기록했습니다. RUN_ISSUE_RELATION-001 near_miss 조건3의 기존 불일치가 재노출됐으며 expected는 고치지 않았습니다.
- tool_error: 도구 실패 span.error는 `tool_error`, 원문은 tool_result·모델 피드백에 그대로 둡니다. 실제 워커의 실패 후 성공·권한 실패 후 답변, DB 저장·attempt=1·채점기 경계를 확인했습니다. trace 예시는 docs/eng_trace_recovery_1124.json·eng_trace_permission_1124.json입니다. 기존 기대값은 오류 원문을 검사하던 stdio 2곳만 바꿨습니다(이전 failed → tool_error, 원문 검사 유지).
- A1: on_grading_finished/on_analysis_done에 부모 행 FOR UPDATE·기존 job 조회·생성을 같은 트랜잭션으로 묶었습니다. 중간 stop도 report 생성과 함께 롤백됩니다. 신규 13건으로 동시 20회·외부 롤백·다른 grading_run·기존 queued/leased/done/failed/cancelled 작업을 검증했습니다. 기존 중복 행 삭제·DB 구조 변경은 하지 않았습니다.
- 단계 검증: 실패 상황 표 → 실패 재현 테스트 → 구현 순서로 진행했습니다. 1단계 139건, 2단계 관련 207건, A1과 기존 인계·큐·워커 48건 통과. Windows 전체 3회 모두 639 passed/1 skipped/실패 0(157.85·156.91·128.47초), Linux 전체 618 passed/22 skipped/실패 0/기존 경고 1(76.24초)입니다. Linux는 의존성 설치 후 네트워크 차단·일반 사용자로 실행했습니다. Linux 호스트 실제 Docker는 미검증입니다. 전체 Ruff의 기존 타 역할 테스트 11건은 남고 변경 파일 새 오류는 0건입니다.
- 범위 종료/남은 일: 사용자 허용에 따라 1~3단계 완료 지점에서 멈춥니다. A4 비용 FK 경합·SQL 상한·수신 비용 보존, A3 영구 오류, NUL/surrogate 워커, attempt 변이, A5 CPU 부하 검증 및 점검 보고서 강제 종료 40회·동시 실행 시드 3개는 미착수입니다. 재과금 위험 해결로 읽으면 안 됩니다. A2·호출 시작 비용 기록은 선택지만 보고했습니다.
- 계약·역할: trace error 설명·CHANGELOG만 사용자 승인 범위로 변경했고 **4명 확인 대기**입니다. packs·DB 구조·②/③/④ 코드·실제 모델 API·개발 DB는 건드리지 않았습니다. 기존 미커밋 변경 보존, 커밋·push·브랜치 전환 없음.
- 상세: `docs/eng_review_fix_1124.md` (단계별 실패 표·골든 20건·기대값 변경 2건·검증·선택지·한계).

## 2026-11-24 · Codex · taemin (① 규칙 채점기 1단계 보완)
- 한 일: `check(kind,spec,trace, *, tool_access=None)` 신뢰 권한 문맥을 추가했습니다. 기존 3인자 호출은 유지하고, trace.access/write_intents 충돌은 오류·문맥 없는 관련 도구는 판정 불가로 처리합니다. forbidden/link/end_state의 확정 정상 근거가 오류·권한 불명에 가려지지 않게 했습니다. 실제 워커·eng_pipeline 연결은 하지 않았습니다.
- 모델 답: NaN/Infinity·NUL·깨진 Unicode·극단 숫자·깊은 중첩은 전용 `RulePolicyRequired(code,key)`로 처리합니다. 잘못된 조건·구조 trace는 여전히 오류입니다. 14종 실제 evidence/판정 불가 메타데이터를 임시 PostgreSQL jsonb INSERT/SELECT로 확인했습니다. 깨진 원문 자체의 보존은 범위 밖입니다.
- 요구 변경으로 기존 테스트 1사례 교체: `test_error_call_needs_policy`의 link는 오류+정상 근거가 모두 있어도 판정 불가 기대 → 오류 근거만 있을 때 판정 불가; 이유는 사용자 승인한 정상 근거 우선 정책입니다. 정상 근거가 있으면 True인 양쪽 호출 순서·배열 재배열 검사를 추가했습니다. forbidden 기존 사례와 order/end_state 등 나머지 기대값은 유지했습니다.
- 골든: 동일 팩 servers.json의 5개 정의/68개 호출만 권한 문맥으로 사용했습니다. 권한 없는 16개 이름/226개 호출은 추측하지 않았습니다. 168개 중 일치 45 / 확인된 불일치 0 / 판정 불가 123입니다. 이전 97/3/68에서 바뀐 조건 197행을 보고서에 개별 설명했습니다. 기존 불일치 3개는 해결한 것이 아니라 권한 부족으로 보류됐고, 승인 18건도 그대로 판정 불가입니다. 변조 정답 192개는 통과 0/실패 192입니다.
- 검증: 규칙 단위 124 passed. Windows 전체 556 → 609 passed, 1 skipped, 실패 0(118.67초). Linux 전체 535 → 588 passed, 22 skipped, 실패 0(50.72초), 기존 경고 1건. Linux skip은 Docker CLI 없음 14·Windows 전용 7·로컬 DB opt-in 1, Windows skip은 로컬 DB opt-in 1입니다. 새 파일 Ruff 오류 0·형식 통과; 전체 Ruff의 기존 타 테스트 11건(I001 9/F401 2)은 수정하지 않았습니다.
- 안 한 일 / 제안: 계약·DB·packs·엔진·eng_pipeline·expected 변경 및 커밋은 하지 않았습니다. 판정 불가를 False/조용한 제외로 바꾸지 않습니다. 재채점 가능한 버전별 3상태 기록(추천), 기존 채점 전체 미완료 보류, 합의한 의미 항목만 ② 판정기로 보내는 3안을 제안했습니다. DB/계약 영향은 보고서에 적었고 구현하지 않았습니다.
- 남은 위험: 권한 출처 부족·승인 18건·기존 불일치 3개·1단계 JSON 필드 규칙의 다른 필드 모순/자유문장 한계가 남습니다. 깨진 원문 재채점에는 손실 없는 별도 인코딩 원본 보존 설계가 필요합니다. Linux 호스트 실제 Docker 검증: 못 했음. 배포 전 일회용 VM 또는 CI 러너에서 확인 필요.
- 상세: `docs/eng_rules_followup_1124.md` (실패 상황 표, 업무 그룹별 집계, 변경 197행, 출처, 제안). 이전 `docs/eng_rules_1124.md` 수치는 문맥 없는 기준으로 보존합니다.

## 2026-11-24 · Codex · taemin (① 규칙 채점기 1단계)
- 담당 결정: 규칙 채점기 `grading/eng_rules.py`는 ① 담당입니다(11/24 사용자 결정). AGENTS.md 1·9번 및 checklist ①에 반영했고 ② 칸은 수정하지 않았습니다.
- 한 일: `check(kind,spec,trace) -> (passed,evidence)` 순수 함수로 info·link·order·forbidden·end_state, 비교 7종을 구현했습니다. contracts로 입력·evidence를 검사하고 seq 순서·쓰기 payload를 사용합니다. 모델·네트워크·DB·전체 성공 판정·eng_pipeline 연결은 하지 않습니다. gate 집계는 대조 도구에서 `checks.condition_gate()`를 사용합니다.
- **1단계 임시 규칙(사용자 확인)**: 답 전체가 JSON 객체이고 key가 최상위에 있으면 그 필드만 비교합니다. 키 누락·중복, 자유문장·최상위 배열/스칼라·앞뒤 설명은 `RulePolicyRequired(code,key)`로 올립니다. null·빈 답은 실패입니다. must_not도 같은 필드만 보므로 다른 필드의 모순은 못 봅니다. 계약·packs·문항을 바꾸지 않았습니다.
- 골든: task_code로 정확히 연결해 168개를 독립 대조했습니다. **일치 97 / 불일치 3 / 판정 불가 68**. 판정 불가 조건은 71건(access 없음 53 / 승인 정책 컨텍스트 없음 18)이며 불일치 3개에도 판정 불가 조건이 있어 궤적 집계와 다릅니다. 의도적으로 틀린 정답 필드 192개는 통과 0·실패 192입니다. info key 문자열이 문항에 없는 조건은 전체 info 291개 중 102개입니다.
- 불일치: RUN_ISSUE_RELATION-001 near_miss 조건3은 도구 근거는 그대로인데 link 기대가 false입니다. ISSUE_DUPLICATE_PREVENTION-002와 CONDITIONAL_FOLLOWUP_ACTION-002 forbidden 조건5는 요구한 쓰기가 존재하고 추가 쓰기도 있는데 end_state 기대가 false입니다. 참조 판정기를 복사하거나 기대·골든·조건을 바꾸지 않았습니다. 업무 그룹별 결과·모든 판정 불가 조건·실패 상황 표는 [eng_rules_1124.md](eng_rules_1124.md)에 기록했습니다.
- 확인: 새 단위 **71 passed**. Windows 전체 **전 485 passed/1 skipped → 후 556 passed/1 skipped, 실패 0**(최종 122.11초). Linux 최종 전체 **535 passed/22 skipped/실패 0/기존 경고 1건**(51.57초). skip은 Docker CLI 없음 14·Windows 전용 7·local DB opt-in 미사용 1입니다. 읽기 전용 저장소 복사본·일반 사용자·uv sync --frozen으로 실행했고 Docker 소켓은 마운트하지 않았습니다. 새 Python 파일 2개 Ruff 오류 0·형식 검사 통과. 전체 Ruff의 기존 11건(I001 9/F401 2)은 다른 테스트 파일이라 고치지 않았습니다.
- 안 한 일/남은 위험: eng_pipeline·DB·계약·packs·pack_* 수정과 커밋·push를 하지 않았습니다. 오류 호출 포함 정책·오류로 차단된 쓰기·반복 호출의 순서 정책·승인 정책 주입은 미정이며 False로 저장하지 않습니다. 현재 골든의 span.error는 0개여서 실제 오류 호출 정책 검증을 대신하지 못합니다. 시간대 변환은 하지 않습니다. contains/link 문자열만으로 실제 관계·ID 경계를 보장하지 않습니다. LLM/분류기 경로와 ② 실제 판정 연계는 후속 작업입니다.
- 정리: 이번 테스트 캐시 11곳·종료한 pytest 임시 폴더 3곳을 경계를 확인한 뒤 삭제했습니다. 시험용 컨테이너·이미지·볼륨과 Linux 실행기 잔여는 0개입니다. 개발 DB·다른 Docker 자원·기존 11/22 임시 폴더는 건드리지 않았습니다. Linux 호스트 실제 Docker 검증: 못 했음. 배포 전 일회용 VM 또는 CI 러너에서 확인 필요.

## 2026-11-24 · Codex · taemin (Docker bind 원본 허용 루트 검사)
- 한 일: 이번 변경은 `engine/eng_docker.py`, `tests/test_eng_docker.py`, 이 기록에만 한정했습니다. `DockerServer.allowed_data_roots`를 추가하고 bind 원본을 명시한 루트 안으로 제한했습니다. 허용 루트가 없으면 실제 실행 전에 env_mcp_server_down으로 거절합니다. `/`, 드라이브 루트, `/var/run`, `/run`과 런타임 경로 하위는 데이터 루트·원본으로 거절합니다. 데이터 전용 루트 자체의 마운트는 허용합니다.
- 경로 검사: `..`를 정규화 전에 거절하고, 실제 파일/디렉터리 존재와 모든 조상의 lstat를 확인합니다. 심볼릭 링크·Windows junction/reparse point, 접근 불가·없는 경로, UNC/device/drive-relative 경로를 거절합니다. Windows 대소문자·슬래시 표기를 처리하며 `/data`와 `/data2`는 구성 요소 단위로 구분합니다. 허용 루트 목록을 복사·동결하고 원본을 정규 경로로 바꿉니다. 생성 시와 실제 start 직전에 다시 검사합니다. 원격 daemon과 Linux 컨테이너 워커는 호스트 경로 공간을 확인할 수 없어 bind를 거절합니다. 로컬 Windows named pipe와 Linux unix socket의 daemon만 지원합니다.
- 호환: named volume은 기존 동작을 유지합니다. 순수 `docker_run_argv`는 파일 시스템·Docker에 접근하지 않는 포맷 함수로 유지하고 실제 실행 경계인 DockerStdioTools에서 승인합니다. 기존 테스트 설정과 기대값은 한 글자도 바꾸지 않았고 새 테스트만 추가했습니다. ② 연계 대기·계약·DB·다른 역할 파일·새 의존성은 건드리지 않았으며 커밋·push 하지 않았습니다.

### 실패 상황 표 — 최종본

| # | 상황 | 들어오는 값/상태 | 기대 결과 (상태값·에러·DB 행) | 테스트 이름 | 결과 |
|---|---|---|---|---|---|
| 1 | 허용 루트 없음 | 빈 allowed_data_roots와 bind | ValueError / 실행 경계에서는 환경 오류, 프로세스 시작 안 함 | test_bind_requires_allowed_roots, test_bind_invalid_config_never_launches | 통과 |
| 2 | 호스트 제어 경로 | /, C:/, 역슬래시 드라이브 루트, /var/run, /run 및 Windows 혼합 대소문자 | 원본·루트 설정 ValueError | test_bind_control_roots_rejected (7종) | 통과 |
| 3 | 정상 데이터 경로 | 허용 루트 아래 파일·디렉터리·루트 자체 | 정규 경로 반환, 실제 Docker 읽기 성공·쓰기 EROFS·close 뒤 0개 | test_bind_allowed_descendant (3종), test_docker_bind_allowed_root | Windows 실제 Docker 통과, Linux 파일 검사 통과·Docker만 skip |
| 4 | 비슷한 접두사 | data 루트 밖 data2 | ValueError | test_bind_sibling_prefix_rejected | 통과 |
| 5 | 상위 이동 | /와 역슬래시의 .. | 정규화로 숨기지 않고 거절 | test_bind_parent_traversal_rejected (2종) | 통과 |
| 6 | 링크·junction | 원본·조상·허용 루트가 링크, reparse 속성 | ValueError | test_bind_links_rejected (3종), test_bind_reparse_flag_rejected | 통과 |
| 7 | Windows 경로 표기 | 대소문자·역슬래시/슬래시, 비슷한 형제 경로 | 정상 원본 허용·형제 거절 | test_bind_windows_path_forms (2종) | Windows 통과, Linux 전용 사유로 skip |
| 8 | 확인 불가 경로 | 없음·타 OS 경로·UNC·device·drive-relative·권한 거절 | ValueError | test_bind_uncheckable_paths_rejected (6종) | 통과 |
| 9 | 검사 뒤 원본 변경 | 생성 후 start 전에 링크로 교체 | 환경 오류, closed·process 없음, 반복 close 안전 | test_bind_rechecked_before_start | 통과 |
| 10 | 다른 호스트 경로 공간 | 원격 DOCKER_HOST/컨텍스트·Linux 컨테이너 워커 | bind 거절, 프로세스 시작 안 함 | test_bind_remote_daemon_rejected, test_bind_daemon_context_checked, test_bind_container_worker_path_space, test_bind_invalid_config_never_launches | 통과 |
| 11 | 기존 volume·수명·회수 | 기존 정상/timeout/취소/워커 kill·재시도 | 기존 환경 오류·회수·잔여 0·attempt 상한 유지 | 기존 Docker 통합 13건 (test_docker_isolation, test_docker_worker_kill_reclaim 등) | Windows 전부 통과, Linux Docker CLI 없음 skip |

- 확인: Windows `./scripts/test.ps1` **직전 332 → 367 passed, 실패 0·skip 0**, 실제 Docker 통합 **14건** 실행. Linux `python:3.12-slim` 읽기 전용 저장소를 /work에 복사하고 일반 사용자로 `uv sync --frozen` → `uv run pytest -rs`: **직전 314 passed/18 skipped → 346 passed/21 skipped, 실패 0**. skip은 Docker CLI 없음 14건 + Windows 전용 7건입니다. 기존 XDG_RUNTIME_DIR RuntimeDirWarning 1건이 있습니다. Docker 소켓은 마운트하지 않았고 복사본 코드를 따로 고치지 않았습니다. backend 전체 Ruff·범위 파일 형식·diff 검사 통과.
- 정리: 이번 테스트 전용 컨테이너·이미지·volume 잔여 0개를 확인했습니다. 경계를 확인한 저장소 테스트 캐시 8곳과 종료한 pytest 임시 폴더 3곳을 정리했습니다. 다른 Docker 자원·기존 OS 임시 폴더는 건드리지 않았습니다.
- 남은 위험: **Linux 호스트 실제 Docker 검증: 못 했음. 배포 전 일회용 VM 또는 CI 러너에서 확인 필요**. 호스트와 워커가 다른 경로를 보는 구성은 bind 미지원이며 named volume을 쓰거나 같은 경로 공간의 신뢰한 워커가 필요합니다. 로컬 endpoint가 실제 로컬 daemon을 가리킨다는 운영 전제가 있으며 원격으로 전달한 소켓은 지원하지 않습니다. 검사 직후 Docker daemon이 bind를 여는 사이의 호스트 경로 교체를 원자적으로 막는 API는 없으므로, 데이터 전용 루트와 그 조상은 신뢰한 관리자만 변경할 수 있어야 합니다. 넓은 일반 디렉터리를 데이터 루트로 지정하지 마세요. 컨테이너의 readonly는 호스트 관리자 변경을 막지 않습니다.

## 2026-11-24 · Codex · taemin (풀이별 Docker MCP 격리 — ① 테스트 서버)
- 한 일: AGENTS.md 9번을 먼저 읽었습니다. 대기 중인 span.error 코드·② 로더/실제 서버 이미지·sa_env_checks·P-05·채점 규약은 수정하지 않았습니다. ①의 eng_stdio_server.py만 넣은 임시 테스트 이미지로 Docker stdio 경로를 구현했습니다. 계약·DB·마이그레이션·새 Python 의존성·다른 역할 파일·기존 테스트 기대값을 바꾸지 않았습니다. Docker CLI가 있는 신뢰한 워커에서만 실행하며 Docker 실패 시 로컬 실행으로 되돌아가지 않습니다.
- 설정: 새 `engine/eng_docker.py`의 DockerServer(image, arguments, mounts, environment, entrypoint, memory_mb, cpus, pids_limit), ReadOnlyMount(source,target,kind='bind'/'volume'), DockerStdioConfig(servers, scope, docker, timeout_sec, control_timeout_sec)로 받습니다. 이미지 이름은 실행 전에 로컬 image ID로 해석하고 `--pull=never`로 그 ID를 실행합니다. 시험 이미지를 ② 이미지로 바꾸는 것은 설정 교체 자리만 준비했고 실제로 교체하지 않았습니다. scope는 같은 DB/실행 환경의 워커가 공유하는 고유한 비밀이 아닌 식별자여야 합니다.
- 격리: StdioTools를 재사용한 DockerStdioTools가 `docker run -i --rm`을 실행합니다. `--network none --init --read-only --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges`, 기본 메모리 128MiB(동일 memory-swap), CPU 1개, pids 64개, 제한된 /tmp tmpfs를 적용합니다. 모든 설정 데이터 마운트는 readonly이며 Docker 제어 소켓·컨테이너 제어/실행 경로에는 마운트할 수 없습니다. 부모 API 키/DATABASE_URL은 CLI와 MCP 컨테이너에 상속하지 않습니다. 컨테이너 env는 LANG/LC_ALL/TZ/PYTHONUTF8만 명시할 수 있고 설정 dict를 나중에 바꿔 키를 넣지 못하게 복사·동결합니다. Docker 컨텍스트 경로/접속 설정은 호스트 CLI에만 제공하고 컨테이너에는 넘기지 않습니다. CLI 설정의 proxy 자동 주입도 빈 값으로 차단합니다.
- 수명·회수: worker가 trial/attempt/job/lease 식별자를 세션에 넘깁니다. 이름에는 trial/attempt/UUID를 쓰고 scope/kind/trial/attempt/job/lease 라벨을 붙입니다. close는 CLI 종료 전후에 해당 이름·scope의 컨테이너를 제거하고 남은 대상을 확인합니다. `queue.reclaim`에 선택적인 cleanup_expired hook을 추가해 만료 임대 행을 잠근 상태에서 컨테이너 정리를 먼저 수행합니다. 실패하면 DB 회수도 롤백하므로 새 워커에 넘기지 않습니다. run_once는 Docker 설정의 hook에 같은 DB 연결을 넘깁니다. 해당 scope의 라벨을 현재 DB 임대와 비교해 만료·지난 임대·종료/없는 job의 고아만 정리하고 유효한 현재 임대는 보존합니다. 만료 작업이 0개여도 검사해 Docker 생성 요청이 늦게 반영된 고아도 다음 reclaim에서 제거합니다. 실행/제어 명령은 각각 시간 상한을 가지며 자동 무한 정리 재시도는 없습니다.

### 실패 상황 표 — 최종본

| # | 상황·입력 | 기대 결과 / 확인한 결과 | 테스트 이름 | 결과 |
|---|---|---|---|---|
| 1 | 이미지 없음·실행 파일 없음·bind 원본 없음 | env_mcp_server_down, 세션 시작 거절·잔여 0 | test_docker_start_failure (3종) | Windows 실제 Docker 통과 |
| 2 | 초기화 무응답 | 환경 오류, 세션 폐기·컨테이너 0 | test_docker_initialize_timeout | 통과 |
| 3 | 정상 워커 풀이 | finished/done, 모델 비용 2행, close 후 0 | test_docker_worker_round_trip | 통과 |
| 4 | 별도 워커 kill 후 임대 만료 | run_once reclaim에서 옛 컨테이너 먼저 제거·pending/queued 복구 확인, 새 attempt=2 완료·비용 3행·잔여 0 | test_docker_worker_kill_reclaim | 통과 |
| 5 | 과거 임대·현재 임대가 함께 존재 | 선택한 과거 임대만 제거, 현재 세션 호출 성공 | test_docker_reclaim_preserves_other_lease | 통과 |
| 6 | DB 현재 임대가 유효 | 고아 검사 후에도 현재 컨테이너 유지 | test_docker_reclaim_preserves_current_db_lease | 통과 |
| 7 | 종료한 job의 컨테이너가 늦게 생성됨 | 만료 job 목록이 비어 있어도 다음 reclaim에서 제거, DB 결과/비용 유지 | test_docker_reclaim_sweeps_late_orphan | 통과 |
| 8 | 컨테이너 내부 TCP·마운트 파일 append | ENETUNREACH/EROFS, 원본 frozen 유지 | test_docker_isolation | 통과 |
| 9 | 부모 키 설정·자원 검사 | 키 미전달, NetworkMode none/ReadonlyRootfs/Init/128MiB/1CPU/pids64 확인 | test_docker_isolation | 통과 |
| 10 | 같은 trial의 재시도·동시 세션 | 이름 2개와 lease 라벨 1/2 구분, 각 close 후 0 | test_docker_retry_names_unique | 통과 |
| 11 | 도구 호출 timeout/취소 | 환경 오류/RunCancelled, 세션 정리·잔여 0 | test_docker_call_abort (2종) | 통과 |
| 12 | Docker 정리 오류 모의 | 회수 롤백으로 leased/running 유지, daemon 복구 후 재회수 가능 | test_docker_reclaim_failure_blocks_requeue | 통과 |
| 13 | 컨테이너 env에 키 요청·설정 사후 변경 | 등록 거절·검증한 설정 불변 | test_docker_secret_environment_rejected / test_docker_environment_snapshot | 통과 |
| 14 | Docker CLI/daemon 없음 | Docker 통합 검사만 이유와 함께 skip | docker_cli fixture + Linux 전체 -rs 출력 | Docker CLI 없음 13건 skip 확인 |
| 15 | Docker 없는 Linux argv 생성 | Linux 절대 경로(공백 포함) RO 마운트·network none·read-only·init·메모리/CPU/pids 상한이 모두 있어야 함 | test_linux_docker_argv_without_docker (기본/사용자 자원값 2종) | Windows·Linux 통과, Docker/외부 프로세스 미사용 |

- 검증: 이전 Windows **314 passed → 최종 332 passed, 실패 0건·skip 0건**, `332 passed in 107.63s`. 기존 314개 + 신규 18개이며 Windows에서는 Docker 통합 검사 13개를 모두 실제 실행했습니다. Linux python:3.12-slim 일반 사용자/읽기 전용 저장소 복사본 전체는 **314 passed, 18 skipped, 1 warning in 36.37s**, 실패 0건입니다. skip은 Docker CLI 없음 13건 + 기존 Windows Job 전용 5건이며 이유를 출력했습니다. XDG_RUNTIME_DIR 경고는 이전과 같습니다. argv 순수 함수 단위 2건은 양쪽 모두 실행했고 subprocess.run/Popen 호출 자체를 금지했습니다. Linux 데이터 경로(공백 포함)와 network none·readonly 마운트·read-only root·init·메모리/CPU/pids 및 사용자 지정 상한 값이 빠지거나 달라지면 실패합니다. backend 전체 Ruff 0건, 변경 Python 7개 format 검사·diff 검사 통과. 새 테스트를 먼저 추가해 모듈/순수 함수 미구현 오류를 확인한 뒤 구현했습니다.
- 중간 검사: 첫 Docker 검사에서 격리 probe 모드가 아직 없어 신규 테스트가 실패했고 보완했습니다. 그 뒤 Linux 컨테이너의 errno=101을 Windows 호스트의 errno=10051과 비교하던 새 테스트의 플랫폼 가정을 오류 이름 ENETUNREACH/EROFS로 고쳤습니다. 기존 테스트는 수정하지 않았습니다. 늦은 Docker 생성 요청 경합과 현재 유효 임대 보존도 추가로 검증한 뒤 전체 실행을 완료했습니다.
- 테스트 자원: fixture가 메모리 tar로 임시 Dockerfile/서버 컨텍스트를 만들고 UUID 태그·라벨의 전용 이미지/데이터 볼륨을 생성합니다. 종료 시 해당 라벨의 컨테이너만 제거한 뒤 전용 이미지·볼륨을 제거합니다. 최종 docker ps/image ls/volume ls 확인에서 테스트 전용 잔여는 모두 0개였습니다. 최종 저장소 캐시 8개와 확인한 OS pytest 임시 폴더도 삭제했습니다. 전역 prune이나 다른 컨테이너·볼륨·사용자 이미지는 건드리지 않았습니다. 실제 공급자 API/② MCP 서버 호출은 0건입니다.

### 사용 경로

```python
# 신뢰한 실행 설정. 이미지/서버 인자/데이터 경로는 운영자가 지정합니다.
stdio = DockerStdioConfig(
    {"github": DockerServer(
        image="고정한-연습-서버-이미지",
        arguments=("서버가-받는-인자",),
        mounts=(ReadOnlyMount("Docker호스트의데이터절대경로", "/data"),),
    )},
    scope="해당-db-실행환경의-고유-scope",
)
run_once(connect, worker_id, deps=dependencies, stdio=stdio)
```

위 문자열은 설명용 자리표시자이며 그대로 실행하는 명령이 아닙니다. 운영 이미지는 아직 배포하지 않았고 실제 시험 이미지는 테스트 fixture에서만 만들고 삭제합니다. queue.reclaim을 직접 쓰는 운영 경로도 같은 scope/DB의 Docker 정리 hook을 연결해야 합니다. 기본 로컬 stdio 검증 경로는 보존했으며 실제 격리는 DockerStdioConfig를 명시한 경로에만 적용됩니다.

### 검증 제한·자동 승인 거절

- Linux에서도 실제 Docker 통합 검사를 돌리기 위해 테스트 실행기 컨테이너에 `/var/run/docker.sock`을 마운트하는 실행을 준비했지만 자동 승인 검토가 거절했습니다. 사유는 테스트 컨테이너가 호스트 Docker daemon을 광범위하게 제어할 수 있는 권한 경계를 노출한다는 것입니다. 이후 사용자가 **소켓을 마운트하지 말고 마무리**하도록 결정했습니다. 거절된 작업을 TCP proxy나 다른 경로로 우회하지 않았고 다시 소켓 마운트 승인을 요청하지 않습니다. **Linux 안에서 Docker 통합 13개를 실제 실행했다고 주장하지 않습니다.** 대신 docker_run_argv를 순수 함수로 분리하고 subprocess.run/Popen을 실행하면 실패하게 한 단위 테스트에서 Linux 경로·모든 필수 격리/자원 옵션의 존재와 값을 검사합니다.

### 남은 위험·다음 단계

- **Linux 호스트 실제 Docker 검증: 못 했음. 배포 전 일회용 VM 또는 CI 러너에서 확인 필요**
- 모든 워커가 죽거나 daemon이 멈춘 동안 즉시 컨테이너가 없어지는 보장은 없습니다. 다음 run_once/reclaim에서 정리하며 daemon 정리 실패는 오류로 드러내고 DB 재임대를 보류합니다. 매우 늦은 생성 요청도 다음 reclaim에서 재검사하므로 운영 워커의 반복 실행/정리 호출이 필요합니다. 같은 DB/daemon의 워커는 동일한 고유 scope를 사용해야 하고 다른 DB/실행 환경과 scope를 공유하면 안 됩니다.
- 원본 데이터 경로는 신뢰한 운영자가 정한 연습 데이터만 지정해야 합니다. 이 단계는 데이터 내용·해시/버전 검수나 이미지의 신뢰성 검토를 대신하지 않습니다. 실제 ② 이미지 digest/데이터 고정·sa_env_checks·P-05는 AGENTS 9번대로 대기합니다. Docker는 별도 VM급 격리를 의미하지 않으며 daemon/커널의 신뢰가 필요합니다.
- 기존 span.error 원문 기록, 원인 미분류 소진 trial, 실험 종료 게이트 제안 등 ②/사용자 합의 대기 사항은 그대로입니다. Windows Job의 CLI 등록 전 틈은 남지만 daemon 컨테이너는 독립 라벨 회수로 관리합니다.
- 이번 변경 파일: engine/eng_docker.py(신규 Docker 설정·수명·고아 정리), eng_stdio.py(내부 execution 인자 호환), worker.py(실행 식별자 전달), common/queue.py(선택적 회수 전 정리 hook), workers/eng_main.py(hook·DB 연결 전달), tests/test_eng_docker.py(신규), tests/eng_stdio_server.py(격리 probe), docs/handoff.md·checklist.md(기록). 계약·DB 변경·새 의존성·커밋·push·브랜치 전환은 없습니다.
- 공식 근거: [Docker 실행·제한 옵션](https://docs.docker.com/engine/containers/run/), [docker run의 init/rm/network 옵션](https://docs.docker.com/reference/cli/docker/container/run/), [읽기 전용 마운트](https://docs.docker.com/engine/storage/bind-mounts/).

## 2026-11-24 · Codex · taemin (MCP timeout 환경 오류 분류·span 오류 코드 검토)
- **1번 변경**: eng_stdio._rpc의 초기화/호출 무응답 기한 소진을 기존 `ToolEnvironmentError(reason='env_mcp_server_down')`으로 올리도록 수정했습니다. start에서 TimeoutError를 그대로 재전파하던 별도 catch를 제거해 native OSError 계열 시간 초과도 기존 환경 오류 처리로 들어갑니다. MCP 전용 timeout을 후보의 풀이 시간 초과로 세지 않습니다. advance.JOB_FAILURE_REASONS의 클래스명 `TimeoutError` 대응은 발생 위치를 확정할 수 없어 삭제했고, 명시적으로 기록된 기존 코드 `timeout_wall_clock`만 유지했습니다.
- **2번 보류·제안**: span.error는 계약상 자유 문자열일 뿐 도구 실행 실패용 기존 코드/의미가 정의돼 있지 않습니다. common.first_fail_type의 `tool_error`는 ②의 채점 단계 값이라 span 코드로 그대로 재사용한다는 합의도 없습니다. 사용자 조건대로 loop/계약을 이번에 수정하지 않았습니다. **②와 `span.error='mcp_tool_error'`를 유효한 MCP isError 실행 실패 코드로 합의하고, 오류 원문은 tool_result에만 두는 방식**을 제안합니다. 기술적으로 현재 스키마가 문자열을 받더라도 새 코드의 역할 간 의미를 혼자 확정하지 않았습니다. 코드 전용 error 테스트는 해당 동작을 아직 구현하지 않아 추가하지 않았고 기존 isError 회복 테스트는 그대로 유지했습니다.

### 실패 상황 표 — 최종본

| # | 상황·입력 | 기대 결과 | 테스트 이름 | 결과 |
|---|---|---|---|---|
| 1 | MCP 초기화 무응답 3회 | job failed/3·last_error=env_mcp_server_down, 모델/신규 비용 0, 수동 재개 거절 후 trial error/env_error, DB 분석 단위 제외 | test_mcp_initialize_timeout_exhaustion_is_environment_error | 통과 |
| 2 | 초기화/호출 무응답·손자 무응답 | 환경 오류, closed·트리 정리, 호출 전 받은 비용 보존 | test_initialize_timeout / test_concurrent_call_rejected / test_call_failure_is_saved[call_timeout-env_mcp_server_down] / test_process_tree_abort[timeout] | 통과 |
| 3 | 과거 job.last_error=TimeoutError | 발생 위치 추정 없이 UnmappedFailureError, 상태/원래 오류 보존 | test_resume_unknown_failure_is_reported[TimeoutError] | 통과 |
| 4 | 명시적 timeout_wall_clock 기록·실제 루프 시간 소진 | 기존 timeout 결과/실패 분류 유지 | test_resume_exhausted_is_terminal[timeout_wall_clock-timeout_wall_clock] / 기존 loop timeout 검사 | 통과 |
| 5 | span 오류 코드 미합의 | 새 코드·원문 저장 위치 변경 보류, ② 합의할 코드 제안 | 구현 안 함, 기존 isError 회복 검사 유지 | 보류 |

- 검증: 이전 Windows **312 passed → 314 passed, 실패 0건**(`314 passed in 76.20s`), Linux python:3.12-slim의 읽기 전용 저장소 복사본에서 일반 사용자 uv sync --frozen → uv run pytest는 **309 passed, 5 skipped, 1 warning in 45.13s**, 실패 0건입니다. 기존 Windows Job 전용 5개 skip과 XDG_RUNTIME_DIR 경고 1건은 동일합니다. backend 전체 Ruff·변경 실행 코드/회귀 테스트 format·diff 검사 통과. 새 통합 테스트를 먼저 추가해 기존 TimeoutError 전파로 실패하는 것을 확인한 뒤 구현했습니다. 분석 제외는 prereg 문자열 검사뿐 아니라 DB `analysis_units`가 `(included=false, exclude_reason='env_error')`를 돌려주는 것까지 확인했습니다.
- 바꾼 파일: engine/eng_stdio.py(MCP 기한 소진 환경 오류), engine/advance.py(모호한 클래스 대응 제거), tests/test_eng_stdio.py(새 요구에 맞춘 MCP timeout 기대만 변경), tests/test_eng_resume.py(명시적 timeout 코드/과거 클래스명 구분·초기화 소진 통합 검사), docs/handoff.md(이 기록). conftest/worker/eng_main/loop/계약/DB/다른 역할 파일은 이번에 수정하지 않았습니다. 커밋·push·브랜치 전환 없음.
- 남은 위험: 코드 합의 전이므로 span.error에 도구 오류 원문이 들어가는 기존 문제는 **아직 남아 있습니다**. 과거 TimeoutError 클래스명만 남은 소진 작업은 원인을 복원할 수 없어 자동 종결하지 않고 Unmapped로 보고합니다. MCP 원인을 확정할 자료가 있을 때만 사람이 검토해야 합니다. 실제 모델·외부 MCP/API 호출은 없고 이번 수정으로 재시도·재개 상한이나 prereg 정책을 바꾸지 않았습니다.

## 2026-11-24 · Codex · taemin (워커 stdio 연결·도구 실패 피드백·수동 재개)
- 한 일: 사용자 승인에 따라 `engine/loop.py`의 ToolExecutionError 경로와 `eng_stdio.StdioTools`의 isError=true 처리를 연결했습니다. 유효한 실패 콘텐츠는 예외로 모델 루프에 전달하되 세션은 ready를 유지합니다. 루프는 기존 자유 문자열 `span.error`에 오류 텍스트를 넣고 `tool_result`/tool 메시지에도 동일 텍스트를 넣어 대화를 계속합니다. 새 trace 필드·오류 코드·enum·계약·DB 변경은 없습니다. 빈 content·비텍스트 content·JSON-RPC error·다른 id·잘못된 JSON·서버 종료는 기존처럼 환경 오류와 세션 폐기를 유지합니다.
- 워커 연결: `LocalStdioConfig({서버명: 신뢰한 argv}, timeout_sec=...)`를 추가했습니다. `run_once(..., deps=..., stdio=설정)` → `run_trial` → `_execute_trial` 경로에서 DB 스냅샷에 있는 MCP 조회 도구만 서버별로 모아 새 StdioTools를 with/ExitStack으로 엽니다. 설정·예산·스냅샷 검사를 통과하고 trial running을 커밋한 뒤, 모델 호출 전에 초기화/목록/스키마 검사를 마칩니다. 준비 실패도 run_trial의 복구 경로에 들어가며 모델 호출은 0회입니다. 완료/오류/취소 때 세션을 최종 DB 저장 전에 닫습니다. 후보/모델/DB 메타데이터에서 임의 실행 명령을 만들지 않습니다. 실제 유료 모델이나 ② 서버를 기본 실행하지 않으며, 로컬 명령 설정은 운영자가 명시해야 합니다.
- 임대 상실: run_once의 `lost.is_set`을 cancel_signals에 직접 넘기고 기존 deps.cancelled도 함께 확인합니다. heartbeat는 기본 20초(기존 정책), 클라이언트는 전달받은 신호를 약 20ms 간격으로 확인하므로 신호 설정 후 MCP timeout까지 기다리지 않습니다. 실제 DB lease_until을 만료시키고 heartbeat가 renew 실패를 감지하는 통합 테스트에서 MCP 상한 10초 대신 3초 이내 RunCancelled·세션 종료를 확인했습니다. 옛 결과·trace는 0행, 이미 받은 모델 비용은 1행 유지됐고 만료 회수 뒤 trial pending/attempt=2·job queued가 됐습니다. 실제 임대 만료에서 감지까지의 지연은 heartbeat 주기·DB 응답에 좌우되므로 즉시 감지를 보장하는 표현은 쓰지 않습니다.
- 수동 재개: `advance.resume_failed_trial(conn, trial_id)`는 IDLE 연결의 짧은 트랜잭션에서 job → experiment → trial 순서로 잠그고 lock/statement timeout 5초를 적용합니다. 같은 최신 failed job만 queued로 바꾸며 attempts·last_error·trial attempt·비용은 초기화하지 않습니다. 이미 queued/leased이면 재개하지 않은 결과를 반환하고, 다른 활성 작업이 있으면 거절합니다. 두 연결이 같은 trial을 동시에 재개해도 새 job은 생성되지 않고 resumed=True는 한 번뿐입니다. 공통 `TRIAL_JOB_MAX_ATTEMPTS=3`을 사용해 run_once도 3을 넘는 상한 설정을 거절합니다. 자동 재개 호출·상한 초기화·새 run_no 생성은 없습니다.
- 소진 종결: 사용자 확인대로 새 failed 상태 대신 기존 `trial.status='error'`를 씁니다. 재개 함수 호출 시 이미 3회를 소진했고 원인을 대응할 수 있으면 같은 트랜잭션에서 outcome_reason·기존 prereg 기반 run_outcome·finished_at을 기록하고 `on_trial_finished`로 기존 다음 단계 게이트를 확인합니다. 작업은 failed/attempts=3으로, job.last_error와 비용은 그대로 남습니다. 종결 커밋을 롤백시키지 않도록 예외 대신 `ResumeResult(resumed=False, exhausted=True)`로 재개 거절을 반환합니다. 현재 자동 워커의 기존 failed/pending 처리 자체는 바꾸지 않았으므로, 소진 종결은 사람이 이 함수를 호출할 때 수행됩니다. 재개 거절 뒤 대상 실험에 pending이 0개가 되는 경우를 실제 DB로 검증했습니다.

### 마지막 작업 오류 대응표 — 코드 한 곳

`engine/advance.py:JOB_FAILURE_REASONS`만 대응표를 관리합니다. 현재 저장소의 이전 ToolEnvironmentError 발생처는 기본 MCP 오류를 사용하는 stdio이므로 과거 클래스명 기록을 호환합니다. 새 워커 기록은 ToolEnvironmentError의 reason을 직접 보존하고, lost가 설정된 RunCancelled는 env_worker_lost로 식별합니다. 수동 재개/종결은 기존 last_error를 덮어쓰지 않습니다.

| job.last_error | 기존 outcome_reason |
|---|---|
| ToolEnvironmentError / env_mcp_server_down | env_mcp_server_down |
| lease_expired / LeaseLost / env_worker_lost | env_worker_lost |
| TimeoutError / timeout_wall_clock | timeout_wall_clock |

- **임의 대응하지 않은 원인**: RuntimeError, ValueError, TypeError, NotImplementedError, CostPersistenceError, CostConflictError, OperationalError/InterfaceError 등 DB 오류, lost가 확인되지 않은 RunCancelled, NULL 및 표에 없는 모든 분류입니다. 엔진 설정/비용 저장 오류를 agent_crash나 연습 DB 오류로 바꾸면 잘못된 통계가 되므로 추정하지 않았습니다. 상한 소진 시 이들은 `UnmappedFailureError.classification`으로 보고하고 상태를 보존합니다. 따라서 이 경우에는 pending이 남을 수 있으며 **"모든 원인의 pending 제거 완료"를 주장하지 않습니다**. RuntimeError/ValueError/CostPersistenceError/NULL의 거절·원본 보존 테스트를 추가했습니다. 원인 확인 또는 팀이 합의한 기존 값 대응이 더 필요합니다.
- **③ 통계 한 줄**: 현재 예시 prereg에서 env_mcp_server_down/env_worker_lost는 env_error → retry_then_exclude이며 DB analysis_units는 해당 후보 쌍을 제외합니다. timeout_wall_clock은 timeout → 실패로 셉니다. 실제 실험은 그 실험의 prereg.outcome_rules.env_error_reasons를 그대로 따릅니다. 정책·③ 계산 코드는 수정하지 않았고 실제 통계 리포트 생성 완료를 주장하지 않습니다.

### 실패 상황 표 — 최종본

| # | 상황·입력 | 기대 결과 / 확인 결과 | 테스트 이름 | 결과 |
|---|---|---|---|---|
| 1 | isError=true 후 같은 세션으로 재호출 | ready 유지, 실패 텍스트 피드백, 다음 성공·최종 답변, 환경 오류 span 없음 | test_iserror_then_success_and_trace / test_worker_iserror_is_not_environment_failure | 통과 |
| 2 | 빈/잘못된 응답·다른 ID·서버 종료 | 기존 환경 오류·폐기 유지 | 기존 test_bad_response_closes_session의 나머지 5종 | 통과·기존 본문/나머지 사례 무수정 |
| 3 | 워커 stdio 정상 연결 | worker가 세션 생성·종료, finished/done, trace 3행·비용 2행 | test_worker_creates_and_closes_stdio_session | 통과 |
| 4 | 같은 설정으로 두 풀이 | 각 풀이에 서로 다른 새 세션, 둘 다 종료 | test_worker_session_is_per_trial | 통과 |
| 5 | MCP 시작 실패 3회 | 모델 0회·비용 0행, 기존 복구·상한으로 failed/3 | test_worker_setup_failure_is_recovered | 통과 |
| 6 | MCP 대기 중 실제 DB 임대 만료 | heartbeat 상실 신호 후 timeout 전 취소·세션 정리, 회수·비용 보존 | test_worker_lost_interrupts_stdio_wait | 통과 |
| 7 | 성공 응답 뒤 최종 인계 예외 | trace/결과 롤백, pending 복구, 비용 2행·세션 정리 | test_worker_stdio_handoff_rollback | 통과 |
| 8 | attempts=1인 failed 작업 수동 재개 | 동일 job 1→2→3 누적, 재실패 후에도 상한 초기화 없음 | test_resume_preserves_attempt_budget | 통과 |
| 9 | 두 연결 동시 재개 | queued 1개, 새 job 없음, 한 호출만 resumed=True | test_resume_concurrently_once | 통과 |
| 10 | 3회 소진 MCP/임대/timeout | 재개 거절·error 종결·last_error/비용 보존, pending 0 | test_resume_exhausted_is_terminal (3종) | 통과 |
| 11 | 대응할 수 없는 소진 원인 | 명시적 오류·원인 분류 보존, 임의 종결 없음 | test_resume_unknown_failure_is_reported (4종) | 통과 |
| 12 | 중단/완료/없는 trial | 재개 거절·추가 작업 없음 | test_resume_invalid_state (3종) | 통과 |
| 13 | 종결 후 다음 단계 트랜잭션 실패 | error 전이 롤백, failed job/시도 횟수 보존 | test_resume_transaction_rollback | 통과 |
| 14 | 상한 4로 워커 호출 | 작업 임대 전에 거절 | test_worker_cannot_raise_global_attempt_limit | 통과 |
| 15 | 중복 임대·강제 종료·DB 단절 등 | 기존 복구/비용/펜싱 유지 | 기존 전체 큐·비용·엔진 검사 | 통과 |

- **요구 변경으로 기존 테스트 1건 교체**: 사용자 승인에 따라 test_bad_response_closes_session의 tool_error 사례만 제거했습니다. 이유는 isError=true의 의미 변경이며, 이전 기대 "환경 오류·세션 폐기" → 새 기대 "같은 세션 재호출 성공·대화 계속·trace 도구 오류 기록"입니다. bad_json/empty/wrong_id/bad_content/exit와 기존 테스트 본문은 한 글자도 바꾸지 않았고, 다른 기존 테스트는 수정하지 않았습니다.
- 검증: 이전 Windows **292 passed → 312 passed, 실패 0건**(`312 passed in 60.39s`). Linux python:3.12-slim의 읽기 전용 저장소 복사본에서 일반 사용자 uv sync --frozen → uv run pytest는 **307 passed, 5 skipped, 1 warning in 46.05s**, 실패 0건입니다. Windows Job 전용 5개만 skip, XDG_RUNTIME_DIR 경고는 이전과 같습니다. 기존 1건 교체 + 신규 20건(워커 6·재개 14)입니다. 테스트 선작성 후 LocalStdioConfig/재개 함수가 없어 실패하는 것을 먼저 확인했습니다. backend 전체 Ruff 0건, 변경된 실행 코드·새 테스트 등 7개 format 검사·diff 검사 통과. 기존 advance.py는 범위 밖의 포맷만 바꾸는 수정을 피했고 추가 코드의 Ruff check는 통과했습니다. 실제 모델·외부 MCP/API 호출·② 파일 수정·새 의존성·계약·마이그레이션 변경 없음.

### 실험 종료 시 미처리 pending 정리 — 제안만

- `advance.on_reports_done`에서 done 전환 전에 "failed run_trial job + pending trial"을 확인하고 정상 done을 거절하는 종료 게이트를 두는 방안을 제안합니다. 사람이 재개를 포기하고 종료를 선택한 경우 별도 명시적 정리 함수가 상태를 잠근 뒤 `stop_experiment(..., 'job_failed')`로 실험을 failed로 끝내고 남은 pending은 기존 규칙대로 cancelled로 정리할 수 있습니다. 이 경우 원인을 알 수 없는 trial을 후보 실패로 꾸며 넣지 않고 last_error·비용도 보존합니다. 현재 P-08은 채점/분석 작업 실패만 실험 failed로 정하므로 이 확대 정책은 합의 후 구현해야 합니다. 이번에는 사용자 요청대로 제안만 남겼습니다.
- **3회 소진 뒤에도 다시 실행하는 새 정책은 이번에 만들지 않았습니다. 필요해지면 총시도 한도·사람 승인 기록을 별도로 정합니다.**

### 남은 위험·사용 범위

- 신뢰한 명령을 제공한 run_once/run_trial 경로에는 실제로 연결됐지만 배포용 반복 워커 진입점·registry 기본 설정·UI/API 운영 화면은 이번 범위 밖입니다. `resume_failed_trial`도 사람이 호출하는 내부 함수이며 엔드포인트는 만들지 않았습니다.
- 소진 종결은 명시적 재개 함수 호출 시 수행합니다. 원인 미분류·DB 실패·운영자 미호출에서는 pending이 남을 수 있으며 이를 숨기지 않습니다. 자동 무한 재개로 이를 덮지 않았습니다. 대응표의 과거 ToolEnvironmentError 매핑은 현재 저장소 발생처 기준입니다. 외부 코드에서 다른 reason으로 같은 옛 클래스명만 저장한 이력이 있으면 먼저 검토해야 합니다.
- 기본 heartbeat 20초와 DB 응답 지연은 실제 상실 감지 시간을 좌우합니다. 신호가 설정되면 즉시 취소 확인 경로를 타지만 DB 호출 자체의 강제 중단 기능을 추가한 것은 아닙니다. 사용자 취소를 StdioTools의 신호에 넣지 않고 DB 상태만 바꾸는 외부 경로는 기존 단계 사이 검사를 따릅니다.
- Windows Job 생성·등록 사이 suspended 자식 잔존 틈, POSIX 워커 강제 종료 시 자식 자동 정리 부재, 파일/네트워크 비격리, 비용 커밋 전 사망 구간은 여전히 남습니다. Docker·② 실제 서버·데이터/이미지 환경 검사는 다음 단계입니다.
- 이번 변경 파일: engine/advance.py(수동 재개·대응표·상한), loop.py(도구 실패 피드백), worker.py(세션 수명), eng_stdio.py(isError/로컬 설정), workers/eng_main.py(lost 주입·정확한 실패 분류), tests/eng_stdio_server.py(실패 후 성공 모드), test_eng_stdio.py(승인한 1건 교체), test_eng_worker_stdio.py(신규), test_eng_resume.py(신규), docs/checklist.md(① 부분 완료), docs/handoff.md(이 기록). 이전 conftest 등 작업은 그대로 보존했습니다. 커밋·push·브랜치 전환 없음.

## 2026-11-24 · Codex · taemin (공용 pg 픽스처 — Linux 소켓 URL 보존)
- 한 일: `backend/tests/conftest.py`의 pgserver 주소 처리만 작은 `database_url(url, dbname)` 함수로 분리했습니다. `urllib.parse.urlsplit(...)._replace(path=...).geturl()`로 DB 경로만 바꾸며 사용자 정보·TCP 호스트/포트·소켓 host query를 보존합니다. pg의 관리자 연결은 /postgres, 마이그레이션·yield는 /e2e URL을 사용합니다. 픽스처 이름·scope·반환값의 PostgreSQL URL 문자열 형식은 유지했습니다. key=value conninfo는 사용하지 않습니다.
- 변경 범위: conftest의 URL import/함수와 pg 내 주소 생성, 새 `tests/test_eng_conftest_url.py`, 이 기록만입니다. `common/db.py`의 URL 검사, 다른 기존 테스트·마이그레이션·계약·체크리스트·의존성 파일은 이번에 수정하지 않았습니다. 기존 미커밋 stdio 작업은 보존했습니다. 커밋·push·브랜치 전환 없음.
- 검증: 테스트를 먼저 추가해 helper 미구현으로 import 오류가 나는 것을 확인한 뒤 구현했습니다. Windows 전체는 **288 passed → 292 passed, 실패 0건**(`scripts/test.ps1`, `292 passed in 59.86s`). Linux `python:3.12-slim`(Debian 13, Python 3.12.16)에서는 **287 passed, 5 skipped, 실패 0건**, `287 passed, 5 skipped, 1 warning in 32.88s`입니다. Windows Job 전용 5개만 skip됐습니다. backend 전체 Ruff 0건, 변경 Python 2개 format 검사·git diff --check 통과. 실제 모델·외부 API 호출은 없습니다. 컨테이너에는 기존 lock의 패키지를 uv sync --frozen으로 설치했으며 저장소 의존성 추가는 없습니다.

### 실패 상황 표 — 최종본

| # | 상황 | 입력/상태 | 기대 결과 | 테스트 이름 | 통과 여부 |
|---|---|---|---|---|---|
| 1 | Windows TCP URL | 사용자 정보·포트·sslmode query 포함 | /postgres만 /e2e로 교체, 나머지 보존 | test_windows_url_changes_only_database | Windows·Linux 통과 |
| 2 | Linux 소켓 URL | postgresql://postgres:@/postgres?host=/tmp/tmpabc | postgresql://postgres:@/e2e?host=/tmp/tmpabc | test_socket_url_preserves_host_query | Windows·Linux 통과 |
| 3 | 제품 DB 설정 검사 | 위 두 주소를 변환해 DATABASE_URL로 설정 | db.get_database_url 통과, URL 문자열 유지 | test_database_url_passes_product_validation (2종) | Windows·Linux 통과 |

- 큐 running 복구·재시도·중복 워커·비용·트랜잭션은 URL을 바꾸는 순수 함수의 변경 범위가 아니며 동작을 수정하지 않았습니다. 해당 기존 검사는 양쪽 OS 전체 실행에 포함됐습니다. Linux에서 기존 제품 DB 연결/커밋/롤백 검사도 통과해 key=value conninfo 변경에 따른 4건의 DatabaseConfigurationError가 발생하지 않았습니다.

### Linux 재현 명령 — 저장소 파일 그대로 실행

저장소는 /src에 읽기 전용 마운트하고 /work로 복사합니다. 가상환경·Git·node_modules·캐시·비밀 환경 파일은 복사하지 않습니다. slim 이미지의 실행 라이브러리와 uv 설치/복사 준비만 root로 하고, uv sync --frozen → uv run pytest는 새 일반 사용자로 실행합니다. 실행 전후 cmp로 conftest가 원본과 같은지 검사합니다. 컨테이너 복사본의 conftest를 따로 수정하는 단계는 없습니다.

```powershell
$pgLinuxScript = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends libicu76 libxml2 libxslt1.1 libldap2 liblz4-1 libpq5 >/dev/null
python -m pip install --no-cache-dir -q uv
useradd --create-home --shell /bin/bash slotagent_test
mkdir /work
tar -C /src --exclude=.git --exclude=.venv --exclude=node_modules --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache --exclude=.env --exclude=.aws --exclude=.codex -cf - . | tar -C /work -xf -
chown -R slotagent_test:slotagent_test /work
cmp /src/backend/tests/conftest.py /work/backend/tests/conftest.py
runuser -u slotagent_test -- bash -c 'set -euo pipefail; cd /work/backend; uv sync --frozen; uv run pytest'
cmp /src/backend/tests/conftest.py /work/backend/tests/conftest.py
'@
docker run --rm --name slotagent-conftest-url-check -v 'D:/final_project:/src:ro' python:3.12-slim bash -c $pgLinuxScript
```

### 남은 위험·팀 공지

- conftest.py는 모든 역할이 함께 쓰므로 ②③④의 DB 테스트에도 영향을 줍니다. 픽스처 인터페이스는 유지했고 현재 저장소의 양쪽 OS 전체 테스트는 통과했지만, 각 역할의 미병합 테스트까지 검증한 것은 아닙니다.
- 팀에 알릴 한 줄: **공용 pg 픽스처의 DB명 변경을 URL path 교체로 수정해 Linux 소켓 host query를 보존했습니다. pg 이름·PostgreSQL URL 반환 형식은 유지했으며 Windows 292 passed / Linux 287 passed·5 skipped로 확인했습니다.** 실제 메시지 전송은 하지 않았습니다.
- Linux는 `test_eng_costs.py::test_error_before_model_response_records_no_cost[ValueError]`에서 XDG_RUNTIME_DIR 미설정에 따른 platformdirs RuntimeDirWarning 1건이 있었으며 /tmp/runtime-1000으로 대체됐습니다. 실패는 아닙니다. Docker 이미지 태그와 OS 패키지 저장소는 시간에 따라 바뀔 수 있으므로 재현 시 동일 환경 확인이 필요합니다.

## 2026-11-24 · Codex · taemin (eng_stdio 보완 — 프로세스 트리·종료 실패·스키마 비교)
- 한 일: 이번 수정은 `engine/eng_stdio.py`, `tests/test_eng_stdio.py`, `tests/eng_stdio_server.py`, 이 기록만입니다. loop/worker/eng_main/계약/DB/체크리스트는 이번에 수정하지 않았습니다. 작업 시작 때 이미 남아 있던 이전 stdio 구현·체크리스트·인계 기록 변경은 보존했습니다. 새 의존성·커밋·push·브랜치 전환 없음.
- Windows 트리: 새 의존성 없이 ctypes로 익명·비상속 Job Object를 만들고 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`를 설정합니다. 자식은 `CREATE_NO_WINDOW | CREATE_SUSPENDED`로 생성 → AssignProcessToJobObject → Toolhelp/OpenThread/ResumeThread로 실행 재개합니다. Popen이 주 스레드 핸들을 닫으므로 문서화된 API로 주 스레드를 다시 엽니다. Job 생성/설정/등록/재개 실패는 시작 거절·ToolEnvironmentError로 올리며, 등록 실패한 suspended 자식도 종료합니다. close는 루트가 이미 종료됐어도 TerminateJobObject로 손자 전체를 종료하고 QueryInformationJobObject의 ActiveProcesses=0 및 루트 wait를 확인한 뒤 핸들을 닫습니다. 손자가 Job 핸들을 상속하지 않아 준비 완료 후 워커 강제 종료 때도 마지막 핸들 소멸로 트리가 종료됩니다.
- POSIX 트리: `start_new_session=True`로 생성하고 close에서 루트 PID를 그룹 ID로 `os.killpg(..., SIGKILL)`합니다. 루트가 이미 종료됐어도 그룹 종료를 시도합니다. 현재 실행 환경은 Windows라 POSIX 실제 실행 검증은 **못 했음**입니다.
- 작은 보완: 스키마 비교는 양쪽 최상위 `$schema`만 제외하고 나머지는 그대로 완전 일치시킵니다. 중첩 `$schema`도 비교하며 원본을 변경하지 않습니다. `cancel_signals=(사용자_취소, 임대_상실, ...)`를 추가해 기존 cancelled와 OR 결합하고 시작 전·응답 대기 중 확인합니다. close의 각 정리 단계 오류를 모아, 앞 단계가 실패해도 프로세스/Job 종료 확인·Job 핸들 해제·closed 전이를 수행한 뒤 RuntimeError를 올립니다. 이미 closed이면 다시 close해도 아무 작업도 하지 않습니다. 실제 IO가 계속 살아 있으면 파이프 close가 내부 lock에서 무한 대기하지 않도록 파이프를 닫지 않고 오류로 보고합니다.
- 검증: 이전 전체 **272 passed → 이번 전체 288 passed, 실패 0건**. 최종 출력은 `288 passed in 48.42s` (`scripts/test.ps1`, backend 전체)입니다. backend 전체 Ruff 0건, 지정 Python 3개 format 검사 통과. 기존 31개 stdio 테스트의 기대값은 유지하고 16개를 추가했습니다. 구현 전에 신규 스키마·복합 취소 테스트 3개가 실패함을 확인했습니다. 중간 실행에서 테스트 중간 실행기의 stdout/stdin 상속이 불명확해 트리 테스트 6개가 실패했으며, 서버의 Popen에 stdin/stdout/stderr 상속을 명시한 뒤 트리 관련 7개가 통과했습니다. 그 후 전체 테스트를 통과했습니다. 실제 모델·외부 API 호출은 0건입니다.

### 실패 상황 표 — 최종본

| # | 상황·입력 | 기대 결과 / 확인 결과 | 테스트 이름 | 통과 여부 |
|---|---|---|---|---|
| 1 | stdout을 상속한 손자 서버, 정상 조회 후 close | 루트·손자 종료, IO 정리, closed | test_process_tree_close | 통과 |
| 2 | 실행기 먼저 종료, 손자만 파이프 유지 | 루트 생존 여부와 무관하게 트리 종료, close 성공 | test_exited_launcher_tree_close | 통과 |
| 3 | 손자 호출 무응답, timeout/취소 | TimeoutError/RunCancelled 유지, 손자 종료·closed | test_process_tree_abort (2종) | 통과 |
| 4 | 별도 Python 워커에서 시작 완료 후 worker.kill | 루트·손자 PID 모두 종료, Job 핸들 사망 정리 | test_worker_kill_closes_job_tree | 통과 (Windows 실제 프로세스) |
| 5 | Job 생성·설정·등록·재개 OSError | ToolEnvironmentError, 생성된 프로세스와 Job 핸들 정리 | test_job_setup_failure (4종) | 통과 |
| 6 | IO join에서 RuntimeError 모의 | 프로세스/Job 종료·핸들 해제·closed, 오류 보고, 재close 안전 | test_close_failure_still_closes_tree | 통과 |
| 7 | 트리 종료 단계 오류 모의 | 종료 확인 단계도 실행, Job 해제·closed 뒤 오류 | test_tree_termination_failure_still_closes | 통과 |
| 8 | 양쪽 최상위 $schema만 다름 | 시작 검사 통과, 원본 불변 | test_top_level_schema_keyword_ignored | 통과 |
| 9 | properties 또는 중첩 $schema 차이 | 이전처럼 시작 거절 | test_other_schema_differences_rejected (2종) | 통과 |
| 10 | 복합 취소 신호 중 하나 설정 | 어느 신호든 대기 중 RunCancelled·세션 정리 | test_combined_cancel_signals (2종) | 통과 |
| 11 | 작업 3회 시작 실패 | 기존 job failed/3, trial pending/4 유지, 더는 임대 안 됨 | 기존 test_start_failure_retry_limit | 통과 (수정 없음) |
| 12 | isError=true 정상 MCP 결과 | 아래 인터페이스 제약으로 변경 보류, 기존 동작 유지 | 기존 test_bad_response_closes_session[tool_error] | 기존 동작 통과 / 새 기능 미구현 |

### 작업 2 — isError 구분은 범위 조건에 따라 미구현

- 조사: `engine/loop.py:run_agent`의 잘못된 도구 호출 피드백은 도구 이름/JSON/스키마 검사에서 `call_tool` 호출 **전에** 지역 변수 error/result를 만드는 경로입니다. `Dependencies.call_tool`은 문자열만 반환하며, 반환 후 오류 표시를 읽는 코드가 없습니다. 현재 catch는 ToolEnvironmentError(환경 오류로 종료)와 TimeoutError(시간 초과로 종료)뿐입니다. 따라서 eng_stdio만 바꿔 isError 내용을 문자열로 반환하면 모델 전달은 되지만 span.error가 남지 않습니다. 문자열 subclass나 내용에서 오류 여부를 추정해 이 제약을 우회하지 않았습니다. 사용자가 "loop나 계약을 고쳐야 하면 구현하지 말 것"이라고 한 조건에 따라 isError 처리와 기존 테스트 기대값을 유지했습니다.
- 제안(미수정): `engine/loop.py`에 텍스트를 담은 별도 ToolExecutionError를 정의하고 도구 호출부에서 잡아 `error='mcp_tool_error'`, `result=도구가 준 텍스트`, `reason=None`으로 기록한 뒤 기존 tool 메시지 추가 경로를 계속 타게 합니다. 그 후 eng_stdio는 유효한 isError=true를 이 예외로 전달하되 ready를 유지하고, 프로토콜/콘텐츠 오류만 세션을 폐기합니다. trace.span.error는 현재 자유 문자열이므로 이 방식에는 JSON 스키마 변경이 필요하지 않아 보이지만 loop 수정 승인이 필요합니다. `test_iserror_then_success` 및 run_agent trace/모델 피드백 테스트를 그 작업에 추가해야 합니다.

### 작업 3 — 맡을 작업이 없는 pending trial은 실제로 남을 수 있음 (코드 미수정)

- 순서: `worker.run_trial`이 running을 커밋 → 준비/실행 예외 → `worker._release_attempt`가 pending으로 반환하며 attempt 증가 → `eng_main.run_once`가 should_retry를 검사 → 3회째에는 `queue.fail(retry=False)` → `_recover_trial`의 queued 결과를 job failed로 저장합니다. 최종 job failed/attempts=3, trial pending/attempt=4이며 다음 lease는 queued만 보므로 이 trial을 더는 잡지 않습니다. 예외 경로는 `advance.on_trial_finished`도 호출하지 않습니다.
- 정리 경로: `advance.stop_experiment`를 명시적으로 부르면 pending을 cancelled로 바꾸지만, run_trial 작업 상한 때문에 자동으로 이 함수를 부르는 경로는 없습니다. `queue.reclaim`도 leased 만료만 보므로 failed 작업을 재등록하지 않습니다. `advance._scope_for`가 부르는 DB `grading_scope_unfinished`는 pending을 미완료로 세어 채점 진행도 막습니다. 현재 api 폴더에는 이를 재개하는 구현도 없습니다. 따라서 외부 조작/명시적 중단 없이는 실험 running과 pending trial이 계속 남을 수 있습니다. 어제 기록의 의도인 "원인 수정 뒤 작업 재등록"은 맞지만 그 운영 절차/API가 아직 구현되지 않은 상태입니다.
- 제안(미수정): 상태 책임자인 `engine/advance.py`에 명시적 재개 함수(예: requeue_failed_trial)를 두고, 같은 트랜잭션에서 experiment/trial을 잠가 실험 running·trial pending·마지막 작업 failed·queued/leased 중복 없음 확인 후 `advance.enqueue`로 새 run_trial 작업을 한 번만 생성합니다. 기존 실패 작업·attempt·비용은 보존하고 새 실행에서도 기존 예산 검사를 수행합니다. `workers/eng_main.py:run_once`의 최종 failed 분기에 운영 조치 필요를 노출하고, 이후 승인받은 API/운영 명령에서만 재개 함수를 호출하는 방안을 권합니다. 재시도 상한을 자동 초기화하는 무한 재등록이나 trial 실패만으로 실험 failed를 확정하는 정책은 넣지 않습니다(P-08 범위 유지).

### 작업 4 — 어댑터 준비 완료, 워커 연결은 제안만

- 구현한 부분: StdioTools의 cancelled와 추가 cancel_signals를 OR로 결합합니다. 이미 제공받은 Event.is_set 신호는 응답 대기 중에도 약 20ms 간격으로 확인합니다. 이 주기는 OS 스케줄링·콜백 실행 시간에 따라 달라지는 확인 간격이며 보장된 종료 지연이 아닙니다.
- 제안(미수정): `workers/eng_main.py:run_once`의 stopped/lost 생성 후에 풀이별 deps/도구 세션을 만드는 factory 경로를 두고 `lost.is_set`과 기존 deps.cancelled를 새 StdioTools에 전달해야 합니다. 지금처럼 완성된 deps를 먼저 받고 replace만 하면 기존 client 내부에는 lost가 전달되지 않습니다. 공유 client의 콜백을 뒤늦게 바꾸기보다 attempt마다 새 세션을 만들고 finally/ExitStack에서 종료하는 구조를 권합니다. `engine/worker.py:_execute_trial`의 실험 중단·현재 attempt 검사까지 즉시 연결하려면 그 최종 cancelled 콜백을 도구 수명주기에 주입하는 별도 확장이 필요합니다. 이번에는 두 파일을 수정하지 않아 내부 lost는 아직 자동 연결되지 않습니다.

### 남은 위험 — Windows Job Object 한계 포함

- **생성과 등록 사이 틈**: CREATE_SUSPENDED로 Job 등록 전 서버 실행/손자 생성을 막았습니다. 그러나 Popen이 자식을 만든 직후 AssignProcessToJobObject 이전에 워커가 강제 종료되면 Job 밖의 정지된 자식이 남을 수 있습니다. 이번 강제 종료 검증은 start 완료 후이며 이 틈의 완전 제거를 주장하지 않습니다. 완전히 없애려면 Job을 생성 시 원자적으로 지정하는 PROC_THREAD_ATTRIBUTE_JOB_LIST 기반 CreateProcess 경로를 별도 검토해야 합니다(현재 Popen 래퍼 범위보다 큼).
- **중첩 Job·권한**: 이미 다른 Job에 속한 실행 환경의 UI 제한·중첩 정책, 관리자/보안 토큰 차이 등으로 등록/종료가 거절될 수 있습니다. 이 경우 보장을 낮춰 실행하지 않고 ToolEnvironmentError로 시작을 거절합니다. 실제 API 자체의 종료/핸들 해제 실패는 close에서 오류를 보고하며 정상 종료로 숨기지 않습니다. 보호 프로세스·모든 권한 조합은 검증하지 않았습니다. CPython 3.12 Windows Popen의 `_handle`을 사용하므로 Python 구현 변경 시 재검토가 필요합니다.
- **격리 범위**: Job은 프로세스 수명 관리이며 파일·네트워크 격리가 아닙니다. Docker 단계는 여전히 필요합니다. POSIX는 새 session/group 안의 프로세스만 종료하므로 서버가 setsid 등으로 탈출하면 이 방식만으로 막지 못하며, 워커 SIGKILL 때 그룹이 자동 종료되는 기능도 없습니다. POSIX 실제 실행 검증은 못 했습니다.
- **기타 미완료**: isError 구분, failed 작업의 명시적 재개, run_once 내부 임대 신호 자동 주입은 위 제안대로 남아 있습니다. 모델 응답 뒤 비용 커밋 전 종료의 기존 미보존 구간과 최종 저장 전 메모리 trace 유실은 이번 작업으로 해결하지 않았습니다.
- 공식 근거: [Job과 마지막 핸들 소멸](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [등록·중첩·suspended 요구](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject), [트리 종료](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject), [주 스레드 재개](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread).

## 2026-11-24 · Codex · taemin (로컬 MCP stdio 최소 연결 — Docker 전 단계)
- 한 일: 어제 채팅의 다음 목표인 "가짜 모델 → 로컬 MCP 조회 → 최종 답변"을 완료했습니다. `engine/eng_stdio.py`에 신뢰한 호출자가 지정한 argv로 시작하는 조회 전용 `StdioTools`를 추가했습니다. MCP 2025-11-25 initialize → initialized → tools/list → tools/call 순서로 실행하고, 후보 도구 이름·입력 스키마를 검사합니다. 모델에는 기존 후보 정의만 노출하고, 서버에 추가 도구가 있어도 호출 허용 목록을 넓히지 않습니다. TextContent 문자열은 JSON 배열을 포함해 원문대로 연결합니다. 기존 loop/worker/run_once의 명시적 Dependencies.call_tool 주입을 사용했고 기존 실행 파일은 변경하지 않았습니다.
- 상한·정리: 기본 연결/요청 상한 5초(도구 호출은 풀이 남은 시간과 둘 중 작은 값), 메시지 1MiB, 요청당 수신 메시지 128개입니다. 페이지 목록·멀티미디어·서버 역방향 요청은 최소 연결에서 지원하지 않습니다. 연결 재시도·모델 자동 재호출은 없습니다. 시작/호출 실패는 세션을 폐기합니다. 상태 전이는 한 함수로 검사하며 동시 호출은 거절합니다. API 키·DATABASE_URL 등 부모 환경은 상속하지 않고 Windows 기본 환경과 PYTHONUTF8만 전달합니다. stderr는 DEVNULL로 보내 버퍼 정체를 막습니다. 프로세스 terminate 대기 0.5초 → kill 대기 0.5초, IO 스레드 대기 0.5초 상한으로 정리합니다.
- 사용 범위: 풀이 attempt마다 새 인스턴스를 만들고 모델 호출 전에 `with StdioTools(argv, 해당_서버의_조회_도구) as client:`로 시작 검사 후 `Dependencies(fake_model, client)`를 run_trial 또는 run_once에 주입합니다. 실행 중 취소 신호를 즉시 전파하려면 client.cancelled와 deps.cancelled에 같은 신호를 주입합니다. 현재 run_once의 내부 임대 상실 신호는 client에 자동 연결되지 않으므로, 대기 중 임대 상실은 요청 시간 상한 뒤 기존 guard로 차단합니다. 실제 시험에서 만료 회수 뒤 옛 결과·trace 저장이 차단되고 비용 1행은 유지됐습니다.
- 검증: 시작 전 전체 **241 passed → 272 passed, 실패 0건**(`scripts/test.ps1`, backend 전체), Ruff 전체 0건, 추가 Python 3개 format 검사 통과. 새 테스트 31개는 ① 전용 `tests/eng_stdio_server.py`의 실제 로컬 자식 프로세스와 임시 PostgreSQL, 가짜 모델만 사용합니다. 실제 공급자 API·GitHub·② 서버 호출은 0건입니다. 먼저 테스트를 추가해 미구현 모듈 오류를 확인한 뒤 구현했습니다. 중간 실행의 새 테스트 구성에 쓰기 도구가 포함된 오류를 조회 전용으로 바로잡았고, 초기화 TimeoutError가 OSError에 잡혀 환경 오류로 바뀌던 구현 오류도 수정했습니다. 기존 테스트는 수정하지 않았습니다.

### 실패 상황 표 — 최종 검증

| # | 상황·입력 | 기대 결과 / 확인한 상태 | 테스트 이름 | 결과 |
|---|---|---|---|---|
| 1 | 없는 실행 파일·초기화 무응답 | 오류/timeout, 프로세스·IO 정리 | test_start_failure / test_initialize_timeout | 통과 |
| 2 | 빈/누락/중복 목록·다른 스키마 | 실행 전 환경 오류, 세션 폐기 | test_tool_inventory_rejected (4종) | 통과 |
| 3 | 호출 중 종료·무응답 | trial error, job done, 환경 오류/timeout span, 받은 비용 1행 유지, 모델 1회 | test_call_failure_is_saved (2종) | 통과 |
| 4 | 빈/잘못된 JSON·다른 ID·빈 결과·isError | 환경 오류, 세션 폐기, 다시 호출 거절 | test_bad_response_closes_session (6종) | 통과 |
| 5 | None/빈 명령·없는 도구·None/잘못된 인자·0/NaN 시간 | 시작 또는 전송 전에 ValueError | test_invalid_command (4종) / test_invalid_input_not_sent (5종) | 통과 |
| 6 | 동시 요청·완료 trial 중복 실행 | 동시 요청 거절, 완료 trial의 모델·도구 호출 증가 없음 | test_concurrent_call_rejected / test_trial_round_trip | 통과 |
| 7 | 대기 중 취소·임대 만료 회수 | 세션 종료, trial pending/attempt=2·job queued, 옛 결과/trace 0행·받은 비용 1행 | test_cancel_during_call / test_cancel_during_call_restores_trial / test_lease_loss_during_call_is_fenced | 통과 |
| 8 | 작업 준비 중 시작 실패 3회 | 기존 재시도 상한 후 job failed/attempts=3, trial pending/attempt=4, 비용 0행, 이후 임대 없음 | test_start_failure_retry_limit | 통과 |
| 9 | MCP 성공 뒤 최종 인계 RuntimeError | 결과/trace 롤백, trial pending/attempt=2·job queued, 비용 2행 보존 | test_handoff_failure_keeps_cost | 통과 |
| 10 | 조회→최종 답변·stderr 대량 출력 | trial finished·job done, trace 3행·비용 2행, 모델에 조회 JSON 전달, 프로세스/IO 종료·키 미상속 | test_trial_round_trip / test_text_content_and_stderr | 통과 |

- 범위 밖: Docker·컨테이너별 환경 검사(sa_env_checks)·데이터/이미지 fingerprint·② 평가팩 실제 연결·P-05·실제 모델·채점 완료는 이번에 구현하지 않았습니다. 새 의존성·계약·DB·다른 역할 파일·기존 테스트·기존 워커를 변경하지 않았고 커밋·push·브랜치 전환도 하지 않았습니다. 시작 실패 재시도 검사는 가짜 모델의 준비 단계에 client.start를 주입해 기존 run_once 복구 경로를 확인한 것이며, 배포용 자동 준비/연결 진입점을 만든 것은 아닙니다.
- 남은 위험: 로컬 실행은 격리가 아닙니다. 워커 자체 강제 종료 시 자식/손자 프로세스 종료 보장은 이번 범위에 없고 Docker 단계에서 보완해야 합니다. 기존 강제 종료·DB 단절의 trial/job 임대 회수 테스트는 전체 실행에 포함됐습니다. 취소/예외의 최종 저장 전 메모리 trace는 기존대로 남지 않을 수 있으나 이미 커밋한 모델 비용은 보존됩니다. isError/미지원 콘텐츠 등은 현재 최소 어댑터에서 env_mcp_server_down으로 거절하므로 제품 도구 오류 의미 구분은 후속 연결 검토가 필요합니다. MCP 연결/서버 동작은 자체 테스트 서버 기준으로만 확인했고 범용 MCP 호환 완료가 아닙니다. 기존 개발 DB의 전날 비용 칼럼 추가 SQL 적용은 이번에 수행하지 않았습니다.
- ② 인계 보류 사항: Downloads의 role2_handoff_20261124.md는 후속 준비 완료를 보고하지만, 11/24 fetch한 origin/minha 최신 593f9ad에는 `packs/it_ops/v0.1/practice/servers.json`, `test_pack_independent.py`, `test_pack_loader.py`가 없습니다. 평가팩 일부·P-05 계약 커밋 e7bdee7은 있으나 load_pack/lock_pack/select_tasks는 미구현입니다. 문서의 후속 작업 커밋을 받기 전 ①이 대신 구현하지 않습니다. fetch만 했고 minha 병합/파일 반영은 하지 않았습니다.

## 2026-11-23 · Codex · taemin (중간 비용 보존 완료 — 임시 DB·가짜 모델)
- 한 일: 사용자 승인 조건대로 `0003_review_1122.sql` 끝에 nullable `sa_cost_ledger.attempt`·`span_seq`와 `source='trial'` 부분 UNIQUE(ref_id,attempt,span_seq)인 `sa_cost_ledger_trial_call_once`만 추가했습니다. 칼럼·인덱스 COMMENT, db_names·NAMES 대응표, contracts/CHANGELOG의 DB 변경 한 줄(②④ 코드 영향 없음)을 맞췄습니다. JSON 스키마·새 마이그레이션 파일·judge/chat/validation 구현은 변경하지 않았습니다. db_names는 Ruff 형식도 맞췄습니다.
- 실행 경로: DB 없는 loop의 `Dependencies.on_model_span`이 모델 응답을 받은 직후, 소유권·취소·시간 검사보다 먼저 호출됩니다. worker가 `engine/costs.record_trial_cost`로 짧은 트랜잭션을 커밋합니다. 비용에는 queue.guard·현재 attempt·실험 상태 조건을 걸지 않으므로 옛 워커나 stopped 실험의 이미 받은 응답 비용도 보존됩니다. 기존 결과·trace 저장은 계속 현재 임대·attempt를 검사합니다. stopped 확인을 단계 사이와 최종 저장에 반영해 비용 기록 뒤 새 호출을 막습니다.
- 중복 처리: 중간·최종 저장 모두 같은 `INSERT ... ON CONFLICT (ref_id,attempt,span_seq) WHERE source='trial' DO NOTHING`을 사용합니다. 충돌하면 기존 experiment·model·입력/출력 토큰·금액·가격표를 읽어 비교합니다. 다른 값은 CostConflictError(ValueError)입니다. 같은 값만 아무것도 추가하지 않습니다. trials.cost_krw는 최종 성공 attempt의 합, 예산 장부는 실패·옛 attempt를 포함한 실제 저장 지출 합입니다.
- 재시도: 비용 DB 오류는 원문 없는 CostPersistenceError(RuntimeError)로 올립니다. 비용 전용 재시도·새 연결·대기·모델 재호출 장치는 없습니다. 기존 run_once의 작업 최대 3회만 적용하며 연결이 끊긴 경우 기존 임대 회수로 복구합니다. 아래 이전 계획의 "비용 저장 별도 재시도 검토"는 사용자 지시로 폐기했고 이번 구현에 없습니다.
- 검증: `scripts/test.ps1` **241 passed**(기존 216 + 새 비용 검사 25), backend 전체 Ruff 0건, 변경 Python 7개 `ruff format --check` 통과, `git diff --check` 통과. 테스트는 임시 PostgreSQL과 가짜 모델만 사용했고 실제 모델·외부 서비스 호출은 0건입니다. 기존 최종 저장 실패 테스트 두 개의 비용 0행 기대는 새 요구에 맞춰 비용 보존·새 attempt 누적 기대로 변경했고, trace·결과 롤백 검사는 유지했습니다. 이전 워커 차단 테스트도 늦은 비용 1행이 더 보존되는 기대로 변경했습니다. 기존 DB 연결·채점/리포트/chat 등 통합 테스트를 포함해 모두 통과했으며 judge/chat/validation의 같은 키 2행 허용과 기존 trial의 NULL 키 허용도 추가 검증했습니다.

### 실패 상황 표 — 확인한 최종 DB 상태

`a`는 시작 trial attempt, `j`는 시작 작업 임대 횟수, C는 이미 응답을 받은 호출 비용입니다. 실제 유료·외부 호출은 전 행 0건이며 표의 모델 횟수는 가짜 모델 기준입니다.

| 상황 | trial status/attempt | job status | 비용 장부·호출 횟수 |
|---|---|---|---|
| 응답 전 ValueError/NotImplementedError | pending/a+1 | failed | 신규 비용 0, 모의 진입 1회 뒤 중단 |
| 응답 전 RuntimeError | pending/a+1 | queued, 상한이면 failed | 신규 비용 0, 모의 진입 1회 뒤 중단 |
| 응답 저장 뒤 ValueError/NotImplementedError | pending/a+1 | failed | C 유지, 모델 1회·두 번째 모델 호출 없음 |
| 응답 저장 뒤 RuntimeError | pending/a+1 | queued, 상한이면 failed | C 유지, 한 시도에 모델 1회 |
| 비용 INSERT DB 오류 | 복구 뒤 pending/a+1 | queued→3회째 failed | INSERT 롤백이면 장부 증가 없음. 모델·비용 INSERT 각각 총 3회, 도구 0회, 비용 자체 재시도 없음 |
| 비용 COMMIT 후 응답 유실 | pending/a+1 | queued | C가 1행 유지. 같은 영수증 수동 재전달 시험에서도 1행, 모델 1회 |
| 최종 결과 저장·인계 실패 | pending/a+1 | queued | trace·결과는 롤백, 응답 2회의 비용 2행·0.264원 유지 |
| 응답 비용 커밋 뒤 프로세스 os._exit | 회수 후 pending/a+1, 재실행 후 finished/a+1 | queued 후 done | 옛 비용 0.12원 유지, 새 시도 후 3행·0.384원. 새 모델 호출 2회 |
| 응답 수신 직후 DB 연결 강제 종료 | 다른 연결의 임대 회수 후 pending/a+1 | queued | 미커밋 비용은 장부에 없음. 모델 1회 뒤 중단. 이는 미보존 위험 구간이며 실제 과금 0원으로 해석하지 않음 |
| 옛 워커의 응답이 새 attempt 완료 뒤 도착 | 새 finished/a+1 그대로 | 새 done 그대로 | 옛 비용도 추가. 옛 결과·trace와 다음 호출은 차단 |
| 같은 키 중복·두 연결 동시 INSERT | 기존 상태 그대로 | 기존 상태 그대로 | 한 행만 저장, 비용 재전달의 모델·도구 호출 0회 |
| 같은 키 금액/입력 토큰/출력 토큰 불일치 | worker 경로는 pending/a+1 | failed | 기존 금액 유지, 오류 노출, 이후 자동 실행 없음 |
| 정상 최종 저장·완료 요청 중복 | finished/a 그대로 | done | seq=1·3 비용 두 행만 유지, 중복 요청의 모델 호출 0회 |
| 반복 RuntimeError | 3회 뒤 pending/a+3 | failed, 이후 빌려주지 않음 | 모델 총 3회, 비용 3행·0.36원 유지 |
| 중간에 stopped, 진행 중 응답 도착 | cancelled/a+1 | cancelled | 늦은 C 유지, 모델 1회·도구 0회 |
| 실패 attempt 비용으로 예산 소진 | 다음 시작 때 cancelled/a+1 | 처리된 현재 작업 done | 저장된 100원으로 budget 중단. 두 번째 시도의 모델 호출 0회 |

DB 단절·프로세스 종료에서 running을 최종 정상 기대로 두지 않고 실제 회수까지 수행해 상태를 확인했습니다. 비용 저장만 호출하는 중복 검사는 trial·job을 변경하지 않으며, 작업 경로의 예외 분기는 별도 테스트에서 확인했습니다.

### 대표 시나리오 — 옛 응답 2원 + 새 응답 3원

| 단계 | 입력·출력 | DB 상태 |
|---|---|---|
| 1 | A가 T/attempt=1/seq=1 호출, 응답을 지연시킴 | running/1, A leased, 비용 0행 |
| 2 | A 임대 만료·회수 후 B가 attempt=2로 재실행 | running/2, B leased |
| 3 | B가 3원 응답을 저장하고 결과까지 완료 | finished/2, job done, 비용 (T,2,1) 1행·3원 |
| 4 | A의 2원 응답이 뒤늦게 도착 | 비용 (T,1,1) 추가, finished/2·done 유지, 옛 결과 저장 차단 |
| 5 | A의 같은 비용 기록 재전달 | 비용 총 2행·5원 유지, 새로운 모델 호출 없음 |

테스트에서는 새 attempt가 이미 완료된 더 엄격한 시점에 옛 비용을 기록했습니다. 두 모델은 각각 1회 호출됐고 결과 span은 attempt=2만 남았습니다.

### 새 raise와 호출부 점검

- `CostConflictError(ValueError)`: 중간/최종 비용 값 충돌 → run_trial 복구 → run_once 즉시 failed. 이미 저장한 비용 유지, 새 결과 롤백.
- `CostPersistenceError(RuntimeError)`: 비용 SQL·커밋·연결 오류 → 다음 모델/도구 호출 중단 → 기존 복구/작업 재시도 상한. DB 원문은 from None으로 숨깁니다. 연결 자체가 끊기면 복구 실패 안내 후 기존 임대 회수가 담당합니다.
- 최종 저장의 새 `RunCancelled`: 실험이 stopped/failed이면 결과를 저장하지 않고 기존 예외 복구를 통해 cancelled로 반환합니다. 비용은 별도 커밋이라 유지합니다.
- record_trial_cost의 중간·최종 호출부, on_model_span의 기본 no-op·worker 주입·테스트 주입, Recorder.model과 loop의 예외 처리, queue.fail/reclaim·should_retry를 rg로 확인했습니다. 새로운 예외를 후보 오답으로 저장하지 않습니다. 모델 ModelError 처리와 JSON trace 계약은 변경하지 않았습니다.

### 남은 빈틈

- 중요: 제공자 과금 후 응답/사용량을 받기 전 종료, 응답 뒤 비용 커밋 전 종료·DB 단절은 확정 비용을 복구하지 못합니다. DB 장애 때문에 새 attempt로 다시 모델을 부르면 이전 미저장 과금이 있을 수 있습니다. 요청대로 별도 비용 재시도 장치는 만들지 않았고 기존 최대 3회에서 멈춥니다. llm 어댑터가 사용량 없는 ModelError로 전달한 호출도 비용을 복원할 수 없습니다.
- 중요: 기존 개발 DB에는 이번 끝부분 SQL을 적용하지 않았습니다. 기존 DB에서 새 실행 코드를 쓰기 전 승인한 추가 구문을 적용해야 합니다. 0003 전체 재실행은 기존 ALTER와 충돌하므로 하지 않았습니다. 검증은 전체 마이그레이션을 처음부터 적용한 임시 DB 기준입니다.
- 중요·범위 제외: pending 풀이 + failed 작업의 재개 절차/API는 구현하지 않았습니다. 로컬 MCP stdio·Docker·P-05 준비도 이번 작업에 포함하지 않았습니다.
- 작음: 늦은 비용은 이미 시작한 다른 호출을 소급 차단하지 못합니다. 예산 검사는 기존 합의대로 풀이 시작 시점 기준이며 회수·재시도에 따른 누적 비용은 다음 시작부터 반영합니다. 기존 NULL 키 장부는 과거 호출로 역추정해 채우지 않았습니다.
- 의문점: 사용자 허용 범위 내에서 구현 완료. 새 마이그레이션·추가 CHECK·JSON 계약 변경·의존성 추가·커밋·push 없음.

## 2026-11-23 · Codex · taemin (중간 비용 보존 — 구현 전 표·DB 의문점)
- 한 일: 사용자 추가 조건을 반영해 비용 기록과 결과 저장의 권한을 분리했습니다. 사용량을 이미 받은 응답의 비용은 임대 상실·attempt 변경·실험 중단 뒤에도 기록해야 하며 queue.guard로 막지 않습니다. 중복 식별자는 `(trial_id, attempt, span_seq)`입니다. 동일 키 재전송·동시 기록·커밋 응답 유실 뒤 재전송·최종 저장에서 장부는 한 번만 증가해야 합니다. 코드·계약·DB 수정, API 호출·테스트 실행, 커밋·push는 하지 않았습니다.
- 의문점 (구현 중지 사유): 현재 sa_cost_ledger에는 attempt·span_seq가 없으며 source=trial의 ref_id는 trial_id입니다. sa_spans에는 UNIQUE(trial_id,attempt,seq)가 있지만 spans_current_attempt 트리거가 현재 running attempt의 INSERT만 받으므로, 임대 회수 뒤 늦게 온 비용의 중복 식별자로 대신 사용할 수 없습니다. 기존 ref_id 의미를 바꾸거나 결과 trace의 펜싱을 풀지 않습니다. 제안은 비용 장부에 nullable attempt·span_seq를 추가하고 source='trial'의 (ref_id,attempt,span_seq)에 부분 UNIQUE를 두는 것입니다(기존 비용 행·다른 source 처리와 이름 대응표는 변경 검토 시 명시). 마이그레이션은 이번 지시에서 허용되지 않아 구현하지 않았습니다. 아래는 목표 동작 표이며 구현·검증 완료 기록이 아닙니다.

### 구현 전 실패 상황 표

기준: 시작은 trial running/attempt=a, job leased/attempts=j, 기존 장부 L. C는 모델에서 사용량을 받은 응답 한 건의 비용이며 키 K=(trial_id,a,span_seq). 일반 경로는 run_once의 작업 최대 3회 정책을 사용합니다. 모든 시험은 가짜 모델로 수행하며 실제 모델·외부 서비스 호출은 0건입니다. 아래 호출 수는 가짜 모델 호출 횟수입니다.

| 경로·실패 상황 | sa_trials.status/attempt | sa_jobs.status | 장부 | 추가 호출·복구 |
|---|---|---|---|---|
| 모델 호출 전 ValueError | pending/a+1 (실행 시작 전이면 기존 상태 유지) | failed | L | 모델 0회, 자동 재실행 없음 |
| 응답·비용 저장 뒤 ValueError | pending/a+1 | failed | L+C 유지 | 이미 호출한 1회, 오류 뒤 모델 호출 0회 |
| 응답·비용 저장 뒤 NotImplementedError | pending/a+1 | failed | L+C 유지 | 이미 호출한 1회, 오류 뒤 모델 호출 0회 |
| 응답·비용 저장 뒤 RuntimeError | pending/a+1 | queued, 작업 상한이면 failed | L+C 유지 | 같은 비용 재전송은 모델 0회. 풀이 재실행은 별도 새 attempt·새 비용이며 작업 상한 적용 |
| 비용 INSERT의 DB 오류·커밋 전 실패 | 연결 복구 가능하면 pending/a+1, 불가능하면 임대 회수 뒤 pending/a+1 | 반환/회수 후 queued 또는 상한의 failed | INSERT 롤백이면 L. 응답 C는 보존되지 않은 위험 구간 | 다음 모델 호출 중단. 응답이 메모리에 있으면 새 DB 연결로 동일 K 저장을 제한적으로 재시도하는 방안 검토. 비용 저장 재시도는 모델 재호출이 아님 |
| 비용 COMMIT은 됐지만 DB 응답 유실 | 연결 복구/임대 회수 후 pending/a+1 또는 새 워커 상태 | queued/상한 failed 또는 새 워커 상태 | 동일 K 재전송 후 정확히 L+C | 비용 재전송으로 모델을 다시 부르지 않음 |
| 비용 저장 후 최종 결과 DB 저장 실패 | pending/a+1 또는 임대 회수 뒤 복구 | queued/상한 failed | L+C 유지, 최종 저장 롤백과 독립 | 재실행 비용은 별도 attempt. 이전 C를 다시 합산하지 않음 |
| 응답·비용 저장 후 프로세스 강제 종료 | 임대 회수 뒤 pending/a+1 | queued 또는 상한 failed | L+C 유지 | 죽은 워커의 메모리에 의존하지 않음 |
| 제공자 호출 중/응답 뒤 비용 커밋 전 강제 종료 | 임대 회수 뒤 pending/a+1 | queued 또는 상한 failed | 마지막 커밋 금액 L만 보장 | 실제 과금 여부·미저장 C를 확정할 수 없음. 완전 보존 미해결로 보고하며 0원으로 단정하지 않음 |
| 임대 회수 후 옛 워커가 응답을 받음 | 새 attempt·완료 상태를 그대로 유지 | 새 워커의 작업 상태 그대로 | 옛 K의 C도 L에 한 번 더함 | 비용 저장에는 guard 없음. 옛 워커는 결과·상태 저장과 다음 모델/도구 호출 금지 |
| 동일 K를 두 번 전달·두 연결 동시 기록 | 변화 없음 | 변화 없음 | C 한 번만 추가 | 비용 저장 자체는 모델/도구 호출 0회. 단순 SELECT 뒤 INSERT만으로 중복 방지하지 않음 |
| 동일 trial·seq지만 attempt가 다름 | 현재 attempt의 상태 유지 | 현재 작업 상태 유지 | 서로 다른 실제 응답 비용은 각각 추가 | 옛 시도 비용을 새 시도로 합쳐 중복으로 오인하지 않음 |
| 정상 최종 저장·완료 요청 중복 | finished/a, 이후 그대로 | done | 중간 저장의 C를 재추가하지 않음 | 완료된 풀이 재요청은 모델 호출 0회 |
| 같은 실패가 계속 반복 | 매 회수/복구 때 attempt 증가, 상한 뒤 pending | 영구 오류 즉시 failed, 나머지 최대 3회 뒤 failed | 저장된 모든 attempt 비용 누적 | 자동 반복은 유한. S=max_steps, R=max_api_retries이면 가짜 모델의 SDK 요청 상한은 작업당 보수적으로 3×S×(R+1), 실제로는 예산·단계 상한이 먼저 막을 수 있음 |
| 실험 stopped, 응답이 진행 중이었다면 | 응답 비용 기록은 상태를 바꾸지 않음. 소유 중 실행 중단의 복구 또는 임대 회수 뒤 cancelled | 반환/회수 뒤 cancelled (이미 완료된 작업은 유지) | 중단 뒤 도착한 확정 비용 C도 한 번 기록 | 진행 중 호출을 없던 것으로 보지 않음. 취소 확인 뒤 다음 모델·도구 호출 0회 |

DB 장애·프로세스 종료 행의 running은 최종 기대값이 아닙니다. 복구/임대 회수를 실제로 수행한 뒤의 상태를 검사합니다. 회수하려면 DB와 회수 워커가 다시 사용 가능해야 합니다. 비용 기록은 소유권이 아니라, 워커가 호출 시작 때 고정한 trial·attempt·seq·가격표·사용량의 유효성을 검사합니다. 동일 K의 서로 다른 금액/토큰을 조용히 같은 응답으로 간주할지는 사전 검증에서 다뤄야 합니다.

### 대표 시나리오: 늦은 비용 응답·중복·최종 저장

| 단계 | 입력·출력 | trial / job | 장부·가짜 모델 호출 |
|---|---|---|---|
| 1 | 워커 A가 trial T, attempt=1, seq=1 모델 호출 시작 | running/1, A leased | L=0, 호출 누적 1 |
| 2 | A 임대 만료 후 회수, B가 같은 풀이를 새 attempt로 시작 | running/2, B leased | L=0, A의 미완료 과금은 아직 확정할 수 없음 |
| 3 | A가 사용량 있는 응답 C1=2원을 받음 | running/2와 B leased 그대로 | K=(T,1,1)로 2원 저장. guard로 거부하지 않음 |
| 4 | 저장 응답 유실을 가정해 A가 같은 K·C1 재전송 | B 상태 그대로 | L=2원 유지, 재전송의 모델 호출 0회 |
| 5 | A가 다음 단계를 시도 | B 상태 그대로, A 결과 저장 거부 | 추가 모델/도구 호출 0회 |
| 6 | B가 응답 C2=3원을 받고 비용 저장 | running/2, B leased | K=(T,2,1)로 저장, L=5원, 모델 호출 누적 2 |
| 7 | B가 최종 결과·trace·다음 단계·작업 완료 저장 | finished/2, done | 장부 L=5원 유지. 결과의 현재 attempt 비용과 실험 전체 지출을 구분 |
| 8 | 동일 완료 요청 재전달 | finished/2, done 그대로 | 장부 2행·5원, 모델 호출 누적 2 유지 |

### 남은 빈틈

- 중요: 비용 저장이 DB에 커밋되기 전 프로세스가 죽거나 제공자 과금 후 사용량을 받지 못한 경우는 이 설계만으로 확정 비용을 복구할 수 없습니다. 제공자 사용량 대조·내구성 있는 별도 전달 등은 추가 설계가 필요합니다. 늦은 비용이 예산 검사 이후 도착해 이미 시작한 호출까지 취소할 수는 없습니다.
- 중요·이번 범위 제외: pending 풀이 + failed 작업의 운영자 재개 절차/API는 사용자 지시대로 구현하지 않습니다. 이 상태를 복구 완료로 표시하지 않습니다.
- 작음: 비용 저장 재시도의 연결 팩터리·상한·대기 간격은 표 검토 후 정해야 합니다. 무제한 재시도나 비용 재전송을 위한 모델 재호출은 하지 않습니다.
- 남은 일: 비용용 중복 식별자 DB 변경의 허용 범위 확인 → 표 확정 → 구현·DB 통합 검사. checklist 완료 표시 없음.

## 2026-11-23 · Codex · taemin (중간발표 자료 수정)
- 다운로드 보완: 발표 뷰어 내보내기 연결이 실패해 확인된 19장 레이아웃에서 편집 가능한 표·텍스트·도식을 복원한 `output/presentation/SlotAgent_중간발표_수정본.pptx`를 저장했습니다. PPTX 구조·글꼴·배치 검사 0건, 재불러오기 19장 확인 및 전체 렌더 검토 완료. 검증 영수증은 `output/.pptx-validation/validation.json`입니다.
- 한 일: 사용자 제공 PPTX를 별도 발표 아티팩트로 불러와 본문 16장·부록 3장으로 재구성했습니다. 에이전트 기본 개념, 6쪽 가상 수치 비교 표, 8쪽 구체적 핵심 기능, 평가 파이프라인·축약 ERD를 반영하고 백업 1~3의 검증·도메인·비용 내용을 본문에 통합했습니다. 최신 프로젝트 규칙에 맞춰 50개 문항 유형·자체 실행 루프·DB 기록 원본을 적용했습니다. 19장 전체 렌더링으로 표·한글·줄바꿈·배치를 확인했습니다.
- 남은 일: 실제 성능 비교 수치는 아직 없어 6쪽을 설명용 가상 예시로 명시했습니다. 진행 현황은 11/23 인계 기록 기준입니다. 사용자는 발표 뷰어에서 PPTX로 내보낼 수 있습니다. 제품 코드·계약·체크리스트 완료 상태는 변경하지 않았고 제품 테스트·커밋·push는 수행하지 않았습니다.
- 의문점: 없음. PDF의 제안은 참고 자료로 사용하고 중간발표의 세부 설명을 줄이라는 사용자 요청을 우선했습니다.

## 2026-11-23 · Codex · taemin (모델 3사 연결 — SDK 모의 응답까지)
- 한 일: `common/llm.py`에 `ProviderModel(clients=..., clock=..., sleep=...)`을 추가해 provider로 네 회사를 선택합니다. 기존 `ChatModel.chat` 인자·`Reply`·`ModelError`와 OpenAI 전용 `OpenAIModel(client=...)`은 유지했습니다. 기존 OpenAI 테스트 본문은 바꾸지 않았습니다. 재시도 while 루프는 `_with_retries` 하나이며 모든 SDK 생성·요청에서 max_retries=0입니다. Google·DeepSeek은 OpenAI SDK, Anthropic은 anthropic SDK를 사용합니다. Anthropic system 분리·tool_use/tool_result·여러 도구 결과 병합·종료 이유 변환을 추가했습니다. 객체가 아닌 tool input은 JSON 문자열로 원래 값을 보존해 루프가 agent_invalid_tool_call로 돌려줍니다. 다음 Anthropic 요청에서는 API가 객체만 받는 tool_use 대신 해당 잘못된 호출과 오류 결과를 글 블록으로 보존해 모델이 수정할 수 있게 합니다(정상 호출은 tool_use/tool_result 그대로). Gemini의 빈 문자열·null·누락·공백 ID는 기존 대화와 현재 응답 ID에 겹치지 않게 생성하며 다음 요청의 tool_call_id와 같습니다.
- 의존성: pyproject에 anthropic만 추가했습니다. uv.lock은 anthropic 2.12.0과 전이 의존성 docstring-parser 0.18.0만 추가됐고 기존 패키지 버전은 유지했습니다. scripts/test.ps1에는 --with anthropic만 추가했습니다(이전 작업의 --with openai 유지).
- 검증: `scripts/test.ps1` 전체 **216 passed**(기존 101 + 새 모의 검사 115), backend 전체 `uv run ruff check .` 0건, 수정 Python 두 파일 `ruff format --check` 통과, `uv lock --check --offline` 235 packages 일치, `git diff --check` 통과. 모든 llm 테스트에서 실제 SDK 생성자를 차단하고 주입한 모의 클라이언트만 사용했습니다. 키 관련 검사는 모의 환경 값·빈 dotenv를 사용하므로 로컬 OpenAI 키도 호출하지 않았습니다. 기존 테스트 외에 네 회사의 아래 표·SDK 오류 원문/키의 메시지 및 traceback 비노출·SDK 생성 옵션·메시지 왕복·Gemini ID 충돌 회피·Anthropic 비객체 인자 및 정상/비정상 혼합 호출 피드백을 확인했습니다.

### 회사별 실패 상황 표 (SDK 모의 응답)

각 요청은 0.1초, 재시도 상한 R=2, 대기는 1초→2초입니다. 측정값은 `api_retries / wait_sec / duration_sec` 순이며 duration은 대기를 제외합니다. ValueError에는 기존 인터페이스대로 이 필드가 없습니다. 대기 후 실제 요청을 못 했어도 기존 동작대로 api_retries가 증가합니다.

| 상황 | OpenAI | Google | DeepSeek | Anthropic | 측정값 |
|---|---|---|---|---|---|
| 429가 3회 계속됨 | ModelError(llm_api_429) | 같음 | 같음 | 같음 | 2 / 3 / 0.3 |
| 5xx·529 후 성공 | Reply | 같음 | 같음 | 같음 | 1 / 1 / 0.2 |
| 연결 오류 후 성공 | Reply | 같음 | 같음 | 같음 | 1 / 1 / 0.2 |
| 5xx가 3회 계속됨 | ModelError(env_llm_api_5xx) | 같음 | 같음 | 같음 | 2 / 3 / 0.3 |
| timeout_sec=0.5, 첫 오류 뒤 대기 중 소진 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 1 / 0.4 / 0.1, 두 번째 요청 없음 |
| SDK 시간 초과 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 0 / 0 / 0.1 |
| 요청 전 제한 시간 소진 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 0 / 0 / 0, 요청 없음 |
| 성공 응답이 제한 시간을 넘어 도착 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 0 / 0 / 실제 경과, 모의 검사는 0.1 |
| 400·401·403 | ValueError | 같음 | 같음 | 같음 | 필드 없음, 모의 경과 0.1·1회 요청 |
| 사용량 또는 입력/출력 토큰 수 누락 | ValueError | 같음 | 같음 | 같음 | 필드 없음, 모의 경과 0.1·1회 요청 |
| 빈 객체 도구 인자 | Reply, arguments="{}" | 같음 | 같음 | input={} → arguments="{}" | 0 / 0 / 0.1 |
| 빈 문자열 도구 인자 | Reply, arguments="" 그대로 | 같음 | 같음 | input="" → JSON 문자열 '\"\"', 비객체 값도 그대로 JSON 직렬화 | 0 / 0 / 0.1, 루프가 잘못된 인자로 기록·모델에 피드백 |
| 텍스트+도구 호출 | 둘 다 보존한 Reply | 같음 | 같음 | 같음 | 0 / 0 / 0.1 |
| 키 없음 | 요청 전 ValueError | 같음 | 같음 | 같음 | 필드 없음, 경과 0·요청 0회 |
| 출력 토큰 한도로 잘림 | Reply(length) | 같음 | 같음 | max_tokens → length | 0 / 0 / 0.1 |
| 비어 있는 도구 호출 ID | 기존 동작 유지 | 겹치지 않는 ID를 채운 Reply, 다음 tool_call_id 일치 | 기존 동작 유지 | 기존 동작 유지 | Google 0 / 0 / 0.1, 별도 대기·재호출 없음 |

### 보내지 않은 인자·변환 표

| 회사 | 보내지 않는 값 | 보내는 형태·이유 |
|---|---|---|
| OpenAI | max_tokens=None일 때 출력 상한, 비어 있는 tools | 기존 seed·temperature·max_completion_tokens 동작 유지 |
| Google | seed, max_completion_tokens | seed 명시 지원을 공식 호환 문서에서 확인하지 못해 생략. 상한이 있으면 max_tokens, 없으면 생략 |
| DeepSeek | seed, max_completion_tokens | 공식 Chat Completions 인자 목록에 seed 없음. 상한이 있으면 max_tokens, 없으면 생략 |
| Anthropic | seed, OpenAI 형식의 system 메시지·tool_calls·tool 역할·parameters·max_completion_tokens | system은 최상위, tool_use/tool_result, input_schema, 필수 max_tokens로 변환. max_tokens=None은 요청 전 ValueError |
| 공통 | 도구 정의의 access·origin·capabilities 등 내부 속성, price·max_api_retries·timeout_sec라는 API 본문 필드 | 이름·설명·입력 스키마만 전달. 가격은 로컬 계산, 재시도는 공용 루프, 남은 시간은 SDK timeout 옵션 |

공식 확인: [Gemini 호환 주소](https://aistudio.google.com/docs/openai?hl=ko) = `https://generativelanguage.googleapis.com/v1beta/openai/`, [DeepSeek 주소](https://api-docs.deepseek.com/) = `https://api.deepseek.com`, [DeepSeek 인자](https://api-docs.deepseek.com/api/create-chat-completion/), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Anthropic 오류·529](https://platform.claude.com/docs/en/api/errors), [Anthropic tool_result 선행 순서](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls). seed를 생략한 회사에서는 같은 seed에 따른 재현성을 보장하지 않습니다.

### 새 raise가 워커까지 전달될 때

| 위치·발생 조건 | 최종 처리 |
|---|---|
| 공용 재시도: 요청 전 시간 소진 | ModelError(timeout_wall_clock) → loop가 풀이 결과로 기록 |
| 공용 재시도: SDK timeout·429/5xx/연결 오류 재시도 소진 | ModelError(기존 이유) → loop가 prereg에 따라 풀이 결과로 기록 |
| 공용 재시도: 제한 시간을 넘어 도착한 성공 | ModelError(timeout_wall_clock) → loop가 풀이 결과로 기록 |
| 공용 재시도: 인증·요청 4xx | ValueError → worker가 현재 풀이 복구, eng_main이 작업 failed |
| _api_key: 회사 키 없음·빈 값 | ValueError → 현재 풀이 복구·작업 failed, API 요청 없음 |
| _tokens: 사용량 누락·음수·정수 아님 | ValueError → 현재 풀이 복구·작업 failed |
| _openai_reply: 응답·사용량 모양 부족 | 원문 없는 ValueError → 현재 풀이 복구·작업 failed |
| _anthropic_reply: 응답·사용량 모양 부족 | 원문 없는 ValueError → 현재 풀이 복구·작업 failed. JSON 비객체 인자는 예외가 아님 |
| anthropic_messages: 알 수 없는 메시지 역할 | ValueError → 현재 풀이 복구·작업 failed |
| ProviderModel: 지원하지 않는 provider | NotImplementedError → 현재 풀이 복구·작업 failed |
| ProviderModel: Anthropic max_tokens=None | ValueError → 현재 풀이 복구·작업 failed, API 요청 없음 |
| OpenAIModel: OpenAI 외 provider | 기존 전용 클래스의 NotImplementedError 유지 → 현재 풀이 복구·작업 failed |

`engine/loop.py`의 chat 호출·Reply.message·도구 JSON 검사·ModelError 처리와 `engine/worker.py`의 예외 복구, `workers/eng_main.py`의 즉시 실패 분기를 읽기 전용으로 재확인했습니다. engine·workers는 수정하지 않았습니다.

### 남은 빈틈·의문점

- 중요: 실제 API는 호출하지 않았습니다. 현재 로컬 키는 OpenAI만 있다는 사용자 설명을 기준으로 하며 추가 키를 요구하거나 읽어 출력하지 않았습니다. SDK 모의 성공은 실제 모델 호환성을 보장하지 않습니다. 체크리스트의 실제 API 확인은 미완료로 유지합니다.
- 중요: 입력이 너무 길어 발생하는 400(context 초과)도 현재 ValueError → 작업 failed입니다. 사용자 지시대로 이번에는 바꾸지 않았습니다. 비용이 발생한 뒤 사용량이 없는 경우·예외로 중단된 호출의 과금 보존도 기존 한계입니다.
- 중요: Anthropic은 max_tokens가 필수라 공통 runtime의 "비우면 모델 기본값"을 구현할 수 없습니다. 사용자 지시대로 기본값을 만들지 않고 ValueError로 막았습니다. 계약 변경 없음, 설정에서 명시 필요.
- 중요: 일부 모델이 요구하는 Gemini thought signature·DeepSeek reasoning_content 등 공급자 확장 필드는 현재 Reply 모양으로 왕복하지 않습니다. 이번에는 인터페이스를 변경하지 않았고 해당 모델의 실제 다중 도구 호출 호환성은 남았습니다.
- 작음: length는 Reply에 보존하지만 현재 loop가 별도 실패로 분류하지 않습니다. Anthropic cache 입력 토큰은 전체 입력에 합산하고 caller의 단일 입력 단가로 계산합니다. 캐시 할인·생성 할증 등 별도 단가와 확장 stop_reason 정책은 지원하지 않습니다.
- 의문점: Anthropic 출력 상한 생략과 공급자별 seed 지원 차이는 위와 같습니다. 계약·마이그레이션·engine·workers 변경, 커밋·push 없음.

## 2026-11-23 · Claude · taemin (실패 작업 무한 재시도 막기)
- 한 일: `workers/eng_main.run_once`가 예외마다 `retry=True`로 돌려 보내, 같은 이유로 실패하는 작업(해시 불일치·가격표 없음·검색 후보·쓰기 도구 호출)이 끝없이 다시 임대되던 문제를 고쳤습니다. `should_retry`: ValueError·TypeError·NotImplementedError(ContractError 포함)는 바로 작업 `failed`, 그 밖은 작업 attempts 가 `max_attempts`(기본 3) 미만일 때만 다시 넣습니다. `queue.reclaim(max_attempts=)`도 같은 상한으로 만료 임대를 `failed`로 둡니다(매번 프로세스를 죽이는 작업 대비). 풀이는 후보 실패로 기록하지 않고 pending 으로 남깁니다.
- 검증: 전체 **101 passed**, Ruff 0건. 새 검사 3개(영구 오류 즉시 failed·다시 안 빌림, 일시 오류 상한에서 failed, 회수 상한).
- 안 한 일 / 남은 일: 실패한 작업의 풀이는 pending 으로 남아 실험이 끝나지 않습니다 — 원인을 고친 뒤 작업을 다시 넣는 운영 절차(또는 API)가 필요합니다. 재시도 간격(백오프) 없음. 상한은 코드 상수이며 settings 계약에 `queue.max_attempts`를 넣을지는 4명 확인 사항입니다. 계약·DB 변경, 커밋·push 없음.
- 의문점: 없음.

## 2026-11-23 · Codex · taemin (큐 임대·회수·실험 잠금)
- 한 일: `common/queue.py`에 우선순위·SKIP LOCKED 임대, settings 임대 시간, attempts·leased_by·만료 검사, 연장·완료·실패·만료 회수를 구현했습니다. 실행 중 풀이를 pending으로 반환하면서 attempt를 증가시키고, 중단된 실험이면 cancelled로 바꾸는 것까지 작업 반환과 같은 트랜잭션입니다. 만료된 이전 워커는 회수 전에도 결과·비용을 저장할 수 없습니다. `run_trial(job=...)`의 최종 기록·비용·advance·작업 완료를 함께 커밋하며, 동시 완료가 채점 생성을 누락하지 않게 실험 행을 먼저 잠급니다. `lock_and_enqueue`는 DB 잠금·풀이·작업 생성·running 전환을 원자화하고 반복 요청 때 중복 생성하지 않습니다. `workers/eng_main.run_once`는 명시적 deps·연결 팩터리로 풀이 하나를 처리하고 별도 연결에서 기본 20초마다 연장합니다(최소 임대 60초 대응). 잡을 수 있는 오류는 작업을 반환하고 원래 예외를 올립니다.
- 검증: 전체 **98 passed**, backend 전체 Ruff 0건. 새 통합 검사 10개에서 잠긴 작업 건너뛰기·토큰 재발급·이전 토큰 거부, 별도 프로세스의 os._exit 비정상 종료, pg_terminate_backend DB 연결 종료 후 새 연결의 회수·재실행, 회수 후 이전 워커의 늦은 저장 차단, 중단된 풀이 취소, 별도 연결 연장·오류 반환, 동시 완료의 채점 실행 하나, 큐 완료 저장 실패 시 spans·장부 롤백, 잠금 중 작업 등록 실패의 전체 롤백·중복 요청을 확인했습니다. 가짜 모델·임시 DB 기준이며 실제 API나 실제 채점 완료를 의미하지 않습니다.
- 안 한 일 / 남은 일: `write_proxy.py`·`tool_search.py`, 풀이별 Docker/MCP와 환경 검사, 나머지 모델 3사 및 실제 API 검증, 실제 채점 완료는 남았습니다. P-05의 문항별 답 계약·승인 대상 비교 규칙은 ①② 협의가 필요합니다. `grading/eng_pipeline.py`도 미구현이라 채점 작업 생성까지 검증했습니다. 배포용 반복 실행 진입점·오류 후 재시도 간격/상한은 정하지 않았고 기존 registry는 변경하지 않았습니다. 큐 경로를 쓸 때는 새 run_once 또는 job을 넘기는 run_trial을 사용해야 하며, job 생략은 기존 독립 실행 검증용입니다. 중단 직전 메모리의 trace·과금 보존과 블로킹 외부 호출 강제 중단은 여전히 남았습니다. 기존 변경을 보존했고 계약·DB 정의·의존성 선언·브랜치 변경, 커밋·push 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): P-05의 미구현 계약을 임의로 추가하지 않았습니다. 재시도 운영 정책과 실제 채점 연결을 끝내기 전에는 체크리스트의 워커·advance 전체 완료로 표시하지 않았습니다.

## 2026-11-23 · Codex · taemin (예외 후 풀이 복구·오류 칼럼 수정)
- 한 일: `worker.run_trial`의 시작 이후 실행·trace 검사·최종 저장 전부를 예외 복구로 감쌌습니다. 현재 status=running과 시작한 attempt가 모두 같을 때만 pending으로 반환하고 attempt를 1 올리며 started_at을 비웁니다. 넘겨받은 다른 워커나 완료 상태는 수정하지 않습니다. 이미 중단된 실험이면 DB 규칙에 따라 pending 반환 후 cancelled로 처리합니다. 원래 예외는 그대로 다시 던지며 자동 모델 재호출은 하지 않습니다. 복구 자체가 실패하면 원문 DB 오류를 노출하지 않는 복구 실패 안내를 원래 예외에 붙입니다. `sa_spans.error`가 존재하는 것을 확인하고 INSERT의 전용 error 칼럼에 기록하도록 수정했습니다(이전 attributes 저장은 잘못된 구현이었습니다).
- 검증: 전체 **88 passed**, backend 전체 Ruff 0건. 쓰기 미지원·인증/미지원 공급자/응답 부족에 해당하는 모델 예외·취소·최종 인계 실패에서 상태 복구를 확인했습니다. 인계 실패 시 spans와 장부 롤백 후 attempt 2로 재실행이 완료됩니다. 다른 워커 attempt 보존, 중단된 실험의 취소, 복구 실패 시 원래 예외 보존, 도구 오류의 error 칼럼 저장도 임시 DB에서 확인했습니다. 기존 테스트의 running 잔류 기대값을 새 복구 동작과 실제 재실행 확인으로 갱신했습니다.
- 안 한 일 / 남은 일: 이 복구는 Python이 예외를 처리하고 DB 연결이 사용 가능할 때 작동합니다. 프로세스 강제 종료·DB 단절의 복구는 큐 임대/회수 단계에서 구현해야 합니다. 중간 비용 보존도 이전 기록대로 남아 있습니다. 쓰기 도구는 여전히 미지원이며 부르면 안전하게 예외·상태 복구됩니다. 스키마 자체 검증·length 응답 정책은 변경하지 않았습니다. max_steps의 모델+도구 합산 설명은 이미 common.schema.json의 runtime.max_steps에 있으므로 계약을 고치지 않았습니다. 계약·DB 정의·브랜치 변경, 커밋·push 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 앞선 기록의 “예외가 나면 running에 머물 수 있음”은 위의 잡을 수 없는 종료/연결 장애에 한정됩니다.

## 2026-11-23 · Codex · taemin (실행 코어 1~3: 읽기 경로)
- 한 일: DB 없는 `engine/loop.py`와 `engine/tracing.py`, 모델 공통 경로 `common/llm.py`를 구현했습니다. `OpenAIModel.chat`과 `FakeModel.chat`은 같은 `Reply`(글·도구 호출·사용량·실제 모델 이름·비용·시간·재시도)를 반환합니다. OpenAI SDK 자동 재시도를 끄고 runtime 횟수·남은 시간으로 제어합니다. 출력 토큰 상한을 비우면 계약대로 제공자 기본값을 쓰며, `max_steps`는 모델 호출과 각 도구 호출을 합산합니다. 잘못된 도구 인자는 실행하지 않고 모델에 오류로 돌려줍니다. 오류 분류는 기존 `checks.run_outcome_for`와 prereg를 그대로 따릅니다.
- 연결 모양: `run_agent(snap, task_prompt, seed, Dependencies(model, call_tool), prereg=prereg)` → `RunResult.trace`. `call_tool(name, args, timeout_sec)`는 문자열을 반환하고 환경 장애는 `ToolEnvironmentError`로 알립니다. 모델 호출은 `common/llm.py`를 통하며 DB는 직접 읽지 않습니다. 호출자는 `Price`로 가격을 넘기고 반환된 비용을 자기 문맥에서 저장합니다. 워커는 settings의 현재 `price.<모델>`을 읽고 실제 모델에 가격표가 없으면 실행하지 않습니다.
- DB 연결: `run_trial(conn, trial_id, deps=...)`가 스냅샷 해시·예산·현재 상태를 확인하고, 모델/도구 호출 동안 DB 트랜잭션을 유지하지 않습니다. 최종 spans·호출별 비용 장부·trial 결과·`advance.on_trial_finished`를 한 트랜잭션으로 저장합니다. attempt가 달라지면 저장을 거부합니다. 취소는 후보 실패로 저장하지 않고 `RunCancelled`로 올립니다. 도구 설명 토큰은 측정할 수 없어 trace에서 생략하고 DB에는 NULL로 둡니다. 기본 deps는 없으므로 등록된 기존 작업 핸들러만으로 유료 모델이 실행되지 않습니다.
- 검증: 새 테스트 26개 포함 전체 **80 passed** (`scripts/test.ps1`), backend 전체 Ruff 0건·추가/수정한 Python 7개 포맷 검사·diff 공백 검사 통과. OpenAI는 SDK 모의 응답으로 확인했습니다. 가짜 모델이 T2-0 조회 → 답변 → 실제 임시 DB 저장까지 돌고, 두 풀이 완료 후 채점 작업 하나가 생기는 것을 확인했습니다. 예산 소진 시 호출 차단·저장 중 인계 실패 시 전체 최종 기록 롤백·오래된 attempt 저장 거부도 확인했습니다. 새 워커 테스트는 기존 E2E와 별도 임시 DB를 사용해 전역 집계에 영향을 주지 않습니다. 테스트 실행 스크립트에 이미 선언돼 있던 openai를 추가했으며 의존성 선언·lock·계약은 변경하지 않았습니다.
- 안 한 일 / 남은 일: 실제 API 호출, 나머지 3개 회사, Docker/MCP·시작 전 환경 검사, 확인 도구·쓰기 프록시·쓰기 기록, 검색·재생, 채점기 구현은 다음 단계입니다. 쓰기·확인·검색은 미지원 예외로 막습니다. 큐 임대·연장·회수·임대 토큰 펜싱·워커 메인도 아직 없습니다. 실행 중 취소/예외/프로세스 종료로 최종 저장에 도달하지 못하면 메모리의 trace와 비용이 남지 않고 trial이 running에 머물 수 있어, 실사용 전에 큐 복구와 중간 비용 보존을 연결해야 합니다. 도구 콜백에는 남은 시간을 전달하지만 블로킹 호출을 강제 중단하는 기능은 아직 없습니다. 가짜 실행 결과는 테스트용이며 실제 ML/DL 학습 성능의 근거로 사용하지 않습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 계약 변경 없음. P-02의 429 분류는 prereg의 기존 값대로 유지했습니다. P-05의 문항별 답 계약은 이번 범위에 포함하지 않았습니다.

## 2026-11-23 · Codex · taemin (공통 DB 연결)
- 한 일: common/db.py에 get_database_url·connect를 구현했습니다. 환경 변수 우선, 없으면 저장소 루트 .env를 읽되 프로세스 환경은 변경하지 않습니다. URL·포트·접속 제한 시간을 확인하고 기본 tuple 행·트랜잭션 연결, 선택적 autocommit을 제공합니다. 새 test_eng_db.py에서 설정 우선순위·잘못된 설정의 비밀값 비노출·조회·커밋·롤백·연결 종료·autocommit을 확인했습니다. 기존 선언된 python-dotenv를 테스트 실행 환경에 추가하고 test.ps1이 실패 코드를 전달하게 수정했습니다. 전체 54 passed, Ruff·추가한 두 파일 포맷 검사 통과.
- 안 한 일 / 남은 일: 큐·워커·API 통합은 아직 구현하지 않았습니다. 로컬 PostgreSQL 서비스를 기동했고 기존 볼륨은 app 계정/빈 app DB여서 그대로 보존한 채 별도 slotagent DB를 만들고 빈 DB에만 0001~0003을 적용했습니다. 예시에서 로컬 .env를 처음 만들고 기존 초기 계정 app에 맞췄습니다(실제 API 키 없음, Git 제외). 공통 connect로 PostgreSQL 17.11·제품 테이블 33개·template_scope 존재를 조회 확인했습니다. DB 서비스는 개발용으로 실행 중입니다. 계약·의존성 선언·lock 변경, 커밋·푸시 없음. 생성 캐시·임시 파일은 정리했습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 로컬 계정명 차이는 .env에만 반영하고 공유 .env.example과 기존 DB는 변경하지 않았습니다.

## 2026-11-23 · Codex · taemin (협업 체크리스트 간소화)
- 한 일: 사용자 피드백에 따라 협업 HTML을 51개 상세 항목에서 4단계·12개 핵심 체크로 줄였습니다. ④에게 받기→②에게 받기→① 연결→공동 결과 확인을 세로로 배치하고 요청 문구·받을 것·넘어가는 기준을 크게 표시했습니다. 기술 기준과 파일 메모는 접어서 숨겼습니다. 자동 저장·JSON·인쇄는 유지하고 이전 상세 기록은 전체 근거를 보존하면서 대응 항목이 모두 완료된 경우만 새 체크로 옮깁니다. 저장·JSON 왕복·이전 기록 변환·초기화·인쇄·반응형 화면을 확인했고 임시 파일은 삭제했습니다.
- 안 한 일 / 남은 일: 협업 HTML과 인계 기록만 수정했습니다. 코드·계약·공식 구현 체크리스트는 변경하지 않았습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.

## 2026-11-23 · Codex · taemin (①②④ 협업 체크리스트 HTML)
- 한 일: docs/SlotAgent_협업체크리스트_1123.html을 만들었습니다. 공통 예시 합의→④ 등록 자료→② 평가 자료→① 연결→공동 검수의 51개 수동 체크, 근거·회의·인계 메모, 담당별·미완료 필터와 진행률, 브라우저 저장, JSON 내보내기·가져오기, 초기화 확인, 전체 인쇄를 제공합니다. 승인·거절 존중·무단 쓰기의 기대 결과와 경계 사례, 계약 합의 지점, 상대에게 요청할 문구와 다음 개발 흐름을 적었습니다. Playwright로 저장·새로고침·필터·JSON 왕복·오류 거절·초기화 취소/승인·인쇄·저장 차단 시 내보내기·1440/768/390px 가로 넘침을 확인하고 화면을 검토했습니다. 검증용 JSON·이미지는 삭제했습니다.
- 안 한 일 / 남은 일: HTML과 이 기록만 추가했습니다. 체크 기록은 브라우저 개인 상태로 저장되며 공식 체크리스트·팀 승인·DB 검증을 자동 갱신하지 않습니다. 코드·계약·다른 역할 작업물과 docs/checklist.md의 구현 완료 칸은 변경하지 않았습니다. 백엔드 테스트·커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 거절 경로의 성공 조건과 P-05 세부 계약은 ①②가 확인할 항목으로 두었고 임의 확정하지 않았습니다.

## 2026-11-23 · Codex · taemin (기술 스택 결정 동기화)
- 한 일: 기술 스택 HTML의 P-05 미정 문구를 문항별 고정 가짜 답·공통 확인 도구·승인 대상 비교·풀이별 초기화로 갱신했습니다. P-03의 Docker·stdio·시작 전 검사·연습용 서버 시간 전제와 P-13 기능 사전 결정도 반영했습니다. P-05의 평가팩 계약·도구 정의·비교 규칙은 추가 구현할 항목으로 구분했습니다. 데스크톱·모바일 문구·가로 넘침을 확인하고 검증 이미지는 삭제했습니다.
- 안 한 일 / 남은 일: HTML과 인계 기록만 수정했습니다. 계약·코드·체크리스트는 변경하지 않았습니다. 문서 변경이라 백엔드 테스트는 생략했습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 정책 결정 완료와 계약 구현 예정 상태를 구분했습니다.

## 2026-11-23 · Claude · taemin (P-03·P-05·이름표 정함)
- 한 일: decisions_pending 에 P-03(연습용 MCP 서버를 풀이별 Docker + stdio, 동결 데이터, 시작 전 검사)·P-05(문항별 가짜 사용자 답, 같은 확인 도구, 승인 대상과 쓰기 비교)·P-13(기능 이름표 사전) 정함. `docs/capabilities.md` 초안(이름표 8개, 규칙, ②④ 확인할 것). checklist 1절 갱신. AGENTS.md(로컬) 다시 정리.
- 안 한 일 / 남은 일: P-05 를 위한 평가팩 계약 칸(문항별 승인·거절 답)과 확인 도구 `request_user_confirmation` 정의는 ①② 가 계약 변경으로 (CHANGELOG). 이름표 코드 검사 목록은 사전이 안정된 뒤. 기술 스택 문서(docs/SlotAgent_기술스택_1123.html)의 "P-05 미정" 표기는 이제 정함으로 고쳐야 함. 커밋 안 함.
- 의문점: 없음.

## 2026-11-23 · Codex · taemin (기술 스택 설명 문서)
- 한 일: 사용자 요청으로 docs/SlotAgent_기술스택_1123.html을 새로 작성했습니다. 기획서 1.3 기준으로 기술별 역할·선택 이유·사용 예시를 쉬운 말로 설명하고, 화면→서버→DB→실행→판정 흐름, 모델 회사 4종·공통 어댑터, 쓰기 실행 방식, P-01 확정과 P-05·P-11 미정, 고도화·선택 기술을 구분했습니다. Playwright로 7개 섹션·20개 설명 카드·15개 요약 행·목차·인쇄 버튼·1440/768/390px 가로 넘침·JS 오류를 확인하고 데스크톱·모바일 렌더링을 검토했습니다. 임시 이미지는 삭제했습니다.
- 안 한 일 / 남은 일: 기술 스택 HTML과 이 인계 기록만 작성했습니다. 코드·계약·의존성·다른 문서는 변경하지 않았습니다. 문서 작업이라 백엔드 테스트는 재실행하지 않았습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 채택한 기술과 구현 완료를 구분했습니다.

## 2026-11-23 · Codex · taemin (최신 상태 검토)
- 한 일: 현재 작업 폴더를 수정 없이 검토했습니다. scripts/test.ps1 38 passed, Ruff check --no-cache . 통과, uv lock --check --offline 233 packages 일치, docker compose config --quiet와 staged/unstaged diff 공백 검사 통과. 최신 skeleton과 계약 스키마 16개·예시 8개 일치를 확인했고 개인 AI 파일의 Git 제외도 확인했습니다. 테스트 생성 캐시는 삭제했습니다.
- 안 한 일 / 남은 일: 검토 발견 사항만 보고했습니다. README.md에는 30 passed·P-01 미정·tool_search 미반영, contracts/README.md에는 50개 한도·exclude 선택 설명이 남아 있습니다. 공유 기술 스택 HTML은 현재 docs에 없습니다. 이미 커밋된 0003에 template_scope·러너 토큰 칸을 추가한 상태로, backend/db/README.md의 합친 뒤 0004부터 추가 규칙과 다릅니다. 새 DB 테스트는 통과하지만 기존 DB 업그레이드는 별도 마이그레이션이 필요합니다. Ruff 수정 등 unstaged 변경도 남아 있습니다. 코드·스키마·의존성 변경, 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 위 마이그레이션 규칙과 파일 상태의 차이를 임의로 고치지 않고 보고했습니다. 기획서 1.3 계약의 4명 확인 필요 기록도 유지돼 있습니다.

## 2026-11-23 · Claude · taemin (ruff 정리)
- 한 일: 뼈대부터 있던 ruff 경고 21건을 0건으로. 자동 수정(import 정렬, collections.abc, datetime.UTC, functools.cache, 안 쓰는 import) + 손으로 zip(strict=True) 4곳, 안 쓰는 반복 변수 이름 앞에 _. intake/service.py 는 ④ 구현 자리라 힌트 import 를 noqa 로 남기고 add_candidate 설명에 template_scope 저장을 적음. 동작 변경 없음, 테스트 38 passed.
- 안 한 일 / 남은 일: skeleton(검증용 원본)은 정리 안 함. 커밋 안 함.
- 의문점: 없음.

## 2026-11-23 · Claude · taemin (DB 추가 2개)
- 한 일: `sa_experiment_candidates.template_scope`(실행 전 범위 판정 저장, 계약 common `$defs/template_scope`, needs_review 는 CHECK 로 저장 못 함, 실험 잠금 뒤 못 바꿈)·`sa_agents.runner_token_hash`(UNIQUE)·`runner_token_revoked_at`(러너 연결 토큰, 해시만). NAMES.md·db_names·e2e(저장·거절 확인)·CHANGELOG·review_1122. 테스트 38 passed. ERD 다시 빌드(318칸, 150/10 통과), skeleton 도 같이.
- 안 한 일 / 남은 일: 실험 후보를 넣는 ④ 코드에서 `checks.template_scope` 결과를 채우는 일, 러너 토큰 발급·확인 API(④). 커밋 안 함.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.

## 2026-11-23 · Claude · taemin (기획서 1.3 반영)
- 한 일: ① P-01 확정(범위 밖 = 실패) — prereg·settings `fail` 만, `tool_def.capabilities` + `sa_templates.required_capabilities` + `checks.template_scope`(실행 전 판정), 리포트 `detail.in_scope`. ② 쓰기 도구 `write_mode`(업로드 fake·exclude_tasks / 러너 fake·test_space / API dry_run 필수), 쓰기 도구 10개까지 `checks.check_write_modes`. ③ 모델 회사 `model_provider` 4종(DB·등록 요청·스냅숏). ④ 도구 50개 한도 뺌(토큰 상한 P-11). ⑤ Tool 자리 먼저 `snapshot.PHASE1_KINDS`, 새 MCP 서버 후보 거절. CHANGELOG·contracts/README·review_1122 8차·decisions_pending(P-01 정함, P-11·P-12 추가)·.env.example(키 4종). 테스트 38 passed. 저장소 밖: ERD v1.2 다시 빌드(150/10 통과), 기술스택 문서·부록(50개, dev/held 15/35 예) 고침, skeleton 도 같이 맞춤(38 passed).
- 안 한 일 / 남은 일: 4명 확인(계약 변경). `common/llm.py`·`template_scope` 를 부르는 plan-proposal·리포트 코드. 기획서 1.3 문서의 "평가 워커(Inspect AI)"·"PostgreSQL 16" 표기는 사용자가 고칠 것. 커밋 안 함.
- 의문점 (계약·미정 사항과 부딪힌 곳): P-05(사용자 확인)는 그대로 미정. 1.3 5.5 예시의 "사용자에게 확인 요청 → 승인"은 P-05 ①안(정해 둔 사용자 답)과 맞음.

## 2026-11-23 · Codex · taemin
- 한 일: 사용자 요청으로 CHANGELOG의 11/23 계약 변경 표시를 "④ 확인함(11/23)"으로 바꾸고 최근 인계 기록의 ④ 확인 대기 항목을 정리했습니다.
- 안 한 일 / 남은 일: 확인 표시만 수정했습니다. 코드·스키마·테스트 변경, 커밋·푸시 없음. 문구 변경을 확인했고 실행 테스트는 생략했습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.
## 2026-11-23 · Codex · taemin
- 한 일: 사용자가 복원한 현재 파일을 수정 없이 재검증했습니다. scripts/test.ps1은 33 passed, uv lock --check --offline은 233 packages로 통과했고 docker compose config --quiet·git diff --check도 통과했습니다. contracts/schemas 16개와 examples 8개를 최신 원본과 대조해 일치를 확인했습니다. AGENTS.md·CLAUDE.md·로컬 도구 설정의 Git 제외도 확인했습니다. 테스트 생성 캐시와 불필요해진 계약 복원 패치는 삭제했습니다.
- 안 한 일 / 남은 일: Ruff check --no-cache .는 21건 실패(import 정리·미사용 항목·zip strict 등). 자동 수정하지 않았습니다. common/llm.py와 화면 타입 생성 파일은 아직 없으며 구현 예정입니다. Compose 실제 기동·동시 워커·격리는 이번 검증 범위가 아닙니다. 코드·계약·의존성 변경, 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 핵심 복원 누락은 해소됐지만 정적 검사까지 완료된 상태는 아닙니다.

## 2026-11-23 · Claude · taemin
- 한 일: 패키지를 다시 덮으면서 빠졌던 11/23 계약 변경을 되살림 — 질문을 연결 방식에서 빼고 `sa_agent_versions.questions_used`, `sa_agents.domain_code`, 도구 검색 후보 `tool_search`(component_kind·component_spec·config_snapshot·checks·snapshot). DB 는 0003 끝, CHANGELOG·contracts/README·review_1122 7차, 예시(후보 C)·테스트 3개 추가. 덮기 전 18개 파일이 모두 원본 그대로인지 확인한 뒤 바꿈(다른 수정 없음). scripts/test.ps1 의 중복 -q 를 빼서 요약 줄이 보이게 함. 테스트 33 passed.
- 안 한 일 / 남은 일: 도구 검색 실행(engine/tool_search.py, W5). 커밋·push 안 함.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. P-01·P-05 값은 건드리지 않음.

## 2026-11-23 · Codex · taemin
- 한 일: 이전 폴더 검토의 누락을 재점검했습니다. 최소 뼈대로 바뀐 backend/pyproject.toml을 현재 lock의 프로젝트 메타데이터(일반 의존성 26개·개발/GPU/Linux 그룹)와 합의한 스택에 맞춰 복원했습니다. 인덱스의 이전 선언에는 Django·Celery·LangChain이 있어 그대로 덮어쓰지 않았습니다. pgvector PostgreSQL 17·Redis 캐시 Compose와 OPENAI_API_KEY·REDIS_URL 환경 예시, 인계 형식 안내를 복원했습니다. uv lock --check --offline(233 packages), docker compose config --quiet, 현재 계약·DB 테스트 30개와 수정 파일 공백 검사를 통과했습니다. 테스트 생성 캐시는 삭제했습니다.
- 안 한 일 / 남은 일: 최신 뼈대의 11/23 계약 변경은 원본 CHANGELOG·검토 기록에 ④ 확인 필요가 남아 있어 적용하지 않았습니다. contracts·예시·DB·공통 코드·추가 테스트를 포함한 artifacts/contract-1123-restore.patch를 만들고 git apply --check --ignore-space-change로 적용 가능성만 확인했습니다. 4명 확인 완료 여부를 사용자에게 질문했습니다. 현재 30개 통과가 누락된 계약 복원을 검증했다는 뜻은 아닙니다. 커밋·푸시·Compose 실제 기동 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): AGENTS.md §5의 계약 변경 4명 확인 규칙 때문에, 확인 기록이 남아 있는 변경은 임의로 반영하지 않았습니다.

## 2026-11-23 · Codex · taemin
- 한 일: 사용자 지시에 따라 앞으로 모든 작업을 taemin에서 진행하도록 로컬 AGENTS.md를 변경했습니다. 기존 미커밋 변경을 유지한 채 taemin으로 전환하고, taemin과 같은 커밋임을 확인한 codex 작업 브랜치 4개와 claude/contract-1123 브랜치를 일반 삭제(-d)했습니다.
- 안 한 일 / 남은 일: 소스·계약·의존성 변경, 커밋·푸시 없음. main·dev·원격 브랜치는 유지했습니다. Git 상태로 미커밋 변경 보존을 확인했고 실행 테스트는 수행하지 않았습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 사용자의 새 지시가 기존 브랜치 규칙을 대체합니다.

## 2026-11-23 · Codex · codex/ignore-local-agent-files
- 한 일: 폴더와 Git 추적 상태를 점검하고 .gitignore에 개인 AGENTS.md·CLAUDE.md(대소문자 변형 포함), .agents/·.codex/·.claude/·.mcp.json, 로컬 도구 설정, 캐시·테스트 결과, artifacts/와 임시 검증 폴더를 추가했습니다. 파일은 삭제하지 않았습니다. git check-ignore로 개인 파일 제외와 .env.example·공유 HTML 포함을 확인했습니다. 개인 지침 파일은 추적 전이라 인덱스 제거가 필요하지 않았습니다.
- 안 한 일 / 남은 일: 코드·계약·의존성은 변경하지 않았습니다. 현재 AGENTS.md §3은 이전 요약형이고 backend/pyproject.toml은 최소 뼈대(slotagent)지만 uv.lock의 프로젝트는 skn35-final-4team이라 최신 설정과의 정합성 확인이 필요합니다. frontend/는 README만 있습니다. 루트 promptfoo용 package.json·node_modules는 유지했습니다. 테스트 실행 없이 Git 제외 규칙만 검증했습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 앞서 확정한 기술 결정 표와 현재 파일 내용이 달라 임의 복원하지 않고 사용자에게 보고합니다.

## 2026-11-23 · Codex · codex/refresh-skeleton-package
- 한 일: 최신 원본의 6차 DB 이름 규칙으로 복사용 패키지를 구성했습니다. db를 backend/db로, web을 frontend로 옮기고 테스트의 SQL·시드 경로와 CODEOWNERS를 맞췄습니다. 오케스트레이터·MCP·도구 검색·서빙 구현 자리를 포함하고 AGENTS.md의 LLM 경계를 반영했습니다. PostgreSQL 17 Compose와 .env.example을 추가했습니다. 계약·DB 연결 테스트 30개 통과.
- 안 한 일 / 남은 일: 실제 실행 엔진·UI·고도화 구현, 동시성·격리 검증. Compose 기동은 검증하지 않았습니다. P-01·P-05 등 임시 값과 계약 스키마는 변경하지 않았습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.
