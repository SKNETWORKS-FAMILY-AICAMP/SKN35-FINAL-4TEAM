"""① SlotAgent MCP 서버: 도구 5개, 저장된 결과 그대로 조회, 잘못된 인자·확인 없는 실행 거절."""

import asyncio
import json
import os
import pathlib
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from test_eng_advance_idempotency import analysis
from test_eng_api import draft as draft
from test_eng_completion import grading, ready, report
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import contracts
from slotagent.common.checks import CheckError
from slotagent.engine import advance
from slotagent.mcp_server import server

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
NAMES = {"get_results", "create_experiment", "calc_sample_size", "start_run", "write_report"}


def finished(experiment):
    """분석·비교·리포트가 저장된 실험."""
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    base, cand = conn.execute(
        """SELECT experiment_candidate_id FROM sa_experiment_candidates WHERE experiment_id=%s
           ORDER BY role='baseline' DESC, experiment_candidate_id""",
        (ids["experiment"],),
    ).fetchall()
    conn.execute(
        """INSERT INTO sa_comparisons(analysis_id,exp_candidate_id,baseline_id,metric,diff,ci_low,ci_high,ci_level,
                                      p_value,n_tasks,n_templates,verdict,reason,exclusions)
           VALUES (%s,%s,%s,'success_rate',0.125,-0.05,0.3,0.95,0.21,8,4,'reject','검사',%s)""",
        (an, cand[0], base[0], Jsonb({"by_reason": {}, "by_candidate": {}, "templates_left": 4, "coverage": {}})),
    )
    return conn, ids["experiment"], an


def test_tools_match_chat_contract():
    tools = {t.name: t for t in server.tools()}
    assert set(tools) == NAMES == set(contracts._registry().contents(contracts.BASE + "chat.schema.json")["$defs"])
    assert "$ref" not in json.dumps([t.input_schema for t in tools.values()])
    assert {n for n, t in tools.items() if not t.annotations.read_only_hint} == {"start_run", "create_experiment"}


def test_get_results_returns_stored_values(experiment):
    conn, exp, an = finished(experiment)
    out = server.call(conn, "get_results", {"experiment_id": exp})
    assert out["cited_experiment_ids"] == [exp] and out["analysis"]["analysis_id"] == an
    assert out["status"]["latest_analysis_id"] == an
    (c,) = out["analysis"]["comparisons"]
    assert (c["metric"], float(c["diff"]), float(c["p_value"]), c["verdict"]) == ("success_rate", 0.125, 0.21, "reject")
    assert sorted(r["kind"] for r in out["reports"]) == ["detail", "one_pager"]
    rep = server.call(conn, "write_report", {"report_id": out["reports"][0]["report_id"]})
    assert (rep["experiment_id"], rep["audience"], rep["content"]) == (exp, "manager", {})


def test_done_experiment_reads_final_analysis_not_latest(experiment):
    """끝난 실험에 리포트 없는 재채점 분석이 더 최신이어도 리포트 2종이 있는 최종 분석을 보여 줌."""
    conn, exp, an = finished(experiment)
    ids = experiment[1]
    assert advance.on_reports_done(conn, exp) == []
    newer = analysis(conn, ids, grading(conn, ids, regrade=True))
    out = server.call(conn, "get_results", {"experiment_id": exp})
    assert out["status"]["status"] == "done" and out["status"]["latest_analysis_id"] == newer > an
    assert out["analysis"]["analysis_id"] == an and sorted(r["kind"] for r in out["reports"]) == ["detail", "one_pager"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_results", {}),
        ("get_results", {"experiment_id": "1"}),
        ("get_results", {"experiment_id": 1, "sql": "SELECT 1"}),
        ("write_report", {"report_id": 1, "audience": "everyone"}),
        ("get_results", {"experiment_id": 1, "confirm_token": "x"}),
    ],
)
def test_bad_args_refused(name, args):
    with pytest.raises(contracts.ContractError):
        server.call(None, name, args)


def test_unknown_tool_and_missing_rows(experiment):
    conn, _ = experiment
    with pytest.raises(CheckError) as e:
        server.call(conn, "run_sql", {})
    assert e.value.code == "not_found"
    for name, args in [("get_results", {"experiment_id": 2**62}), ("write_report", {"report_id": 2**62})]:
        with pytest.raises(CheckError) as e:
            server.call(conn, name, args)
        assert e.value.code == "not_found"


def test_start_run_needs_confirmation(draft):
    conn, exp = draft
    first = server.call(conn, "start_run", {"experiment_id": exp})
    assert first["needs_confirmation"] and first["preview"]["status"] == "draft"
    assert first["preview"]["trials_total"] == 2
    wrong = server.call(conn, "start_run", {"experiment_id": exp, "confirm_token": "0" * 64})
    assert wrong["needs_confirmation"] and wrong["stale_token"]
    assert conn.execute("SELECT status FROM sa_experiments WHERE experiment_id=%s", (exp,)).fetchone()[0] == "draft"
    done = server.call(conn, "start_run", {"experiment_id": exp, "confirm_token": first["confirm_token"]})
    assert done == {"confirmed": True, "result": {"experiment_id": exp, "status": "running", "trials_total": 2}}
    # 상태가 바뀐 뒤 옛 확인값은 다시 쓸 수 없음
    again = server.call(conn, "start_run", {"experiment_id": exp, "confirm_token": first["confirm_token"]})
    assert again["needs_confirmation"]


def test_unbuilt_backends_say_not_ready(experiment, monkeypatch):
    conn, _ = experiment
    req = {"agent_version_id": 1, "slot_id": 1, "pack_version_id": 1, "candidate_ids": [1, 2]}
    assert not contracts.errors("api", req, part="plan_proposal_request")
    # propose 본체는 test_eng_proposal 이 봄. 여기서는 ③ sample_size 가 아직 없을 때 MCP 가 not_ready 로 바꾸는지만
    monkeypatch.setattr(server.eng_plan_proposal, "propose", lambda *_: (_ for _ in ()).throw(NotImplementedError()))
    with pytest.raises(NotImplementedError) as e:
        server.call(conn, "calc_sample_size", req)
    assert server.error_body(e.value)["code"] == "not_ready"
    monkeypatch.delenv("SLOTAGENT_USER_ID", raising=False)
    with pytest.raises(server.NotReady):
        server.create_experiment(conn, {})


def test_stdio_lists_tools_and_reads_results(experiment, engine_db):
    conn, exp, an = finished(experiment)
    o = conninfo_to_dict(engine_db)
    url = f"postgresql://{o['user']}@{o['host']}:{o['port']}/{o['dbname']}"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(SRC)}

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "slotagent.mcp_server.server"], env=env)
        async with stdio_client(params) as streams, ClientSession(*streams, read_timeout_seconds=30) as session:
            await session.initialize()
            listed = await session.list_tools()
            ok = await session.call_tool("get_results", {"experiment_id": exp})
            bad = await session.call_tool("get_results", {"experiment_id": "x"})
            return {t.name for t in listed.tools}, ok, bad

    names, ok, bad = asyncio.run(run())
    assert names == NAMES
    assert not ok.is_error and json.loads(ok.content[0].text)["analysis"]["analysis_id"] == an
    assert bad.is_error and json.loads(bad.content[0].text)["code"] == "invalid_spec"
