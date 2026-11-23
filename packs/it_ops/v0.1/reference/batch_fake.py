"""고정 행동 모델. 정답 조건 대신 실제 조회 결과만으로 구조화 답을 만든다."""

import json
from datetime import datetime

from deployment_answer import KST


def respond(code, values, data_path, alternate, record):
    def query(key, tool):
        data = json.loads(data_path.read_text(encoding="utf-8"))
        args = {} if alternate else {"repo": values["repo"]}
        rows = [r for r in data[key] if not args or r["repo"] == args["repo"]]
        record("tool", tool, tool_args=args, tool_result=json.dumps(rows))
        return [r for r in rows if r["repo"] == values["repo"]]

    def time(value):
        return datetime.fromisoformat(value).astimezone(KST)

    if code.startswith("ISSUES_"):
        rows = query("issues", "list_operation_issues")
        if code == "ISSUES_UNLABELED_OPEN":
            return {"issue_ids": sorted({r["id"] for r in rows if not r["labels"] and r["state"] == "open"})}
        if code == "ISSUES_LABEL_COUNTS":
            return {f"{label}_count": len([r for r in rows if r["state"] == "open" and label in r["labels"]])
                    for label in ("bug", "urgent")}
        if code == "ISSUES_ASSIGNED_OPEN":
            selected = [r for r in rows if r["state"] == "open" and values["assignee"] in r["assignees"]]
        elif code == "ISSUES_STALE_UNASSIGNED":
            selected = [r for r in rows if r["state"] == "open" and r["assignees"] == []
                        and time(r["updated_at"]) < time(values["cutoff"])]
        elif code == "ISSUES_CLOSED_PERIOD":
            selected = [r for r in rows if r["state"] == "closed" and r["closed_at"]
                        and time(values["start"]) <= time(r["closed_at"]) < time(values["end"])]
        else:
            raise ValueError(code)
        return {"issue_ids": sorted({r["id"] for r in selected})}
    rows = query("runs", "list_operation_runs")
    if code == "DEPLOY_ENV_COMPARE":
        return {f"{env}_version": sorted(
            [r for r in rows if r["environment"] == env and r["status"] == "success"],
            key=lambda r: time(r["finished_at"]), reverse=True)[0]["version"] for env in ("production", "staging")}
    rows = [r for r in rows if r["environment"] == values["environment"]]
    if code == "DEPLOY_FAILURE_STREAK":
        ordered = sorted(rows, key=lambda r: time(r["finished_at"]), reverse=True)
        last_success = next((i for i, r in enumerate(ordered) if r["status"] == "success"), len(ordered))
        return {"failure_streak": last_success}
    if code == "DEPLOY_UNDEPLOYED_RELEASES":
        releases = query("releases", "list_operation_releases")
        return {"release_tags": sorted({r["tag"] for r in releases
                                       if not any(d["status"] == "success" and d["sha"] == r["sha"] for d in rows)})}
    if code == "DEPLOY_DAILY_COUNTS":
        rows = [r for r in rows if time(r["finished_at"]).date().isoformat() == values["date"]]
        return {f"{status}_count": len([r for r in rows if r["status"] == status]) for status in ("success", "failure")}
    if code == "DEPLOY_FAILURES_PERIOD":
        selected = [r for r in rows if r["status"] == "failure"
                    and time(values["start"]) <= time(r["finished_at"]) < time(values["end"])]
    elif code == "DEPLOY_SLOW_RUNS":
        selected = [r for r in rows if (time(r["finished_at"])-time(r["started_at"])).total_seconds() > values["threshold_sec"]]
    elif code == "DEPLOY_RECOVERY":
        failed = next(r for r in rows if r["id"] == values["failed_run"])
        selected = sorted([r for r in rows if r["status"] == "success"
                           and time(r["finished_at"]) > time(failed["finished_at"])],
                          key=lambda r: time(r["finished_at"]))[:1]
    elif code == "DEPLOY_RELEASE_LINK":
        latest = sorted([r for r in rows if r["status"] == "success"],
                        key=lambda r: time(r["finished_at"]), reverse=True)[0]
        releases = query("releases", "list_operation_releases")
        matching = [r for r in releases if r["sha"] == latest["sha"]]
        if len(matching) != 1:
            raise ValueError("Missing or ambiguous release")
        return {"release_tag": matching[0]["tag"]}
    else:
        raise ValueError(code)
    return {"run_ids": sorted({r["id"] for r in selected})}
