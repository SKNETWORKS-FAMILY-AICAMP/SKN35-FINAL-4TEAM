"""추가 10개 템플릿의 정답 계산. 실행 에이전트에 제공하지 않는 평가 준비 코드."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
CODES = (
    "DEPLOY_FAILURES_PERIOD", "DEPLOY_SLOW_RUNS", "DEPLOY_DAILY_COUNTS", "DEPLOY_RECOVERY",
    "DEPLOY_ENV_COMPARE", "ISSUES_ASSIGNED_OPEN", "ISSUES_STALE_UNASSIGNED",
    "ISSUES_CLOSED_PERIOD", "ISSUES_LABEL_COUNTS", "DEPLOY_RELEASE_LINK",
    "DEPLOY_FAILURE_STREAK", "ISSUES_UNLABELED_OPEN", "DEPLOY_UNDEPLOYED_RELEASES",
)


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timezone is required")
    return result.astimezone(KST)


def calculate(code, values, data):
    """기간은 [start, end), 오래됨은 cutoff 미만, 느림은 threshold 초과."""
    repo = values["repo"]
    runs = [r for r in data["runs"] if r["repo"] == repo]
    issues = [r for r in data["issues"] if r["repo"] == repo]
    if code == "ISSUES_UNLABELED_OPEN":
        return {"issue_ids": sorted(r["id"] for r in issues if r["state"] == "open" and r["labels"] == [])}
    if code in {"DEPLOY_FAILURE_STREAK", "DEPLOY_UNDEPLOYED_RELEASES"}:
        runs = [r for r in runs if r["environment"] == values["environment"]]
        if code == "DEPLOY_UNDEPLOYED_RELEASES":
            deployed = {r["sha"] for r in runs if r["status"] == "success"}
            return {"release_tags": sorted(r["tag"] for r in data["releases"]
                                           if r["repo"] == repo and r["sha"] not in deployed)}
        count = 0
        for row in sorted(runs, key=lambda r: stamp(r["finished_at"]), reverse=True):
            if row["status"] != "failure":
                break
            count += 1
        return {"failure_streak": count}
    if code in CODES[:4] or code == "DEPLOY_RELEASE_LINK":
        runs = [r for r in runs if r["environment"] == values["environment"]]
    if code == "DEPLOY_FAILURES_PERIOD":
        return {"run_ids": sorted(r["id"] for r in runs if r["status"] == "failure"
                                  and stamp(values["start"]) <= stamp(r["finished_at"]) < stamp(values["end"]))}
    if code == "DEPLOY_SLOW_RUNS":
        return {"run_ids": sorted(r["id"] for r in runs
                                  if (stamp(r["finished_at"]) - stamp(r["started_at"])).total_seconds()
                                  > values["threshold_sec"])}
    if code == "DEPLOY_DAILY_COUNTS":
        selected = [r for r in runs if stamp(r["finished_at"]).date().isoformat() == values["date"]]
        return {"success_count": sum(r["status"] == "success" for r in selected),
                "failure_count": sum(r["status"] == "failure" for r in selected)}
    if code == "DEPLOY_RECOVERY":
        failed = next(r for r in runs if r["id"] == values["failed_run"] and r["status"] == "failure")
        later = [r for r in runs if r["status"] == "success" and stamp(r["finished_at"]) > stamp(failed["finished_at"])]
        chosen = min(later, key=lambda r: stamp(r["finished_at"]))
        return {"run_ids": [chosen["id"]]}
    if code == "DEPLOY_ENV_COMPARE":
        result = {}
        for environment in ("production", "staging"):
            chosen = max((r for r in runs if r["status"] == "success" and r["environment"] == environment),
                         key=lambda r: stamp(r["finished_at"]))
            result[f"{environment}_version"] = chosen["version"]
        return result
    if code == "ISSUES_ASSIGNED_OPEN":
        return {"issue_ids": sorted(r["id"] for r in issues if r["state"] == "open" and values["assignee"] in r["assignees"])}
    if code == "ISSUES_STALE_UNASSIGNED":
        return {"issue_ids": sorted(r["id"] for r in issues if r["state"] == "open" and not r["assignees"]
                                    and stamp(r["updated_at"]) < stamp(values["cutoff"]))}
    if code == "ISSUES_CLOSED_PERIOD":
        return {"issue_ids": sorted(r["id"] for r in issues if r["state"] == "closed" and r["closed_at"] is not None
                                    and stamp(values["start"]) <= stamp(r["closed_at"]) < stamp(values["end"]))}
    if code == "ISSUES_LABEL_COUNTS":
        return {"bug_count": sum(r["state"] == "open" and "bug" in r["labels"] for r in issues),
                "urgent_count": sum(r["state"] == "open" and "urgent" in r["labels"] for r in issues)}
    if code == "DEPLOY_RELEASE_LINK":
        chosen = max((r for r in runs if r["status"] == "success"), key=lambda r: stamp(r["finished_at"]))
        releases = [r for r in data["releases"] if r["repo"] == repo and r["sha"] == chosen["sha"]]
        if len(releases) != 1:
            raise ValueError("Release link is missing or ambiguous")
        return {"release_tag": releases[0]["tag"]}
    raise ValueError(f"Unsupported template: {code}")


def verify_batch(pack_dir=PACK_DIR):
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    data = json.loads((pack_dir / "data/operations.json").read_text(encoding="utf-8"))
    answers = {}
    for task in pack["tasks"]:
        if task["template"] not in CODES:
            continue
        actual = calculate(task["template"], task["slot_values"], data)
        expected = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if actual != expected:
            raise ValueError(f"{task['code']}: answer differs from snapshot")
        answers[task["code"]] = actual
    return answers


if __name__ == "__main__":
    print(json.dumps(verify_batch(), ensure_ascii=False, indent=2))
