"""contracts/examples 중 '만들어지는' 값을 다시 만든다.
- config_snapshot.B.json (build_config_snapshot 결과)
- experiment.json 의 plan.proposal (저장된 실험 = 서버가 채운 칸, 3차 5)
- api_and_jobs.json 의 create 요청 proposal = {request, as_of} (plan-proposal 요청·응답과 같게)

    uv run --no-project -p 3.12 --with jsonschema python scripts/make_examples.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from slotagent.common.proposal import proposed_values, record  # noqa: E402
from slotagent.common.snapshot import merge_snapshot  # noqa: E402

EX = ROOT / "contracts" / "examples"
load = lambda n: json.loads((EX / n).read_text(encoding="utf-8"))  # noqa: E731
dump = lambda n, d: (EX / n).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")  # noqa: E731

av = load("agent_version.json")
sc = load("slot_and_candidates.json")
dump("config_snapshot.B.json", merge_snapshot(av, sc["slot"], sc["candidates"][1]))

aj = load("api_and_jobs.json")
req, resp = aj["api.plan_proposal_request"], aj["api.plan_proposal_response"]
aj["api.create_experiment_request"]["proposal"] = {"request": req, "as_of": resp["as_of"]}
dump("api_and_jobs.json", aj)

# 저장된 실험 예시: experiment.json 의 값이 곧 제안 그대로라고 침 (edited = false)
ex = load("experiment.json")
plan = {k: v for k, v in ex["plan"].items() if k != "proposal"}
saved = {"prereg": ex["prereg"], "plan": plan, "reps": ex["reps"], "budget_krw": ex["budget_krw"], "candidates": ex["candidates"]}
ex_req = dict(req, reps=ex["reps"], budget_krw=ex["budget_krw"], candidate_ids=ex["candidates"])
ex_resp = {"prereg": ex["prereg"], "plan": plan, "reps": ex["reps"]}
ex["plan"] = dict(plan, proposal=record(ex_req, resp["as_of"], proposed_values(ex_req, ex_resp), saved))
dump("experiment.json", ex)
print("wrote config_snapshot.B.json, experiment.json, api_and_jobs.json")
