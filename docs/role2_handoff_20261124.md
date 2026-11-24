# ② 독립 준비 결과 / ① 확인 요청 — 2026-11-24

기준: 평가팩3개·총20유형·62문항·골든80개. [현재 안내](../packs/README.md)와 [전체 문항 목록](../packs/QUESTIONS.md)을 함께 본다.

## 준비한 것

| 항목 | 결과 | 제품 통합 상태 |
|---|---|---|
| 조회 팩 | 15유형·47문항·골든60개 | 전부 dev, 독립 검수 전 |
| 쓰기 팩 | 2유형·6문항·골든8개·가짜28실행 | confirmation 칼럼 적용 대기, 실제 write_proxy 미검증 |
| 장애 분석 팩 | 3유형·9문항·골든12개·가짜46실행 | 로그·관계근거·승인공유. MCP 확장/제품 채점 미연동 |
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

① DB 칼럼·ERD·migration은 변경하지 않았다. 현재 DB에는 sa_tasks.confirmation이 없어 쓰기 팩은 저장 전 안내 오류를 낸다. 조회 팩은 NULL 정책이므로 기존 DB에서도 로딩 가능하다.

① 칼럼 적용 후 `SLOTAGENT_RUN_DB_TESTS=1`로 쓰기 팩 JSONB 저장 분기를 다시 확인해야 한다. 테스트 행은 롤백하지만 PostgreSQL 시퀀스 번호는 소비될 수 있다. 이번에 제품 평가팩 행을 영구 등록하거나 잠그지는 않았다.

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
.venv/Scripts/python.exe packs/it_ops_writes/v0.1/smoke.py
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_independent.py backend/tests/test_pack_loader.py
```

## ①에게 보낼 요약

②에서 연습 MCP 서버/Docker 이미지·데이터 고정·조회형 골든60개·쓰기형 골든8개·장애형 골든12개와 loader/문항선택/잠금 게이트까지 준비했습니다. 실제 컨테이너 stdio 20호출과 Docker DB 로딩·미검증 잠금 거절을 확인했습니다. P-03 후보 매핑/metadata 규약, P-05 칼럼 적용, 골든 task_code 전달, 전체 팩 해시 저장 위치, 제품 검증 기록/잠금 게이트 규약을 확인 부탁드립니다. 실제 제품 엔진·write_proxy·규칙 채점/E1~E6 완료 표시는 하지 않았습니다.

## ② 다음 단계

① 연동 피드백 후 어댑터/스키마 조정, 독립 검수자 배정, held 유형 확보, 실제 모델 파일럿 비용·시간 측정, 사람이 라벨한 데이터로 판정기 사전 검증을 진행한다. 독립 사람 라벨·공급자 모델 설정·GPU 없이 LLM 판정기 정확도/LoRA 채택 여부를 임의로 확정하지 않는다.
