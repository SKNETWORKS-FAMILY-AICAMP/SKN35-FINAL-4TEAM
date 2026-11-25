"""개발용 trace에도 엔진과 같은 승인·실행 상태를 기록한다. 외부 호출은 없다."""

import json

from slotagent.common.confirmation import approved_write
from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_rules import check

CAPABILITIES = {
    "post_message": ["slack.messages.write"],
    "create_issue": ["github.issues.write"],
}


def context(task):
    return from_tools(
        [
            {"name": name, "access": "write", "capabilities": caps}
            for name, caps in CAPABILITIES.items()
        ],
        task.get("confirmation"),
    )


def annotate(task, trace):
    spans = {s["seq"]: s for s in trace["spans"]}
    for intent in trace["write_intents"]:
        approved = approved_write(
            task.get("confirmation"),
            trace,
            intent["span_seq"],
            set(CAPABILITIES),
            CAPABILITIES,
        )
        intent["user_confirmed"] = approved
        span = spans[intent["span_seq"]]
        span.setdefault("attributes", {}).update(
            write_mode="fake",
            write_status="ok" if approved else "blocked",
            write_applied=approved,
        )
        if not approved:
            span["tool_result"] = json.dumps(
                {
                    "fake": True,
                    "status": "blocked",
                    "reason": "user_confirmation_required",
                }
            )
    return trace


def exact(task, spec, trace):
    return check("exact_writes", spec, trace, **context(task))[0]
