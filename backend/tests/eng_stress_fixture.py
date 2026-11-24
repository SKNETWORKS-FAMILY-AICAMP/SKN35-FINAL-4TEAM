"""① 실제 임시 DB에서 가짜 모델 풀이·원자적 저장·오래된 시도 차단을 확인합니다."""

import copy
from uuid import uuid4

import psycopg
import pytest
from conftest import ROOT, load
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from slotagent.common.hashing import agent_spec_hash, canonical_hash
from slotagent.common.snapshot import build_config_snapshot


@pytest.fixture(scope="module")
def engine_db(pg):
    """기존 통합 검사의 전역 집계와 섞이지 않는 별도 임시 DB를 사용합니다."""
    params = conninfo_to_dict(pg)
    name = "eng_core_" + uuid4().hex
    admin_uri = make_conninfo(**{**params, "dbname": "postgres"})
    uri = make_conninfo(**{**params, "dbname": name})
    with psycopg.connect(admin_uri, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(uri, autocommit=True) as conn:
                for path in sorted((ROOT / "backend" / "db" / "migrations").glob("*.sql")):
                    conn.execute(path.read_text(encoding="utf-8"))
            yield uri
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture
def large_experiment(engine_db):
    """① 전용 작은 실험을 만들어 다른 역할의 테스트 데이터와 분리합니다."""
    with psycopg.connect(engine_db, autocommit=True) as conn:
        suffix = uuid4().hex[:12]

        def one(query, *values):
            return conn.execute(query, values).fetchone()[0]

        user = one(
            "INSERT INTO sa_users(email,name) VALUES (%s,'엔진 검사') RETURNING user_id", suffix + "@example.test"
        )
        domain = "eng_" + suffix
        conn.execute("INSERT INTO sa_domains(domain_code,name,status) VALUES (%s,'엔진 검사','active')", (domain,))
        av = load("agent_version.json")
        agent = one("INSERT INTO sa_agents(owner_id,name) VALUES (%s,'엔진 검사') RETURNING agent_id", user)
        av_id = one(
            """INSERT INTO sa_agent_versions(agent_id,version_no,connection_type,model_provider,control_level,
                    model,temperature,instructions,spec,spec_hash) VALUES (%s,1,'spec_upload',%s,'C2',%s,%s,%s,%s,%s)
                    RETURNING agent_version_id""",
            agent,
            av["model_provider"],
            av["model"],
            av["temperature"],
            av["instructions"],
            Jsonb(av["spec"]),
            agent_spec_hash(av["model"], av["temperature"], av["instructions"], av["spec"]),
        )
        slot = one(
            """INSERT INTO sa_slots(agent_version_id,name,service,access,comparable)
                      VALUES (%s,'GitHub 조회','github','read',true) RETURNING slot_id""",
            av_id,
        )
        base = load("slot_and_candidates.json")["candidates"][0]["component_spec"]
        candidates = []
        for label in ["A", "B"]:
            candidates.append(
                one(
                    """INSERT INTO sa_candidates(slot_id,label,name,component_kind,component_spec,spec_hash,is_baseline)
                                    VALUES (%s,%s,%s,'tool_bundle',%s,%s,%s) RETURNING candidate_id""",
                    slot,
                    label,
                    label,
                    Jsonb(base),
                    canonical_hash(base),
                    label == "A",
                )
            )
        pack = one(
            """INSERT INTO sa_pack_versions(domain_code,pack_code,version,premises)
                      VALUES (%s,%s,'v1',%s) RETURNING pack_version_id""",
            domain,
            "eng_" + suffix,
            Jsonb(load("pack.json")["pack_version"]["premises"]),
        )
        conn.execute(
            """INSERT INTO sa_data_snapshots(pack_version_id,source_kind,location,content_hash,frozen_at)
                        VALUES (%s,'repo','fake://engine',%s,now())""",
            (pack, canonical_hash({"engine": suffix})),
        )
        template = one(
            """INSERT INTO sa_templates(pack_version_id,code,question_pattern,is_representative,split,required_capabilities)
                         VALUES (%s,'T2','열린 이슈 조회',false,'held','["github.issues.read"]') RETURNING template_id""",
            pack,
        )
        task_data = next(t for t in load("pack.json")["tasks"] if t["code"] == "T2-0")
        task = one(
            """INSERT INTO sa_tasks(template_id,code,prompt,slot_values,seed)
                     VALUES (%s,'T2-0',%s,%s,%s) RETURNING task_id""",
            template,
            task_data["prompt"],
            Jsonb(task_data["slot_values"]),
            task_data["seed"],
        )
        tasks = [task]
        for index in range(1, 50):
            tasks.append(
                one(
                    """INSERT INTO sa_tasks(template_id,code,prompt,slot_values,seed)
                SELECT template_id,%s,prompt,slot_values,seed FROM sa_tasks WHERE task_id=%s RETURNING task_id""",
                    f"T2-{index}",
                    task,
                )
            )
        conn.execute("UPDATE sa_pack_versions SET status='locked',locked_at=now() WHERE pack_version_id=%s", (pack,))
        source = load("experiment.json")
        plan = copy.deepcopy(source["plan"])
        plan["tasks"] = [{"task_id": task_id, "batch_no": 1} for task_id in tasks]
        exp = one(
            """INSERT INTO sa_experiments(kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by)
                    VALUES ('compare',%s,%s,%s,1,%s,%s,100,%s) RETURNING experiment_id""",
            av_id,
            slot,
            pack,
            Jsonb(source["prereg"]),
            Jsonb(plan),
            user,
        )
        for label, candidate in zip(["A", "B"], candidates, strict=True):
            snap, digest = build_config_snapshot(conn, candidate)
            conn.execute(
                """INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash,template_scope)
                            VALUES (%s,%s,%s,%s,%s,%s,'{"T2":"in_scope"}')""",
                (exp, candidate, label, "baseline" if label == "A" else "candidate", Jsonb(snap), digest),
            )
        conn.execute(
            """INSERT INTO sa_settings(scope,scope_ref,key,value) VALUES ('global','',%s,%s)""",
            ("price." + av["model"], Jsonb({"in_per_1k_krw": 1, "out_per_1k_krw": 2})),
        )
        assert one("SELECT lock_experiment(%s)", exp) == 100
        trials = [
            r[0]
            for r in conn.execute("SELECT trial_id FROM sa_trials WHERE experiment_id=%s ORDER BY trial_id", (exp,))
        ]
        yield conn, {"experiment": exp, "trials": trials, "seed": task_data["seed"]}
