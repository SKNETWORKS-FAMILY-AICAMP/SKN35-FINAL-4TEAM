"""[① 실행 엔진] 잠금 → 풀이 실행 → 실행 기록 → 다음 단계 넘기기.

받는 것: experiment_id (API) / jobs.payload {kind: run_trial, trial_id}
읽는 것: 후보 구성은 experiment_candidates.config_snapshot 만 (재현성). 문항·연습 환경은 평가팩(tasks, data_snapshots)
쓰는 테이블: trials(상태·결과), spans, write_intents, jobs, cost_ledger, grading_runs(만들기만), experiments.status
넘겨주는 것: 범위 안 풀이가 모두 끝나면 advance.on_trial_finished 가 grading_run 1개 + grade 작업
⚠ 연습 환경에 MCP 서버를 어떻게 붙이는지(D-05 저장소 쪽)는 결정 전 — docs/decisions_pending.md
"""
