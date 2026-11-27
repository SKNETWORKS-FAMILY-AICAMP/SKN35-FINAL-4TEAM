"""① 기록·재생: 저장된 trace 의 모델 응답·도구 결과를 그대로 다시 먹여 실행 루프를 재현합니다.

모델 API 키·MCP 서버 없이 돌고 비용은 0 입니다. 쓰기·확인·도구 검색·고정 응답은 실제 엔진 코드가 다시 처리하므로
엔진이 원래와 다르게 움직이면(다른 도구·인자로 부름, 호출 수가 다름) 숨기지 않고 어긋남으로 돌려줍니다.
재생 trace 는 비교용이며 DB 에 저장하지 않습니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from psycopg.rows import dict_row

from slotagent.common.llm import ModelError, Reply, ToolCall
from slotagent.common.snapshot import trial_seed
from slotagent.engine import fixed_tools
from slotagent.engine.loop import Dependencies, ToolEnvironmentError, ToolExecutionError, run_agent
from slotagent.engine.write_proxy import BUILTIN_NAMES
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_pipeline import ConditionResult, check_conditions, load_trace

# 실행마다 달라지는 값. 시각·걸린 시간과 워커가 붙이는 풀이 번호는 비교하지 않습니다.
SKIP_SPAN = {"started_at", "duration_sec", "wait_sec"}
SKIP_TRACE = {"usage", "trial_id", "attempt"}


class ReplayDivergence(Exception):
    """재생 중 엔진이 기록에 없는 모델·도구 호출을 하려 했습니다."""


def _external(snap: dict) -> set[str]:
    """실행 루프가 deps.call_tool 로 보내는 도구 이름. 쓰기·내장·고정 응답·검색은 엔진 안에서 처리합니다."""
    inside = set(snap["write_tools"]) | BUILTIN_NAMES
    return {t["name"] for t in snap["tools"] if t["access"] != "write" and t["name"] not in inside
            and not fixed_tools.is_fixed_read(t)}


@dataclass
class _Script:
    trace: dict
    snap: dict
    model_spans: list = field(init=False)
    tool_spans: list = field(init=False)
    times: list = field(init=False)
    is_fake: bool = field(default=True, init=False)  # 가격표 없이 돌도록. 비용은 기록값을 그대로 돌려줍니다

    def __post_init__(self):
        spans = self.trace["spans"]
        external = _external(self.snap)
        self.model_spans = [s for s in spans if s["kind"] == "llm"]
        self.tool_spans = [s for s in spans if s["kind"] == "tool" and s["name"] in external
                           and s.get("error") != "agent_invalid_tool_call"]
        # span 하나를 만들 때마다 now() 를 한 번 부릅니다. 승인 순서 검사가 원래 시각을 보도록 그대로 돌려줍니다.
        self.times = [datetime.fromisoformat(s["started_at"]) for s in spans]

    def now(self) -> datetime:
        if self.times:
            self._last = self.times.pop(0)
        else:
            self._last = getattr(self, "_last", datetime.fromisoformat("2000-01-01T00:00:00+00:00")) + timedelta(
                microseconds=1)
        return self._last

    def chat(self, **_request) -> Reply:
        if not self.model_spans:
            raise ReplayDivergence("기록보다 모델 호출이 많습니다.")
        span = self.model_spans.pop(0)
        attrs = span.get("attributes", {})
        if "in_tokens" not in span:
            raise ModelError(span["error"], duration_sec=span["duration_sec"], wait_sec=span.get("wait_sec", 0),
                             api_retries=attrs.get("api_retries", 0))
        return Reply(
            text=span.get("output") or "",
            tool_calls=tuple(ToolCall(c["id"], c["function"]["name"], c["function"]["arguments"])
                             for c in attrs["tool_calls"]),
            in_tokens=span["in_tokens"],
            out_tokens=span["out_tokens"],
            model=attrs["model.resolved"],
            finish_reason=attrs["model.finish_reason"],
            duration_sec=span["duration_sec"],
            wait_sec=span.get("wait_sec", 0),
            api_retries=attrs["api_retries"],
            cost_krw=Decimal(attrs["cost_krw"]),
            source=attrs["model.source"],
        )

    def call_tool(self, name: str, args: dict, _timeout: float) -> str:
        if not self.tool_spans:
            raise ReplayDivergence(f"기록에 없는 도구 호출: {name}")
        span = self.tool_spans.pop(0)
        if (span["name"], span["tool_args"]) != (name, args):
            raise ReplayDivergence(
                f"seq {span['seq']}: 기록은 {span['name']}({span['tool_args']}) 인데 {name}({args}) 를 부르려 함")
        error = span.get("error")
        if error == "tool_error":
            raise ToolExecutionError(span["tool_result"])
        if error == "timeout_wall_clock":
            raise TimeoutError
        if error:
            raise ToolEnvironmentError(error)
        return span["tool_result"]


def replay(snap: dict, task_prompt: str, seed: int, trace: dict, *, prereg: dict, confirmation=None,
           write_scenario=None) -> tuple[dict | None, list[str]]:
    """(재생 trace, 어긋남 목록). 엔진이 기록에 없는 호출을 하려 하면 trace 는 None 입니다.

    shortcut: 시계는 멈춰 두므로 모델 호출 사이(도구 호출 밖)에서 난 시간 초과는 재현하지 못하고 어긋남으로 나옵니다.
    """
    script = _Script(trace, snap)
    deps = Dependencies(script, script.call_tool, clock=lambda: 0.0, now=script.now)
    try:
        result = run_agent(snap, task_prompt, seed, deps, prereg=prereg, confirmation=confirmation,
                           write_scenario=write_scenario)
    except ReplayDivergence as exc:
        return None, [str(exc)]
    replayed = result.trace
    leftover = [f"쓰이지 않은 도구 기록 seq {s['seq']}" for s in script.tool_spans]
    return replayed, compare_traces(trace, replayed) + leftover


def compare_traces(original: dict, replayed: dict) -> list[str]:
    """시각·걸린 시간을 뺀 나머지가 다른 곳의 경로 목록. 같으면 빈 목록."""
    return _diff(_strip(original), _strip(replayed), "trace")


def _strip(trace: dict) -> dict:
    out = {k: v for k, v in trace.items() if k not in SKIP_TRACE}
    # DB 는 빈 attributes 를 {} 로 저장하고 엔진 기록은 칸을 뺍니다. 같은 뜻이라 맞춥니다.
    out["spans"] = [{k: v for k, v in s.items() if k not in SKIP_SPAN and not (k == "attributes" and v == {})}
                    for s in trace["spans"]]
    return out


def _diff(a, b, path) -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(a.keys() | b.keys(), key=str)
                for d in (_diff(a[k], b[k], f"{path}.{k}") if k in a and k in b else [f"{path}.{k}: 한쪽에만 있음"])]
    if isinstance(a, list) and isinstance(b, list):
        found = [d for i, (x, y) in enumerate(zip(a, b, strict=False)) for d in _diff(x, y, f"{path}[{i}]")]
        return found + ([f"{path}: 길이 {len(a)} != {len(b)}"] if len(a) != len(b) else [])
    # bool 은 int 의 하위형이라 True == 1 이 되므로 형까지 봅니다.
    return [] if type(a) is type(b) and a == b else [f"{path}: {a!r} != {b!r}"]


@dataclass(frozen=True)
class ReplayReport:
    trial_id: int
    differences: list[str]  # trace 어긋남
    original: tuple[ConditionResult, ...]  # 저장된 trace 의 규칙 결과
    replayed: tuple[ConditionResult, ...] | None  # 재생 trace 의 규칙 결과 (재생이 멈췄으면 None)

    @property
    def same(self) -> bool:
        return not self.differences and self.original == self.replayed


def replay_trial(conn, trial_id: int, *, grading_run_id: int | None = None, trace: dict | None = None) -> ReplayReport:
    """DB 의 풀이 하나를 키 없이 재생하고, 두 trace 로 규칙 채점을 다시 해 견줍니다. DB 에는 쓰지 않습니다.

    grading_run_id 를 주면 재생 trace 의 규칙 결과를 그 실행에 저장된 조건 결과와도 견줍니다.
    trace 를 넘기면 저장된 기록 대신 그것을 재생합니다 (변조 검사용).
    """
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """SELECT t.*, ec.config_snapshot, k.prompt, k.seed, k.confirmation, k.write_scenario, e.prereg
               FROM sa_trials t JOIN sa_experiment_candidates ec USING (experiment_candidate_id)
               JOIN sa_tasks k USING (task_id) JOIN sa_experiments e ON e.experiment_id=t.experiment_id
               WHERE t.trial_id=%s""",
            (trial_id,),
        ).fetchone()
        if row is None or row["run_outcome"] is None:
            raise ValueError("끝난 풀이가 없습니다.")
        conditions = cur.execute(
            "SELECT answer_condition_id,seq,kind,spec FROM sa_answer_conditions WHERE task_id=%s ORDER BY seq",
            (row["task_id"],),
        ).fetchall()
    snap = row["config_snapshot"]
    stored = trace if trace is not None else load_trace(conn, row)
    replayed, differences = replay(snap, row["prompt"], trial_seed(row["seed"], row["rep"]), stored,
                                   prereg=row["prereg"], confirmation=row["confirmation"],
                                   write_scenario=row["write_scenario"])
    context = from_snapshot(snap, row["confirmation"])
    original = check_conditions(conditions, stored, context)
    again = None if replayed is None else check_conditions(conditions, replayed, context)
    if grading_run_id is not None and again is not None:
        saved = {k: (p, e) for k, p, e in conn.execute(
            "SELECT answer_condition_id,passed,evidence FROM sa_condition_results WHERE grading_run_id=%s AND trial_id=%s",
            (grading_run_id, trial_id),
        ).fetchall()}
        now = {r.answer_condition_id: (r.passed, r.evidence) for r in again if r.passed is not None}
        differences += [f"조건 {k}: 저장 결과 {saved.get(k)} != 재채점 {now.get(k)}"
                        for k in sorted(saved.keys() | now.keys()) if saved.get(k) != now.get(k)]
    return ReplayReport(trial_id, differences, original, again)
