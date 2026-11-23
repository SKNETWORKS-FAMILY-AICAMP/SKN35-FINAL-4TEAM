"""[공동] analysis_id → reports.content (report_content 스키마). 숫자는 comparisons·trials 에서만, evidence 에 행 번호."""


def build(conn, analysis_id: int, kind: str) -> dict:
    raise NotImplementedError
