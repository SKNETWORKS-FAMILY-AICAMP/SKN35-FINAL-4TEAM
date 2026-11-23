# SlotAgent — 복사용 뼈대 (2026-11-23 최신)

11/23 원본 slotagent_skeleton의 DB 이름 6차 규칙을 반영한 개발 시작용 패키지입니다.
압축을 풀면 나오는 내용물을 저장소 루트에 복사합니다. 기존 저장소의 동명 파일은 비교한 뒤 반영하세요.
실제 에이전트 실행·프런트엔드가 완성된 서비스는 아니며, 역할별 구현 자리와 계약·DB 연결 검증을 제공합니다.

## 폴더

```text
backend/
  pyproject.toml
  src/slotagent/
    common/        # ① 공통 DB·큐·검사·해시
    engine/        # ① 잠금·실행·기록·단계 전환
    orchestrator/  # ① 고도화 구현 자리
    mcp_server/    # ① MCP 서버 구현 자리
    workers/       # ① 작업 처리 등록표
    grading/       # ① eng_* 규칙 / ② pack_* 판정·분류
    packs/         # ② 평가팩 로딩
    stats/         # ③ 통계
    intake/        # ④ 등록
    chatbot/       # ④ 대화
    reports/       # 공동, 1차 ③
    api/           # 공동, 1차 ①
  tests/
  db/              # 마이그레이션·시드·연습 DB·NAMES.md
frontend/          # Next.js 구현 자리
contracts/         # 원본 스키마·예시, 변경 없음
packs/             # 평가팩 원본
serving/           # Linux GPU 모델 서빙 구현 자리
runner/            # ④ 고객 러너 구현 자리
scripts/
docs/
fixtures/
```

## 처음 실행

```powershell
Copy-Item .env.example .env
# .env의 로컬 개발 설정을 확인한 뒤 실행합니다.
docker compose up -d
cd backend
uv sync
cd ..
./scripts/test.ps1
```

테스트는 pgserver 임시 DB를 사용하므로 Docker와 로컬 PostgreSQL 없이도 실행할 수 있습니다.
Python 3.12와 uv가 필요합니다. 첫 실행에는 테스트 의존성을 다운로드할 수 있습니다.
Compose는 PostgreSQL 17을 사용하며 새 볼륨의 최초 초기화 때 backend/db/migrations를 적용합니다.
기존 볼륨에는 초기화 SQL이 다시 실행되지 않으므로 추가 마이그레이션을 별도로 적용해야 합니다.
연습 DB는 제품 DB와 별도로 구성합니다(backend/db/practice 참고).

## 이름과 역할 경계

테이블은 sa_<테이블>, PK는 <테이블 단수>_id(domains만 domain_code), FK는 참조 PK 이름, 일반 칸은 짧은 ERD 이름을 씁니다.
전체 대응표: backend/db/NAMES.md. 변환 코드: backend/src/slotagent/common/db_names.py.

④ 등록 → ② 평가팩 → ④ 실험 초안 → ① 잠금·실행 → ①② 채점 → ③ 통계 판정 → 공동 리포트·④ chatbot.
역할 사이는 DB와 contracts로 연결하며 공통 함수는 common에서 제공합니다.
4단계 이후 작업 전환과 실험 상태는 engine/advance.py가 담당합니다.
② LLM 판정기는 규칙으로 못 보는 항목을 맡고, 고도화 LLM은 판정에 개입하지 않으며 ③ 통계는 LLM을 쓰지 않습니다.

## 검증과 남은 일

2026-11-23 이 패키지의 계약·DB 연결 테스트: 30 passed.
테스트는 backend/db로 옮긴 마이그레이션·시드를 실제 임시 DB에 적용합니다.
동시 워커·장애 복구·실제 실행 격리를 검증했다는 의미는 아닙니다.
P-01·P-05 등 팀 결정 사항은 docs/decisions_pending.md의 임시 값을 유지했습니다.
계약 스키마·예시는 원본과 같고 고도화의 tool_search 계약은 추가하지 않았습니다.
CODEOWNERS의 @role-*는 실제 담당자의 GitHub 아이디로 바꿔야 합니다.
