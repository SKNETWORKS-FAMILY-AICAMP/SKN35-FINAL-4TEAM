# 기능 이름표 사전 (초안, 11/23) — ②④ 같이 관리

문항 유형의 `required_capabilities`(②)와 도구의 `capabilities`(④)는 **이 표의 이름만** 씁니다.
같은 이름이어야 실행 전 범위 판정(`checks.template_scope`)이 맞습니다. 결정 기록: `docs/decisions_pending.md` P-13.

## 규칙
- 이름 모양: `<서비스>.<대상>.<read|write>` (더 잘게 나눌 땐 `<서비스>.<대상>.<세부>.<read|write>`)
- **"무엇을 할 수 있다는 뜻인지"를 먼저 적고**, "해당하지 않는 경우"로 경계를 분명히 함
- 목록 조회 ≠ 상세 조회, 실행 요약 ≠ 로그 조회 → 다르게 필요하면 이름표를 나눔
- 도구 하나에 이름표 여러 개 가능
- 처음 보는 도구는 이름만 보고 자동 확정하지 않음 → 사람 확인
- 누락·오타는 등록 오류나 확인 대상 (후보 능력 부족으로 단정하지 않음)
- 새 이름표 추가: 이 표에 한 줄 + ②④ 둘 다 확인. 지운 이름표는 지우지 말고 "안 씀" 표시
- 사전이 안정되면 코드 검사용 목록 파일을 만들어 `checks` 가 읽게 함 (그때 CHANGELOG)

## 사전
| 이름표 | 정확한 뜻 (할 수 있는 것) | 해당하지 않는 경우 | 예시 도구 |
|---|---|---|---|
| `github.releases.read` | 저장소의 릴리스 **목록**과 각 릴리스의 버전·시각 조회 | 배포(워크플로) 실행 정보만 조회 | `list_releases` |
| `github.actions.read` | 워크플로 **실행 요약** 목록 조회 (이름·상태·시각·커밋) | 작업 단계·로그까지 본다고 가정하지 않음 → `github.actions.logs.read` | `list_workflow_runs` |
| `github.actions.logs.read` | 워크플로 실행 하나의 **작업 단계와 실패 로그** 조회 | 실행 목록만 조회 | (후보 B 의 `list_workflow_jobs` 를 여기로 옮길지 ②④ 확인) |
| `github.issues.read` | 조건(상태·라벨·담당자)으로 이슈 **목록** 조회 | 이슈 번호 하나의 상세만 조회 | `list_issues` |
| `github.code.read` | 저장소 코드 검색 | 파일 하나 내용 읽기만 | `search_code` |
| `github.issues.write` | 이슈 생성 | 댓글만 달기 | `create_issue` |
| `slack.messages.write` | 지정 채널에 메시지 작성 | 채널 목록 조회만 | `post_message` |
| `db.errors.read` | 연습 DB 에서 기간별 에러 수 조회 (읽기 전용) | 임의 SQL 실행 (= 쓰기로 봄) | `query_errors` (1.3 5.5 예시) |

## 확인할 것 (②④)
- [ ] 지금 예시는 `list_workflow_jobs` 를 `github.actions.read` 로 붙였는데, 단계·로그까지 보는 도구라 `github.actions.logs.read` 로 나눌지
- [ ] IT 운영 파일럿 문항 15개에 필요한 이름표가 이 표로 다 되는지
- [ ] 장애 기록·배포 기록 등 연습 DB 이름표 추가


## 운영 계산형 추가 이름표 — ② 제안 / ④ 확인 대기

아래는 it_ops 팩의 metrics 개발 그룹의 필요 기능을 표현하기 위한 제안이다. 기존 확정 이름표로 자동 간주하지 않고, ②④ 확인 전 실제 후보 도구에 자동 부여하지 않는다. 실제 연습 MCP/DB 구현도 아직 없다.

| 이름표 | 제안 의미 | 포함하지 않는 것 | 개발용 어댑터 |
|---|---|---|---|
| `db.requests.read` | 서비스·시간별 총 요청 수와 그중 오류 요청 수 조회 | 에러 로그 건수만 조회, 임의 쓰기 SQL | query_metric_traffic |
| `db.incidents.read` | 서비스별 장애 시작·종료 시각 조회 | 로그의 ERROR 시각을 장애 구간으로 추정 | query_metric_incidents |
| `db.latency.read` | 서비스·시간별 개별 요청 지연 표본 조회 | 이미 집계된 평균만 조회해 p90을 복원한다고 가정 | query_metric_latency |

에러 레코드 수/중복 제거는 기존 `db.errors.read`를 사용한다. 집계 raw 데이터와 최종 계산값의 근거 연결 규칙은 ① 제품 채점기와 확인해야 한다.


## 요청 흐름 복원 이름표 — ② 제안 / ④ 확인 대기

| 이름표 | 제안 의미 | 포함하지 않는 것 | 개발용 어댑터 |
|---|---|---|---|
| `ops.traces.read` | 지정 trace ID의 span·부모 관계·시각·서비스 조회 | 단순 워크플로 실행 목록만으로 서비스 간 요청 경로를 추정 | read_workflow_context(trace 시나리오) |

it_ops 팩 workflows 그룹의 개발용 필요 기능이며 실제 후보에 자동 부여하지 않는다. 실제 trace 조회 도구·서비스 범위는 ①④ 확인이 필요하다. 나머지 새 유형의 기존 이름표도 실제 어댑터 입력·출력을 확인한 뒤 매핑한다.


## ① 회신 후보1~5의 기능 제안 — ② 제안 / ④ 확인 대기

| 이름표 | 제안 의미 | 경계 |
|---|---|---|
| ops.dependencies.read | 명시된 서비스의 caller→dependency 그래프 조회 | 그래프만으로 실제 장애를 확정하지 않음 |
| ops.health.read | 이전 제안·사용 안 함(현재 후보2는 ops.status.read로 정리) | 자동 별칭 매핑하지 않음 |
| web.urls.read | 이전 제안·사용 안 함(현재 후보5는 web.pages.read로 정리) | 자동 별칭 매핑하지 않음 |

위3개는 로컬 합성 평가의 필요 기능을 표현한 제안이며 후보 도구에 자동 부여하지 않는다. 로그·코드·명시 필드 마스킹은 기존 이름표를 재사용하되 실제 데이터 필드 제공 여부는 도구 매핑에서 확인해야 한다.


## role2_reply_8types.md 제안 형식으로 정리 — ②④ 최종 확인 대기

| 이름표 | 이번 로컬 유형의 의미 | 경계 |
|---|---|---|
| ops.status.read | 고정 시각의 서비스 상태·자체 오류 수·상위 오류 조회 | 임의 로그만으로 원인 확정 아님 |
| github.code.content.read | repo/commit/path로 해당 커밋의 파일 내용 조회 | 기존 github.code.read의 코드 검색과 구별 |
| ops.incidents.read | 합성 장애 원문 조회 | 답 전체의 민감정보 유출 검사 아님 |
| web.pages.read | 고정 URL의200/302/403 응답과 location 조회 | 자동 리다이렉트·실제 네트워크 허용 아님 |

ops.dependencies.read는 앞선 제안을 유지한다. ① MD의 이름은 가칭이며 이번 정리는 평가팩의 필요 기능 제안이다. 실제 후보의 기능 확정/자동 등록/기존 이름표의 자동 별칭은 수행하지 않는다. MD 예시의 service=github도 자리표시이므로 실제 서비스 분류로 임의 확정하지 않는다.
