def lock_and_enqueue(conn, experiment_id: int) -> dict:
    """SELECT lock_experiment(id) + run_trial 작업 넣기 + advance.mark_running (한 트랜잭션). 돌려주는 값: api.run_response"""
    raise NotImplementedError
