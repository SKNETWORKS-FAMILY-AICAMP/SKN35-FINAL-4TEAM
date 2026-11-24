# 평가팩 안내 (② 담당)

기준: 현재 저장소의 pack.json과 구현 코드. 문항·정답의 단일 원본은 JSON이며 전체 목록은 [QUESTIONS.md](QUESTIONS.md)에서 확인한다.

| 팩 | 유형 | 문항 | 골든 | 용도 |
|---|---:|---:|---:|---|
| [it_ops/v0.1](it_ops/v0.1/README.md) | 15 | 47 | 60 | 조회·집계·배포/이슈/릴리스 연결 |
| [it_ops_writes/v0.1](it_ops_writes/v0.1/README.md) | 2 | 6 | 8 | 승인·거절·응답 없음에 따른 단순 쓰기 |
| [it_ops_incidents/v0.1](it_ops_incidents/v0.1/README.md) | 3 | 9 | 12 | 장애 로그 분석·근거 연결·승인 후 공유 |
| 합계 | **20** | **62** | **80** | 모두 IT 운영 도메인의 개발용 팩 |

## 구현과 검증 상태

- 모든 유형은 dev다. held 독립 평가용으로 표시하지 않는다.
- 가짜 실행은 조회235건·쓰기28건·장애46건이며 각 팩의 임시 검사기로 기대 판정을 확인한다. 실제 LLM 성능/비용이나 제품 채점 검증을 뜻하지 않는다.
- 조회 팩의 실제 연습 MCP 서버와 Docker 이미지가 준비됐고 stdio 도구20호출을 확인했다. 쓰기·장애 팩의 제품 MCP/엔진 연결은 후속이다.
- load_pack은 검증 후 draft 버전·데이터 해시·문항·정답·골든을 단일 트랜잭션으로 저장한다. 조회 팩은 실제 Docker DB 저장/조회 후 롤백 검증을 했다.
- 승인 정책은 sa_tasks.confirmation에 저장한다. 최근 DB 확인에서 칼럼이 없어 쓰기 팩 저장 전 차단을 확인했다. 칼럼 적용은 ①과 확인한 뒤 수행한다.
- select_tasks는 locked 팩만 선택하고 노출된 유형 전체를 제외한다. lock_pack는 현재 DB fingerprint에 묶인 독립 환경·제품 골든 검증 기록을 요구한다. 실제 팩 잠금/영구 등록/독립 승인 완료를 의미하지 않는다.

## 문서 갱신

새 배치 설명 MD를 만들지 않고 이 안내·관련 기존 README와 전체 문항 목록을 갱신한다. BATCH_10.md·PILOT_3.md·팩별 QUESTIONS.md의 문항 내용은 전체 목록으로 통합했다.

```powershell
.venv/Scripts/python.exe scripts/update_pack_catalog.py
.venv/Scripts/python.exe scripts/update_pack_catalog.py --check
```

## 공통 규칙

팩 위치는 packs/<pack_code>/<version>/pack.json이다. 잠긴 버전은 수정하지 않고 새 버전으로 만든다. dev/held는 유형 단위로 분리하고 노출된 유형은 효과 검증에서 제외한다.

정답 조건은 answer_condition 스키마와 common.checks.check_task_conditions로 검사한다. 기본 gate는 info/order/forbidden/end_state=true, link=false다. 골든은 golden/<template>.<kind>.json이며 pack.json에 task_code와 기대 판정을 등록한다. DB에는 loader가 첫 span의 attributes['golden.task_code']로 대상 문항 코드를 보존한다.

pack.json·전체 문항 목록·reference·골든·검수표는 정답을 포함하므로 실행 모델/러너에 제공하지 않는다. 연습 컨테이너에는 허용된 원본 데이터만 읽기 전용 마운트한다.

① 연동 검토 사항은 [전달 문서](../docs/role2_handoff_20261124.md), 승인 규칙은 [P-05 문서](../docs/P05_confirmation_handoff.md)를 따른다.
