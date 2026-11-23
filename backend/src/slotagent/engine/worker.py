"""작업 하나 실행. 임대(10분, 1분마다 연장)·attempt 펜싱은 common.queue 가 처리."""


def run_trial(conn, trial_id: int) -> None:
    """한 풀이 실행.
    1. advance.check_budget — 예산 도달이면 실행 안 함
    2. 후보 구성 = experiment_candidates.config_snapshot / 문항 = tasks.prompt·seed / 환경 = data_snapshots (실험의 평가팩)
       풀이 seed = snapshot.trial_seed(task.seed, rep), trials.harness_version = snapshot.HARNESS_VERSION
    3. 실행 → trace 스키마 모양 → spans 먼저, write_intents 는 span_seq 를 spans.id 로 바꿔서 (contracts/README)
    4. trials 끝내기 + cost_ledger 1행 + advance.on_trial_finished (같은 트랜잭션)"""
    raise NotImplementedError
