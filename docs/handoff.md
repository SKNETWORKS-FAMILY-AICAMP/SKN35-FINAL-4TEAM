# 작업 인계 기록

Codex·Claude·팀원이 같이 씁니다. **새 기록은 맨 위에** 더합니다. 한 작업에 기록 하나를 씁니다.

```
## YYYY-MM-DD · <도구 또는 사람> · <브랜치>
- 한 일:
- 안 한 일 / 남은 일:
- 의문점 (계약·미정 사항과 부딪힌 곳):
```

---

## 2026-11-23 · Codex · taemin (중간 비용 보존 완료 — 임시 DB·가짜 모델)
- 한 일: 사용자 승인 조건대로 `0003_review_1122.sql` 끝에 nullable `sa_cost_ledger.attempt`·`span_seq`와 `source='trial'` 부분 UNIQUE(ref_id,attempt,span_seq)인 `sa_cost_ledger_trial_call_once`만 추가했습니다. 칼럼·인덱스 COMMENT, db_names·NAMES 대응표, contracts/CHANGELOG의 DB 변경 한 줄(②④ 코드 영향 없음)을 맞췄습니다. JSON 스키마·새 마이그레이션 파일·judge/chat/validation 구현은 변경하지 않았습니다. db_names는 Ruff 형식도 맞췄습니다.
- 실행 경로: DB 없는 loop의 `Dependencies.on_model_span`이 모델 응답을 받은 직후, 소유권·취소·시간 검사보다 먼저 호출됩니다. worker가 `engine/costs.record_trial_cost`로 짧은 트랜잭션을 커밋합니다. 비용에는 queue.guard·현재 attempt·실험 상태 조건을 걸지 않으므로 옛 워커나 stopped 실험의 이미 받은 응답 비용도 보존됩니다. 기존 결과·trace 저장은 계속 현재 임대·attempt를 검사합니다. stopped 확인을 단계 사이와 최종 저장에 반영해 비용 기록 뒤 새 호출을 막습니다.
- 중복 처리: 중간·최종 저장 모두 같은 `INSERT ... ON CONFLICT (ref_id,attempt,span_seq) WHERE source='trial' DO NOTHING`을 사용합니다. 충돌하면 기존 experiment·model·입력/출력 토큰·금액·가격표를 읽어 비교합니다. 다른 값은 CostConflictError(ValueError)입니다. 같은 값만 아무것도 추가하지 않습니다. trials.cost_krw는 최종 성공 attempt의 합, 예산 장부는 실패·옛 attempt를 포함한 실제 저장 지출 합입니다.
- 재시도: 비용 DB 오류는 원문 없는 CostPersistenceError(RuntimeError)로 올립니다. 비용 전용 재시도·새 연결·대기·모델 재호출 장치는 없습니다. 기존 run_once의 작업 최대 3회만 적용하며 연결이 끊긴 경우 기존 임대 회수로 복구합니다. 아래 이전 계획의 "비용 저장 별도 재시도 검토"는 사용자 지시로 폐기했고 이번 구현에 없습니다.
- 검증: `scripts/test.ps1` **241 passed**(기존 216 + 새 비용 검사 25), backend 전체 Ruff 0건, 변경 Python 7개 `ruff format --check` 통과, `git diff --check` 통과. 테스트는 임시 PostgreSQL과 가짜 모델만 사용했고 실제 모델·외부 서비스 호출은 0건입니다. 기존 최종 저장 실패 테스트 두 개의 비용 0행 기대는 새 요구에 맞춰 비용 보존·새 attempt 누적 기대로 변경했고, trace·결과 롤백 검사는 유지했습니다. 이전 워커 차단 테스트도 늦은 비용 1행이 더 보존되는 기대로 변경했습니다. 기존 DB 연결·채점/리포트/chat 등 통합 테스트를 포함해 모두 통과했으며 judge/chat/validation의 같은 키 2행 허용과 기존 trial의 NULL 키 허용도 추가 검증했습니다.

### 실패 상황 표 — 확인한 최종 DB 상태

`a`는 시작 trial attempt, `j`는 시작 작업 임대 횟수, C는 이미 응답을 받은 호출 비용입니다. 실제 유료·외부 호출은 전 행 0건이며 표의 모델 횟수는 가짜 모델 기준입니다.

| 상황 | trial status/attempt | job status | 비용 장부·호출 횟수 |
|---|---|---|---|
| 응답 전 ValueError/NotImplementedError | pending/a+1 | failed | 신규 비용 0, 모의 진입 1회 뒤 중단 |
| 응답 전 RuntimeError | pending/a+1 | queued, 상한이면 failed | 신규 비용 0, 모의 진입 1회 뒤 중단 |
| 응답 저장 뒤 ValueError/NotImplementedError | pending/a+1 | failed | C 유지, 모델 1회·두 번째 모델 호출 없음 |
| 응답 저장 뒤 RuntimeError | pending/a+1 | queued, 상한이면 failed | C 유지, 한 시도에 모델 1회 |
| 비용 INSERT DB 오류 | 복구 뒤 pending/a+1 | queued→3회째 failed | INSERT 롤백이면 장부 증가 없음. 모델·비용 INSERT 각각 총 3회, 도구 0회, 비용 자체 재시도 없음 |
| 비용 COMMIT 후 응답 유실 | pending/a+1 | queued | C가 1행 유지. 같은 영수증 수동 재전달 시험에서도 1행, 모델 1회 |
| 최종 결과 저장·인계 실패 | pending/a+1 | queued | trace·결과는 롤백, 응답 2회의 비용 2행·0.264원 유지 |
| 응답 비용 커밋 뒤 프로세스 os._exit | 회수 후 pending/a+1, 재실행 후 finished/a+1 | queued 후 done | 옛 비용 0.12원 유지, 새 시도 후 3행·0.384원. 새 모델 호출 2회 |
| 응답 수신 직후 DB 연결 강제 종료 | 다른 연결의 임대 회수 후 pending/a+1 | queued | 미커밋 비용은 장부에 없음. 모델 1회 뒤 중단. 이는 미보존 위험 구간이며 실제 과금 0원으로 해석하지 않음 |
| 옛 워커의 응답이 새 attempt 완료 뒤 도착 | 새 finished/a+1 그대로 | 새 done 그대로 | 옛 비용도 추가. 옛 결과·trace와 다음 호출은 차단 |
| 같은 키 중복·두 연결 동시 INSERT | 기존 상태 그대로 | 기존 상태 그대로 | 한 행만 저장, 비용 재전달의 모델·도구 호출 0회 |
| 같은 키 금액/입력 토큰/출력 토큰 불일치 | worker 경로는 pending/a+1 | failed | 기존 금액 유지, 오류 노출, 이후 자동 실행 없음 |
| 정상 최종 저장·완료 요청 중복 | finished/a 그대로 | done | seq=1·3 비용 두 행만 유지, 중복 요청의 모델 호출 0회 |
| 반복 RuntimeError | 3회 뒤 pending/a+3 | failed, 이후 빌려주지 않음 | 모델 총 3회, 비용 3행·0.36원 유지 |
| 중간에 stopped, 진행 중 응답 도착 | cancelled/a+1 | cancelled | 늦은 C 유지, 모델 1회·도구 0회 |
| 실패 attempt 비용으로 예산 소진 | 다음 시작 때 cancelled/a+1 | 처리된 현재 작업 done | 저장된 100원으로 budget 중단. 두 번째 시도의 모델 호출 0회 |

DB 단절·프로세스 종료에서 running을 최종 정상 기대로 두지 않고 실제 회수까지 수행해 상태를 확인했습니다. 비용 저장만 호출하는 중복 검사는 trial·job을 변경하지 않으며, 작업 경로의 예외 분기는 별도 테스트에서 확인했습니다.

### 대표 시나리오 — 옛 응답 2원 + 새 응답 3원

| 단계 | 입력·출력 | DB 상태 |
|---|---|---|
| 1 | A가 T/attempt=1/seq=1 호출, 응답을 지연시킴 | running/1, A leased, 비용 0행 |
| 2 | A 임대 만료·회수 후 B가 attempt=2로 재실행 | running/2, B leased |
| 3 | B가 3원 응답을 저장하고 결과까지 완료 | finished/2, job done, 비용 (T,2,1) 1행·3원 |
| 4 | A의 2원 응답이 뒤늦게 도착 | 비용 (T,1,1) 추가, finished/2·done 유지, 옛 결과 저장 차단 |
| 5 | A의 같은 비용 기록 재전달 | 비용 총 2행·5원 유지, 새로운 모델 호출 없음 |

테스트에서는 새 attempt가 이미 완료된 더 엄격한 시점에 옛 비용을 기록했습니다. 두 모델은 각각 1회 호출됐고 결과 span은 attempt=2만 남았습니다.

### 새 raise와 호출부 점검

- `CostConflictError(ValueError)`: 중간/최종 비용 값 충돌 → run_trial 복구 → run_once 즉시 failed. 이미 저장한 비용 유지, 새 결과 롤백.
- `CostPersistenceError(RuntimeError)`: 비용 SQL·커밋·연결 오류 → 다음 모델/도구 호출 중단 → 기존 복구/작업 재시도 상한. DB 원문은 from None으로 숨깁니다. 연결 자체가 끊기면 복구 실패 안내 후 기존 임대 회수가 담당합니다.
- 최종 저장의 새 `RunCancelled`: 실험이 stopped/failed이면 결과를 저장하지 않고 기존 예외 복구를 통해 cancelled로 반환합니다. 비용은 별도 커밋이라 유지합니다.
- record_trial_cost의 중간·최종 호출부, on_model_span의 기본 no-op·worker 주입·테스트 주입, Recorder.model과 loop의 예외 처리, queue.fail/reclaim·should_retry를 rg로 확인했습니다. 새로운 예외를 후보 오답으로 저장하지 않습니다. 모델 ModelError 처리와 JSON trace 계약은 변경하지 않았습니다.

### 남은 빈틈

- 중요: 제공자 과금 후 응답/사용량을 받기 전 종료, 응답 뒤 비용 커밋 전 종료·DB 단절은 확정 비용을 복구하지 못합니다. DB 장애 때문에 새 attempt로 다시 모델을 부르면 이전 미저장 과금이 있을 수 있습니다. 요청대로 별도 비용 재시도 장치는 만들지 않았고 기존 최대 3회에서 멈춥니다. llm 어댑터가 사용량 없는 ModelError로 전달한 호출도 비용을 복원할 수 없습니다.
- 중요: 기존 개발 DB에는 이번 끝부분 SQL을 적용하지 않았습니다. 기존 DB에서 새 실행 코드를 쓰기 전 승인한 추가 구문을 적용해야 합니다. 0003 전체 재실행은 기존 ALTER와 충돌하므로 하지 않았습니다. 검증은 전체 마이그레이션을 처음부터 적용한 임시 DB 기준입니다.
- 중요·범위 제외: pending 풀이 + failed 작업의 재개 절차/API는 구현하지 않았습니다. 로컬 MCP stdio·Docker·P-05 준비도 이번 작업에 포함하지 않았습니다.
- 작음: 늦은 비용은 이미 시작한 다른 호출을 소급 차단하지 못합니다. 예산 검사는 기존 합의대로 풀이 시작 시점 기준이며 회수·재시도에 따른 누적 비용은 다음 시작부터 반영합니다. 기존 NULL 키 장부는 과거 호출로 역추정해 채우지 않았습니다.
- 의문점: 사용자 허용 범위 내에서 구현 완료. 새 마이그레이션·추가 CHECK·JSON 계약 변경·의존성 추가·커밋·push 없음.

## 2026-11-23 · Codex · taemin (중간 비용 보존 — 구현 전 표·DB 의문점)
- 한 일: 사용자 추가 조건을 반영해 비용 기록과 결과 저장의 권한을 분리했습니다. 사용량을 이미 받은 응답의 비용은 임대 상실·attempt 변경·실험 중단 뒤에도 기록해야 하며 queue.guard로 막지 않습니다. 중복 식별자는 `(trial_id, attempt, span_seq)`입니다. 동일 키 재전송·동시 기록·커밋 응답 유실 뒤 재전송·최종 저장에서 장부는 한 번만 증가해야 합니다. 코드·계약·DB 수정, API 호출·테스트 실행, 커밋·push는 하지 않았습니다.
- 의문점 (구현 중지 사유): 현재 sa_cost_ledger에는 attempt·span_seq가 없으며 source=trial의 ref_id는 trial_id입니다. sa_spans에는 UNIQUE(trial_id,attempt,seq)가 있지만 spans_current_attempt 트리거가 현재 running attempt의 INSERT만 받으므로, 임대 회수 뒤 늦게 온 비용의 중복 식별자로 대신 사용할 수 없습니다. 기존 ref_id 의미를 바꾸거나 결과 trace의 펜싱을 풀지 않습니다. 제안은 비용 장부에 nullable attempt·span_seq를 추가하고 source='trial'의 (ref_id,attempt,span_seq)에 부분 UNIQUE를 두는 것입니다(기존 비용 행·다른 source 처리와 이름 대응표는 변경 검토 시 명시). 마이그레이션은 이번 지시에서 허용되지 않아 구현하지 않았습니다. 아래는 목표 동작 표이며 구현·검증 완료 기록이 아닙니다.

### 구현 전 실패 상황 표

기준: 시작은 trial running/attempt=a, job leased/attempts=j, 기존 장부 L. C는 모델에서 사용량을 받은 응답 한 건의 비용이며 키 K=(trial_id,a,span_seq). 일반 경로는 run_once의 작업 최대 3회 정책을 사용합니다. 모든 시험은 가짜 모델로 수행하며 실제 모델·외부 서비스 호출은 0건입니다. 아래 호출 수는 가짜 모델 호출 횟수입니다.

| 경로·실패 상황 | sa_trials.status/attempt | sa_jobs.status | 장부 | 추가 호출·복구 |
|---|---|---|---|---|
| 모델 호출 전 ValueError | pending/a+1 (실행 시작 전이면 기존 상태 유지) | failed | L | 모델 0회, 자동 재실행 없음 |
| 응답·비용 저장 뒤 ValueError | pending/a+1 | failed | L+C 유지 | 이미 호출한 1회, 오류 뒤 모델 호출 0회 |
| 응답·비용 저장 뒤 NotImplementedError | pending/a+1 | failed | L+C 유지 | 이미 호출한 1회, 오류 뒤 모델 호출 0회 |
| 응답·비용 저장 뒤 RuntimeError | pending/a+1 | queued, 작업 상한이면 failed | L+C 유지 | 같은 비용 재전송은 모델 0회. 풀이 재실행은 별도 새 attempt·새 비용이며 작업 상한 적용 |
| 비용 INSERT의 DB 오류·커밋 전 실패 | 연결 복구 가능하면 pending/a+1, 불가능하면 임대 회수 뒤 pending/a+1 | 반환/회수 후 queued 또는 상한의 failed | INSERT 롤백이면 L. 응답 C는 보존되지 않은 위험 구간 | 다음 모델 호출 중단. 응답이 메모리에 있으면 새 DB 연결로 동일 K 저장을 제한적으로 재시도하는 방안 검토. 비용 저장 재시도는 모델 재호출이 아님 |
| 비용 COMMIT은 됐지만 DB 응답 유실 | 연결 복구/임대 회수 후 pending/a+1 또는 새 워커 상태 | queued/상한 failed 또는 새 워커 상태 | 동일 K 재전송 후 정확히 L+C | 비용 재전송으로 모델을 다시 부르지 않음 |
| 비용 저장 후 최종 결과 DB 저장 실패 | pending/a+1 또는 임대 회수 뒤 복구 | queued/상한 failed | L+C 유지, 최종 저장 롤백과 독립 | 재실행 비용은 별도 attempt. 이전 C를 다시 합산하지 않음 |
| 응답·비용 저장 후 프로세스 강제 종료 | 임대 회수 뒤 pending/a+1 | queued 또는 상한 failed | L+C 유지 | 죽은 워커의 메모리에 의존하지 않음 |
| 제공자 호출 중/응답 뒤 비용 커밋 전 강제 종료 | 임대 회수 뒤 pending/a+1 | queued 또는 상한 failed | 마지막 커밋 금액 L만 보장 | 실제 과금 여부·미저장 C를 확정할 수 없음. 완전 보존 미해결로 보고하며 0원으로 단정하지 않음 |
| 임대 회수 후 옛 워커가 응답을 받음 | 새 attempt·완료 상태를 그대로 유지 | 새 워커의 작업 상태 그대로 | 옛 K의 C도 L에 한 번 더함 | 비용 저장에는 guard 없음. 옛 워커는 결과·상태 저장과 다음 모델/도구 호출 금지 |
| 동일 K를 두 번 전달·두 연결 동시 기록 | 변화 없음 | 변화 없음 | C 한 번만 추가 | 비용 저장 자체는 모델/도구 호출 0회. 단순 SELECT 뒤 INSERT만으로 중복 방지하지 않음 |
| 동일 trial·seq지만 attempt가 다름 | 현재 attempt의 상태 유지 | 현재 작업 상태 유지 | 서로 다른 실제 응답 비용은 각각 추가 | 옛 시도 비용을 새 시도로 합쳐 중복으로 오인하지 않음 |
| 정상 최종 저장·완료 요청 중복 | finished/a, 이후 그대로 | done | 중간 저장의 C를 재추가하지 않음 | 완료된 풀이 재요청은 모델 호출 0회 |
| 같은 실패가 계속 반복 | 매 회수/복구 때 attempt 증가, 상한 뒤 pending | 영구 오류 즉시 failed, 나머지 최대 3회 뒤 failed | 저장된 모든 attempt 비용 누적 | 자동 반복은 유한. S=max_steps, R=max_api_retries이면 가짜 모델의 SDK 요청 상한은 작업당 보수적으로 3×S×(R+1), 실제로는 예산·단계 상한이 먼저 막을 수 있음 |
| 실험 stopped, 응답이 진행 중이었다면 | 응답 비용 기록은 상태를 바꾸지 않음. 소유 중 실행 중단의 복구 또는 임대 회수 뒤 cancelled | 반환/회수 뒤 cancelled (이미 완료된 작업은 유지) | 중단 뒤 도착한 확정 비용 C도 한 번 기록 | 진행 중 호출을 없던 것으로 보지 않음. 취소 확인 뒤 다음 모델·도구 호출 0회 |

DB 장애·프로세스 종료 행의 running은 최종 기대값이 아닙니다. 복구/임대 회수를 실제로 수행한 뒤의 상태를 검사합니다. 회수하려면 DB와 회수 워커가 다시 사용 가능해야 합니다. 비용 기록은 소유권이 아니라, 워커가 호출 시작 때 고정한 trial·attempt·seq·가격표·사용량의 유효성을 검사합니다. 동일 K의 서로 다른 금액/토큰을 조용히 같은 응답으로 간주할지는 사전 검증에서 다뤄야 합니다.

### 대표 시나리오: 늦은 비용 응답·중복·최종 저장

| 단계 | 입력·출력 | trial / job | 장부·가짜 모델 호출 |
|---|---|---|---|
| 1 | 워커 A가 trial T, attempt=1, seq=1 모델 호출 시작 | running/1, A leased | L=0, 호출 누적 1 |
| 2 | A 임대 만료 후 회수, B가 같은 풀이를 새 attempt로 시작 | running/2, B leased | L=0, A의 미완료 과금은 아직 확정할 수 없음 |
| 3 | A가 사용량 있는 응답 C1=2원을 받음 | running/2와 B leased 그대로 | K=(T,1,1)로 2원 저장. guard로 거부하지 않음 |
| 4 | 저장 응답 유실을 가정해 A가 같은 K·C1 재전송 | B 상태 그대로 | L=2원 유지, 재전송의 모델 호출 0회 |
| 5 | A가 다음 단계를 시도 | B 상태 그대로, A 결과 저장 거부 | 추가 모델/도구 호출 0회 |
| 6 | B가 응답 C2=3원을 받고 비용 저장 | running/2, B leased | K=(T,2,1)로 저장, L=5원, 모델 호출 누적 2 |
| 7 | B가 최종 결과·trace·다음 단계·작업 완료 저장 | finished/2, done | 장부 L=5원 유지. 결과의 현재 attempt 비용과 실험 전체 지출을 구분 |
| 8 | 동일 완료 요청 재전달 | finished/2, done 그대로 | 장부 2행·5원, 모델 호출 누적 2 유지 |

### 남은 빈틈

- 중요: 비용 저장이 DB에 커밋되기 전 프로세스가 죽거나 제공자 과금 후 사용량을 받지 못한 경우는 이 설계만으로 확정 비용을 복구할 수 없습니다. 제공자 사용량 대조·내구성 있는 별도 전달 등은 추가 설계가 필요합니다. 늦은 비용이 예산 검사 이후 도착해 이미 시작한 호출까지 취소할 수는 없습니다.
- 중요·이번 범위 제외: pending 풀이 + failed 작업의 운영자 재개 절차/API는 사용자 지시대로 구현하지 않습니다. 이 상태를 복구 완료로 표시하지 않습니다.
- 작음: 비용 저장 재시도의 연결 팩터리·상한·대기 간격은 표 검토 후 정해야 합니다. 무제한 재시도나 비용 재전송을 위한 모델 재호출은 하지 않습니다.
- 남은 일: 비용용 중복 식별자 DB 변경의 허용 범위 확인 → 표 확정 → 구현·DB 통합 검사. checklist 완료 표시 없음.

## 2026-11-23 · Codex · taemin (중간발표 자료 수정)
- 다운로드 보완: 발표 뷰어 내보내기 연결이 실패해 확인된 19장 레이아웃에서 편집 가능한 표·텍스트·도식을 복원한 `output/presentation/SlotAgent_중간발표_수정본.pptx`를 저장했습니다. PPTX 구조·글꼴·배치 검사 0건, 재불러오기 19장 확인 및 전체 렌더 검토 완료. 검증 영수증은 `output/.pptx-validation/validation.json`입니다.
- 한 일: 사용자 제공 PPTX를 별도 발표 아티팩트로 불러와 본문 16장·부록 3장으로 재구성했습니다. 에이전트 기본 개념, 6쪽 가상 수치 비교 표, 8쪽 구체적 핵심 기능, 평가 파이프라인·축약 ERD를 반영하고 백업 1~3의 검증·도메인·비용 내용을 본문에 통합했습니다. 최신 프로젝트 규칙에 맞춰 50개 문항 유형·자체 실행 루프·DB 기록 원본을 적용했습니다. 19장 전체 렌더링으로 표·한글·줄바꿈·배치를 확인했습니다.
- 남은 일: 실제 성능 비교 수치는 아직 없어 6쪽을 설명용 가상 예시로 명시했습니다. 진행 현황은 11/23 인계 기록 기준입니다. 사용자는 발표 뷰어에서 PPTX로 내보낼 수 있습니다. 제품 코드·계약·체크리스트 완료 상태는 변경하지 않았고 제품 테스트·커밋·push는 수행하지 않았습니다.
- 의문점: 없음. PDF의 제안은 참고 자료로 사용하고 중간발표의 세부 설명을 줄이라는 사용자 요청을 우선했습니다.

## 2026-11-23 · Codex · taemin (모델 3사 연결 — SDK 모의 응답까지)
- 한 일: `common/llm.py`에 `ProviderModel(clients=..., clock=..., sleep=...)`을 추가해 provider로 네 회사를 선택합니다. 기존 `ChatModel.chat` 인자·`Reply`·`ModelError`와 OpenAI 전용 `OpenAIModel(client=...)`은 유지했습니다. 기존 OpenAI 테스트 본문은 바꾸지 않았습니다. 재시도 while 루프는 `_with_retries` 하나이며 모든 SDK 생성·요청에서 max_retries=0입니다. Google·DeepSeek은 OpenAI SDK, Anthropic은 anthropic SDK를 사용합니다. Anthropic system 분리·tool_use/tool_result·여러 도구 결과 병합·종료 이유 변환을 추가했습니다. 객체가 아닌 tool input은 JSON 문자열로 원래 값을 보존해 루프가 agent_invalid_tool_call로 돌려줍니다. 다음 Anthropic 요청에서는 API가 객체만 받는 tool_use 대신 해당 잘못된 호출과 오류 결과를 글 블록으로 보존해 모델이 수정할 수 있게 합니다(정상 호출은 tool_use/tool_result 그대로). Gemini의 빈 문자열·null·누락·공백 ID는 기존 대화와 현재 응답 ID에 겹치지 않게 생성하며 다음 요청의 tool_call_id와 같습니다.
- 의존성: pyproject에 anthropic만 추가했습니다. uv.lock은 anthropic 2.12.0과 전이 의존성 docstring-parser 0.18.0만 추가됐고 기존 패키지 버전은 유지했습니다. scripts/test.ps1에는 --with anthropic만 추가했습니다(이전 작업의 --with openai 유지).
- 검증: `scripts/test.ps1` 전체 **216 passed**(기존 101 + 새 모의 검사 115), backend 전체 `uv run ruff check .` 0건, 수정 Python 두 파일 `ruff format --check` 통과, `uv lock --check --offline` 235 packages 일치, `git diff --check` 통과. 모든 llm 테스트에서 실제 SDK 생성자를 차단하고 주입한 모의 클라이언트만 사용했습니다. 키 관련 검사는 모의 환경 값·빈 dotenv를 사용하므로 로컬 OpenAI 키도 호출하지 않았습니다. 기존 테스트 외에 네 회사의 아래 표·SDK 오류 원문/키의 메시지 및 traceback 비노출·SDK 생성 옵션·메시지 왕복·Gemini ID 충돌 회피·Anthropic 비객체 인자 및 정상/비정상 혼합 호출 피드백을 확인했습니다.

### 회사별 실패 상황 표 (SDK 모의 응답)

각 요청은 0.1초, 재시도 상한 R=2, 대기는 1초→2초입니다. 측정값은 `api_retries / wait_sec / duration_sec` 순이며 duration은 대기를 제외합니다. ValueError에는 기존 인터페이스대로 이 필드가 없습니다. 대기 후 실제 요청을 못 했어도 기존 동작대로 api_retries가 증가합니다.

| 상황 | OpenAI | Google | DeepSeek | Anthropic | 측정값 |
|---|---|---|---|---|---|
| 429가 3회 계속됨 | ModelError(llm_api_429) | 같음 | 같음 | 같음 | 2 / 3 / 0.3 |
| 5xx·529 후 성공 | Reply | 같음 | 같음 | 같음 | 1 / 1 / 0.2 |
| 연결 오류 후 성공 | Reply | 같음 | 같음 | 같음 | 1 / 1 / 0.2 |
| 5xx가 3회 계속됨 | ModelError(env_llm_api_5xx) | 같음 | 같음 | 같음 | 2 / 3 / 0.3 |
| timeout_sec=0.5, 첫 오류 뒤 대기 중 소진 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 1 / 0.4 / 0.1, 두 번째 요청 없음 |
| SDK 시간 초과 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 0 / 0 / 0.1 |
| 요청 전 제한 시간 소진 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 0 / 0 / 0, 요청 없음 |
| 성공 응답이 제한 시간을 넘어 도착 | ModelError(timeout_wall_clock) | 같음 | 같음 | 같음 | 0 / 0 / 실제 경과, 모의 검사는 0.1 |
| 400·401·403 | ValueError | 같음 | 같음 | 같음 | 필드 없음, 모의 경과 0.1·1회 요청 |
| 사용량 또는 입력/출력 토큰 수 누락 | ValueError | 같음 | 같음 | 같음 | 필드 없음, 모의 경과 0.1·1회 요청 |
| 빈 객체 도구 인자 | Reply, arguments="{}" | 같음 | 같음 | input={} → arguments="{}" | 0 / 0 / 0.1 |
| 빈 문자열 도구 인자 | Reply, arguments="" 그대로 | 같음 | 같음 | input="" → JSON 문자열 '\"\"', 비객체 값도 그대로 JSON 직렬화 | 0 / 0 / 0.1, 루프가 잘못된 인자로 기록·모델에 피드백 |
| 텍스트+도구 호출 | 둘 다 보존한 Reply | 같음 | 같음 | 같음 | 0 / 0 / 0.1 |
| 키 없음 | 요청 전 ValueError | 같음 | 같음 | 같음 | 필드 없음, 경과 0·요청 0회 |
| 출력 토큰 한도로 잘림 | Reply(length) | 같음 | 같음 | max_tokens → length | 0 / 0 / 0.1 |
| 비어 있는 도구 호출 ID | 기존 동작 유지 | 겹치지 않는 ID를 채운 Reply, 다음 tool_call_id 일치 | 기존 동작 유지 | 기존 동작 유지 | Google 0 / 0 / 0.1, 별도 대기·재호출 없음 |

### 보내지 않은 인자·변환 표

| 회사 | 보내지 않는 값 | 보내는 형태·이유 |
|---|---|---|
| OpenAI | max_tokens=None일 때 출력 상한, 비어 있는 tools | 기존 seed·temperature·max_completion_tokens 동작 유지 |
| Google | seed, max_completion_tokens | seed 명시 지원을 공식 호환 문서에서 확인하지 못해 생략. 상한이 있으면 max_tokens, 없으면 생략 |
| DeepSeek | seed, max_completion_tokens | 공식 Chat Completions 인자 목록에 seed 없음. 상한이 있으면 max_tokens, 없으면 생략 |
| Anthropic | seed, OpenAI 형식의 system 메시지·tool_calls·tool 역할·parameters·max_completion_tokens | system은 최상위, tool_use/tool_result, input_schema, 필수 max_tokens로 변환. max_tokens=None은 요청 전 ValueError |
| 공통 | 도구 정의의 access·origin·capabilities 등 내부 속성, price·max_api_retries·timeout_sec라는 API 본문 필드 | 이름·설명·입력 스키마만 전달. 가격은 로컬 계산, 재시도는 공용 루프, 남은 시간은 SDK timeout 옵션 |

공식 확인: [Gemini 호환 주소](https://aistudio.google.com/docs/openai?hl=ko) = `https://generativelanguage.googleapis.com/v1beta/openai/`, [DeepSeek 주소](https://api-docs.deepseek.com/) = `https://api.deepseek.com`, [DeepSeek 인자](https://api-docs.deepseek.com/api/create-chat-completion/), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Anthropic 오류·529](https://platform.claude.com/docs/en/api/errors), [Anthropic tool_result 선행 순서](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls). seed를 생략한 회사에서는 같은 seed에 따른 재현성을 보장하지 않습니다.

### 새 raise가 워커까지 전달될 때

| 위치·발생 조건 | 최종 처리 |
|---|---|
| 공용 재시도: 요청 전 시간 소진 | ModelError(timeout_wall_clock) → loop가 풀이 결과로 기록 |
| 공용 재시도: SDK timeout·429/5xx/연결 오류 재시도 소진 | ModelError(기존 이유) → loop가 prereg에 따라 풀이 결과로 기록 |
| 공용 재시도: 제한 시간을 넘어 도착한 성공 | ModelError(timeout_wall_clock) → loop가 풀이 결과로 기록 |
| 공용 재시도: 인증·요청 4xx | ValueError → worker가 현재 풀이 복구, eng_main이 작업 failed |
| _api_key: 회사 키 없음·빈 값 | ValueError → 현재 풀이 복구·작업 failed, API 요청 없음 |
| _tokens: 사용량 누락·음수·정수 아님 | ValueError → 현재 풀이 복구·작업 failed |
| _openai_reply: 응답·사용량 모양 부족 | 원문 없는 ValueError → 현재 풀이 복구·작업 failed |
| _anthropic_reply: 응답·사용량 모양 부족 | 원문 없는 ValueError → 현재 풀이 복구·작업 failed. JSON 비객체 인자는 예외가 아님 |
| anthropic_messages: 알 수 없는 메시지 역할 | ValueError → 현재 풀이 복구·작업 failed |
| ProviderModel: 지원하지 않는 provider | NotImplementedError → 현재 풀이 복구·작업 failed |
| ProviderModel: Anthropic max_tokens=None | ValueError → 현재 풀이 복구·작업 failed, API 요청 없음 |
| OpenAIModel: OpenAI 외 provider | 기존 전용 클래스의 NotImplementedError 유지 → 현재 풀이 복구·작업 failed |

`engine/loop.py`의 chat 호출·Reply.message·도구 JSON 검사·ModelError 처리와 `engine/worker.py`의 예외 복구, `workers/eng_main.py`의 즉시 실패 분기를 읽기 전용으로 재확인했습니다. engine·workers는 수정하지 않았습니다.

### 남은 빈틈·의문점

- 중요: 실제 API는 호출하지 않았습니다. 현재 로컬 키는 OpenAI만 있다는 사용자 설명을 기준으로 하며 추가 키를 요구하거나 읽어 출력하지 않았습니다. SDK 모의 성공은 실제 모델 호환성을 보장하지 않습니다. 체크리스트의 실제 API 확인은 미완료로 유지합니다.
- 중요: 입력이 너무 길어 발생하는 400(context 초과)도 현재 ValueError → 작업 failed입니다. 사용자 지시대로 이번에는 바꾸지 않았습니다. 비용이 발생한 뒤 사용량이 없는 경우·예외로 중단된 호출의 과금 보존도 기존 한계입니다.
- 중요: Anthropic은 max_tokens가 필수라 공통 runtime의 "비우면 모델 기본값"을 구현할 수 없습니다. 사용자 지시대로 기본값을 만들지 않고 ValueError로 막았습니다. 계약 변경 없음, 설정에서 명시 필요.
- 중요: 일부 모델이 요구하는 Gemini thought signature·DeepSeek reasoning_content 등 공급자 확장 필드는 현재 Reply 모양으로 왕복하지 않습니다. 이번에는 인터페이스를 변경하지 않았고 해당 모델의 실제 다중 도구 호출 호환성은 남았습니다.
- 작음: length는 Reply에 보존하지만 현재 loop가 별도 실패로 분류하지 않습니다. Anthropic cache 입력 토큰은 전체 입력에 합산하고 caller의 단일 입력 단가로 계산합니다. 캐시 할인·생성 할증 등 별도 단가와 확장 stop_reason 정책은 지원하지 않습니다.
- 의문점: Anthropic 출력 상한 생략과 공급자별 seed 지원 차이는 위와 같습니다. 계약·마이그레이션·engine·workers 변경, 커밋·push 없음.

## 2026-11-23 · Claude · taemin (실패 작업 무한 재시도 막기)
- 한 일: `workers/eng_main.run_once`가 예외마다 `retry=True`로 돌려 보내, 같은 이유로 실패하는 작업(해시 불일치·가격표 없음·검색 후보·쓰기 도구 호출)이 끝없이 다시 임대되던 문제를 고쳤습니다. `should_retry`: ValueError·TypeError·NotImplementedError(ContractError 포함)는 바로 작업 `failed`, 그 밖은 작업 attempts 가 `max_attempts`(기본 3) 미만일 때만 다시 넣습니다. `queue.reclaim(max_attempts=)`도 같은 상한으로 만료 임대를 `failed`로 둡니다(매번 프로세스를 죽이는 작업 대비). 풀이는 후보 실패로 기록하지 않고 pending 으로 남깁니다.
- 검증: 전체 **101 passed**, Ruff 0건. 새 검사 3개(영구 오류 즉시 failed·다시 안 빌림, 일시 오류 상한에서 failed, 회수 상한).
- 안 한 일 / 남은 일: 실패한 작업의 풀이는 pending 으로 남아 실험이 끝나지 않습니다 — 원인을 고친 뒤 작업을 다시 넣는 운영 절차(또는 API)가 필요합니다. 재시도 간격(백오프) 없음. 상한은 코드 상수이며 settings 계약에 `queue.max_attempts`를 넣을지는 4명 확인 사항입니다. 계약·DB 변경, 커밋·push 없음.
- 의문점: 없음.

## 2026-11-23 · Codex · taemin (큐 임대·회수·실험 잠금)
- 한 일: `common/queue.py`에 우선순위·SKIP LOCKED 임대, settings 임대 시간, attempts·leased_by·만료 검사, 연장·완료·실패·만료 회수를 구현했습니다. 실행 중 풀이를 pending으로 반환하면서 attempt를 증가시키고, 중단된 실험이면 cancelled로 바꾸는 것까지 작업 반환과 같은 트랜잭션입니다. 만료된 이전 워커는 회수 전에도 결과·비용을 저장할 수 없습니다. `run_trial(job=...)`의 최종 기록·비용·advance·작업 완료를 함께 커밋하며, 동시 완료가 채점 생성을 누락하지 않게 실험 행을 먼저 잠급니다. `lock_and_enqueue`는 DB 잠금·풀이·작업 생성·running 전환을 원자화하고 반복 요청 때 중복 생성하지 않습니다. `workers/eng_main.run_once`는 명시적 deps·연결 팩터리로 풀이 하나를 처리하고 별도 연결에서 기본 20초마다 연장합니다(최소 임대 60초 대응). 잡을 수 있는 오류는 작업을 반환하고 원래 예외를 올립니다.
- 검증: 전체 **98 passed**, backend 전체 Ruff 0건. 새 통합 검사 10개에서 잠긴 작업 건너뛰기·토큰 재발급·이전 토큰 거부, 별도 프로세스의 os._exit 비정상 종료, pg_terminate_backend DB 연결 종료 후 새 연결의 회수·재실행, 회수 후 이전 워커의 늦은 저장 차단, 중단된 풀이 취소, 별도 연결 연장·오류 반환, 동시 완료의 채점 실행 하나, 큐 완료 저장 실패 시 spans·장부 롤백, 잠금 중 작업 등록 실패의 전체 롤백·중복 요청을 확인했습니다. 가짜 모델·임시 DB 기준이며 실제 API나 실제 채점 완료를 의미하지 않습니다.
- 안 한 일 / 남은 일: `write_proxy.py`·`tool_search.py`, 풀이별 Docker/MCP와 환경 검사, 나머지 모델 3사 및 실제 API 검증, 실제 채점 완료는 남았습니다. P-05의 문항별 답 계약·승인 대상 비교 규칙은 ①② 협의가 필요합니다. `grading/eng_pipeline.py`도 미구현이라 채점 작업 생성까지 검증했습니다. 배포용 반복 실행 진입점·오류 후 재시도 간격/상한은 정하지 않았고 기존 registry는 변경하지 않았습니다. 큐 경로를 쓸 때는 새 run_once 또는 job을 넘기는 run_trial을 사용해야 하며, job 생략은 기존 독립 실행 검증용입니다. 중단 직전 메모리의 trace·과금 보존과 블로킹 외부 호출 강제 중단은 여전히 남았습니다. 기존 변경을 보존했고 계약·DB 정의·의존성 선언·브랜치 변경, 커밋·push 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): P-05의 미구현 계약을 임의로 추가하지 않았습니다. 재시도 운영 정책과 실제 채점 연결을 끝내기 전에는 체크리스트의 워커·advance 전체 완료로 표시하지 않았습니다.

## 2026-11-23 · Codex · taemin (예외 후 풀이 복구·오류 칼럼 수정)
- 한 일: `worker.run_trial`의 시작 이후 실행·trace 검사·최종 저장 전부를 예외 복구로 감쌌습니다. 현재 status=running과 시작한 attempt가 모두 같을 때만 pending으로 반환하고 attempt를 1 올리며 started_at을 비웁니다. 넘겨받은 다른 워커나 완료 상태는 수정하지 않습니다. 이미 중단된 실험이면 DB 규칙에 따라 pending 반환 후 cancelled로 처리합니다. 원래 예외는 그대로 다시 던지며 자동 모델 재호출은 하지 않습니다. 복구 자체가 실패하면 원문 DB 오류를 노출하지 않는 복구 실패 안내를 원래 예외에 붙입니다. `sa_spans.error`가 존재하는 것을 확인하고 INSERT의 전용 error 칼럼에 기록하도록 수정했습니다(이전 attributes 저장은 잘못된 구현이었습니다).
- 검증: 전체 **88 passed**, backend 전체 Ruff 0건. 쓰기 미지원·인증/미지원 공급자/응답 부족에 해당하는 모델 예외·취소·최종 인계 실패에서 상태 복구를 확인했습니다. 인계 실패 시 spans와 장부 롤백 후 attempt 2로 재실행이 완료됩니다. 다른 워커 attempt 보존, 중단된 실험의 취소, 복구 실패 시 원래 예외 보존, 도구 오류의 error 칼럼 저장도 임시 DB에서 확인했습니다. 기존 테스트의 running 잔류 기대값을 새 복구 동작과 실제 재실행 확인으로 갱신했습니다.
- 안 한 일 / 남은 일: 이 복구는 Python이 예외를 처리하고 DB 연결이 사용 가능할 때 작동합니다. 프로세스 강제 종료·DB 단절의 복구는 큐 임대/회수 단계에서 구현해야 합니다. 중간 비용 보존도 이전 기록대로 남아 있습니다. 쓰기 도구는 여전히 미지원이며 부르면 안전하게 예외·상태 복구됩니다. 스키마 자체 검증·length 응답 정책은 변경하지 않았습니다. max_steps의 모델+도구 합산 설명은 이미 common.schema.json의 runtime.max_steps에 있으므로 계약을 고치지 않았습니다. 계약·DB 정의·브랜치 변경, 커밋·push 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 없음. 앞선 기록의 “예외가 나면 running에 머물 수 있음”은 위의 잡을 수 없는 종료/연결 장애에 한정됩니다.

## 2026-11-23 · Codex · taemin (실행 코어 1~3: 읽기 경로)
- 한 일: DB 없는 `engine/loop.py`와 `engine/tracing.py`, 모델 공통 경로 `common/llm.py`를 구현했습니다. `OpenAIModel.chat`과 `FakeModel.chat`은 같은 `Reply`(글·도구 호출·사용량·실제 모델 이름·비용·시간·재시도)를 반환합니다. OpenAI SDK 자동 재시도를 끄고 runtime 횟수·남은 시간으로 제어합니다. 출력 토큰 상한을 비우면 계약대로 제공자 기본값을 쓰며, `max_steps`는 모델 호출과 각 도구 호출을 합산합니다. 잘못된 도구 인자는 실행하지 않고 모델에 오류로 돌려줍니다. 오류 분류는 기존 `checks.run_outcome_for`와 prereg를 그대로 따릅니다.
- 연결 모양: `run_agent(snap, task_prompt, seed, Dependencies(model, call_tool), prereg=prereg)` → `RunResult.trace`. `call_tool(name, args, timeout_sec)`는 문자열을 반환하고 환경 장애는 `ToolEnvironmentError`로 알립니다. 모델 호출은 `common/llm.py`를 통하며 DB는 직접 읽지 않습니다. 호출자는 `Price`로 가격을 넘기고 반환된 비용을 자기 문맥에서 저장합니다. 워커는 settings의 현재 `price.<모델>`을 읽고 실제 모델에 가격표가 없으면 실행하지 않습니다.
- DB 연결: `run_trial(conn, trial_id, deps=...)`가 스냅샷 해시·예산·현재 상태를 확인하고, 모델/도구 호출 동안 DB 트랜잭션을 유지하지 않습니다. 최종 spans·호출별 비용 장부·trial 결과·`advance.on_trial_finished`를 한 트랜잭션으로 저장합니다. attempt가 달라지면 저장을 거부합니다. 취소는 후보 실패로 저장하지 않고 `RunCancelled`로 올립니다. 도구 설명 토큰은 측정할 수 없어 trace에서 생략하고 DB에는 NULL로 둡니다. 기본 deps는 없으므로 등록된 기존 작업 핸들러만으로 유료 모델이 실행되지 않습니다.
- 검증: 새 테스트 26개 포함 전체 **80 passed** (`scripts/test.ps1`), backend 전체 Ruff 0건·추가/수정한 Python 7개 포맷 검사·diff 공백 검사 통과. OpenAI는 SDK 모의 응답으로 확인했습니다. 가짜 모델이 T2-0 조회 → 답변 → 실제 임시 DB 저장까지 돌고, 두 풀이 완료 후 채점 작업 하나가 생기는 것을 확인했습니다. 예산 소진 시 호출 차단·저장 중 인계 실패 시 전체 최종 기록 롤백·오래된 attempt 저장 거부도 확인했습니다. 새 워커 테스트는 기존 E2E와 별도 임시 DB를 사용해 전역 집계에 영향을 주지 않습니다. 테스트 실행 스크립트에 이미 선언돼 있던 openai를 추가했으며 의존성 선언·lock·계약은 변경하지 않았습니다.
- 안 한 일 / 남은 일: 실제 API 호출, 나머지 3개 회사, Docker/MCP·시작 전 환경 검사, 확인 도구·쓰기 프록시·쓰기 기록, 검색·재생, 채점기 구현은 다음 단계입니다. 쓰기·확인·검색은 미지원 예외로 막습니다. 큐 임대·연장·회수·임대 토큰 펜싱·워커 메인도 아직 없습니다. 실행 중 취소/예외/프로세스 종료로 최종 저장에 도달하지 못하면 메모리의 trace와 비용이 남지 않고 trial이 running에 머물 수 있어, 실사용 전에 큐 복구와 중간 비용 보존을 연결해야 합니다. 도구 콜백에는 남은 시간을 전달하지만 블로킹 호출을 강제 중단하는 기능은 아직 없습니다. 가짜 실행 결과는 테스트용이며 실제 ML/DL 학습 성능의 근거로 사용하지 않습니다. 커밋·푸시 없음.
- 의문점 (계약·미정 사항과 부딪힌 곳): 계약 변경 없음. P-02의 429 분류는 prereg의 기존 값대로 유지했습니다. P-05의 문항별 답 계약은 이번 범위에 포함하지 않았습니다.

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
