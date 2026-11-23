# IT 운영 파일럿 — 템플릿 15개 검수표

2026-11-23 / 대상: 개발용 v0.1, 15개 유형·47문항.

**작성·1차 점검: Codex(② 작업 지원). 독립 확인자: 미배정. 최종 승인: 미완료.** 이 표의 확인은 문장·코드·합성 데이터의 정합성 점검이며, 작성자와 다른 확인자의 승인이나 제품 검증을 대신하지 않는다.

## 템플릿별 점검

아래 모든 유형은 기존 정답 조건 스키마 검사·데이터에서 정답 재계산·가짜 실행 5개 시나리오에 연결돼 있다. 경계값을 데이터/코드 수준에서 확인했더라도 실제 모델이 이를 구별하는지는 별도다.

| # | 유형 | 문항 | 핵심 정답 기준 / 확인한 함정 | 골든 원본 | 후속 확인 |
|---|---|---:|---|---|---|
| 1 | DEPLOY_LATEST_SUCCESS | 4 | 저장소·환경·성공·KST 날짜를 거른 뒤 마지막 종료. 다른 환경·실패·UTC 날짜 경계 포함 | 4종 등록 | ① 재채점, 동률/누락 오류 정책 확인 |
| 2 | ISSUES_UNASSIGNED_OPEN | 4 | open + 지정 라벨 + assignees=[]; 번호는 저장소 안에서 집합 비교. 빈 정답 포함 | 없음 | null/누락 assignees 정책은 미지원 |
| 3 | DEPLOY_FAILURES_PERIOD | 3 | 종료 시각 [start,end), failure만. 끝 경계 제외 | 없음 | 실제 API 페이지·기간 필터 대응 |
| 4 | DEPLOY_SLOW_RUNS | 3 | 종료-시작 > threshold. 같은 값은 제외, 성공 여부 무관 | 없음 | 음수/누락 시각 입력 정책 |
| 5 | DEPLOY_DAILY_COUNTS | 3 | KST 종료 날짜, 환경별 성공·실패 각각 집계 | 없음 | cancelled/pending 등 상태 확대 |
| 6 | DEPLOY_RECOVERY | 3 | 지정 실패 종료 이후 최초 성공 종료 | 없음 | 복구 없음·동률 사례 미포함 |
| 7 | DEPLOY_ENV_COMPARE | 3 | production/staging 각각 마지막 성공 버전 | 없음 | 한 환경에 성공이 없는 경우 미포함 |
| 8 | ISSUES_ASSIGNED_OPEN | 3 | open + assignee 포함. 미존재 담당자 빈 정답 포함 | 없음 | 다중 담당자 데이터 확대 |
| 9 | ISSUES_STALE_UNASSIGNED | 3 | open + 미배정 + updated_at < cutoff. 같은 시각 제외 | 없음 | cutoff와 고정 현재 시각 관계 설명 검수 |
| 10 | ISSUES_CLOSED_PERIOD | 3 | closed + closed_at이 [start,end). 끝 경계 제외 | 없음 | 재오픈 이력 미포함 |
| 11 | ISSUES_LABEL_COUNTS | 3 | open만, 복수 라벨이면 각 항목에 중복 집계 | 없음 | 세 문항 답이 같은 점에 따른 다양성 보강 |
| 12 | DEPLOY_RELEASE_LINK | 3 | 같은 저장소의 마지막 성공 배포 SHA와 릴리스 SHA 연결 | 없음 | 필드 기반 link 계약 협의; 문자열만으로 관계 증명 불충분 |
| 13 | DEPLOY_FAILURE_STREAK | 3 | 종료 최신순으로 첫 성공까지 실패 수, 최신 성공이면 0 | 없음 | 동률·진행중 상태·재실행 정책 |
| 14 | ISSUES_UNLABELED_OPEN | 3 | open + labels=[] | 없음 | null/누락 labels는 초안 범위 밖 |
| 15 | DEPLOY_UNDEPLOYED_RELEASES | 3 | 지정 환경의 성공 SHA 어디에도 없는 릴리스 태그; 실패/다른 환경 제외 | 없음 | 목록 완전성·페이지 누락 검사 필요 |

## 공통 체크

- [x] 유형 15개, 문항 47개, 유형별 2~4문항 및 고유 문항 코드 확인.
- [x] 문항→유형 참조, 필요 capability 목록 및 정답 조건 스키마 검사.
- [x] 원본 JSON에서 정답 재계산. 독립 기대값 테스트와 날짜/기간 경계·빈 결과 사례 포함.
- [x] 첫 대표 유형 골든 4종의 trace/expected 스키마와 임시 조건별 판정 대조.
- [x] 실제 정답 수치나 정답 ID를 문항에 직접 적지 않음. 조회 범위·업무 조건은 명시.
- [x] 원본 파일은 로컬 평가팩 아래 관리. 합성 데이터·KST·기간 경계를 문서화.
- [ ] 출제자 외 사람이 자연스러움·답 유출·모호성·업무 현실성을 독립 검수.
- [ ] 유형별 필요 capability를 ④와 확인. 실제 API가 기간·환경·상태·SHA 필드를 제공하는지 확인.
- [ ] 고정 스냅샷 해시를 DB에 저장하고 실행 시작 시 일치 검사. 현재는 파일 기반 재계산만 함.
- [ ] 나머지 대표 유형 14개의 골든 4종씩 등록. 전체 잠금 전에 모두 검증.
- [ ] 첫 유형의 결과 분류·첫 실패 단계 기대 라벨을 독립 검수하고 ① 제품 출력과 대조.
- [ ] load_pack/lock_pack·DB 저장·실제 MCP 응답 적합성·격리·외부 쓰기 차단 통합 검증.
- [ ] 모델에 정답·reference·검수표·golden이 노출되지 않는 실제 실행 경로 확인.
- [ ] held 유형 별도 확보. 현재는 전부 dev이며 독립 성능 추정용이 아님.
- [ ] P-05 승인 계약 팀 확인 및 승인 후 쓰기 유형 추가. 현재 모든 문항은 조회 전용.
- [ ] 실제 모델 반복 실행의 시간·토큰·비용 측정, ③과 15개 유형의 표본 적정성 검토.

## 발견 사항과 판정

**개발 지속 가능, 평가팩 잠금/검증 완료 표시는 보류.** DB 등록과 제품 채점 통과가 완료 기준이라는 팀 규약은 아직 충족하지 않았다.

초기 pack premises의 ‘마지막 성공 배포 조회’ 문구는 첫 유형에만 해당한다. 나머지 유형은 각 prompt와 slot_values가 기준이다. 모든 유형이 대표 유형으로 설정되어 있는데 현재 골든은 첫 유형에만 있으므로 전체 팩의 잠금 게이트를 통과했다고 해석하면 안 된다.

합성 데이터는 작은 고정 집합이며 실제 API의 null·페이지네이션·오류·로그인 형식까지 재현하지 않는다. 정상 성공/다른 경로 성공은 같은 도구의 조회 범위를 바꾼 수준이다. 첫 15개 수량은 확보했지만 다양한 능력을 포괄하는 제품 파일럿은 쓰기·다단계 관계·오류 데이터 확장이 더 필요하다.

① 제품 규칙 채점은 현재 NotImplementedError 상태다. 이번 골든 조건 비교는 `grade_smoke` 임시 검사기이며 결과 3분류와 첫 실패 단계는 자동 검증하지 않았다. 190/235개 가짜 실행의 기대값 일치는 실제 LLM 성능이나 통계 검증 통과를 뜻하지 않는다.

## 재확인 명령

```powershell
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/verify_golden.py
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_golden.py backend/tests/test_pack_deployment.py backend/tests/test_pack_batch.py backend/tests/test_pack_issues.py backend/tests/test_deployment_smoke.py
```

독립 검수 기록은 `검수자 / 날짜 / 유형 / 수정 요청 / 재확인 결과`로 이 문서에 추가한다. 미완료 체크는 증거가 생긴 뒤 변경한다.
