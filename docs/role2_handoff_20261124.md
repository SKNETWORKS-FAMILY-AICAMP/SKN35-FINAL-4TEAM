# ② 독립 준비 결과 / ① 확인 요청 — 2026-11-24

현재: 활성 평가팩1개(it_ops/v0.1)·47유형·143문항·골든188개. 별도3유형9문항은 엔진/계약 대기 초안이며 아래 이전 수량은 당시 검증 이력이다. [현재 안내](../packs/README.md)와 [전체 문항 목록](../packs/QUESTIONS.md)을 함께 본다.

7개 업무 그룹은 독립 평가팩이 아니다. 데이터·문항·골든·개발 어댑터를 단일 폴더에 통합했고 전체 가짜 실행은 reference/run_pack.py로 수행한다.

최신 재편: 조회8유형·26문항, 쓰기6유형·18문항, 장애6유형·18문항이다. 아래 과거 검증 수량은 당시 범위의 기록이며 현재 구성은 packs/README.md를 기준으로 한다. 실제 서버 도구5개는 유지했고 활성 MCP 지원 목록은8유형이다. 새로운7유형은 로컬 시뮬레이터 단계다.

## 준비한 것

| 항목 | 결과 | 제품 통합 상태 |
|---|---|---|
| 조회 그룹 | 8유형·26문항·골든32개 | 전부 dev, 독립 검수 전 |
| 쓰기 그룹 | 6유형·18문항·골든24개·가짜100실행 | confirmation 칼럼 적용 대기, 실제 write_proxy 미검증 |
| 장애 분석 그룹 | 6유형·18문항·골든24개·가짜100실행 | 로그·관계근거·승인공유. MCP 확장/제품 채점 미연동 |
| 오류복구/페이지 그룹 | 3유형·9문항·골든12개·가짜60실행 | 순서 재생·한도·cursor 검사. 전용 MCP/제품 의미검증 미연동 |
| 정보충돌 그룹 | 3유형·9문항·골든12개·가짜69실행 | 동급 충돌/신선도/근거부족. 제품 출처 매핑·MCP 미연동 |
| 운영계산 그룹 | 6유형·18문항·골든24개·가짜108실행 | JSON 원본 어댑터. 요청/장애/지연 기능 제안·파생 지표 제품 채점 미연동 |
| 운영절차 그룹 | 10유형·30문항·골든40개·가짜189실행 | 고정 상태·단일 풀이. ops.traces.read 제안/실제 도구·제품 채점 대기 |
| MCP 연습 서버 | GitHub 조회 도구5개, resource 메타데이터, 시작 시 데이터 검증 | Docker stdio 20호출 통과 |
| DB loader | 정책·참조·스키마 사전 검사, 단일 트랜잭션 draft 저장 | 실제 DB에 47문항·골든60개 저장/조회 후 롤백 확인 |
| 문항 선택 | split 분리, 유형 전체 노출 제외, 동일 유형 동일 묶음 | 순수 선택 테스트 및 draft 선택 거절 확인 |
| 팩 잠금 | 독립 환경/제품 검증+현재 DB fingerprint 필요 | 증거 형식 ① 검토 요청, 실제 팩은 잠그지 않음 |

데이터·모델 계정 없이 가능한 준비 범위다. 실제 모델 성능·라벨 품질·E1~E6 통과·held 효과 판정·LoRA 학습을 완료했다고 주장하지 않는다.

## P-03 바로 연결할 정보

- 명세: `packs/it_ops/v0.1/practice/servers.json`
- 서버 코드: 같은 폴더 `server.py`, 빌드: `Dockerfile`.
- 로컬 태그: `slotagent-it-ops-practice:0.1.0`
- 실제 확인한 image: `sha256:4db1d9c66a0dd2338fab2b294c4bae66e92fe186c1af9fdd3d9befd0dd7e2aa3`
- 위 ID는 로컬 Docker용이며 레지스트리에 게시하지 않았다. 팀원 PC에서는 직접 빌드/ID 고정이 필요하다.
- command: `python /app/server.py --manifest /app/servers.json --data-dir /data`.
- 데이터: 명세에 적힌 JSON 3개만 `/data/<파일명>`으로 읽기 전용 마운트.
- resource: `slotagent://practice/manifest` — version/data_version/snapshot_hashes/도구와 스키마 확인.
- tool result: MCP TextContent 안 JSON 배열. structuredContent 없음.
- 새 trial/attempt마다 컨테이너 새로 실행, 종료 후 제거. 후보별 도구 차이 보존 매핑은 ①② 확인 필요.

검증: initialize·tools/list·resources/read와 도구20호출 통과. 도구5개에 전체조회·repo필터·빈결과·잘못된인자 각각 확인. network=none, 비root, read-only filesystem. 현재 서버는 합성 조회 API이며 공식 GitHub MCP 응답의 모든 세부 동작을 재현한 서버는 아니다.

## DB 경계

① DB 칼럼·ERD·migration은 변경하지 않았다. 현재 DB에는 sa_tasks.confirmation이 없어 쓰기 그룹은 저장 전 안내 오류를 낸다. 통합 팩은 정책이 있는 문항을 포함하므로 해당 칼럼이 없으면 전체 팩 로딩을 차단한다. 과거 조회 그룹만의 롤백 검증은 통합 팩 전체 DB 검증이 아니다.

① 칼럼 적용 후 `SLOTAGENT_RUN_DB_TESTS=1`로 쓰기 그룹 JSONB 저장 분기를 다시 확인해야 한다. 테스트 행은 롤백하지만 PostgreSQL 시퀀스 번호는 소비될 수 있다. 이번에 제품 평가팩 행을 영구 등록하거나 잠그지는 않았다.

전체 manifest 해시는 pack_content_hash로 제공하고 데이터별 해시는 sa_data_snapshots에 저장한다. 전체 해시의 최종 DB 칼럼/제품 snapshot 저장 위치는 ①과 합의가 남아 있다.

골든 대상 task_code는 현재 DB에 독립 칼럼이 없어 첫 span의 attributes['golden.task_code']에 보존한다. ① 재채점 코드가 이 값을 읽을지 별도 대응표를 둘지 확인 부탁드린다.

## select_tasks / 잠금 검토 요청

선택 함수는 locked 팩만 사용하고 기본 split=held다. 노출 문항이 하나라도 있는 유형은 전체를 제외한다. 아직 모두 dev이므로 실제 실험 전 held 확보/검수 계획이 필요하다. 현재 선택은 template_id 순서의 결정적 방식이며 도메인 비율·난수화 설계가 필요하면 ②③과 추가한다.

`pack_readiness(conn,id)`로 현재 DB fingerprint와 blocker를 조회한다. `lock_pack`는 아래 증거가 없으면 거절한다. 이 증거 규약은 아직 ① 확인 전 구현 제안이다.

- sa_env_checks kind=tool_shape/data_design/prompt_leak, target='pack'의 최신 결과 pass.
- 각 유형 kind=golden_test, target=유형 code의 최신 결과 pass.
- 위 모든 행은 checked_by가 있고 detail.pack_fingerprint가 현재 fingerprint와 일치해야 함.
- golden_test는 detail.product_grader_version도 필요.

②는 임시 채점 결과를 제품 검증으로 등록하지 않았다. ① 제품 채점 검증 결과를 어떤 코드가 기록할지 정해야 한다. 잠금 시 관련 테이블 SHARE lock을 잠깐 사용하므로 ①의 실행/동시성 구조와 맞는지도 리뷰 부탁드린다.

## 재검증

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/practice/check_mcp.py --docker-image slotagent-it-ops-practice:0.1.0
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/verify_golden.py --all
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/run_pack.py --group writes
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_independent.py backend/tests/test_pack_loader.py
```

## ①에게 보낼 요약

②에서 연습 MCP 서버/Docker 이미지·데이터 고정·조회형 골든60개·쓰기형 골든8개·장애형 골든12개와 loader/문항선택/잠금 게이트까지 준비했습니다. 실제 컨테이너 stdio 20호출과 Docker DB 로딩·미검증 잠금 거절을 확인했습니다. P-03 후보 매핑/metadata 규약, P-05 칼럼 적용, 골든 task_code 전달, 전체 팩 해시 저장 위치, 제품 검증 기록/잠금 게이트 규약을 확인 부탁드립니다. 실제 제품 엔진·write_proxy·규칙 채점/E1~E6 완료 표시는 하지 않았습니다.

## ② 다음 단계

① 연동 피드백 후 어댑터/스키마 조정, 독립 검수자 배정, held 유형 확보, 실제 모델 파일럿 비용·시간 측정, 사람이 라벨한 데이터로 판정기 사전 검증을 진행한다. 독립 사람 라벨·공급자 모델 설정·GPU 없이 LLM 판정기 정확도/LoRA 채택 여부를 임의로 확정하지 않는다.


## 오류복구/페이지 그룹 추가 확인 요청

②에서 it_ops/v0.1 내부 reliability 그룹에 고정된 도구 오류 순서·페이지 응답과 9문항/골든12개/가짜60실행을 준비했다. 전체 목록은 기존 packs/QUESTIONS.md, 사용법은 packs/README.md를 갱신했다. query_issue_ids/list_paged_issues 실제 도구 연결, 후보·trial·attempt별 독립 상태, 도구 결과 오류와 env_error 구분, 엔진의 자동 재시도가 에이전트 한도에 중복 집계되지 않는 방식을 검토 부탁드린다. 현행 조건의 status/items/call_count뿐 아니라 trace 응답 재생·순서·페이지 완전성까지 제품 채점에서 확인해야 한다.


## 정보 충돌 팩 추가 확인 요청

it_ops/v0.1 내부 conflicts 그룹의9문항은 동급 주 원본 불일치, 과거 캐시/미래 관측 제외, 확인된 상태와 미확정 버전 구분을 평가한다. 고정 판단시각·24시간 범위·주 원본 등급은 문항에 명시했다. get_run_facts/list_version_evidence 실제 도구와 신뢰할 수 있는 출처 매핑, 구조화 conflict/resolved/insufficient 의미 검증을 제품 채점에 연결할지 검토 부탁드린다. 모든 정책은 합성 평가 문제의 가정이며 source 이름이 본문에 보인다는 이유만으로 제품에서 신뢰하면 안 된다.


## 운영계산 27~32번 추가 확인 요청

it_ops/v0.1 내부 metrics 그룹에 에러 수 비교·트래픽 정규화 비율·중복 제거·장애 합집합·nearest-rank p90·최소 표본의6유형을 추가했다. raw 레코드의 계산으로 도출한 bp/p90/중단시간을 제품 채점기의 출처 추적에서 어떻게 검증할지 확인이 필요하다. exact 비교를 위해 단위/반올림/시간 구간을 문항에 고정했다. db.requests.read/db.incidents.read/db.latency.read는 ② 제안이며 ④ 확인 전 자동 매핑하지 않는다. 실제 DB/SQL/MCP는 아직 연결하지 않았다.


## 독립 제작10유형 추가 확인 요청

it_ops/v0.1 내부 workflows 그룹에 설정 우선순위·trace 복원·점검 누락·본문 악성 지시 무시·고정 저장소 범위·권한오류 구별·JSON 파싱·중복 이슈 방지·조건부 승인 쓰기·완료 범위 보고를 추가했다. 30문항/골든40개/가짜189실행을 준비했으며 50개 목표까지 남은8유형은 선협의 상태다. read_workflow_context/lookup_workflow_items의 실제 도구 매핑, ops.traces.read 기능 확정, 관계·범위·정확한 쓰기 횟수·부분완료 의미 검증을 ①④와 확인해야 한다. 일반 보안 통제나 동시 쓰기 검증을 완료한 것은 아니다.


## 쓰기 그룹 데이터 조회 보완

writes 그룹6문항의 하드코딩된 버전을 제거했다. context.json 단일 조회 → 원본 버전으로 요청 생성 → 승인 → 같은 인자로 fake 쓰기를 수행한다. 임시 채점기는 조회 원본·순서와 요청/실제 쓰기의 버전을 검증한다. 승인받았지만 버전이 틀린 쓰기는 완료 조건 실패로 구분한다. get_write_context는 개발용 로컬 도구라 실제 MCP/필요 capability 매핑은 ①④ 확인이 필요하다. 현재 GitHub 연습 서버가 지원한다고 간주하지 않는다. 쓰기 골든8개는 조회를 추가했으며 기대값은 유지했다. 계약·DB·동결 데이터·문항 수는 변경하지 않았다. tool_error 관련 변경은 별도 대기다.


## ① 회신 반영 — 2026-11-24

- ① 규칙 채점 eng_rules·채점 실행 흐름 eng*pipeline·제품 골든 검증 기록 / ② 정답 조건·골든168개·LLM 판정·결과3분류·첫 실패 단계로 역할 표기를 맞췄다. 독립 판정/제품 채점이 구현 완료됐다는 뜻은 아니다.
- 조회15유형·47문항 서버부터 연결한다는 방향을 확인했다. golden.task_code는 현재 방식으로 ①이 읽는다.
- lock_pack에 lock_timeout_ms(기본5000)를 추가했다. 트랜잭션 로컬 설정을 잠금 전에 적용하고 성공 시 이전 설정을 복원한다. 실패는 transaction/savepoint 롤백에 맡긴다.
- content_hash 칼럼이 있으면 load_pack 트랜잭션에서 pack_content_hash를 저장한다. 칼럼이 없으면 이전 경로를 유지하며 해시는 미저장이다. 칼럼은 ① 제안/적용 대기이고 ②는 DDL/DB 적용을 하지 않았다. 모의 연결 검사이며 실제 칼럼 저장 검증은 마이그레이션 후 필요하다.
- sa_tasks.confirmation jsonb(NULL 허용)는 ① 계약 검토 회신·4명 확인 대기다. 현재 loader의 정책 검증/SQL NULL 처리는 유지한다.
- tool_error는 구조 변경 없는 기록 규약으로 CHANGELOG에 기록했다. ① 구현과 실제 trace 예시가 오면 ② reliability/workflows를 조정한다. product_grader_version을 임시 검사기 버전으로 채우지 않는다.

비중 재편 후에도 전체42유형/128문항/168골든은 유지한다. 새 유형7개는 required_capabilities의 기존 이름표를 재사용하지만 실제 도구 응답·매핑은 ①④ 확인 대기다. 문항 선택의 실제 출제 비율·held 계획까지 확정한 변경은 아니다.


## 후보8개 후속 — 활성5 + 대기 초안3

① 회신의1~5를 각3문항·골든4종으로 로컬 등록했다. 실제 MCP 지원은 조회8유형·26문항 유지다. 제한4·5의 다른 필드 유출/미기재 URL 탐지 한계는 문항/검수표에 명시했다. 후보6~8은 write_proxy가 아직 주석 상태라 pending_writes.json에 요구사항과9개 시나리오만 준비했고 활성 제외했다. 정확한 쓰기/횟수 계약과 trace 예시를 받은 뒤 골든·활성 등록을 진행한다. 기존 응답 규격/도구 정의19종/골든 불일치/DB/tool_error/held 선정 보완은 사용자 요청대로 보류 중이다.


## 상세 MD 수신 후 추가5유형 정리

role2_reply_8types.md의 제안에 맞춰 direct/indirect 단계 조회, cause/certainty, commit/file/function, [EMAIL]/[TOKEN], fetch_url의302/403을 반영했다. 신규20골든은 명시적 access 문맥으로 eng_rules.check 조건별 일치까지 확인한다. 원래188개 전체 제품 대조/파이프라인 연결이 완료된 것은 아니다. 이름표는 ops.dependencies.read/ops.status.read/github.code.content.read/ops.incidents.read/web.pages.read 제안으로 정리했으며 ②④ 최종 확인 대기다. 실제 MCP 서버 지원은8유형26문항 그대로다. 쓰기3유형·DB·기존tool_error 작업은 계속 보류한다.
