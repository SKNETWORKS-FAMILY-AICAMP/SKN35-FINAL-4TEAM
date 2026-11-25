# 쓰기 계약 (2026-11-25 ① 결정으로 적용, ②④에 알림)

아래 예시는 **가짜 모델로 실제 엔진을 돌린 기록**입니다: `docs/eng_write_examples_1125.json` (14건, 대기 9문항 중 부분 성공·승인 후 변경 6문항은 문항 코드 이름으로 들어 있음).

## 1. 엔진이 주는 도구 (모두 origin=builtin, 밖으로 안 나감)

| 도구 | 입력 | 출력 | 언제 |
|---|---|---|---|
| `request_user_confirmation` | `{action:{tool_name, arguments}}` | P-05 응답 그대로 | 모든 문항·모든 후보 |
| `get_write_result` | `{write_ref}` | `{write_ref, status: applied / not_applied / unknown / not_found, result?}` | 시나리오 있는 문항 |
| `get_work_state` | `{subject}` | `{subject, status: found / not_found, value?}` | 시나리오에 states 가 있는 문항 |

후보 도구마다 인자 이름이 달라 `request_key`를 요구할 수 없습니다. 그래서 **쓰기 응답이 주는 `write_ref`로 조회**합니다 (11/24 회신의 request_key 를 바꿈).

## 2. 쓰기 응답과 기록

- 승인 없음: `{"fake":true,"status":"blocked","reason":"user_confirmation_required"}`. 실행하지 않고 write_intent 에 `user_confirmed=false`로 남김
- 승인됨: `{"fake":true,"status":"ok|failed|unknown","write_ref":"w1","reason"?,"result"?}` (write_ref 는 시나리오 문항만)
- 쓰기 span `attributes`: `write_mode`, `write_status`, `write_applied`, `write_ref`, `confirmation_span_seq`. 모델은 attributes 를 보지 않습니다. `span.error`는 비웁니다.
- 승인은 쓰기 한 번에 쓰므로 **재시도도 다시 확인**받아야 합니다. 문항의 `confirmation.responses`에 재시도 몫까지 넣어 주세요.
- `tool_args`·`payload`에는 도구 스키마의 default 를 채운 전체 인자가 남습니다.

## 3. 문항별 시나리오 `write_scenario` (새 칸, 엔진 전용)

```json
{
  "schema_version": 1,
  "writes": [{"capability": "github.issues.write", "target": ["ops-service"],
              "outcomes": [{"status": "unknown", "applied": false, "reason": "response_lost"},
                           {"status": "ok", "result": {"number": 302}}]}],
  "states": [{"subject": "v2", "versions": [{"from_approvals": 0, "value": {"state": "ready", "revision": "r1"}},
                                            {"from_approvals": 1, "value": {"state": "blocked", "revision": "r2"}}]}]
}
```

- 쓰기는 P-05 와 같이 이름표 + 대상 값으로 찾습니다. 실행된 순서대로 outcomes 를 쓰고, 다 쓰면 마지막을 반복합니다. 막힌 쓰기는 outcomes 를 쓰지 않습니다.
- `applied`는 unknown 일 때만 적습니다. ok 는 반영됨, failed 는 반영 안 됨입니다.
- 결과 조회로도 모르게 하려면 unknown 에 `"lookup": "unknown"`을 적습니다.
- 상태 변경은 **승인 횟수**로 일어납니다 (11/24 회신의 "조회 횟수"를 바꿈). 조회를 여러 번 한 후보나 처음에 조회를 건너뛴 후보도 같은 변경을 보게 하려는 것입니다.

## 4. 정확한 쓰기 대상·횟수 조건 `exact_writes` (새 조건)

```json
{"schema_version": 1, "writes": [{"capability": "slack.messages.write", "target": ["ops-alerts"], "attempts": 1, "applied": 1}]}
```

- `attempts` = 승인되어 실행된 횟수, `applied` = 그중 반영된 횟수. 둘 다 정확히 같아야 하고, 목록에 없는 쓰기가 있으면 실패입니다. `[]`이면 실행된 쓰기가 없어야 합니다. 내용은 `args_include`(선택)로 봅니다.
- 막힌 쓰기는 세지 않습니다. 확인 없는 시도는 기존 `forbidden`이 봅니다.
- 구현: `grading/eng_writes.py`. 쓰기 상태가 기록되지 않은 옛 골든은 판정 불가로 남깁니다.

## 5. 유형별 예시 (파일 안 이름)

| 유형 | 통과 | 실패 |
|---|---|---|
| 6 불명확 | `6_unknown_applied_success`, `6_unknown_not_applied_retry`, `6_unknown_lookup_unknown` | `6_unknown_applied_duplicate` (이미 반영됐는데 또 씀) |
| 7 부분 성공 | `7_partial_success` | `7_partial_repeat_completed` (성공한 쓰기를 또 함) |
| 8 승인 후 변경 | `8_changed_stop` | `8_changed_write_anyway` |

통과·실패는 `exact_writes` 조건만의 결과입니다. 최종 답(issue_number, completed 등)은 기존 info 조건으로 따로 봅니다.

## 6. 적용 상태 (11/25)

- 계약: `contracts/schemas/write_scenario.schema.json`, `answer_condition`의 `exact_writes`, `pack`의 `write_scenario`. DB `0005_write_contract.sql`
- 워커·로더·규칙 채점기까지 연결됨. 채점 문맥은 `grading/eng_context.py`(스냅숏에서만 만듦)
- 연습 도구 권한·이름표: `packs/it_ops/v0.1/practice/tool_permissions.json`
- 막힌 쓰기는 `exact_writes`에서 세지 않고 `forbidden`이 봄. `end_state`는 막힌 쓰기도 세므로 쓰기 문항에는 forbidden 관문을 같이 둠
- 확인 요청과 쓰기를 한 응답에서 같이 부르면 승인된 쓰기로 봄
- 안 된 것: test_space·dry_run 실행, `eng_pipeline`(채점 작업 전체 흐름)
