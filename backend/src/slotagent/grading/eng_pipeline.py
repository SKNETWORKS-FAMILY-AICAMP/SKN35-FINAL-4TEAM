"""① 채점 실행 하나의 전체 흐름: 규칙 채점 → ② 판정 함수 → trial_grades → finished_at → analyze 작업.

- 규칙 결과는 풀이마다 따로 커밋합니다. 중간에 죽어도 다시 부르면 남은 풀이만 이어서 합니다.
- ② 판정(LLM 판정·결과 3분류·첫 실패 단계)은 classify 로 주입하고, LLM 을 부를 수 있으므로 DB 트랜잭션 밖에서 부릅니다.
- classify 가 없으면 규칙 결과만 저장하고 JudgeNotConnected 를 올립니다. 채점 행과 finished_at 은 쓰지 않습니다.
- 규칙으로 못 정한 조건은 실패로 저장하지 않고 undecided 로 넘깁니다 (condition_results 행 없음).

classify(conn, item) -> Verdict
    conn 은 트랜잭션이 없는 상태로 넘기고, 같은 상태로 돌려받습니다 (llm_votes·비용 저장은 ②가 짧은 트랜잭션으로).
    같은 풀이로 다시 불릴 수 있으므로 이미 저장한 투표를 재사용해야 합니다.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from slotagent.common import checks, contracts, queue
from slotagent.common.hashing import canonical_hash, canonical_json
from slotagent.engine import advance
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_policy import PolicyResult, check_policy, policy_context
from slotagent.grading.eng_rules import RulePolicyRequired, TraceError, check


class JudgeNotConnected(NotImplementedError):
    """② 판정 함수가 아직 없습니다. 규칙 결과까지만 저장했습니다."""


@dataclass(frozen=True)
class ConditionResult:
    answer_condition_id: int
    seq: int
    kind: str
    passed: bool | None  # None = 규칙으로 판정 불가
    evidence: dict = field(default_factory=dict)
    undecided: str | None = None
    gate: bool = True  # False 면 진단용. 성공 여부를 막지 않습니다 (checks.condition_gate)


@dataclass(frozen=True)
class GradeItem:
    """②에게 넘기는 풀이 하나. 후보 이름·라벨은 넣지 않습니다."""

    grading_run_id: int
    trial_id: int
    prompt: str
    trace: dict
    run_outcome: str
    conditions: tuple[ConditionResult, ...]
    out_of_scope: bool
    forbidden_action: bool
    judge_model: str | None
    judge_settings: dict
    policy: tuple[PolicyResult, ...] = ()  # prereg.process_policy 규칙별 결과 (없으면 비어 있음)
    policy_gate: bool = False  # true 면 정책 위반 풀이는 성공일 수 없음


@dataclass(frozen=True)
class Verdict:
    """②가 정하는 값. success 는 result_class == 'correct' 로만 정해집니다."""

    result_class: str
    first_fail_type: str | None = None
    judge_status: str = "ok"
    fail_tags: tuple[str, ...] = ()
    unmeasurable: tuple[str, ...] = ()


def load_trace(conn, trial: dict) -> dict:
    """지금 시도의 spans·write_intents 를 trace 계약 모양으로 되돌립니다."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT * FROM sa_spans WHERE trial_id=%s AND attempt=%s ORDER BY seq", (trial["trial_id"], trial["attempt"])
        ).fetchall()
        intents = cur.execute(
            """SELECT s.seq AS span_seq,w.tool_name,w.payload,w.in_rule_list,w.user_confirmed
               FROM sa_write_intents w JOIN sa_spans s USING (span_id)
               WHERE w.trial_id=%s AND s.attempt=%s ORDER BY w.write_intent_id""",
            (trial["trial_id"], trial["attempt"]),
        ).fetchall()
    spans = []
    for row in rows:
        span = {
            "seq": row["seq"],
            "kind": row["kind"],
            "started_at": row["started_at"].isoformat(),
            "duration_sec": float(row["duration_sec"]),
            "wait_sec": float(row["wait_sec"]),
            "attributes": row["attributes"],
        }
        for key in ("name", "in_tokens", "out_tokens", "output", "tool_args", "tool_result", "error"):
            if row[key] is not None:
                span[key] = row[key]
        spans.append(span)
    trace = {
        "schema_version": 1,
        "trial_id": trial["trial_id"],
        "attempt": trial["attempt"],
        "spans": spans,
        "write_intents": intents,
        "final_answer": trial["final_answer"],
        "run_outcome": trial["run_outcome"],
    }
    if trial["outcome_reason"]:
        trace["outcome_reason"] = trial["outcome_reason"]
    return contracts.validate("trace", trace)


def _is_empty(result: str | None) -> bool:
    if result is None or not result.strip():
        return True
    try:
        return json.loads(result) in (None, [], {}, "")
    except (ValueError, RecursionError):
        return False


def error_kind(code: str) -> str:
    """오류 코드 → 원인 묶음. 코드 체계(agent_·env_·timeout_·tool_error) 밖의 값은 unclassified."""
    if code == "tool_error":
        return "tool"
    if code.startswith("agent_"):
        return "agent"
    if code.startswith(("env_", "timeout_")):
        return "env"
    return "unclassified"


def error_calls(tools: list[dict]) -> dict:
    """오류로 끝난 도구 호출 수를 원인 묶음별로 (trial_metrics v2)."""
    counts = {"agent": 0, "tool": 0, "env": 0, "unclassified": 0}
    for span in tools:
        if "error" in span:
            counts[error_kind(span["error"])] += 1
    return counts


def trial_metrics(trace: dict) -> dict:
    """진단 지표. 엔진 내장 도구(확인·검색)도 실제 호출이므로 같이 셉니다."""
    tools = [s for s in trace["spans"] if s["kind"] == "tool"]
    calls = Counter((s["name"], canonical_json(s.get("tool_args", {}))) for s in tools)
    seconds: dict[str, float] = {}
    for span in tools:
        seconds[span["name"]] = seconds.get(span["name"], 0) + span["duration_sec"]
    metrics = {
        "schema_version": 2,
        "tool_calls": len(tools),
        "distinct_tools": len(seconds),
        "repeated_calls": sum(n - 1 for n in calls.values()),
        "empty_results": sum("error" not in s and _is_empty(s.get("tool_result")) for s in tools),
        "steps": sum(s["kind"] in {"llm", "tool"} for s in trace["spans"]),
        "tool_sec_by_tool": seconds,
        "error_calls": error_calls(tools),
    }
    return contracts.validate("grading", metrics, part="trial_metrics")


def check_conditions(conditions: list[dict], trace: dict, context: dict) -> tuple[ConditionResult, ...]:
    """조건 전부를 규칙으로 봅니다. 판정 불가는 남기고, 잘못된 조건·기록은 예외로 올립니다."""
    results = []
    for c in conditions:
        base = (c["answer_condition_id"], c["seq"], c["kind"])
        gate = checks.condition_gate(c["kind"], c["spec"])
        try:
            passed, evidence = check(c["kind"], c["spec"], trace, **context)
        except RulePolicyRequired as exc:
            results.append(ConditionResult(*base, None, undecided=exc.code, gate=gate))
            continue
        contracts.validate("grading", evidence, part="condition_evidence")
        results.append(ConditionResult(*base, passed, evidence, gate=gate))
    return tuple(results)


def _run(conn, grading_run_id):
    with queue.transaction(conn), conn.cursor(row_factory=dict_row) as cur:
        run = cur.execute("SELECT * FROM sa_grading_runs WHERE grading_run_id=%s", (grading_run_id,)).fetchone()
        if run is None:
            raise ValueError("채점 실행이 없습니다.")
        trials = cur.execute(
            """SELECT trial_id FROM sa_effective_trials WHERE experiment_id=%s AND run_outcome<>'env_error'
               AND (%s::int IS NULL OR batch_no<=%s) ORDER BY trial_id""",
            (run["experiment_id"], run["upto_batch_no"], run["upto_batch_no"]),
        ).fetchall()
    return run, [t["trial_id"] for t in trials]


def _load(conn, run, trial_id):
    """(풀이, 채점 기준 조건). 승인 정책은 실행에 쓴 문항, 조건은 채점 평가팩의 같은 문항 코드에서 읽습니다."""
    with conn.cursor(row_factory=dict_row) as cur:
        trial = cur.execute(
            """SELECT t.*, k.prompt, k.confirmation, k.code AS task_code, tp.code AS template_code,
                      ec.config_snapshot, ec.config_hash, ec.template_scope
               FROM sa_trials t JOIN sa_tasks k USING (task_id) JOIN sa_templates tp USING (template_id)
               JOIN sa_experiment_candidates ec USING (experiment_candidate_id) WHERE t.trial_id=%s""",
            (trial_id,),
        ).fetchone()
        task = cur.execute(
            """SELECT k.task_id FROM sa_tasks k JOIN sa_templates tp USING (template_id)
               WHERE tp.pack_version_id=%s AND tp.code=%s AND k.code=%s""",
            (run["pack_version_id"], trial["template_code"], trial["task_code"]),
        ).fetchone()
        if task is None:
            raise ValueError("채점 평가팩에 이 풀이의 문항이 없습니다.")
        conditions = cur.execute(
            "SELECT answer_condition_id,seq,kind,spec FROM sa_answer_conditions WHERE task_id=%s ORDER BY seq",
            (task["task_id"],),
        ).fetchall()
    if not conditions:
        # 조건이 하나도 없으면 아무 답이나 통과하므로 채점하지 않습니다.
        raise ValueError("정답 조건이 없는 문항입니다.")
    for c in conditions:
        # 조건이 틀린 것은 평가팩 문제입니다. 풀이마다 grader_error 로 굳히지 않고 채점을 멈춥니다.
        contracts.validate("answer_condition", c["spec"], part=c["kind"])
    if canonical_hash(trial["config_snapshot"]) != trial["config_hash"]:
        raise ValueError("실행 스냅샷의 해시가 일치하지 않습니다.")
    if trial["template_scope"].get(trial["template_code"]) not in {"in_scope", "out_of_scope"}:
        raise ValueError("실행 전 범위 판정이 없는 문항 유형입니다.")
    return trial, conditions


@contextmanager
def _fenced(conn, job):
    """임대를 쥔 채로만 저장합니다. 트랜잭션 도중 만료되면 끝에서 전부 되돌립니다."""
    with queue.transaction(conn):
        if job is not None:
            queue.guard(conn, job)
        yield
        if job is not None:
            queue.guard(conn, job)


def _is_finished(conn, run_id) -> bool:
    """채점 실행 행을 잠가 _finish 와 순서를 정합니다. 작업 없이 같은 실행을 동시에 부를 때 필요합니다."""
    return conn.execute(
        "SELECT finished_at IS NOT NULL FROM sa_grading_runs WHERE grading_run_id=%s FOR SHARE", (run_id,)
    ).fetchone()[0]


def _ensure_unchanged(what: str, saved: dict, recomputed: dict) -> None:
    """중단 전과 다른 규칙으로 이어서 채점하면 한 실행에 결과가 섞입니다.

    저장된 확정 결과가 판정 불가(None)·결과 없음으로 바뀌는 것도 섞임으로 봅니다.
    """
    if any(recomputed.get(key) != passed for key, passed in saved.items()):
        raise ValueError(f"저장된 {what} 결과와 다시 계산한 결과가 다릅니다. 새 채점 실행을 만드세요.")


def _grade_rules(conn, run, trial_id, job) -> GradeItem | None:
    """규칙 결과를 저장하고 ②에게 넘길 값을 만듭니다. 이미 채점한 풀이와 채점기 오류 풀이는 None."""
    run_id = run["grading_run_id"]
    with _fenced(conn, job):
        if _is_finished(conn, run_id) or conn.execute(
            "SELECT 1 FROM sa_trial_grades WHERE grading_run_id=%s AND trial_id=%s", (run_id, trial_id)
        ).fetchone():
            return None
        trial, conditions = _load(conn, run, trial_id)
        context = from_snapshot(trial["config_snapshot"], trial["confirmation"])
        prereg = conn.execute(
            "SELECT prereg FROM sa_experiments WHERE experiment_id=%s", (run["experiment_id"],)
        ).fetchone()[0]
        policy = (prereg or {}).get("process_policy")
        try:
            trace = load_trace(conn, trial)
            unreadable = False
        except (ValueError, RecursionError):
            unreadable = True
        if not unreadable:
            try:
                # 기록 오류(TraceError)만 풀이 탓입니다. 조건·코드 결함은 그대로 올려 채점을 멈춥니다.
                results = check_conditions(conditions, trace, context)
                policy_results = check_policy(
                    policy, trace, policy_ctx=policy_context(trial["config_snapshot"]), **context
                )
            except TraceError:
                unreadable = True
        if unreadable:
            # 이 풀이의 기록을 채점기가 읽지 못했습니다. 후보 실패로 세지 않습니다.
            conn.execute(
                """INSERT INTO sa_trial_grades(grading_run_id,trial_id,grade_status) VALUES (%s,%s,'grader_error')
                   ON CONFLICT (grading_run_id,trial_id) DO NOTHING""",
                (run_id, trial_id),
            )
            return None
        trial_metrics(trace)
        saved = dict(
            conn.execute(
                "SELECT answer_condition_id,passed FROM sa_condition_results WHERE grading_run_id=%s AND trial_id=%s",
                (run_id, trial_id),
            ).fetchall()
        )
        _ensure_unchanged("규칙", saved, {r.answer_condition_id: r.passed for r in results})
        for r in results:
            if r.passed is not None:
                conn.execute(
                    """INSERT INTO sa_condition_results(grading_run_id,trial_id,answer_condition_id,passed,evidence)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (grading_run_id,trial_id,answer_condition_id) DO NOTHING""",
                    (run_id, trial_id, r.answer_condition_id, r.passed, Jsonb(r.evidence)),
                )
        saved_policy = dict(
            conn.execute(
                "SELECT rule,passed FROM sa_policy_results WHERE grading_run_id=%s AND trial_id=%s", (run_id, trial_id)
            ).fetchall()
        )
        _ensure_unchanged("정책", saved_policy, {p.rule: p.passed for p in policy_results})
        for p in policy_results:
            if p.passed is None:
                continue  # 판정 불가는 저장하지 않습니다 (condition_results 와 같음)
            conn.execute(
                """INSERT INTO sa_policy_results(grading_run_id,trial_id,rule,passed,evidence) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (grading_run_id,trial_id,rule) DO NOTHING""",
                (run_id, trial_id, p.rule, p.passed, Jsonb(p.evidence)),
            )
    return GradeItem(
        run_id,
        trial_id,
        trial["prompt"],
        trace,
        trial["run_outcome"],
        results,
        trial["template_scope"][trial["template_code"]] == "out_of_scope",
        any(r.kind == "forbidden" and r.passed is False for r in results),
        run["judge_model"],
        run["judge_settings"],
        policy_results,
        bool((policy or {}).get("gate", False)),
    )


def check_verdict(item: GradeItem, verdict: Verdict) -> bool:
    """② 값이 규칙 결과와 어긋나면 저장하지 않습니다. 돌려주는 값: success."""
    if not isinstance(verdict, Verdict):
        raise TypeError("판정 함수는 Verdict 를 돌려줘야 합니다.")
    contracts.validate("common", verdict.result_class, part="result_class")
    if verdict.first_fail_type is not None:
        contracts.validate("common", verdict.first_fail_type, part="first_fail_type")
    if verdict.judge_status not in {"ok", "undecidable"}:
        raise ValueError("judge_status 값이 올바르지 않습니다.")
    for value in (verdict.fail_tags, verdict.unmeasurable):
        if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
            raise TypeError("태그·측정 불가 지표는 문자열 목록이어야 합니다.")
    success = verdict.result_class == "correct"
    if success and item.run_outcome != "completed":
        raise ValueError("끝까지 실행하지 못한 풀이는 성공일 수 없습니다.")
    if success and any(r.gate and r.passed is False for r in item.conditions):
        raise ValueError("규칙 조건에서 실패한 풀이를 성공으로 바꿀 수 없습니다.")
    if success and item.policy_gate and any(p.passed is False for p in item.policy):
        raise ValueError("관문인 과정 정책을 어긴 풀이를 성공으로 바꿀 수 없습니다.")
    if success and verdict.first_fail_type is not None:
        raise ValueError("성공한 풀이에는 첫 실패 단계가 없습니다.")
    if not success and item.run_outcome == "completed" and not item.out_of_scope and verdict.first_fail_type is None:
        raise ValueError("끝까지 실행한 실패에는 첫 실패 단계가 필요합니다.")
    return success


def _save_grade(conn, item, verdict, job):
    success = check_verdict(item, verdict)
    with _fenced(conn, job):
        if _is_finished(conn, item.grading_run_id):
            return  # 같은 실행을 다른 호출이 먼저 끝냈습니다. 끝난 채점에는 더하지 않습니다.
        conn.execute(
            """INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,first_fail_type,fail_tags,
               out_of_scope,forbidden_action,judge_status,unmeasurable,metrics)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (grading_run_id,trial_id) DO NOTHING""",
            (
                item.grading_run_id,
                item.trial_id,
                success,
                verdict.result_class,
                verdict.first_fail_type,
                list(verdict.fail_tags),
                item.out_of_scope,
                item.forbidden_action,
                verdict.judge_status,
                list(verdict.unmeasurable),
                Jsonb(trial_metrics(item.trace)),
            ),
        )


def _finish(conn, run, job):
    """finished_at·analyze 작업·작업 완료를 한 트랜잭션으로. 빠진 채점은 DB 트리거가 거절합니다."""
    with queue.transaction(conn):
        if job is not None:
            queue.guard(conn, job)
        conn.execute(
            "UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=%s AND finished_at IS NULL",
            (run["grading_run_id"],),
        )
        if run["purpose"] in {"initial", "regrade"}:
            advance.on_grading_finished(conn, run["grading_run_id"])
        if job is not None:
            queue.finish(conn, job)


def grade(
    conn,
    grading_run_id: int,
    *,
    classify: Callable[..., Verdict] | None = None,
    job: dict | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    """범위 안 유효 풀이(effective_trials, env_error 제외)마다 rules → ② classify → trial_grades 1행."""
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("채점 시작 전 외부 트랜잭션을 끝내고 독립된 연결을 넘기세요.")
    if job is not None and (job["kind"] != "grade" or job["payload"]["grading_run_id"] != grading_run_id):
        raise ValueError("채점 실행과 작업이 일치하지 않습니다.")
    run, trials = _run(conn, grading_run_id)
    if run["finished_at"] is None:
        waiting = False
        for trial_id in trials:
            if cancelled():
                raise queue.LeaseLost("채점 작업의 소유권을 잃었습니다.")
            item = _grade_rules(conn, run, trial_id, job)
            if item is None:
                continue
            if classify is None:
                waiting = True
                continue
            verdict = classify(conn, item)
            if conn.info.transaction_status != TransactionStatus.IDLE:
                raise ValueError("판정 함수가 트랜잭션을 열어 둔 채 끝났습니다.")
            _save_grade(conn, item, verdict, job)
        if waiting:
            raise JudgeNotConnected("② 판정 함수가 없어 규칙 결과까지만 저장했습니다.")
    _finish(conn, run, job)
