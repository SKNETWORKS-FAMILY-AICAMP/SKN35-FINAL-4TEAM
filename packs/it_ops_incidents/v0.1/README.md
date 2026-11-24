# 장애 분석·근거 연결·승인 공유 평가팩 (dev 초안)

기존 조회 팩 15개 유형과 단순 쓰기 팩 2개 유형을 유지하면서 **새 3유형·9문항**을 별도 `it_ops_incidents/v0.1` 팩으로 추가했다. 모두 IT 운영 도메인이며 세 팩을 합쳐 하나의 검증된 평가 결과로 취급하지 않는다.

| 유형 | 실제 요청 예 | 문항 |
|---|---|---:|
| LOG_FIRST_ERROR | payment 실행501의 로그에서 첫 ERROR 코드·시각 찾기 | 3 |
| RUN_ISSUE_RELATION | 실패 배포의 SHA와 연결된 closed 이슈 찾기 | 3 |
| CONFIRMED_INCIDENT_SHARE | 로그·SHA·이슈 확인 후 허락받아 ops-alerts 공유 | 3 |

전체 문장·정답·고정 정책은 [전체 문항 목록](../../QUESTIONS.md)에 있다. 이 문서는 정답을 포함하므로 에이전트 실행 환경에 제공하지 않는다.

## 설계 기준

로그 분석은 근본 원인을 추측하는 문제가 아니다. 시간순 최초 ERROR를 관측 근거로 식별한다. WARN·후속 정리 오류·다른 환경을 혼동하면 실패다. 자유 서술의 ‘근거 없는 원인 단정’ 여부는 아직 LLM/사람 라벨 기준이 없으므로 자동 채점했다고 주장하지 않는다.

연결은 같은 저장소 + 배포 head_sha=이슈 fixed_in_sha + closed를 모두 요구한다. 제목에 같은 오류 코드가 있어도 관계가 다르면 오답이다. 현재 계약의 link.result_contains를 함께 작성했고, 임시 검사기는 필드 관계를 추가 검증한다. 제품 채점기의 문자열 검사만으로 이 관계까지 보장하려면 ①과 link 계약 확장이 필요하다.

공유형은 최초 오류·배포 SHA·관련 이슈를 먼저 확인하고 승인 요청을 한다. 승인/거절/응답 없음 정책은 모델에게 주지 않고 엔진이 적용한다. 승인된 전체 인자와 실제 쓰기가 같아야 하며 승인 후 누락은 종료 조건 실패다. 외부 전송은 전혀 하지 않는다.

## 구현·검증 범위

- data/incidents.json: 세 서비스의 배포·로그·이슈와 혼동 사례. 정답 전용 칼럼 없음.
- pack.json: 기존 info/link/order/forbidden/end_state 계약을 사용한 9문항.
- evaluate.py: 실제 JSON 조회, 기준 정답 계산, 고정 모델/엔진 시뮬레이션, 제한된 임시 검사.
- golden/: 각 유형 정상/전체범위 조회 성공/오답/금지 쓰기 4종씩 총12개. 독립 사람 검수·제품 채점 검증 전.

```powershell
.venv/Scripts/python.exe packs/it_ops_incidents/v0.1/evaluate.py
.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_pack_incidents.py
```

가짜 실행은 46건이며 tmp/incident-smoke에 기록한다. 승인 정책·정답 조건은 모델 입력에서 제외한다. 조회 없는 정답 시나리오는 이미 만든 답에서 조회 기록을 제거한 공격 fixture다. 시간·지연은 합성값이고 실제 비용/모델 성능을 측정하지 않는다.

임시 답 형식과 메시지 내용은 구조화 JSON이다. 임시 종료 검사는 메시지 핵심값을 비교하지만 현행 제품 end_state는 채널 중심이라, 제품의 ‘발송 내용이 충분한가’ 채점은 ①② 추가 확인이 필요하다. 같은 도구를 전체/저장소 범위로 조회한 두 경로이며 실제 후보 구현 간 비교를 대신하지 않는다.

현재 GitHub 연습 MCP 서버 5개 도구에는 이 팩의 get_incident_logs/list_incident_runs/list_incident_issues가 아직 없다. 해당 서버 확장·Slack fake write_proxy·P-05 DB 칼럼 적용·제품 엔진 연동은 후속이다. 이번에는 기존 서버·DB·공용 계약을 변경하지 않았다. 모든 유형은 dev이며 held/검증 완료 표시는 하지 않는다.
