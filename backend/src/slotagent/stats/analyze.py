def analyze(conn, grading_run_id: int, *, is_interim: bool = False, batch_no: int | None = None) -> int:
    """실험은 grading_runs.experiment_id 로 앎. analyses.method 를 저장하기 전에 common.checks.check_method(method, prereg).
    중간 분석이면 method.sequential.stop 에 판정(true = 멈춤)을 남김 — 멈추는 일은 ①(engine/advance.py)이 함.
    끝나면 engine.advance.on_analysis_done"""
    raise NotImplementedError


def sample_size(margin_pp: float, alpha: float, power: float, p_base: float) -> dict:
    """필요한 문항 유형 수. plan-proposal API 와 chatbot 의 calc_sample_size 가 부름 (④는 API 로만)"""
    raise NotImplementedError
