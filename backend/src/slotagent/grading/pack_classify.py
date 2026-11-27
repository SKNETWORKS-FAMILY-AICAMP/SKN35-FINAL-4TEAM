"""② 워커에 주입하는 결과 분류기."""

from slotagent.grading.eng_pipeline import Verdict, check_verdict
from slotagent.grading.pack_judge import judge


def classify(conn, item):
    """grade_once(connect, worker_id, classify=classify). 모델 설정은 채점 실행에서 읽습니다."""
    if item.out_of_scope:
        return Verdict("ask_or_giveup", fail_tags=("out_of_scope",))
    if item.run_outcome != "completed":
        return Verdict(
            "ask_or_giveup",
            "tool_error" if any(s.get("error") and s["kind"] == "tool" for s in item.trace["spans"]) else None,
        )
    if item.judge_settings:
        verdict = judge(conn, item)
    elif any(c.gate and c.passed is None for c in item.conditions):
        verdict = Verdict("ask_or_giveup", "final_answer", judge_status="undecidable")
    elif any(c.gate and c.passed is False for c in item.conditions):
        # shortcut: 규칙만으로 인과상 첫 단계를 알 수 없음, LLM 설정 시 기록으로 판정합니다.
        verdict = Verdict("wrong_assertion", "final_answer", judge_status="undecidable")
    else:
        verdict = Verdict("correct")
    if verdict.result_class == "correct" and (
        item.forbidden_action or any(c.gate and c.passed is not True for c in item.conditions)
    ):
        if item.forbidden_action or any(c.gate and c.passed is False for c in item.conditions):
            verdict = Verdict(
                "wrong_assertion",
                "forbidden" if item.forbidden_action else "final_answer",
                judge_status="undecidable",
                fail_tags=("rule_conflict",),
            )
        else:
            verdict = Verdict("ask_or_giveup", "final_answer", judge_status="undecidable",
                              fail_tags=("rule_undecidable",))
    check_verdict(item, verdict)
    return verdict
