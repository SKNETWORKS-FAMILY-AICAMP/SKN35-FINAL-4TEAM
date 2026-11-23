# 첫 배포 조회 평가팩 (개발용 초안)

IT 운영 템플릿 15개, 총 47문항. 첫 템플릿: 지정한 날짜·저장소·환경에서 마지막으로 성공한 배포의 종료 시각과 버전 조회. 같은 틀에서 값을 바꾼 개발용 문항 4개를 포함한다.

| 문항 | 날짜(KST) | 저장소 | 환경 | 정답 시각 | 정답 버전 |
|---|---|---|---|---|---|
| 001 | 2026-11-16 | acme/ops-service | production | 18:20 | v1.8.3 |
| 002 | 2026-11-17 | acme/ops-service | production | 00:05 | v1.8.5 |
| 003 | 2026-11-16 | acme/ops-service | staging | 19:00 | v1.9.0-rc1 |
| 004 | 2026-11-16 | acme/other-service | production | 21:00 | v3.0.0 |

- `data/deployments.json`: 에이전트가 조회할 합성 원본 데이터. 실패한 배포·다른 저장소·staging·한국 날짜 경계를 포함한다.
- `reference/deployment_answer.py`: 평가 준비용 기준 정답 계산 및 정답 조건 일치 검사.
- `pack.json`: 기존 평가팩 예시 구조에 맞춘 문항 47개와 정답 조건. 수정에 사용하는 유형이므로 모두 `split=dev`이다.

## 실행 (저장소 루트, PowerShell)

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/deployment_answer.py
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_deployment.py
```

UTC 종료 시각을 KST로 변환한 뒤 날짜·저장소·환경·성공 여부로 필터하고, 가장 늦은 배포를 선택한다. 후보가 없거나 마지막 시각이 동률이면 임의로 고르지 않고 오류를 낸다. 데이터 또는 정답 조건이 바뀌어 서로 어긋나면 검증이 실패한다. 002는 UTC 날짜와 한국 날짜의 차이를, 003·004는 환경·저장소 구분을 확인한다.

## 경계와 다음 단계

가짜 모델 실행은 저장소 루트에서 다음 명령으로 확인한다.

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/smoke_run.py
```

`tmp/deployment-smoke/`에 기존 trace 스키마를 통과한 실행 기록 235개와 `summary.json`을 저장한다. 전체 문항 47개 × 정상 성공·전체 목록을 통한 다른 경로 성공·오답·조회 없는 정답·가짜 쓰기 위반의 5개 시나리오다. 읽기 도구는 실제 합성 JSON을 읽고 가짜 쓰기는 기록만 남긴다. 외부 API·DB·실제 LLM을 호출하지 않는다.

`reference/smoke_run.py`의 검사기는 현재 15개 템플릿의 구조화 JSON 응답과 현재 정답 조건만 지원한다. 기존 ①번 `eng_rules`를 구현하거나 대체한 것이 아니다. 실행 결과가 정답과 일치하는지와 조회 결과에 근거가 있는지를 각각 검사한다. 조회 없는 정답 사례에만 테스트용 정답을 명시적으로 주입하며, 정상 시나리오는 문항과 조회 데이터로 답을 만든다. 시간은 합성값이고 비용·토큰 수는 측정하지 않는다. 이 결과를 실제 모델 성능이나 제품 채점 검증 통과로 해석하지 않는다.

이 폴더는 아직 잠기거나 검증 완료된 평가팩이 아니다. DB 저장, 실제 MCP 실행, 제품 규칙 채점 연동은 다음 단계다. 첫 대표 유형의 골든 4종은 pack.json에 등록했으며, 임시 검사만 통과한 상태다. 나머지 14개 유형의 골든은 미등록이다.

실행 환경에는 읽기용 데이터만 제공한다. `pack.json`과 `reference/`는 정답을 포함하므로 에이전트/러너에 전달하지 않는다. 폴더 전체를 실행 컨테이너에 마운트하지 않는다.

문항은 절대 날짜를 쓰고 승인·쓰기·허용 오차가 필요 없는 범위로 제한했다. 협의 문서의 task_run·tolerance·필드 기반 연결 조건 제안은 아직 이 평가팩에서 도입하지 않았다. 기존 contracts는 변경하지 않았다. 실제 출처 추적과 쓰기 금지 판정은 ①의 trace·규칙 채점 연동 후 별도로 검증한다.

다음에는 나머지 대표 유형의 골든을 추가하고, 첫 4종을 ① 제품 채점기로 확인한 뒤 loader·잠금·환경 검증을 연결한다. 잠긴 버전을 고칠 때는 새 버전을 만든다.


## 두 번째 템플릿: 담당자 없는 열린 이슈 조회

`ISSUES_UNASSIGNED_OPEN`은 지정 저장소에서 해당 라벨이 붙은 미배정 열린 이슈 번호를 모두 묻는다. 모두 개발용(dev)이다.

| 문항 | 저장소 | 라벨 | 정답 번호 |
|---|---|---|---|
| 001 | acme/ops-service | bug | 145, 148 |
| 002 | acme/ops-service | enhancement | 152 |
| 003 | acme/other-service | bug | 145, 210 |
| 004 | acme/ops-service | security | 빈 목록 |

`data/issues.json`에는 닫힌 이슈·담당자 있는 이슈·다른 저장소의 같은 번호·빈 라벨·복수 라벨을 포함했다. 라벨은 대소문자를 구분한 정확 일치이고 미배정은 `assignees=[]`로 정의한다. 번호는 문자열 집합으로 비교하므로 응답 순서는 무관하지만 누락·추가는 실패다. 기존 `github.issues.read` 기능 이름표를 사용한다.

원본 데이터와 정답의 연결은 다음 명령으로 검사한다.

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/issue_answer.py
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_deployment.py backend/tests/test_pack_issues.py backend/tests/test_deployment_smoke.py
```

빈 목록 정답도 실제 조회 기록이 있어야 통과한다. 실제 MCP·DB·제품 채점기 연동과 골든 등록은 아직 수행하지 않았다.


## 추가 10개 템플릿 (3문항씩, 총 30문항)

전체 문장과 정답은 [BATCH_10.md](BATCH_10.md)에 정리했다. 기간·시간 기준은 문항마다 명시하며 모든 시각은 KST로 해석한다.

1. 지정 기간의 실패 배포 목록
2. 기준 시간보다 오래 걸린 배포
3. 날짜별 성공·실패 배포 건수
4. 실패 후 최초 복구 배포
5. production·staging 최신 버전 비교
6. 담당자별 열린 이슈
7. 오래 방치된 미배정 이슈
8. 지정 기간에 닫힌 이슈
9. 열린 이슈의 라벨별 건수
10. 배포 커밋과 릴리스 연결

`data/operations.json`은 세 저장소의 합성 원본 데이터다. `reference/batch_reference.py`가 정답을 계산하고 저장된 조건과 비교한다. `reference/build_batch.py`는 개발용 초안 생성 코드이며 재실행하면 해당 10개 유형을 재생성한다. 잠금 후에는 실행하지 않는다.

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/batch_reference.py
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_batch.py backend/tests/test_pack_deployment.py backend/tests/test_pack_issues.py backend/tests/test_deployment_smoke.py
```

새 30문항은 정답 재계산·스키마·기간 경계·배열 순서·연결 무결성을 검증했다. 가짜 모델 실행기는 현재 15개 유형 전체를 지원하며 `unsupported_templates`는 빈 목록이다. 47문항에 5개 시나리오를 적용해 235건을 실행한다. 실제 모델 실행·골든 등록·① 제품 채점기 검증은 남아 있다.

릴리스 연결은 저장소+SHA로 정답을 계산하며 현행 `link.result_contains` 계약도 사용한다. 이 문자열 검사만으로 필드 관계를 완전히 증명할 수는 없어 ①② 협의 자료의 필드 기반 연결 조건은 계속 협의가 필요하다. 승인 후 쓰기 유형은 승인 이벤트 계약과 엔진 연동 이후 추가한다. 이번 10개는 조회·집계·연결 업무에 한정한다.


## 전체 가짜 실행 연결

`reference/batch_fake.py`는 추가 10개 유형을 고정 행동으로 푼다. `operations.json`을 도구 호출 때 실제로 읽고, 저장소별 목록 조회 또는 전체 목록 조회 뒤 문항 조건으로 필터·집계·연결한다. 정상 실행에는 정답 조건이나 기준 정답 계산 함수를 전달하지 않는다. 임시 검사기는 실행 기록에 저장된 조회 결과에서 정답을 다시 계산해 최종 답과 정답 조건을 검사한다.

릴리스 연결 유형은 배포와 릴리스 두 조회 결과가 모두 있어야 하고, 저장소·SHA 연결도 일치해야 한다. 한쪽 조회가 없거나 연결이 깨지면 실패다. 같은 유형의 링크 문자열 조건도 추가 검사한다. 이는 제한된 합성 실행 기록용 검사이며 임의의 제품 trace 전체를 검증하는 범용 출처 추적기는 아니다.

정상 성공·다른 조회 경로 성공·오답·조회 없는 정답·금지 쓰기 5개 시나리오가 모두 예상대로 판정되면 `all_matched=true`다. 이는 실제 모델의 성공률이 100%라는 뜻이 아니다. 시각·지연은 합성값이며 실제 LLM 비용과 토큰은 측정하지 않는다. 생성된 trace는 스키마 검증을 통과하지만 자동으로 잠긴 골든 데이터로 등록되지는 않는다.


## 파일럿 추가 3개 유형 (각 3문항)

전체 문장과 정답은 [PILOT_3.md](PILOT_3.md)에 있다.

- `DEPLOY_FAILURE_STREAK`: 최신 종료 기록부터 성공을 만날 때까지의 연속 실패 수. 최신 성공이면 0.
- `ISSUES_UNLABELED_OPEN`: 라벨이 빈 배열인 열린 이슈 전체 조회.
- `DEPLOY_UNDEPLOYED_RELEASES`: 릴리스의 SHA가 지정 환경의 어떤 성공 배포 SHA와도 일치하지 않는 태그 조회. 다른 환경·실패 배포는 제외.

세 유형은 기존 `operations.json` 스냅샷을 사용하며 모두 dev다. 기존 capability 이름만 사용하고 계약 스키마는 변경하지 않았다. 성공 배포되지 않은 릴리스 판정에는 배포·릴리스 양쪽 조회 기록이 필요하다. 현재 15개 유형의 모든 47문항에 5개 시나리오를 연결해 235건을 검사한다. 이는 조회 중심의 개발용 파일럿이며, 승인 후 쓰기 유형·실제 비용/시간 측정·held 분리·제품 채점 검증은 별도 작업이다.


## 검수표와 첫 대표 유형의 골든

- [15개 템플릿 검수표](REVIEW_CHECKLIST.md): 유형별 확인 사항·미완료 항목·독립 검수 대기 상태.
- [골든 4종 안내](golden/README.md): 첫 배포 조회 유형의 success/alt_success/near_miss/forbidden.
- `pack.json`의 `golden`에 trace 경로·대상 문항 코드·조건별 기대 판정을 등록했다. DB 등록이나 잠금 완료를 뜻하지 않는다.

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/verify_golden.py
```

임시 검사기는 전체 성공·조건별 통과·금지 행동만 확인한다. 결과 분류·첫 실패 단계의 목표 라벨은 별도 검수와 ① 제품 채점기 확인이 남아 있다.
