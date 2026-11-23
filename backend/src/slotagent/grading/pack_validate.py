"""[② 1차 담당, ③ 계산 도움] 채점 검증 (FR-VAL-01~04, 검증 실험 E1~E6). 11/22 검토 7 — 담당 자리가 없던 것.

받는 것: jobs.payload {kind: validation, validation_run_id}
읽는 것: validation_runs(params), labels(사람 라벨, 블라인드만), 채점 결과
쓰는 것: grader_checks(error_rate·judge_calibration·label_agreement), validation_runs.result·passed
숫자(거짓 성공·실패율의 95% 상한, κ)는 stats 의 함수로 계산 — 판정 규칙은 ③, 무엇을 뽑아 라벨할지는 ②
도메인이 E1~E6 을 모두 통과하면 domains.validated_at (리포트 caveats.grader_validated)
"""


def run_validation(conn, validation_run_id: int) -> None:
    raise NotImplementedError
