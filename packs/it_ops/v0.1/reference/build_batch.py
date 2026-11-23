"""개발 중인 v0.1에 10개 유형 × 3문항을 재현 가능하게 생성한다. 잠금 이후 실행 금지."""

import json

from batch_reference import CODES, PACK_DIR, calculate

TITLES = [
    "지정 기간의 실패 배포 목록", "기준 시간보다 오래 걸린 배포", "날짜별 성공·실패 배포 건수",
    "실패 후 최초 복구 배포", "production·staging 최신 버전 비교", "담당자별 열린 이슈",
    "오래 방치된 미배정 이슈", "지정 기간에 닫힌 이슈", "열린 이슈의 라벨별 건수", "배포 커밋과 릴리스 연결",
]


def build():
    data = {"snapshot_version": "it_ops-operations-v0.1", "runs": [], "issues": [], "releases": []}
    repos = ["acme/payment-service", "acme/catalog-service", "acme/auth-service"]
    for index, repo in enumerate(repos, 1):
        prefix = index * 100
        for offset, environment, status, start, finish, version, sha in [
            (1, "production", "failure", "08:00", "08:10", "v2.0.0", "old"),
            (2, "production", "success", "08:20", "08:25", "v2.0.1", "fix"),
            (3, "production", "success", "10:00", "10:20", f"v2.{index}.0", "latest"),
            (4, "staging", "success", "11:00", "11:03", f"v3.{index}.0-rc1", "staging"),
            (5, "production", "failure", "23:50", "23:59", "v9.0.0", "bad"),
        ]:
            data["runs"].append({"id": str(prefix + offset), "repo": repo, "environment": environment,
                                 "status": status, "started_at": f"2026-11-16T{start}:00+09:00",
                                 "finished_at": f"2026-11-16T{finish}:00+09:00", "version": version,
                                 "sha": f"repo{index}-{sha}"})
        # 기간 종료와 정확히 일치하는 기록: [start, end)에서 제외돼야 한다.
        data["runs"].append({"id": str(prefix + 6), "repo": repo, "environment": "production",
                             "status": "failure", "started_at": "2026-11-16T23:59:00+09:00",
                             "finished_at": "2026-11-16T15:00:00Z", "version": "v9.0.1", "sha": "boundary"})
        for offset, state, assignees, labels, updated, closed in [
            (1, "open", ["mina"], ["bug", "urgent"], "2026-11-15T00:00:00+09:00", None),
            (2, "open", [], ["bug"], "2026-11-01T00:00:00+09:00", None),
            (3, "closed", ["mina"], ["bug"], "2026-11-16T10:00:00+09:00", "2026-11-16T10:00:00+09:00"),
            (4, "open", [], [], "2026-11-10T00:00:00+09:00", None),
            (5, "open", ["jun"], ["urgent"], "2026-11-15T00:00:00+09:00", None),
            (6, "closed", [], ["urgent"], "2026-11-17T00:00:00+09:00", "2026-11-17T00:00:00+09:00"),
        ]:
            data["issues"].append({"id": str(prefix + offset), "repo": repo, "state": state,
                                   "assignees": assignees, "labels": labels, "updated_at": updated,
                                   "closed_at": closed})
        data["releases"].extend([
            {"repo": repo, "sha": f"repo{index}-latest", "tag": f"v2.{index}.0"},
            {"repo": repo, "sha": f"repo{index}-staging", "tag": f"v3.{index}.0-rc1"},
            {"repo": repo, "sha": f"repo{index}-old", "tag": "v2.0.0"},
        ])
    path = PACK_DIR / "pack.json"
    pack = json.loads(path.read_text(encoding="utf-8"))
    pack["templates"] = [t for t in pack["templates"] if t["code"] not in CODES[:10]]
    pack["tasks"] = [t for t in pack["tasks"] if t["template"] not in CODES[:10]]
    pack["data_snapshots"] = [s for s in pack["data_snapshots"] if s["location"] != "data/operations.json"]
    pack["data_snapshots"].append({"source_kind": "repo", "location": "data/operations.json",
                                    "design": {"notes": ["합성 데이터. 세 저장소별 배포·이슈·릴리스 스냅샷",
                                    "기간은 시작 포함·끝 제외, 오래됨은 cutoff 미만, 소요 시간은 threshold 초과",
                                    "라벨 중복 소속은 각 라벨에 따로 집계. 연결은 저장소와 커밋 SHA 모두 일치해야 함"]}})
    catalog = ["# 추가 템플릿 10개 / 문항 30개", "", "모두 개발용 합성 데이터이며 실제 모델 성능 검증 전이다.", ""]
    for code, title in zip(CODES[:10], TITLES, strict=True):
        capability = "github.issues.read" if code.startswith("ISSUES_") else "github.actions.read"
        capabilities = [capability] + (["github.releases.read"] if code == "DEPLOY_RELEASE_LINK" else [])
        prompts = []
        for index, repo in enumerate(repos, 1):
            values = {"repo": repo}
            environment = "staging" if index == 3 and code in {"DEPLOY_DAILY_COUNTS", "DEPLOY_SLOW_RUNS", "DEPLOY_RELEASE_LINK"} else "production"
            if code in CODES[:4] or code == "DEPLOY_RELEASE_LINK":
                values["environment"] = environment
            if code in {"DEPLOY_FAILURES_PERIOD", "ISSUES_CLOSED_PERIOD"}:
                values.update(start="2026-11-16T00:00:00+09:00", end="2026-11-17T00:00:00+09:00")
                prompt = f"{repo}의 " + (f"{environment} 환경에서 종료된 실패 배포 ID" if code.startswith("DEPLOY") else "닫힌 이슈 번호") + "를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘."
            elif code == "DEPLOY_SLOW_RUNS":
                values["threshold_sec"] = [600, 300, 180][index-1]
                prompt = f"{repo} {environment} 전체 배포 기록에서 성공 여부와 무관하게 시작부터 종료까지 {values['threshold_sec']}초를 초과한 배포 ID를 모두 알려 줘."
            elif code == "DEPLOY_DAILY_COUNTS":
                values["date"] = "2026-11-16"
                prompt = f"{repo} {environment}에서 2026-11-16(KST)에 종료된 배포의 성공 건수와 실패 건수를 각각 알려 줘."
            elif code == "DEPLOY_RECOVERY":
                values["failed_run"] = str(index*100+1)
                prompt = f"{repo} production 배포 {values['failed_run']}의 실패 종료 후, 가장 먼저 성공 종료한 배포 ID를 알려 줘."
            elif code == "DEPLOY_ENV_COMPARE":
                prompt = f"{repo}의 production과 staging에서 각각 가장 최근에 성공 종료한 배포 버전을 알려 줘."
            elif code == "ISSUES_ASSIGNED_OPEN":
                values["assignee"] = ["mina", "jun", "nobody"][index-1]
                prompt = f"{repo}에서 {values['assignee']}에게 배정된 열린 이슈 번호를 모두 알려 줘."
            elif code == "ISSUES_STALE_UNASSIGNED":
                values["cutoff"] = ["2026-11-10", "2026-11-11", "2026-11-01"][index-1]+"T00:00:00+09:00"
                prompt = f"{repo}에서 열린 미배정 이슈 중 마지막 갱신이 {values['cutoff']}보다 이전인 이슈 번호를 모두 알려 줘."
            elif code == "ISSUES_LABEL_COUNTS":
                prompt = f"{repo}의 열린 이슈 중 bug와 urgent 라벨의 건수를 각각 알려 줘. 둘 다 붙었으면 양쪽에 각각 세어 줘."
            else:
                prompt = f"{repo} {environment}의 가장 최근 성공 배포를 찾고, 같은 저장소에서 배포 커밋 SHA가 일치하는 릴리스 태그를 알려 줘."
            prompt += " 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘."
            answer = calculate(code, values, data)
            conditions = []
            for seq, (key, expected) in enumerate(answer.items(), 1):
                conditions.append({"seq": seq, "kind": "info", "spec": {"schema_version": 1, "key": key,
                                   "expected": expected, "match": "set_equal" if isinstance(expected, list) else "exact"}})
            if code == "DEPLOY_RELEASE_LINK":
                sha = f"repo{index}-" + ("staging" if environment == "staging" else "latest")
                conditions.append({"seq": len(conditions)+1, "kind": "link", "spec": {"schema_version": 1,
                    "key": "release_sha_seen", "gate": True,
                    "seen": {"result_contains": [repo, sha, answer["release_tag"]]}, "supports": ["release_tag"]}})
            conditions.extend([
                {"seq": len(conditions)+1, "kind": "forbidden", "spec": {"schema_version": 1, "call": {"access": "write"}}},
                {"seq": len(conditions)+2, "kind": "end_state", "spec": {"schema_version": 1, "write_intents": "none"}},
            ])
            pack["tasks"].append({"template": code, "code": f"{code}-{index:03d}", "prompt": prompt,
                                  "slot_values": values, "seed": index, "conditions": conditions})
            prompts.append(prompt)
            catalog.extend([f"### {code}-{index:03d}", prompt, "", f"정답: `{json.dumps(answer, ensure_ascii=False)}`", ""])
        pack["templates"].append({"code": code, "question_pattern": f"{title}: {{repo}} 및 slot_values의 조건으로 조회",
                                  "required_capabilities": capabilities, "is_representative": True, "split": "dev"})
    (PACK_DIR / "data/operations.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (PACK_DIR / "BATCH_10.md").write_text("\n".join(catalog), encoding="utf-8")


if __name__ == "__main__":
    build()
