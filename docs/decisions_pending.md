# 팀이 정해야 하는 것 (2026-11-22)

뼈대에는 **임시 값**을 넣어 두었습니다. 정하면 이 표에서 지우고, 바뀌는 파일을 고칩니다.

**★우선 (3차 검토, 11/22)**: P-01·P-05 는 성공을 어떻게 판정하느냐를 바꾸므로 먼저 정함. 나머지는 개발하면서 정해도 됨. P-08 은 그대로 둠.

| # | 무엇 | 지금 넣어 둔 임시 값 | 고를 수 있는 것 | 정하면 고칠 곳 | 누가 |
|---|------|----------------------|-----------------|----------------|------|
| ~~P-01~~ | ~~도구 범위 밖(out_of_scope)을 실패로 셀지~~ | **정함 (11/23, 기획서 1.3 5.4)**: 실패로 셈. 실행 전 구조 분석으로 판정(`checks.template_scope`), 리포트에 범위 밖 비율·공통 문항 범위 안 성공률(`detail.in_scope`) | — | prereg·settings `fail` 만 (반영함) | 팀 |
| P-02 | 외부 API 429(요청 제한)를 환경 탓으로 볼지 | `llm_api_429` 값은 있지만 기본 env_error_reasons 에서 뺌 (= 후보 탓) | 환경 탓(다시 실행) / 후보 탓(실패) | settings `env_error_reasons` | 팀 |
| P-03 | 연습 환경에 MCP 서버를 어떻게 붙이는지 (D-05 저장소 쪽) | 계약 없음. 워커가 `data_snapshots.location` 을 읽는다는 것만 정함 | 서버마다 연습 저장소 주소·토큰을 넘기는 방법, 컨테이너 이미지 고정 등 | `docs/decisions/D-05.md`, engine/worker.py | ① |
| P-04 | 담당 확인 (역할 나누기 v1 에 없던 일) | ①·④가 겹치는 곳은 ①로 정함(11/22 팀장): 다음 단계 넘기기·실험 상태·api/·plan-proposal 응답 모양·web 1차 = ①. 남은 확인: 채점 검증(FR-VAL) = ② 1차·③ 계산, reports 1차 = ③, settings 값 = ②③ | 다른 배분 | CODEOWNERS, README 흐름표 | 팀 |
| **P-05 ★우선** | 자동 실행에서 "사용자 확인 뒤"를 무엇으로 볼지 (`forbidden.unless_user_confirmed`) | 확인해 줄 사용자가 없으므로 `write_intents.user_confirmed` 는 항상 false → 확인 뒤 허용 조건이 있어도 금지로 채점 | ① 문항마다 정해 둔 사용자 답(가짜 사용자) ② "확인을 물으면" 그 자체를 성공으로 보고 거기서 멈춤 ③ 이 조건을 8주 안에는 안 씀 | answer_condition 스키마, write_proxy, 요구사항(D-15 로 올림) | ①② |
| ~~P-06~~ | ~~contracts/ 4명 합의를 어떻게 강제할지~~ | **정함 (11/22)**: 4명 모두 admin 이라 PR 승인 수로 막지 않음. CHANGELOG 한 줄 + 4명 확인을 약속으로 | — | README, CODEOWNERS 주석 | 팀장 |
| P-07 | 실패 원인(outcome_reason) 값 목록 | 12개 (env_ 6, llm_api_429, agent_ 4, timeout_ 1) | 더하기·이름 바꾸기 | common.schema.json `$defs/outcome_reason` + DB CHECK `trials_outcome_reason_known`(지금 0003). 값을 바꾸면 0004 마이그레이션으로 CHECK 교체 | ① |
| P-08 | 실험을 failed 로 보는 조건 | 채점·분석 작업이 끝내 실패할 때만 | 환경 오류 비율이 높을 때도 등 | engine/advance.py | ① |
| P-09 | 월 호출 수를 등록 때 물을지 | `agents.expected_monthly_calls` (비워도 됨, 비면 월 비용 안 보임) | 필수로 / 리포트 화면에서 입력 | api register_agent_request, 데모 등록 화면 | ④ |
| P-11 | 도구·Skill 설명 토큰 합계 상한 (기획서 1.3 8.2) | 없음 (도구 개수 한도도 뺌) | 실제로 돌려 본 비용·시간과 다른 평가 서비스 정책을 보고 정함 | settings 새 key, ④ 등록 검사 | ①④ |
| P-12 | 비교 프리셋 4종(균형·정확도·비용·속도)의 기본 최대 예산 (기획서 1.3 5.2) | 없음 | 처음 15개 문항 유형으로 시간·비용을 잰 뒤 | settings 새 key, plan-proposal | ①③ |
| P-10 | 새 문항 유형의 기본 split | `held` (확인용) | `dev` | 0003 의 DEFAULT | ② |
