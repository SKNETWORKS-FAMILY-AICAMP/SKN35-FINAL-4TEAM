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
