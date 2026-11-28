"""① SlotAgent MCP 서버 (stdio). ④ chatbot 함수 5개(contracts/schemas/chat.schema.json)를 같은 모양으로 엽니다.

실행: uv run python -m slotagent.mcp_server.server   (backend/ 에서, DATABASE_URL 필요)

- 인자 검사는 validate('chat', args, part=도구 이름). 값은 DB·기존 API 함수에서 읽기만 하고 숫자를 만들지 않습니다.
- 상태를 바꾸는 start_run·create_experiment 는 두 번 부릅니다. 처음엔 요약·예상 비용과 confirm_token 만 돌려주고,
  사용자가 확인한 뒤 같은 인자 + confirm_token 으로 다시 불러야 실행합니다 (FR-BOT-03).
- 뒤쪽이 아직 없는 함수(③ sample_size, ④ create_experiment_draft)는 not_ready 오류를 돌려줍니다.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from decimal import Decimal
from functools import partial

import psycopg
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from slotagent.api import eng_errors, eng_experiments, eng_plan_proposal
from slotagent.api.eng_app import GENERIC, MESSAGES
from slotagent.common import contracts, db
from slotagent.common.checks import CheckError
from slotagent.common.hashing import canonical_hash
from slotagent.engine.advance import final_analysis_id
from slotagent.engine.lock import lock_and_enqueue
from slotagent.intake import service

VERSION = "0.1.0"
CONFIRMED = {"start_run", "create_experiment"}  # chat_messages CHECK 와 같은 목록
NUMBERS = "숫자는 DB 에 저장된 값 그대로입니다. 답에 쓸 때 바꾸거나 새로 계산하지 말고 근거 실험 ID 를 같이 적으세요."
DESCRIPTIONS = {
    "get_results": "실험의 진행 상태, 최신 분석의 비교·판정, 리포트 내용을 DB 에서 읽어 돌려줍니다. " + NUMBERS,
    "create_experiment": "실험 초안을 만듭니다 (POST /api/experiments 와 같은 인자). confirm_token 없이 부르면 요약만 "
    "돌려줍니다. 요약을 사용자에게 보여 주고 확인받은 뒤에만 confirm_token 을 넣어 다시 부르세요.",
    "calc_sample_size": "필요한 문항 수·계획 제안을 계산합니다 (POST /api/experiments/plan-proposal 과 같은 인자). 저장하지 않습니다.",
    "start_run": "실험 실행을 시작합니다. confirm_token 없이 부르면 풀이 수·예산·예상 비용 요약만 돌려줍니다. "
    "요약을 사용자에게 보여 주고 확인받은 뒤에만 confirm_token 을 넣어 다시 부르세요.",
    "write_report": "저장된 리포트 내용을 돌려줍니다. 받은 쪽이 audience(manager·developer)에 맞게 쉬운 말로 다시 쓰되 " + NUMBERS,
}
TOKEN = {"type": "string", "description": "요약 단계에서 받은 값. 사용자 확인 뒤에만 넣음"}


class NotReady(Exception):
    pass


def _inline(schema, resolver, depth=0):
    """클라이언트가 $ref 를 못 풀 수 있어 계약 스키마를 펼쳐서 보여 줍니다 (검사는 contracts.validate 가 함)."""
    if depth > 40:
        raise ValueError("계약 스키마가 너무 깊습니다")
    if isinstance(schema, list):
        return [_inline(s, resolver, depth + 1) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        found = resolver.lookup(schema["$ref"])
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        return {**_inline(found.contents, found.resolver, depth + 1), **_inline(rest, resolver, depth + 1)}
    return {k: _inline(v, resolver, depth + 1) for k, v in schema.items() if k not in ("$schema", "$id", "$defs")}


def input_schema(name: str) -> dict:
    resolver = contracts._registry().resolver(contracts.BASE + "chat.schema.json")
    schema = _inline({"$ref": f"#/$defs/{name}"}, resolver)
    if name in CONFIRMED:
        schema["properties"] = {**schema["properties"], "confirm_token": TOKEN}
    return schema


def tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=text,
            inputSchema=input_schema(name),
            annotations=types.ToolAnnotations(
                readOnlyHint=name not in CONFIRMED, destructiveHint=False, idempotentHint=True, openWorldHint=False
            ),
        )
        for name, text in DESCRIPTIONS.items()
    ]


def _one(conn, sql, params):
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else dict(zip([c.name for c in cur.description], row, strict=True))


def _all(conn, sql, params):
    cur = conn.execute(sql, params)
    names = [c.name for c in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def get_results(conn, args: dict) -> dict:
    exp = args["experiment_id"]
    state = eng_experiments.status(conn, exp)
    # 끝난 실험은 종료 게이트와 같은 최종 분석(리포트 2종 있음). latest(max)는 리포트 없는 재채점일 수 있음
    analysis_id = final_analysis_id(conn, exp) if state["status"] == "done" else state["latest_analysis_id"]
    analysis = None
    if analysis_id is not None:
        analysis = _one(
            conn,
            "SELECT analysis_id, grading_run_id, is_interim, batch_no, created_at FROM sa_analyses WHERE analysis_id=%s",
            (analysis_id,),
        )
        analysis["comparisons"] = _all(
            conn,
            """SELECT c.comparison_id, c.metric, ec.label AS candidate, eb.label AS baseline, c.diff, c.ci_low, c.ci_high,
                      c.ci_level, c.p_value, c.n_tasks, c.n_templates, c.regression_rate, c.verdict, c.reason,
                      c.extra_needed, c.exclusions
               FROM sa_comparisons c
               JOIN sa_experiment_candidates ec ON ec.experiment_candidate_id=c.exp_candidate_id
               JOIN sa_experiment_candidates eb ON eb.experiment_candidate_id=c.baseline_id
               WHERE c.analysis_id=%s ORDER BY c.comparison_id""",
            (analysis_id,),
        )
    reports = _all(
        conn,
        """SELECT report_id, kind, created_at, content FROM sa_reports
           WHERE experiment_id=%s AND analysis_id=%s ORDER BY report_id""",
        (exp, analysis_id),
    )
    return {"experiment_id": exp, "cited_experiment_ids": [exp], "status": state, "analysis": analysis,
            "reports": reports, "note": NUMBERS}


def write_report(conn, args: dict) -> dict:
    row = _one(conn, "SELECT report_id, experiment_id, kind, content FROM sa_reports WHERE report_id=%s",
               (args["report_id"],))
    if row is None:
        raise CheckError("not_found", ["리포트가 없습니다."])
    return {**row, "audience": args.get("audience", "manager"), "cited_experiment_ids": [row["experiment_id"]],
            "note": NUMBERS}


def calc_sample_size(conn, args: dict) -> dict:
    return eng_plan_proposal.handle(conn, args)


def _run_preview(conn, args: dict) -> dict:
    state = eng_experiments.status(conn, args["experiment_id"])
    plan = conn.execute("SELECT plan->'estimate' FROM sa_experiments WHERE experiment_id=%s",
                        (args["experiment_id"],)).fetchone()[0]
    return {"status": state["status"], "trials_total": state["trials_total"], "budget_krw": state["budget_krw"],
            "cost_krw_so_far": state["cost_krw"], "estimate": plan}


def _create_preview(_conn, args: dict) -> dict:
    return {"reps": args.get("reps"), "budget_krw": args.get("budget_krw"), "candidates": len(args.get("candidates", [])),
            "tasks": len(args.get("plan", {}).get("tasks", [])), "estimate": args.get("plan", {}).get("estimate")}


def start_run(conn, args: dict) -> dict:
    return lock_and_enqueue(conn, args["experiment_id"])


def create_experiment(conn, args: dict) -> dict:
    user = os.environ.get("SLOTAGENT_USER_ID")
    if not user:
        raise NotReady("SLOTAGENT_USER_ID 가 없어 실험을 만든 사람을 정할 수 없습니다.")
    return {"experiment_id": service.create_experiment_draft(conn, args, int(user))}


READ = {"get_results": get_results, "write_report": write_report, "calc_sample_size": calc_sample_size}
WRITE = {"start_run": (_run_preview, start_run), "create_experiment": (_create_preview, create_experiment)}


def call(conn, name: str, arguments: dict) -> dict:
    """도구 한 번. 오류는 CheckError·ContractError·NotReady·psycopg.Error 로 올립니다."""
    if name not in DESCRIPTIONS:
        raise CheckError("not_found", [f"없는 도구입니다: {name}"])
    args = dict(arguments)
    token = args.pop("confirm_token", None) if name in CONFIRMED else None
    contracts.validate("chat", args, part=name)
    if name in READ:
        return READ[name](conn, args)
    preview_fn, run = WRITE[name]
    preview = preview_fn(conn, args)
    expected = canonical_hash({"tool": name, "args": args, "preview": preview})
    if token != expected:
        return {"needs_confirmation": True, "stale_token": token is not None, "preview": preview,
                "confirm_token": expected,
                "next": "이 요약을 사용자에게 보여 주고, 사용자가 확인하면 같은 인자에 confirm_token 을 넣어 다시 부르세요."}
    return {"confirmed": True, "result": run(conn, args)}


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def error_body(exc: Exception) -> dict:
    if isinstance(exc, CheckError):
        return {"code": exc.code, "message": "; ".join(exc.errors)}
    if isinstance(exc, contracts.ContractError):
        return {"code": "invalid_spec", "message": "; ".join(exc.errors[:5])}
    if isinstance(exc, NotImplementedError):
        return {"code": "not_ready", "message": "아직 준비되지 않은 기능입니다 (뒤쪽 함수가 구현되지 않음)."}
    if isinstance(exc, NotReady):
        return {"code": "not_ready", "message": str(exc)}
    if isinstance(exc, psycopg.Error):
        code = eng_errors.to_api_code(exc)
        return {"code": code, "message": MESSAGES.get(code, GENERIC)}  # DB 원문에는 값이 섞일 수 있어 보내지 않음
    if isinstance(exc, db.DatabaseConfigurationError):
        return {"code": "internal", "message": "DATABASE_URL 이 없거나 형식이 올바르지 않습니다."}
    return {"code": "internal", "message": GENERIC}


def _text(obj, error=False) -> types.CallToolResult:
    text = json.dumps(obj, ensure_ascii=False, default=_plain)
    return types.CallToolResult(isError=error, content=[types.TextContent(type="text", text=text)])


def build(connect=None) -> Server:
    connect = connect or partial(db.connect, autocommit=True)

    async def list_tools(context, params):
        return types.ListToolsResult(tools=tools())

    def work(name, arguments):
        with connect() as conn:
            return call(conn, name, arguments)

    async def call_tool(context, params):
        try:
            return _text(await asyncio.to_thread(work, params.name, params.arguments or {}))
        except Exception as exc:  # 어떤 오류든 정해진 모양으로만 돌려줌
            return _text(error_body(exc), error=True)

    return Server("slotagent", version=VERSION, on_list_tools=list_tools, on_call_tool=call_tool)


async def serve() -> None:
    server = build()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(serve())
