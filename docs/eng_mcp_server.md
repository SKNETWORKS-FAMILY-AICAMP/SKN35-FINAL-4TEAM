# SlotAgent MCP 서버 붙이기 (①, 11/27)

SlotAgent 를 MCP 서버(stdio)로 엽니다. 도구 = ④ chatbot 함수 5개(`contracts/schemas/chat.schema.json`) 그대로.
코드: `backend/src/slotagent/mcp_server/server.py`, 시험: `backend/tests/test_mcp_server.py`.

| 도구 | 하는 일 | 지금 |
|---|---|---|
| `get_results` | 실험 상태(`status`), 분석의 비교·판정(`sa_comparisons`), 그 분석의 리포트(`sa_reports.content`). 분석은 `done` 이면 `engine/advance.final_analysis_id`(리포트 2종 있는 최종), 아니면 최신(`is_interim` 같이) | 됨 |
| `write_report` | 저장된 리포트 내용을 돌려줌. 쉬운 말로 다시 쓰는 것은 붙인 쪽 에이전트가 함 (숫자는 content 것만) | 됨 |
| `start_run` | `lock_and_enqueue` (= POST /run) | 됨, 확인 필요 |
| `calc_sample_size` | `eng_plan_proposal.handle` (= POST /plan-proposal) | `not_ready` (③ `sample_size`·`propose` 미구현) |
| `create_experiment` | `intake.create_experiment_draft` (= POST /api/experiments) | `not_ready` (④ 미구현), `SLOTAGENT_USER_ID` 필요 |

- 인자는 `validate('chat', args, part=도구)` 로 검사. 임의 SQL 도구 없음. 숫자는 DB 값 그대로, 답마다 `cited_experiment_ids`.
- `start_run`·`create_experiment` 는 두 번 부름: 처음엔 요약(풀이 수·예산·지금까지 비용·`plan.estimate`)과 `confirm_token` 만.
  사용자가 확인하면 같은 인자 + `confirm_token` 으로 다시 부름. 토큰은 인자+요약의 해시라 상태가 바뀌면 다시 확인해야 함.
  토큰은 에이전트가 요약을 건너뛰지 못하게 할 뿐이고, 사람이 승인하는 자리는 클라이언트의 도구 승인 창입니다.
- 오류는 `{code, message}` (api.error 코드 + `not_ready`). DB 원문은 보내지 않음.

## 실행
```powershell
cd D:\final_project\backend; $env:PYTHONPATH = "src"; uv run python -m slotagent.mcp_server.server
```
`DATABASE_URL` 은 환경 변수 또는 루트 `.env` (`common/db.py`). 로그인이 없으므로 내 PC 에서만 씀.

## Claude Desktop
`%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "slotagent": {
      "command": "uv",
      "args": ["--directory", "D:\\final_project\\backend", "run", "python", "-m", "slotagent.mcp_server.server"],
      "env": { "PYTHONPATH": "D:\\final_project\\backend\\src" }
    }
  }
}
```
Claude Desktop 을 다시 켜고 "실험 6 결과 알려 줘"처럼 물으면 `get_results` 를 부릅니다.
Claude Code: `claude mcp add slotagent -e PYTHONPATH=D:\final_project\backend\src -- uv --directory D:\final_project\backend run python -m slotagent.mcp_server.server`
