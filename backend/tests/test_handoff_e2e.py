"""1 → 7 단계를 예시 데이터로 실제 DB에 끝까지 넣어 본다.

각 단계는 '그 역할이 할 일'만 하고, 다음 단계는 앞 단계가 DB에 남긴 것만 읽는다.
이 테스트가 통과하면 역할 사이 이음매(테이블 + 스키마)가 맞는다는 뜻.

이야기 (contracts/examples/grading_analysis_report.json _note):
  A(조회 4개) 는 T1-1 에서 틀림(작업 단계 조회가 없음), B(3개) 는 list_issues 를 빼서 T2 가 도구 범위 밖. 둘 다 4/6.
"""
import json

import psycopg
import pytest
from psycopg.types.json import Jsonb

from conftest import ROOT, load
from slotagent.api.eng_errors import to_api_code
from slotagent.common import db_names, checks, contracts, proposal
from slotagent.common.hashing import agent_spec_hash, canonical_hash
from slotagent.common.snapshot import HARNESS_VERSION, build_config_snapshot, trial_seed
from slotagent.engine import advance


def one(cur, sql, *args):
    return cur.execute(sql, args).fetchone()[0]


def rejected(conn, sql, *args):
    """막히면 api.error code 를 돌려줌 (막히지 않으면 None)."""
    try:
        with conn.transaction():
            conn.execute(sql, args)
        return None
    except psycopg.errors.Error as e:
        return to_api_code(e)


@pytest.fixture(scope="module")
def conn(pg):
    with psycopg.connect(pg, autocommit=True) as c:
        yield c


@pytest.fixture(scope="module")
def ids():
    return {}


# ---- 0. 이름 규칙 (backend/db/README.md): 테이블·뷰 sa_, PK <단수>_id, FK = 가리키는 PK, 나머지 짧은 이름 ----
def test_0_naming(conn):
    rels = conn.execute("""SELECT table_name, table_type FROM information_schema.tables
                           WHERE table_schema = 'public'""").fetchall()
    assert rels and all(name.startswith("sa_") for name, _ in rels), [n for n, _ in rels if not n.startswith("sa_")]
    pks = dict(conn.execute("""SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc
                               JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name
                              WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'""").fetchall())
    wrong = {t: c for t, c in pks.items() if c != db_names.PK[t[3:]]}   # PK = <테이블 단수>_id (domains 는 domain_code)
    assert not wrong, wrong
    assert len(pks) == sum(1 for _, kind in rels if kind == "BASE TABLE") == 33
    # FK 칸: 가리키는 PK 이름 그대로, 아니면 역할 이름 (같은 테이블을 두 번·역할 이름) — 그 목록은 db/README.md
    fks = conn.execute("""SELECT kcu.table_name, kcu.column_name, ccu.table_name, ccu.column_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name
                            JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
                           WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'""").fetchall()
    role_fk = {("sa_agents", "owner_id"), ("sa_experiments", "derived_from"), ("sa_experiments", "created_by"),
               ("sa_labels", "labeler_id"), ("sa_comparisons", "exp_candidate_id"), ("sa_comparisons", "baseline_id"),
               ("sa_cost_ledger", "price_setting_id"), ("sa_env_checks", "checked_by"), ("sa_task_exposures", "seen_by")}
    bad_fk = [f for f in fks if f[1] != f[3] and (f[0], f[1]) not in role_fk]
    assert fks and not bad_fk, bad_fk
    # 나머지 칸: 접두사 없이 db_names 표에 있는 이름 그대로, PK·FK 아닌 칸이 다른 테이블 PK 이름을 쓰지 않음
    cols = conn.execute("""SELECT table_name, column_name FROM information_schema.columns c
                            JOIN information_schema.tables t USING (table_schema, table_name)
                           WHERE table_schema = 'public' AND t.table_type = 'BASE TABLE'""").fetchall()
    known = {(f"sa_{t}", c) for t, m in db_names.COLUMNS.items() for c in m.values()}
    assert not [x for x in cols if x not in known], [x for x in cols if x not in known]
    fk_cols = {(t, c) for t, c, _, _ in fks}
    pk_names = set(db_names.PK.values())
    assert not [(t, c) for t, c in cols if c in pk_names and c != pks[t] and (t, c) not in fk_cols]


# ---- 1. ④ 에이전트·자리·후보 등록 --------------------------------------
def test_1_intake(conn, ids):
    cur = conn.cursor()
    user = one(cur, "INSERT INTO sa_users(email, name) VALUES ('dev@example.test', '개발자') RETURNING user_id")
    cur.execute("INSERT INTO sa_domains(domain_code, name, status) VALUES ('it_ops', 'IT 운영', 'active')")
    for f in sorted((ROOT / "backend" / "db" / "seeds").glob("*.sql")):            # 기본값 (settings)
        cur.execute(f.read_text(encoding="utf-8"))
    for key, value in cur.execute("SELECT key, value FROM sa_settings").fetchall():   # 시드 값도 settings 스키마 (3차 2)
        contracts.validate("settings", value, part="price" if key.startswith("price.") else key)
    av = load("agent_version.json")
    agent = one(cur, "INSERT INTO sa_agents(owner_id, name, expected_monthly_calls, domain_code) VALUES (%s, %s, %s, %s) RETURNING agent_id",
                user, av["_agent"]["name"], av["_agent"]["expected_monthly_calls"], av["_agent"]["domain_code"])
    spec = contracts.validate("agent_spec", av["spec"])
    av_id = one(cur, """INSERT INTO sa_agent_versions(agent_id, version_no, connection_type, questions_used, control_level, model, temperature,
                         instructions, spec, spec_hash) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING agent_version_id""",
                agent, av["connection_type"], av["questions_used"], av["control_level"], av["model"], av["temperature"], av["instructions"],
                Jsonb(spec), agent_spec_hash(av["model"], av["temperature"], av["instructions"], spec))
    sc = load("slot_and_candidates.json")
    s = sc["slot"]
    slot = one(cur, "INSERT INTO sa_slots(agent_version_id, name, service, access, comparable) VALUES (%s,%s,%s,%s,%s) RETURNING slot_id",
               av_id, s["name"], s["service"], s["access"], s["comparable"])
    cands = {}
    for c in sc["candidates"]:
        comp = contracts.validate("component_spec", c["component_spec"])
        checks.check_component(comp, s)
        if c["is_baseline"]:
            checks.check_baseline(comp, spec, s)                          # 기준 = agent_spec 그대로
        cands[c["label"]] = one(cur, """INSERT INTO sa_candidates(slot_id, label, name, component_kind, component_spec, spec_hash, is_baseline)
                                        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING candidate_id""",
                                slot, c["label"], c["name"], c["component_kind"], Jsonb(comp), canonical_hash(comp), c["is_baseline"])
    ids.update(user=user, av=av_id, slot=slot, cand=cands, cand_by_example={c["id"]: cands[c["label"]] for c in sc["candidates"]})

    # ④가 막아야 하는 경우 — DB 오류가 문구가 아니라 code 로 나오는지 (검토 20)
    assert rejected(conn, "INSERT INTO sa_candidates(slot_id,label,name,component_spec,spec_hash,is_baseline) VALUES (%s,'Z','x','{}','h',true)", slot) == "baseline_exists"
    assert rejected(conn, "INSERT INTO sa_candidates(slot_id,label,name,component_spec,spec_hash) VALUES (%s,'A','x','{}','h')", slot) == "label_taken"
    assert rejected(conn, "UPDATE sa_candidates SET name='고침' WHERE candidate_id=%s", cands["B"]) == "immutable"
    # 질문은 연결 방식이 아님 (11/23) — DB 에서도 막힘. 도구 검색 후보 C 는 위에서 들어감
    assert rejected(conn, """INSERT INTO sa_agent_versions(agent_id, version_no, connection_type, control_level, model, instructions, spec, spec_hash)
                             VALUES (%s, 2, 'questions', 'C2', 'm', 'i', '{}', 'h')""", agent) is not None


# ---- 2. ② 평가팩 만들고 잠그기 -------------------------------------------
def test_2_pack(conn, ids):
    cur = conn.cursor()
    p = load("pack.json")
    pv = p["pack_version"]
    premises = contracts.validate("pack", pv["premises"], part="premises")          # 평가팩 jsonb 도 스키마 (3차 2)
    pack = one(cur, "INSERT INTO sa_pack_versions(domain_code, pack_code, version, premises) VALUES (%s,%s,%s,%s) RETURNING pack_version_id",
               pv["domain_code"], pv["pack_code"], pv["version"], Jsonb(premises))
    for d in p["data_snapshots"]:
        contracts.validate("pack", d["design"], part="data_design")
        cur.execute("""INSERT INTO sa_data_snapshots(pack_version_id, source_kind, location, design, content_hash, frozen_at)
                       VALUES (%s,%s,%s,%s,%s, now())""", (pack, d["source_kind"], d["location"], Jsonb(d["design"]), canonical_hash(d)))
    tmpl = {t["code"]: one(cur, """INSERT INTO sa_templates(pack_version_id, code, question_pattern, is_representative, split)
                                   VALUES (%s,%s,%s,%s,%s) RETURNING template_id""",
                            pack, t["code"], t["question_pattern"], t["is_representative"], t["split"]) for t in p["templates"]}
    tasks, conds, template_of = [], {}, {}
    for t in p["tasks"]:
        checks.check_task_conditions(t["conditions"])
        tid = one(cur, "INSERT INTO sa_tasks(template_id, code, prompt, slot_values, seed) VALUES (%s,%s,%s,%s,%s) RETURNING task_id",
                  tmpl[t["template"]], t["code"], t["prompt"], Jsonb(t["slot_values"]), t["seed"])
        tasks.append(tid)
        template_of[tid] = t["template"]
        for c in t["conditions"]:
            spec = contracts.validate("answer_condition", c["spec"], part=c["kind"])
            conds.setdefault(tid, []).append(one(cur, "INSERT INTO sa_answer_conditions(task_id, seq, kind, spec) VALUES (%s,%s,%s,%s) RETURNING answer_condition_id",
                                                 tid, c["seq"], c["kind"], Jsonb(spec)))
    for g in p["golden"]:
        golden = contracts.validate("trace", load(g["trace"]))
        expected = contracts.validate("pack", g["expected"], part="golden_expected")
        cur.execute("INSERT INTO sa_golden_trajectories(template_id, kind, trace, expected) VALUES (%s,%s,%s,%s)",
                    (tmpl[g["template"]], g["kind"], Jsonb(golden), Jsonb(expected)))
    cur.execute("UPDATE sa_pack_versions SET status='locked', locked_at=now() WHERE pack_version_id=%s", (pack,))
    ids.update(pack=pack, tasks=tasks, conds=conds, template_of=template_of)


# ---- 3. ④ 실험 초안 (값: plan-proposal 응답 = settings·③·②) -----------------
def test_3_experiment_draft(conn, ids):
    cur = conn.cursor()
    ex = load("experiment.json")
    prereg = contracts.validate("prereg", ex["prereg"])
    assert prereg["margin_pp"] == json.loads(json.dumps(advance.latest_setting(conn, "ni_margin_pp")))   # 기본값은 settings
    plan = {k: v for k, v in json.loads(json.dumps(ex["plan"])).items() if k != "proposal"}   # ④가 보내는 plan 엔 proposal 없음
    for item, real in zip(plan["tasks"], ids["tasks"]):   # 예시의 1,2,3 → 실제 문항 id
        item["task_id"] = real
    contracts.validate("plan", plan, part="body")
    checks.check_plan(plan, ids["template_of"], prereg)
    # 서버가 제안을 다시 만들어 비교 (3차 5). propose() 는 아직 본체가 없어 "제안 = 예시 값" 으로 침
    req = dict(ex["plan"]["proposal"]["request"], agent_version_id=ids["av"], slot_id=ids["slot"], pack_version_id=ids["pack"])
    as_of = ex["plan"]["proposal"]["as_of"]
    cands = [ids["cand_by_example"][c] for c in ex["candidates"]]
    req["candidate_ids"] = cands
    proposed = proposal.proposed_values(req, {"prereg": prereg, "plan": plan, "reps": ex["reps"]})
    saved = {"prereg": prereg, "plan": plan, "reps": ex["reps"], "budget_krw": ex["budget_krw"], "candidates": cands}
    plan["proposal"] = proposal.record(req, as_of, proposed, saved)
    assert plan["proposal"]["edited"] is False                                   # 제안 그대로
    fewer = dict(saved, plan=dict(plan, tasks=plan["tasks"][:2]))
    assert proposal.record(req, as_of, proposed, fewer)["edited_fields"] == ["plan.tasks"]   # 고치면 서버가 알아냄
    contracts.validate("plan", plan, part="stored")
    exp = one(cur, """INSERT INTO sa_experiments(kind, agent_version_id, slot_id, pack_version_id, reps, prereg, plan, budget_krw, created_by)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING experiment_id""",
              ex["kind"], ids["av"], ids["slot"], ids["pack"], ex["reps"], Jsonb(prereg), Jsonb(plan), ex["budget_krw"], ids["user"])
    rows = [dict(zip(["id", "slot_id", "label", "is_baseline"], r)) for r in cur.execute(
        "SELECT candidate_id, slot_id, label, is_baseline FROM sa_candidates WHERE candidate_id = ANY(%s)",
        ([ids["cand_by_example"][c] for c in ex["candidates"]],)).fetchall()]
    checks.check_experiment_candidates(rows)
    ec = {}
    for r in rows:                                                          # 역할·label 은 후보 행에서 (검토 32)
        snap, h = build_config_snapshot(conn, r["id"])                      # ①이 준 함수
        ec[r["label"]] = one(cur, """INSERT INTO sa_experiment_candidates(experiment_id, candidate_id, label, role, config_snapshot, config_hash)
                                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING experiment_candidate_id""",
                             exp, r["id"], r["label"], "baseline" if r["is_baseline"] else "candidate", Jsonb(snap), h)
    # 기준이 아닌 후보를 baseline 으로 넣으면 DB 가 막음
    assert rejected(conn, """INSERT INTO sa_experiment_candidates(experiment_id, candidate_id, label, role, config_snapshot, config_hash)
                             VALUES (%s,%s,'B','baseline','{}','h')""", exp, ids["cand"]["B"]) is not None
    ids.update(exp=exp, ec=ec, reps=ex["reps"])


# ---- 4. ① 잠금·실행 -----------------------------------------------------
def test_4_lock_and_run(conn, ids):
    cur = conn.cursor()
    n = one(cur, "SELECT lock_experiment(%s)", ids["exp"])
    assert n == 2 * len(ids["tasks"]) * ids["reps"]                       # 후보 × 문항 × 반복
    assert rejected(conn, "DELETE FROM sa_experiment_candidates WHERE experiment_candidate_id=%s", ids["ec"]["B"]) == "experiment_locked"
    assert rejected(conn, "SELECT lock_experiment(%s)", ids["exp"]) is not None
    advance.mark_running(conn, ids["exp"])
    # jobs.kind 와 payload.kind 가 다르면 막음 (검토 18)
    assert rejected(conn, """INSERT INTO sa_jobs(kind, payload) VALUES ('grade', '{"schema_version":1,"kind":"run_trial","trial_id":1}')""") is not None

    trace = load("trace.json")
    trials = cur.execute("""SELECT t.trial_id, ec.label, k.code, ec.config_snapshot, k.seed, t.rep FROM sa_trials t
                            JOIN sa_experiment_candidates ec ON ec.experiment_candidate_id = t.experiment_candidate_id JOIN sa_tasks k ON k.task_id = t.task_id
                            WHERE t.experiment_id=%s ORDER BY t.trial_id""", (ids["exp"],)).fetchall()
    for tid, label, code, snap, task_seed, rep in trials:
        advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": tid})
        contracts.validate("config_snapshot", snap)                          # 후보 구성은 이것만 보고 실행
        assert advance.check_budget(conn, ids["exp"])
        cur.execute("UPDATE sa_trials SET status='running', started_at=now(), harness_version=%s WHERE trial_id=%s", (HARNESS_VERSION, tid))
        span_id = {}
        for s in trace["spans"]:                                             # spans 먼저 (seq → id)
            attrs = dict(s.get("attributes", {}))
            if s["kind"] == "llm":
                attrs["model.seed"] = trial_seed(task_seed, rep)
            span_id[s["seq"]] = one(cur, """INSERT INTO sa_spans(trial_id, attempt, seq, kind, name, started_at, duration_sec, wait_sec,
                           in_tokens, out_tokens, output, tool_args, tool_result, attributes)
                           VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING span_id""",
                           tid, s["seq"], s["kind"], s.get("name"), s["started_at"], s["duration_sec"], s.get("wait_sec", 0),
                           s.get("in_tokens"), s.get("out_tokens"), s.get("output"),
                           Jsonb(s["tool_args"]) if "tool_args" in s else None, s.get("tool_result"), Jsonb(attrs))
        u = trace["usage"]
        cur.execute("""UPDATE sa_trials SET status='finished', run_outcome='completed', finished_at=now(), final_answer=%s,
                       in_tokens=%s, out_tokens=%s, tool_desc_tokens=%s, cost_krw=%s, llm_sec=%s, tool_sec=%s, wait_sec=%s
                       WHERE trial_id=%s""",
                    (trace["final_answer"], u["in_tokens"], u["out_tokens"], u["tool_desc_tokens"], u["cost_krw"],
                     u["llm_sec"], u["tool_sec"], u["wait_sec"], tid))
        cur.execute("""INSERT INTO sa_cost_ledger(source, ref_id, experiment_id, model, in_tokens, out_tokens, cost_krw)
                       VALUES ('trial', %s, %s, %s, %s, %s, %s)""",
                    (tid, ids["exp"], snap["model"]["name"], u["in_tokens"], u["out_tokens"], u["cost_krw"]))
        gr = advance.on_trial_finished(conn, tid)                           # 마지막 풀이에서만 채점 실행이 생김
        assert (gr is not None) == (tid == trials[-1][0])
        ids["gr"] = gr or ids.get("gr")
        ids.setdefault("last_span", (tid, span_id[2]))
    # 끝난 풀이에는 가짜 쓰기 기록을 붙일 수 없음 (검토 19)
    t0, s0 = ids["last_span"]
    assert rejected(conn, "INSERT INTO sa_write_intents(trial_id, span_id, tool_name, payload, in_rule_list) VALUES (%s,%s,'create_issue','{}',true)",
                    t0, s0) is not None
    # 같은 마지막 풀이를 두 워커가 동시에 끝냈다고 쳐도 채점 실행은 1개 (검토 1)
    assert advance.on_trial_finished(conn, trials[-1][0]) is None
    assert one(cur, "SELECT count(*) FROM sa_grading_runs WHERE experiment_id=%s", ids["exp"]) == 1
    assert one(cur, "SELECT count(*) FROM sa_jobs WHERE kind='grade'") == 1
    ids["trials"] = trials


# ---- 5. ① 규칙 채점 + ② LLM 판정·분류 ----------------------------------
def test_5_grade(conn, ids):
    cur = conn.cursor()
    ex = load("grading_analysis_report.json")
    judge = one(cur, "SELECT judge_settings FROM sa_grading_runs WHERE grading_run_id=%s", ids["gr"])   # ②의 설정이 settings 에서 옴 (검토 2)
    assert judge["votes"] == 3
    contracts.validate("grading", judge, part="judge_settings")
    evidence = contracts.validate("grading", ex["grading.condition_evidence"][0], part="condition_evidence")
    metrics = contracts.validate("grading", ex["grading.trial_metrics"][0], part="trial_metrics")
    task_of = dict(zip(["T1-0", "T1-1", "T2-0"], ids["tasks"]))
    for tid, label, code, *_ in ids["trials"]:
        out_of_scope = label == "B" and code == "T2-0"                     # B 는 list_issues 를 뺌
        ok = not out_of_scope and not (label == "A" and code == "T1-1")
        for cid in ids["conds"][task_of[code]]:
            cur.execute("INSERT INTO sa_condition_results(grading_run_id, trial_id, answer_condition_id, passed, evidence) VALUES (%s,%s,%s,%s,%s)",
                        (ids["gr"], tid, cid, ok, Jsonb(evidence)))
        cur.execute("""INSERT INTO sa_trial_grades(grading_run_id, trial_id, success, result_class, first_fail_type, out_of_scope, metrics)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (ids["gr"], tid, ok, "correct" if ok else ("ask_or_giveup" if out_of_scope else "wrong_assertion"),
                     None if ok or out_of_scope else "info_missing", out_of_scope, Jsonb(metrics)))
    t0 = ids["trials"][0][0]                                               # LLM 투표: 질문 종류는 한 목록 (3차 3)
    cur.execute("""INSERT INTO sa_llm_votes(grading_run_id, trial_id, question_kind, vote_no, model, answer)
                   VALUES (%s,%s,'grounded',1,'gpt-4.1-mini','yes')""", (ids["gr"], t0))
    assert rejected(conn, """INSERT INTO sa_llm_votes(grading_run_id, trial_id, question_kind, vote_no, model, answer)
                             VALUES (%s,%s,'is_good',1,'gpt-4.1-mini','yes')""", ids["gr"], t0) is not None
    cur.execute("UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=%s", (ids["gr"],))
    advance.on_grading_finished(conn, ids["gr"])
    job = one(cur, "SELECT payload FROM sa_jobs WHERE kind='analyze'")
    assert job == {"schema_version": 1, "kind": "analyze", "grading_run_id": ids["gr"], "is_interim": False}
    success = dict(cur.execute("""SELECT ec.label, count(*) FILTER (WHERE g.success) FROM sa_trial_grades g
                                  JOIN sa_trials t ON t.trial_id = g.trial_id JOIN sa_experiment_candidates ec ON ec.experiment_candidate_id = t.experiment_candidate_id
                                  WHERE g.grading_run_id=%s GROUP BY ec.label""", (ids["gr"],)).fetchall())
    assert success == {"A": 4, "B": 4}                                    # 리포트 예시의 4/6 과 같음 (검토 38)


# ---- 6. ③ 분석·판정 -----------------------------------------------------
def test_6_analyze(conn, ids):
    cur = conn.cursor()
    ex = load("grading_analysis_report.json")
    method = contracts.validate("analysis", ex["analysis.method"], part="method")
    checks.check_method(method, load("experiment.json")["prereg"])
    rows = cur.execute("""SELECT g.trial_grade_id, g.success FROM sa_trial_grades g WHERE g.grading_run_id=%s ORDER BY g.trial_grade_id""", (ids["gr"],)).fetchall()
    an = one(cur, """INSERT INTO sa_analyses(experiment_id, grading_run_id, method, code_version, input_hash)
                     VALUES (%s,%s,%s,'test',%s) RETURNING analysis_id""", ids["exp"], ids["gr"], Jsonb(method), canonical_hash(rows))
    # 같은 채점·같은 범위의 분석은 1개 (3차 4)
    assert rejected(conn, """INSERT INTO sa_analyses(experiment_id, grading_run_id, method, code_version, input_hash)
                             VALUES (%s,%s,%s,'test2','h')""", ids["exp"], ids["gr"], Jsonb(method)) is not None
    units = cur.execute("SELECT included, exclude_reason FROM analysis_units(%s, %s)", (ids["gr"], ids["ec"]["B"])).fetchall()
    assert units and all(inc for inc, _ in units)
    excl = contracts.validate("analysis", ex["analysis.exclusions"], part="exclusions")
    extra = contracts.validate("analysis", ex["analysis.extra_needed"], part="extra_needed")
    comp = one(cur, """INSERT INTO sa_comparisons(analysis_id, exp_candidate_id, baseline_id, metric, diff, ci_low, ci_high, ci_level,
                       n_tasks, n_templates, verdict, reason, extra_needed, exclusions)
                       VALUES (%s,%s,%s,'success_rate',0,-0.5,0.5,0.95,3,2,'hold','문항 유형 2개',%s,%s) RETURNING comparison_id""",
               an, ids["ec"]["B"], ids["ec"]["A"], Jsonb(extra), Jsonb(excl))
    # 지표 이름은 한 목록 (검토 13)
    assert rejected(conn, """INSERT INTO sa_comparisons(analysis_id, exp_candidate_id, baseline_id, metric, diff, ci_low, ci_high, ci_level,
                             n_tasks, n_templates, exclusions) VALUES (%s,%s,%s,'cost_per_success',0,0,0,0.95,3,2,%s)""",
                    an, ids["ec"]["B"], ids["ec"]["A"], Jsonb(excl)) is not None
    advance.on_analysis_done(conn, an)
    assert one(cur, "SELECT payload->'report_kinds' FROM sa_jobs WHERE kind='report'") == ["one_pager", "detail"]
    ids.update(an=an, comp=comp)


# ---- 7. 공동 리포트 · ④ chatbot ----------------------------------------
def test_7_report_and_chat(conn, ids):
    cur = conn.cursor()
    b_t2 = next(tid for tid, label, code, *_ in ids["trials"] if label == "B" and code == "T2-0")
    for content in load("grading_analysis_report.json")["report_content"]:
        for e in content["evidence"]:
            if "comparison_id" in e:
                e["comparison_id"] = ids["comp"]
            else:
                e["trial_id"] = b_t2                                        # 풀이가 근거 (검토 26)
        contracts.validate("report_content", content)
        cur.execute("INSERT INTO sa_reports(experiment_id, analysis_id, kind, content) VALUES (%s,%s,%s,%s)",
                    (ids["exp"], ids["an"], content["kind"], Jsonb(content)))
    # 같은 분석·같은 종류의 리포트는 1개 (3차 4)
    assert rejected(conn, "INSERT INTO sa_reports(experiment_id, analysis_id, kind, content) VALUES (%s,%s,'one_pager','{}')",
                    ids["exp"], ids["an"]) is not None
    advance.on_reports_done(conn, ids["exp"])
    args = contracts.validate("chat", {"experiment_id": ids["exp"]}, part="get_results")   # 함수 인자도 스키마 (3차 2)
    cur.execute("""INSERT INTO sa_chat_messages(conversation_id, user_id, role, function_name, function_args, cited_experiment_ids)
                   VALUES (gen_random_uuid(), %s, 'function', 'get_results', %s, ARRAY[%s]::bigint[])""",
                (ids["user"], Jsonb(args), ids["exp"]))
    # 화면이 받는 상태 응답: 계획 단위(후보, 문항, 반복)마다 마지막 실행으로 셈 (검토 31)
    counts = dict(cur.execute("""SELECT status, count(*) FROM (
                                   SELECT DISTINCT ON (experiment_candidate_id, task_id, rep) status FROM sa_trials
                                    WHERE experiment_id=%s ORDER BY experiment_candidate_id, task_id, rep, run_no DESC) last
                                 GROUP BY status""", (ids["exp"],)).fetchall())
    exp_status = one(cur, "SELECT status FROM sa_experiments WHERE experiment_id=%s", ids["exp"])
    status = {"experiment_id": ids["exp"], "status": exp_status, "stop_reason": None, "trials_total": len(ids["trials"]),
              "trials": {k: counts.get(k, 0) for k in ["pending", "running", "finished", "error", "cancelled"]},
              "env_reruns": one(cur, "SELECT count(*) FROM sa_trials WHERE experiment_id=%s AND run_no > 1", ids["exp"]),
              "cost_krw": float(one(cur, "SELECT coalesce(sum(cost_krw),0) FROM sa_cost_ledger WHERE experiment_id=%s", ids["exp"])),
              "budget_krw": 3000, "latest_grading_run_id": ids["gr"], "latest_analysis_id": ids["an"]}
    contracts.validate("api", status, part="status_response")
    assert exp_status == "done"
    assert sum(status["trials"].values()) == status["trials_total"]


# ---- 8. ① 멈춤: 예산 도달 → 대기 풀이 취소 (검토 6) ----------------------
def test_8_budget_stop(conn, ids):
    cur = conn.cursor()
    ex = load("experiment.json")
    plan = {"schema_version": 1, "tasks": [{"task_id": ids["tasks"][0], "batch_no": 1}]}
    req = dict(ex["plan"]["proposal"]["request"], reps=1, budget_krw=1, candidate_ids=list(ids["cand"].values()))
    vals = {"prereg": ex["prereg"], "plan": plan, "reps": 1, "budget_krw": 1, "candidates": list(ids["cand"].values())}
    plan["proposal"] = proposal.record(req, ex["plan"]["proposal"]["as_of"], vals, vals)
    contracts.validate("plan", plan, part="stored")
    exp = one(cur, """INSERT INTO sa_experiments(kind, agent_version_id, slot_id, pack_version_id, reps, prereg, plan, budget_krw, created_by)
                      VALUES ('compare',%s,%s,%s,1,%s,%s,1,%s) RETURNING experiment_id""",
              ids["av"], ids["slot"], ids["pack"], Jsonb(ex["prereg"]), Jsonb(plan), ids["user"])
    for label, cid in ids["cand"].items():
        snap, h = build_config_snapshot(conn, cid)
        cur.execute("""INSERT INTO sa_experiment_candidates(experiment_id, candidate_id, label, role, config_snapshot, config_hash)
                       VALUES (%s,%s,%s,%s,%s,%s)""", (exp, cid, label, "baseline" if label == "A" else "candidate", Jsonb(snap), h))
    cur.execute("SELECT lock_experiment(%s)", (exp,))
    advance.mark_running(conn, exp)
    cur.execute("INSERT INTO sa_cost_ledger(source, experiment_id, model, in_tokens, out_tokens, cost_krw) VALUES ('trial',%s,'m',0,0,1.5)", (exp,))
    assert advance.check_budget(conn, exp) is False
    assert cur.execute("SELECT status, stop_reason FROM sa_experiments WHERE experiment_id=%s", (exp,)).fetchone() == ("stopped", "budget")
    assert one(cur, "SELECT count(*) FROM sa_trials WHERE experiment_id=%s AND status='cancelled'", exp) == len(ids["cand"])   # 후보마다 1문항 × 1회
    # 멈춘 이유는 정해 둔 값만 (2차 검토 5)
    assert rejected(conn, "UPDATE sa_experiments SET stop_reason='돈이 없어서' WHERE experiment_id=%s", exp) is not None
    # 잠긴 실험의 사전 등록은 탐색적 표시를 켜도 바꿀 수 없음 (데이터 약속 v2-1)
    assert rejected(conn, """UPDATE sa_experiments SET exploratory=true,
                             prereg = prereg || '{"margin_pp": 7}' WHERE experiment_id=%s""", exp) == "experiment_locked"
    # 기준을 바꾸려면 원본을 가리키는 새 실험 — 반드시 탐색적
    new_exp = """INSERT INTO sa_experiments(kind, agent_version_id, slot_id, pack_version_id, reps,
                 prereg, plan, budget_krw, created_by, derived_from,
                 exploratory) VALUES ('compare',%s,%s,%s,1,%s,%s,1,%s,%s,%s)"""
    args = (ids["av"], ids["slot"], ids["pack"], Jsonb(dict(ex["prereg"], margin_pp=7)), Jsonb(plan), ids["user"], exp)
    assert rejected(conn, new_exp, *args, False) is not None
    assert rejected(conn, new_exp, *args, True) is None
