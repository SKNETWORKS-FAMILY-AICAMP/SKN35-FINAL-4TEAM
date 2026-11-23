# 작업 인계 기록

Codex·Claude·팀원이 같이 씁니다. **새 기록은 맨 위에** 더합니다. 한 작업에 기록 하나를 씁니다.

```
## YYYY-MM-DD · <도구 또는 사람> · <브랜치>
- 한 일:
- 안 한 일 / 남은 일:
- 의문점 (계약·미정 사항과 부딪힌 곳):
```

---

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
