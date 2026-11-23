"""담당자가 없는 열린 이슈의 기준 정답 계산. 평가 준비 전용."""

import json
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[1]


def issue_answer(rows: list[dict], *, repo: str, label: str) -> dict:
    """번호는 저장소 범위 안에서 집합으로 비교한다. 없으면 빈 목록이 정답."""
    numbers = {
        row["number"] for row in rows
        if row["repo"] == repo and row["state"] == "open"
        and label in row["labels"] and row["assignees"] == []
    }
    return {"issues": sorted(numbers, key=int)}


def verify_issues(pack_dir: Path = PACK_DIR) -> dict:
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    snapshot = next(s for s in pack["data_snapshots"] if s["location"] == "data/issues.json")
    rows = json.loads((pack_dir / snapshot["location"]).read_text(encoding="utf-8"))["issues"]
    answers = {}
    for task in pack["tasks"]:
        if task["template"] != "ISSUES_UNASSIGNED_OPEN":
            continue
        answer = issue_answer(rows, **task["slot_values"])
        stored = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if stored != answer:
            raise ValueError(f"{task['code']}: answer conditions differ from snapshot")
        answers[task["code"]] = answer
    return answers


if __name__ == "__main__":
    print(json.dumps(verify_issues(), ensure_ascii=False, indent=2))
