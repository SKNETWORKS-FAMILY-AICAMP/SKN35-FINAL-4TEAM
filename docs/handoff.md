# 작업 인계 기록

Codex·Claude·팀원이 같이 씁니다. **새 기록은 맨 위에** 더합니다. 한 작업에 기록 하나를 씁니다.

```
## YYYY-MM-DD · <도구 또는 사람> · <브랜치>
- 한 일:
- 안 한 일 / 남은 일:
- 의문점 (계약·미정 사항과 부딪힌 곳):
```

---

## 2026-11-23 · Codex · taemin (공통 DB 연결)
- 한 일: common/db.py에 get_database_url·connect를 구현했습니다. 환경 변수 우선, 없으면 저장소 루트 .env를 읽되 프로세스 환경은 변경하지 않습니다. URL·포트·접속 제한 시간을 확인하고 기본 tuple 행·트랜잭션 연결, 선택적 autocommit을 제공합니다. 새 test_eng_db.py에서 설정 우선순위·잘못된 설정의 비밀값 비노출·조회·커밋·롤백·연결 종료·autocommit을 확인했습니다. 기존 선언된 python-dotenv를 테스트 실행 환경에 추가하고 test.ps1이 실패 코드를 전달하게 수정했습니다. 전체 54 passed, Ruff·추가한 두 파일 포맷 검사 통과.
- 안 한 일 / 남은 일: 큐·워커·API 통합은 아직 구현하지 않았습니다. 로컬 PostgreSQL 서비스를 기동했고 기존 볼륨은 app 계정/빈 app DB여서 그대로 보존한 채 별도 slotagent DB를 만들고 빈 DB에만 0001~0003을 적용했습니다. 예시에서 로컬 .env를 처음 만들고 기존 초기 계정 app에 맞췄습니다(실제 API 키 없음, Git 제외). 공통 connect로 PostgreSQL 17.11·제품 테이블 33개·template_scope 존재를 조회 확인했습니다. DB 서비스는 개발용으로 실행 중입니다. 계약·의존성 선언·lock 변경, 커밋·푸시 없음. 생성 캐시·임시 파일은 정리했습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 로컬 계정명 차이는 .env에만 반영하고 공유 .env.example과 기존 DB는 변경하지 않았습니다.

## 2026-11-23 · Codex · taemin (협업 체크리스트 간소화)
- 한 일: 사용자 피드백에 따라 협업 HTML을 51개 상세 항목에서 4단계·12개 핵심 체크로 줄였습니다. ④에게 받기→②에게 받기→① 연결→공동 결과 확인을 세로로 배치하고 요청 문구·받을 것·넘어가는 기준을 크게 표시했습니다. 기술 기준과 파일 메모는 접어서 숨겼습니다. 자동 저장·JSON·인쇄는 유지하고 이전 상세 기록은 전체 근거를 보존하면서 대응 항목이 모두 완료된 경우만 새 체크로 옮깁니다. 저장·JSON 왕복·이전 기록 변환·초기화·인쇄·반응형 화면을 확인했고 임시 파일은 삭제했습니다.
- 안 한 일 / 남은 일: 협업 HTML과 인계 기록만 수정했습니다. 코드·계약·공식 구현 체크리스트는 변경하지 않았습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.

## 2026-11-23 · Codex · taemin (①②④ 협업 체크리스트 HTML)
- 한 일: docs/SlotAgent_협업체크리스트_1123.html을 만들었습니다. 공통 예시 합의→④ 등록 자료→② 평가 자료→① 연결→공동 검수의 51개 수동 체크, 근거·회의·인계 메모, 담당별·미완료 필터와 진행률, 브라우저 저장, JSON 내보내기·가져오기, 초기화 확인, 전체 인쇄를 제공합니다. 승인·거절 존중·무단 쓰기의 기대 결과와 경계 사례, 계약 합의 지점, 상대에게 요청할 문구와 다음 개발 흐름을 적었습니다. Playwright로 저장·새로고침·필터·JSON 왕복·오류 거절·초기화 취소/승인·인쇄·저장 차단 시 내보내기·1440/768/390px 가로 넘침을 확인하고 화면을 검토했습니다. 검증용 JSON·이미지는 삭제했습니다.
- 안 한 일 / 남은 일: HTML과 이 기록만 추가했습니다. 체크 기록은 브라우저 개인 상태로 저장되며 공식 체크리스트·팀 승인·DB 검증을 자동 갱신하지 않습니다. 코드·계약·다른 역할 작업물과 docs/checklist.md의 구현 완료 칸은 변경하지 않았습니다. 백엔드 테스트·커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 거절 경로의 성공 조건과 P-05 세부 계약은 ①②가 확인할 항목으로 두었고 임의 확정하지 않았습니다.

## 2026-11-23 · Codex · taemin (기술 스택 결정 동기화)
- 한 일: 기술 스택 HTML의 P-05 미정 문구를 문항별 고정 가짜 답·공통 확인 도구·승인 대상 비교·풀이별 초기화로 갱신했습니다. P-03의 Docker·stdio·시작 전 검사·연습용 서버 시간 전제와 P-13 기능 사전 결정도 반영했습니다. P-05의 평가팩 계약·도구 정의·비교 규칙은 추가 구현할 항목으로 구분했습니다. 데스크톱·모바일 문구·가로 넘침을 확인하고 검증 이미지는 삭제했습니다.
- 안 한 일 / 남은 일: HTML과 인계 기록만 수정했습니다. 계약·코드·체크리스트는 변경하지 않았습니다. 문서 변경이라 백엔드 테스트는 생략했습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 정책 결정 완료와 계약 구현 예정 상태를 구분했습니다.

## 2026-11-23 · Claude · taemin (P-03·P-05·이름표 정함)
- 한 일: decisions_pending 에 P-03(연습용 MCP 서버를 풀이별 Docker + stdio, 동결 데이터, 시작 전 검사)·P-05(문항별 가짜 사용자 답, 같은 확인 도구, 승인 대상과 쓰기 비교)·P-13(기능 이름표 사전) 정함. `docs/capabilities.md` 초안(이름표 8개, 규칙, ②④ 확인할 것). checklist 1절 갱신. AGENTS.md(로컬) 다시 정리.
- 안 한 일 / 남은 일: P-05 를 위한 평가팩 계약 칸(문항별 승인·거절 답)과 확인 도구 `request_user_confirmation` 정의는 ①② 가 계약 변경으로 (CHANGELOG). 이름표 코드 검사 목록은 사전이 안정된 뒤. 기술 스택 문서(docs/SlotAgent_기술스택_1123.html)의 "P-05 미정" 표기는 이제 정함으로 고쳐야 함. 커밋 안 함.
- 의문점: 없음.

## 2026-11-23 · Codex · taemin (기술 스택 설명 문서)
- 한 일: 사용자 요청으로 docs/SlotAgent_기술스택_1123.html을 새로 작성했습니다. 기획서 1.3 기준으로 기술별 역할·선택 이유·사용 예시를 쉬운 말로 설명하고, 화면→서버→DB→실행→판정 흐름, 모델 회사 4종·공통 어댑터, 쓰기 실행 방식, P-01 확정과 P-05·P-11 미정, 고도화·선택 기술을 구분했습니다. Playwright로 7개 섹션·20개 설명 카드·15개 요약 행·목차·인쇄 버튼·1440/768/390px 가로 넘침·JS 오류를 확인하고 데스크톱·모바일 렌더링을 검토했습니다. 임시 이미지는 삭제했습니다.
- 안 한 일 / 남은 일: 기술 스택 HTML과 이 인계 기록만 작성했습니다. 코드·계약·의존성·다른 문서는 변경하지 않았습니다. 문서 작업이라 백엔드 테스트는 재실행하지 않았습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 채택한 기술과 구현 완료를 구분했습니다.

## 2026-11-23 · Codex · taemin (최신 상태 검토)
- 한 일: 현재 작업 폴더를 수정 없이 검토했습니다. scripts/test.ps1 38 passed, Ruff check --no-cache . 통과, uv lock --check --offline 233 packages 일치, docker compose config --quiet와 staged/unstaged diff 공백 검사 통과. 최신 skeleton과 계약 스키마 16개·예시 8개 일치를 확인했고 개인 AI 파일의 Git 제외도 확인했습니다. 테스트 생성 캐시는 삭제했습니다.
- 안 한 일 / 남은 일: 검토 발견 사항만 보고했습니다. README.md에는 30 passed·P-01 미정·tool_search 미반영, contracts/README.md에는 50개 한도·exclude 선택 설명이 남아 있습니다. 공유 기술 스택 HTML은 현재 docs에 없습니다. 이미 커밋된 0003에 template_scope·러너 토큰 칸을 추가한 상태로, backend/db/README.md의 합친 뒤 0004부터 추가 규칙과 다릅니다. 새 DB 테스트는 통과하지만 기존 DB 업그레이드는 별도 마이그레이션이 필요합니다. Ruff 수정 등 unstaged 변경도 남아 있습니다. 코드·스키마·의존성 변경, 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 위 마이그레이션 규칙과 파일 상태의 차이를 임의로 고치지 않고 보고했습니다. 기획서 1.3 계약의 4명 확인 필요 기록도 유지돼 있습니다.

## 2026-11-23 · Claude · taemin (ruff 정리)
- 한 일: 뼈대부터 있던 ruff 경고 21건을 0건으로. 자동 수정(import 정렬, collections.abc, datetime.UTC, functools.cache, 안 쓰는 import) + 손으로 zip(strict=True) 4곳, 안 쓰는 반복 변수 이름 앞에 _. intake/service.py 는 ④ 구현 자리라 힌트 import 를 noqa 로 남기고 add_candidate 설명에 template_scope 저장을 적음. 동작 변경 없음, 테스트 38 passed.
- 안 한 일 / 남은 일: skeleton(검증용 원본)은 정리 안 함. 커밋 안 함.
- 의문점: 없음.

## 2026-11-23 · Claude · taemin (DB 추가 2개)
- 한 일: `sa_experiment_candidates.template_scope`(실행 전 범위 판정 저장, 계약 common `$defs/template_scope`, needs_review 는 CHECK 로 저장 못 함, 실험 잠금 뒤 못 바꿈)·`sa_agents.runner_token_hash`(UNIQUE)·`runner_token_revoked_at`(러너 연결 토큰, 해시만). NAMES.md·db_names·e2e(저장·거절 확인)·CHANGELOG·review_1122. 테스트 38 passed. ERD 다시 빌드(318칸, 150/10 통과), skeleton 도 같이.
- 안 한 일 / 남은 일: 실험 후보를 넣는 ④ 코드에서 `checks.template_scope` 결과를 채우는 일, 러너 토큰 발급·확인 API(④). 커밋 안 함.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.

## 2026-11-23 · Claude · taemin (기획서 1.3 반영)
- 한 일: ① P-01 확정(범위 밖 = 실패) — prereg·settings `fail` 만, `tool_def.capabilities` + `sa_templates.required_capabilities` + `checks.template_scope`(실행 전 판정), 리포트 `detail.in_scope`. ② 쓰기 도구 `write_mode`(업로드 fake·exclude_tasks / 러너 fake·test_space / API dry_run 필수), 쓰기 도구 10개까지 `checks.check_write_modes`. ③ 모델 회사 `model_provider` 4종(DB·등록 요청·스냅숏). ④ 도구 50개 한도 뺌(토큰 상한 P-11). ⑤ Tool 자리 먼저 `snapshot.PHASE1_KINDS`, 새 MCP 서버 후보 거절. CHANGELOG·contracts/README·review_1122 8차·decisions_pending(P-01 정함, P-11·P-12 추가)·.env.example(키 4종). 테스트 38 passed. 저장소 밖: ERD v1.2 다시 빌드(150/10 통과), 기술스택 문서·부록(50개, dev/held 15/35 예) 고침, skeleton 도 같이 맞춤(38 passed).
- 안 한 일 / 남은 일: 4명 확인(계약 변경). `common/llm.py`·`template_scope` 를 부르는 plan-proposal·리포트 코드. 기획서 1.3 문서의 "평가 워커(Inspect AI)"·"PostgreSQL 16" 표기는 사용자가 고칠 것. 커밋 안 함.
- 의문점 (계약·미정 사항과 부딪힌 곳): P-05(사용자 확인)는 그대로 미정. 1.3 5.5 예시의 "사용자에게 확인 요청 → 승인"은 P-05 ①안(정해 둔 사용자 답)과 맞음.

## 2026-11-23 · Codex · taemin
- 한 일: 사용자 요청으로 CHANGELOG의 11/23 계약 변경 표시를 "④ 확인함(11/23)"으로 바꾸고 최근 인계 기록의 ④ 확인 대기 항목을 정리했습니다.
- 안 한 일 / 남은 일: 확인 표시만 수정했습니다. 코드·스키마·테스트 변경, 커밋·푸시 없음. 문구 변경을 확인했고 실행 테스트는 생략했습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.
## 2026-11-23 · Codex · taemin
- 한 일: 사용자가 복원한 현재 파일을 수정 없이 재검증했습니다. scripts/test.ps1은 33 passed, uv lock --check --offline은 233 packages로 통과했고 docker compose config --quiet·git diff --check도 통과했습니다. contracts/schemas 16개와 examples 8개를 최신 원본과 대조해 일치를 확인했습니다. AGENTS.md·CLAUDE.md·로컬 도구 설정의 Git 제외도 확인했습니다. 테스트 생성 캐시와 불필요해진 계약 복원 패치는 삭제했습니다.
- 안 한 일 / 남은 일: Ruff check --no-cache .는 21건 실패(import 정리·미사용 항목·zip strict 등). 자동 수정하지 않았습니다. common/llm.py와 화면 타입 생성 파일은 아직 없으며 구현 예정입니다. Compose 실제 기동·동시 워커·격리는 이번 검증 범위가 아닙니다. 코드·계약·의존성 변경, 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 핵심 복원 누락은 해소됐지만 정적 검사까지 완료된 상태는 아닙니다.

## 2026-11-23 · Claude · taemin
- 한 일: 패키지를 다시 덮으면서 빠졌던 11/23 계약 변경을 되살림 — 질문을 연결 방식에서 빼고 `sa_agent_versions.questions_used`, `sa_agents.domain_code`, 도구 검색 후보 `tool_search`(component_kind·component_spec·config_snapshot·checks·snapshot). DB 는 0003 끝, CHANGELOG·contracts/README·review_1122 7차, 예시(후보 C)·테스트 3개 추가. 덮기 전 18개 파일이 모두 원본 그대로인지 확인한 뒤 바꿈(다른 수정 없음). scripts/test.ps1 의 중복 -q 를 빼서 요약 줄이 보이게 함. 테스트 33 passed.
- 안 한 일 / 남은 일: 도구 검색 실행(engine/tool_search.py, W5). 커밋·push 안 함.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. P-01·P-05 값은 건드리지 않음.

## 2026-11-23 · Codex · taemin
- 한 일: 이전 폴더 검토의 누락을 재점검했습니다. 최소 뼈대로 바뀐 backend/pyproject.toml을 현재 lock의 프로젝트 메타데이터(일반 의존성 26개·개발/GPU/Linux 그룹)와 합의한 스택에 맞춰 복원했습니다. 인덱스의 이전 선언에는 Django·Celery·LangChain이 있어 그대로 덮어쓰지 않았습니다. pgvector PostgreSQL 17·Redis 캐시 Compose와 OPENAI_API_KEY·REDIS_URL 환경 예시, 인계 형식 안내를 복원했습니다. uv lock --check --offline(233 packages), docker compose config --quiet, 현재 계약·DB 테스트 30개와 수정 파일 공백 검사를 통과했습니다. 테스트 생성 캐시는 삭제했습니다.
- 안 한 일 / 남은 일: 최신 뼈대의 11/23 계약 변경은 원본 CHANGELOG·검토 기록에 ④ 확인 필요가 남아 있어 적용하지 않았습니다. contracts·예시·DB·공통 코드·추가 테스트를 포함한 artifacts/contract-1123-restore.patch를 만들고 git apply --check --ignore-space-change로 적용 가능성만 확인했습니다. 4명 확인 완료 여부를 사용자에게 질문했습니다. 현재 30개 통과가 누락된 계약 복원을 검증했다는 뜻은 아닙니다. 커밋·푸시·Compose 실제 기동 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): AGENTS.md §5의 계약 변경 4명 확인 규칙 때문에, 확인 기록이 남아 있는 변경은 임의로 반영하지 않았습니다.

## 2026-11-23 · Codex · taemin
- 한 일: 사용자 지시에 따라 앞으로 모든 작업을 taemin에서 진행하도록 로컬 AGENTS.md를 변경했습니다. 기존 미커밋 변경을 유지한 채 taemin으로 전환하고, taemin과 같은 커밋임을 확인한 codex 작업 브랜치 4개와 claude/contract-1123 브랜치를 일반 삭제(-d)했습니다.
- 안 한 일 / 남은 일: 소스·계약·의존성 변경, 커밋·푸시 없음. main·dev·원격 브랜치는 유지했습니다. Git 상태로 미커밋 변경 보존을 확인했고 실행 테스트는 수행하지 않았습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 사용자의 새 지시가 기존 브랜치 규칙을 대체합니다.

## 2026-11-23 · Codex · codex/ignore-local-agent-files
- 한 일: 폴더와 Git 추적 상태를 점검하고 .gitignore에 개인 AGENTS.md·CLAUDE.md(대소문자 변형 포함), .agents/·.codex/·.claude/·.mcp.json, 로컬 도구 설정, 캐시·테스트 결과, artifacts/와 임시 검증 폴더를 추가했습니다. 파일은 삭제하지 않았습니다. git check-ignore로 개인 파일 제외와 .env.example·공유 HTML 포함을 확인했습니다. 개인 지침 파일은 추적 전이라 인덱스 제거가 필요하지 않았습니다.
- 안 한 일 / 남은 일: 코드·계약·의존성은 변경하지 않았습니다. 현재 AGENTS.md §3은 이전 요약형이고 backend/pyproject.toml은 최소 뼈대(slotagent)지만 uv.lock의 프로젝트는 skn35-final-4team이라 최신 설정과의 정합성 확인이 필요합니다. frontend/는 README만 있습니다. 루트 promptfoo용 package.json·node_modules는 유지했습니다. 테스트 실행 없이 Git 제외 규칙만 검증했습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 앞서 확정한 기술 결정 표와 현재 파일 내용이 달라 임의 복원하지 않고 사용자에게 보고합니다.

## 2026-11-23 · Codex · codex/refresh-skeleton-package
- 한 일: 최신 원본의 6차 DB 이름 규칙으로 복사용 패키지를 구성했습니다. db를 backend/db로, web을 frontend로 옮기고 테스트의 SQL·시드 경로와 CODEOWNERS를 맞췄습니다. 오케스트레이터·MCP·도구 검색·서빙 구현 자리를 포함하고 AGENTS.md의 LLM 경계를 반영했습니다. PostgreSQL 17 Compose와 .env.example을 추가했습니다. 계약·DB 연결 테스트 30개 통과.
- 안 한 일 / 남은 일: 실제 실행 엔진·UI·고도화 구현, 동시성·격리 검증. Compose 기동은 검증하지 않았습니다. P-01·P-05 등 임시 값과 계약 스키마는 변경하지 않았습니다.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음.
