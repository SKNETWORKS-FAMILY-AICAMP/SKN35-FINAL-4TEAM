"""① 평가팩(it_ops)의 문항을 실제 엔진·DB·규칙 채점까지 연결합니다. 모델은 골든 궤적을 따라 하는 가짜입니다.

- 서버 시험: ②의 연습 MCP 서버를 실제 프로세스로 띄웁니다 (서버가 지원하는 유형만).
- 재생 시험: 서버가 아직 없는 유형은 골든에 적힌 조회 결과를 돌려줍니다. 쓰기·승인은 실제 write_proxy 가 처리합니다.
등록(④)·판정(②)·분석(③)이 없는 부분은 DB에 직접 넣거나 가짜 판정을 주입합니다. 팩 잠금은 임시 DB에서만 합니다.
"""

import copy
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from functools import lru_cache

import psycopg
import pytest
from conftest import ROOT, load
from psycopg.types.json import Jsonb
from test_eng_worker import engine_db as engine_db

from slotagent.common import checks, contracts
from slotagent.common.hashing import agent_spec_hash, canonical_hash
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import build_config_snapshot
from slotagent.engine.eng_stdio import LocalStdioConfig
from slotagent.engine.lock import lock_and_enqueue
from slotagent.engine.loop import Dependencies, run_agent
from slotagent.engine.write_proxy import BUILTIN_NAMES
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_pipeline import JudgeNotConnected, Verdict, check_conditions, grade, load_trace
from slotagent.packs.loader import load_pack
from slotagent.workers.eng_main import grade_once, run_once

PACK = ROOT / "packs/it_ops/v0.1"


@lru_cache
def read(name):
    return json.loads((PACK / name).read_text(encoding="utf-8"))


TASKS = {t["code"]: t for t in read("pack.json")["tasks"]}
GOLDEN = read("pack.json")["golden"]
PILOT = [t["template"] for t in read("practice/pilot_selection.json")["templates"]]
SERVED = read("practice/servers.json")["template_codes"]


def success(template):
    return next(g for g in GOLDEN if (g["template"], g["kind"]) == (template, "success"))


def calls(golden):
    return [s for s in read(golden["trace"])["spans"] if s["kind"] == "tool"]


def replies(golden):
    tools = [
        Reply(tool_calls=(ToolCall(f"c{n}", s["name"], json.dumps(s["tool_args"], ensure_ascii=False)),),
              in_tokens=10, out_tokens=1)
        for n, s in enumerate(calls(golden))
    ]
    return [*tools, Reply(text=read(golden["trace"])["final_answer"], in_tokens=10, out_tokens=1)]


class ByPrompt:
    """문항 문장으로 대본을 고릅니다. 워커가 어떤 순서로 풀이를 가져가도 같습니다."""

    is_fake = True

    def __init__(self, goldens):
        self.scripts = {TASKS[g["task_code"]]["prompt"]: g for g in goldens}
        assert len(self.scripts) == len(goldens)

    def chat(self, **request):
        golden = self.current = self.scripts[request["messages"][1]["content"]]
        step = sum(m["role"] == "assistant" for m in request["messages"])
        self.step = step
        return FakeModel([replies(golden)[step]]).chat(**request)

    def call_tool(self, name, args, _):
        """지금 풀이의 골든에 적힌 조회 결과. 다른 유형이 같은 조회를 써도 섞이지 않습니다."""
        span = calls(self.current)[self.step]
        assert (span["name"], span["tool_args"]) == (name, args)
        return span["tool_result"]


def tool_definitions(names):
    served = {t["name"]: t for t in read("practice/servers.json")["services"][0]["tools"]}
    rows = []
    for tool in read("practice/tool_permissions.json")["tools"]:
        if tool["name"] not in names:
            continue
        known = served.get(tool["name"])
        row = {
            "name": tool["name"],
            "description": known["semantics"] if known else tool["name"],
            "parameters": known["input_schema"] if known else {"type": "object"},
            "service": "slack" if tool["name"] == "post_message" else "github",
            "access": tool["access"],
            "origin": "mcp:github",
            "capabilities": tool["capabilities"],
        }
        if tool["access"] == "write":
            row["write_mode"] = "fake"
        rows.append(row)
    assert {r["name"] for r in rows} == set(names)
    return rows


def agent_spec(names):
    spec = copy.deepcopy(load("agent_version.json")["spec"])
    spec["services"] = [{"code": "github", "name": "GitHub"}, {"code": "slack", "name": "Slack"}]
    spec["tools"] = tool_definitions(names)
    used = {t["service"] for t in spec["tools"]}
    spec["services"] = [s for s in spec["services"] if s["code"] in used]
    checks.check_registration("spec_upload", spec)
    return contracts.validate("agent_spec", spec)


@pytest.fixture(scope="module")
def pack_id(engine_db):
    with psycopg.connect(engine_db, autocommit=True) as conn:
        conn.execute("INSERT INTO sa_domains(domain_code,name,status) VALUES ('it_ops','IT 운영','active')")
        pack = load_pack(conn, PACK)
        # 제품 잠금(lock_pack)은 독립 검증 기록이 있어야 합니다. 임시 DB라 상태만 바꿉니다.
        conn.execute("UPDATE sa_pack_versions SET status='locked',locked_at=now() WHERE pack_version_id=%s", (pack,))
        yield pack


def create_experiment(conn, pack_id, goldens, names):
    """④ register_agent·실험 저장이 할 일을 대신합니다. 자리와 기준 후보는 ①의 checks 함수로 만듭니다."""

    def one(query, *values):
        return conn.execute(query, values).fetchone()[0]

    av, spec = load("agent_version.json"), agent_spec(names)
    user = one("INSERT INTO sa_users(email,name) VALUES (gen_random_uuid()::text,'파일럿') RETURNING user_id")
    agent = one("INSERT INTO sa_agents(owner_id,name,domain_code) VALUES (%s,'파일럿','it_ops') RETURNING agent_id", user)
    version = one(
        """INSERT INTO sa_agent_versions(agent_id,version_no,connection_type,model_provider,control_level,model,
           temperature,instructions,spec,spec_hash) VALUES (%s,1,'spec_upload',%s,'C2',%s,0,%s,%s,%s)
           RETURNING agent_version_id""",
        agent, av["model_provider"], av["model"], av["instructions"], Jsonb(spec),
        agent_spec_hash(av["model"], 0, av["instructions"], spec),
    )
    chosen = None
    for slot in checks.build_slots("spec_upload", "C2", spec):
        slot_id = one(
            """INSERT INTO sa_slots(agent_version_id,name,service,access,comparable,not_comparable_reason)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING slot_id""",
            version, slot["name"], slot["service"], slot["access"], slot["comparable"], slot["not_comparable_reason"],
        )
        comp = checks.baseline_component(spec, slot)
        for label in ("A", "B") if slot["comparable"] else ("A",):
            candidate = one(
                """INSERT INTO sa_candidates(slot_id,label,name,component_kind,component_spec,spec_hash,is_baseline)
                   VALUES (%s,%s,%s,'tool_bundle',%s,%s,%s) RETURNING candidate_id""",
                slot_id, label, label, Jsonb(comp), canonical_hash(comp), label == "A",
            )
            if slot["comparable"]:
                chosen = (slot_id, [*(chosen[1] if chosen else []), candidate])
    source = load("experiment.json")
    codes = [g["task_code"] for g in goldens]
    plan = {**copy.deepcopy(source["plan"]), "tasks": [
        {"task_id": one("SELECT task_id FROM sa_tasks k JOIN sa_templates t USING(template_id) "
                        "WHERE t.pack_version_id=%s AND k.code=%s", pack_id, code), "batch_no": 1} for code in codes]}
    slot_id, candidates = chosen
    exp = one(
        """INSERT INTO sa_experiments(kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by)
           VALUES ('compare',%s,%s,%s,1,%s,%s,100000,%s) RETURNING experiment_id""",
        version, slot_id, pack_id, Jsonb(source["prereg"]), Jsonb(plan), user,
    )
    templates = [t for t in read("pack.json")["templates"]]
    for label, candidate in zip("AB", candidates, strict=True):
        snap, digest = build_config_snapshot(conn, candidate)
        scope = checks.template_scope(snap["tools"], templates)
        scope = {t: s for t, s in scope.items() if t in {g["template"] for g in goldens}}
        # 이름표가 없는 연습 조회 도구가 있어도 여기서 쓰는 유형은 모두 범위 안이어야 합니다.
        assert set(scope.values()) == {"in_scope"}, scope
        conn.execute(
            """INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash,
               template_scope) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (exp, candidate, label, "baseline" if label == "A" else "candidate", Jsonb(snap), digest, Jsonb(scope)),
        )
    conn.execute("INSERT INTO sa_settings(scope,scope_ref,key,value) VALUES ('global','',%s,%s)",
                 ("price." + av["model"], Jsonb({"in_per_1k_krw": 1, "out_per_1k_krw": 2})))
    lock_and_enqueue(conn, exp)
    return exp


def by_rules(_, item):
    """② 판정 자리의 가짜. 관문 조건이 모두 규칙으로 통과했을 때만 정답."""
    if item.run_outcome == "completed" and all(c.passed for c in item.conditions if c.gate):
        return Verdict("correct")
    return Verdict("wrong_assertion", "final_answer")


def run_experiment(uri, exp, goldens, *, stdio=None):
    def connect():
        return psycopg.connect(uri, autocommit=True)

    model = ByPrompt(goldens)
    deps = Dependencies(model, model.call_tool if stdio is None else forbidden_call)
    done = 0
    while run_once(connect, "pilot", deps=deps, stdio=stdio):
        done += 1
    with connect() as conn:
        trials = conn.execute("SELECT status,run_outcome,count(*) FROM sa_trials WHERE experiment_id=%s GROUP BY 1,2",
                              (exp,)).fetchall()
        assert trials == [("finished", "completed", done)] and done == 2 * len(goldens), trials
        run = conn.execute("SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (exp,)).fetchall()
        assert len(run) == 1
        with pytest.raises(JudgeNotConnected):  # 판정 함수 없이는 규칙 결과만 남음
            grade(conn, run[0][0])
        assert conn.execute("SELECT count(*) FROM sa_trial_grades WHERE grading_run_id=%s", run[0]).fetchone() == (0,)
    assert grade_once(connect, "pilot-grade", classify=by_rules)
    return run[0][0]


def forbidden_call(*_):
    raise AssertionError("서버 시험에서 가짜 조회를 부르면 안 됩니다.")


def check_results(conn, exp, run_id, goldens):
    rows = conn.execute(
        """SELECT k.code,c.seq,r.passed FROM sa_condition_results r JOIN sa_answer_conditions c USING(answer_condition_id)
           JOIN sa_trials t USING(trial_id) JOIN sa_tasks k ON k.task_id=t.task_id WHERE grading_run_id=%s""", (run_id,)
    ).fetchall()
    expected = {(g["task_code"], int(s)): p for g in goldens for s, p in g["expected"]["conditions"].items()}
    assert {(c, s): p for c, s, p in rows} == expected
    assert len(rows) == 2 * len(expected)
    grades = conn.execute("SELECT grade_status,success,count(*) FROM sa_trial_grades WHERE grading_run_id=%s GROUP BY 1,2",
                          (run_id,)).fetchall()
    assert grades == [("graded", True, 2 * len(goldens))]
    assert conn.execute("SELECT finished_at IS NOT NULL FROM sa_grading_runs WHERE grading_run_id=%s",
                        (run_id,)).fetchone() == (True,)
    assert conn.execute("SELECT count(*) FROM sa_jobs WHERE kind='analyze' AND payload->>'grading_run_id'=%s",
                        (str(run_id),)).fetchone() == (1,)
    regrade(conn, exp, run_id)


def check_reads(conn, exp, goldens):
    """저장된 조회의 이름·인자·결과가 골든과 같은지. 서버의 데이터·도구가 어긋나도 여기서 실패합니다."""
    access = {t["name"]: t["access"] for t in read("practice/tool_permissions.json")["tools"]}
    for trial_id, code in conn.execute(
        "SELECT trial_id,code FROM sa_trials JOIN sa_tasks USING(task_id) WHERE experiment_id=%s", (exp,)
    ).fetchall():
        got = conn.execute(
            "SELECT name,tool_args,tool_result FROM sa_spans WHERE trial_id=%s AND kind='tool' ORDER BY seq", (trial_id,)
        ).fetchall()
        want = calls(next(g for g in goldens if g["task_code"] == code))
        assert [(n, a) for n, a, _ in got] == [(s["name"], s["tool_args"]) for s in want], code
        for (name, _, result), s in zip(got, want, strict=True):
            if access.get(name) == "read":
                assert json.loads(result) == json.loads(s["tool_result"]), (code, name)


def regrade(conn, exp, run_id):
    """저장한 기록만으로 새 채점 실행을 해도 조건·채점 결과가 똑같아야 합니다 (모델·도구 호출 없음)."""
    again = conn.execute(
        """INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose)
           SELECT experiment_id,pack_version_id,grader_version,'regrade' FROM sa_grading_runs WHERE grading_run_id=%s
           RETURNING grading_run_id""", (run_id,)
    ).fetchone()[0]
    spans = conn.execute("SELECT count(*) FROM sa_spans").fetchone()
    grade(conn, again, classify=by_rules)
    assert conn.execute("SELECT count(*) FROM sa_spans").fetchone() == spans
    for query in (
        "SELECT trial_id,answer_condition_id,passed,evidence FROM sa_condition_results WHERE grading_run_id=%s ORDER BY 1,2",
        "SELECT trial_id,success,result_class,forbidden_action,metrics FROM sa_trial_grades WHERE grading_run_id=%s ORDER BY 1",
    ):
        assert conn.execute(query, (run_id,)).fetchall() == conn.execute(query, (again,)).fetchall()


def python_with_mcp():
    if importlib.util.find_spec("mcp"):
        return sys.executable
    for name in ("Scripts/python.exe", "bin/python"):
        path = ROOT / "backend/.venv" / name
        # 파일만 있고 패키지가 없을 수 있어 실제로 불러 봅니다.
        if path.exists() and not subprocess.run([path, "-c", "import mcp"], capture_output=True).returncode:
            return str(path)
    pytest.skip("연습 서버를 띄울 mcp 패키지가 없습니다 (backend 에서 uv sync).")


def test_practice_server_to_grading(engine_db, pack_id):
    """②의 실제 연습 서버 → 엔진 → DB → 규칙 채점 → 재채점. 서버가 지원하는 유형 전부."""
    goldens = [success(t) for t in SERVED]
    names = {t["name"] for t in read("practice/servers.json")["services"][0]["tools"]} | {"post_message", "create_issue"}
    with psycopg.connect(engine_db, autocommit=True) as conn:
        exp = create_experiment(conn, pack_id, goldens, names)
        server = LocalStdioConfig({"github": [python_with_mcp(), "-u", str(PACK / "practice/server.py")]},
                                  timeout_sec=10, startup_timeout_sec=30)
        run_id = run_experiment(engine_db, exp, goldens, stdio=server)
        check_results(conn, exp, run_id, goldens)
        check_reads(conn, exp, goldens)


def test_pilot_types_to_grading(engine_db, pack_id):
    """파일럿 15유형을 DB 흐름 전체로. 쓰기·승인은 골든에 적힌 값이 아니라 write_proxy 가 만든 값입니다."""
    goldens = [success(t) for t in PILOT]
    assert len(goldens) == 15
    names = {s["name"] for g in goldens for s in calls(g)} - BUILTIN_NAMES
    with psycopg.connect(engine_db, autocommit=True) as conn:
        exp = create_experiment(conn, pack_id, goldens, names)
        run_id = run_experiment(engine_db, exp, goldens)
        check_results(conn, exp, run_id, goldens)
        check_reads(conn, exp, goldens)
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            trials = cur.execute("SELECT * FROM sa_trials WHERE experiment_id=%s", (exp,)).fetchall()
        traces = [load_trace(conn, t) for t in trials]
        confirmed = [w["user_confirmed"] for t in traces for w in t["write_intents"]]
        assert confirmed and all(confirmed)


def replay_all():
    """골든 200개를 엔진에서 다시 실행해 기대와 다른 조건을 모읍니다."""
    prereg, different, unknown, outcomes = load("experiment.json")["prereg"], [], [], Counter()
    base = load("config_snapshot.B.json")
    for golden in GOLDEN:
        task = TASKS[golden["task_code"]]
        names = {s["name"] for s in calls(golden)} - BUILTIN_NAMES
        snap = copy.deepcopy(base)
        snap.pop("tool_search", None)
        snap["tools"] = tool_definitions(names)
        snap["write_tools"] = sorted(t["name"] for t in snap["tools"] if t["access"] == "write")
        snap["runtime"] = {**snap["runtime"], "max_steps": 100}
        model = ByPrompt([golden])
        result = run_agent(snap, task["prompt"], 1, Dependencies(model, model.call_tool),
                           prereg=prereg, confirmation=task.get("confirmation"),
                           write_scenario=task.get("write_scenario"))
        contracts.validate("trace", result.trace)
        outcomes[result.outcome] += 1
        conditions = [{"answer_condition_id": c["seq"], **c} for c in task["conditions"]]
        for r in check_conditions(conditions, result.trace, from_snapshot(snap, task.get("confirmation"))):
            if r.passed is None:
                unknown.append((task["code"], golden["kind"], r.seq, r.undecided))
            elif r.passed != golden["expected"]["conditions"][str(r.seq)]:
                different.append((task["code"], golden["kind"], r.seq))
    return different, unknown, outcomes


def test_all_golden_replayed_by_engine():
    different, unknown, outcomes = replay_all()
    assert outcomes == {"completed": len(GOLDEN)}
    assert not unknown, unknown
    assert not different, different


