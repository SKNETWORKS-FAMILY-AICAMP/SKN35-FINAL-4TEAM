# IT 운영 조회·집계·연결 평가팩 v0.1

**15개 유형·47문항·골든60개**, 모두 개발용 dev다. 전체 문장과 정답 조건은 [전체 문항 목록](../../QUESTIONS.md)에 있다. 파일 수는 등록 기준이며 독립 검수·제품 채점·팩 잠금 완료를 의미하지 않는다.

## 업무 범위

마지막 성공 배포, 미배정 열린 이슈, 기간별 실패 배포, 느린 배포, 일별 성공/실패 건수, 실패 후 최초 복구, 환경별 버전, 담당자별 열린 이슈, 방치된 미배정 이슈, 종료 이슈, 라벨별 건수, 배포-릴리스 연결, 연속 실패 수, 라벨 없는 열린 이슈, 미배포 릴리스를 다룬다.

첫 두 유형은 각4문항, 나머지는 각3문항이다. 이 팩은 조회형이며 승인 후 쓰기는 별도 it_ops_writes와 it_ops_incidents 팩에서 다룬다.

## 데이터·정답·골든

- data/deployments.json: 배포 조회. UTC/KST 날짜 경계·다른 환경·실패 기록 포함.
- data/issues.json: 미배정 이슈. 번호는 저장소 내 집합으로 비교하며 빈 목록 정답 포함.
- data/operations.json: 나머지13유형. 기간은 [start,end), 느림은 기준 초과, 방치는 cutoff 미만.
- reference의 정답 계산기는 데이터에서 정답을 재계산한다. 문자열 link 조건에 더해 임시 검사기가 저장소·SHA 관계를 확인한다. 제품 필드 기반 관계 검증은 ①② 협의가 남아 있다.
- 대표 유형15개 모두 success/alt_success/near_miss/forbidden 4종씩 원본 등록했다. 상세는 [골든 안내](golden/README.md).

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/deployment_answer.py
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/issue_answer.py
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/batch_reference.py
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/verify_golden.py --all
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/smoke_run.py
```

가짜 실행은 47문항×5시나리오=235건. 생성물은 tmp/deployment-smoke/다. all_matched는 기대한 성공·실패를 구별했다는 뜻이며 실제 모델 성공률이 아니다. 시각은 합성값이고 실제 비용·토큰을 측정하지 않는다. 결과 분류와 첫 실패 단계의 독립 라벨 검수는 미완료다.

## 실제 MCP·DB 상태

[연습 서버 안내](practice/README.md)의 서버·Docker 이미지로 조회 도구5개를 실제 제공한다. 실제 stdio 호출20건과 서버/데이터 버전·해시를 확인했다. 후보 도구 차이를 보존하는 매핑과 ① 제품 엔진의 컨테이너 수명주기·sa_env_checks 연동은 후속이다.

load_pack은 구현됐고 실제 Docker DB에 47문항·골든60개를 저장·조회한 후 롤백했다. 제품 팩을 영구 등록하거나 잠그지는 않았다. select_tasks/lock_pack도 구현됐으나 현재 독립 환경/제품 채점 증거가 없어 잠금은 거절된다.

## 남은 일과 문서 관리

[검수표](REVIEW_CHECKLIST.md)에 유형별 한계와 독립 확인 대기 항목을 유지한다. 실제 LLM 파일럿·held 확보·제품 규칙 채점과 리포트 통합은 남아 있다.

문항은 pack.json에서 관리하고 scripts/update_pack_catalog.py로 단일 전체 목록을 갱신한다. reference/build_batch.py는 기존10유형을 재생성하는 개발 도구다. 잠금 후 실행하지 않고, 실행 시 골든·데이터·서버 해시 재검증이 필요하다.
