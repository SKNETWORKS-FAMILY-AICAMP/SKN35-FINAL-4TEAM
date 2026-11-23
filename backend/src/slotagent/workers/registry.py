"""[①] jobs.kind → 처리 함수. 새 작업은 여기 한 줄 + job_payload 스키마에 한 갈래 (jobs.kind = payload.kind 는 DB CHECK)."""
from slotagent.engine.worker import run_trial
from slotagent.grading.eng_pipeline import grade
from slotagent.grading.pack_validate import run_validation
from slotagent.reports import build as build_report
from slotagent.stats.analyze import analyze

HANDLERS = {
    "run_trial": lambda conn, p: run_trial(conn, p["trial_id"]),
    "grade": lambda conn, p: grade(conn, p["grading_run_id"]),
    "analyze": lambda conn, p: analyze(conn, p["grading_run_id"], is_interim=p["is_interim"], batch_no=p.get("batch_no")),
    "report": lambda conn, p: [build_report(conn, p["analysis_id"], k) for k in p["report_kinds"]],
    "validation": lambda conn, p: run_validation(conn, p["validation_run_id"]),
}
