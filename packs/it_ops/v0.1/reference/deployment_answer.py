"""채점 준비용 기준 정답 계산. 에이전트/러너에 이 파일이나 pack.json을 전달하지 않는다."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[1]
# v0.1은 한국 시간만 사용한다. Windows에서도 tzdata 설치 없이 동작한다.
KST = timezone(timedelta(hours=9), name="Asia/Seoul")


def deployment_answer(rows: list[dict], *, repo: str, environment: str, day: str) -> dict:
    """한국 날짜로 필터한 뒤 마지막 성공 배포를 선택한다. 없거나 동률이면 오류."""
    target_date = date.fromisoformat(day)
    matches = []
    for row in rows:
        if (row["repo"], row["environment"], row["status"]) != (repo, environment, "success"):
            continue
        finished = datetime.fromisoformat(row["finished_at"])
        if finished.utcoffset() is None:
            raise ValueError("finished_at must include a timezone")
        local = finished.astimezone(KST)
        if local.date() == target_date:
            matches.append((local, row))
    if not matches:
        raise ValueError("No matching successful deployment")
    latest = max(stamp for stamp, _ in matches)
    winners = [row for stamp, row in matches if stamp == latest]
    if len(winners) != 1:
        raise ValueError("Ambiguous latest deployment")
    return {"finished_at": latest.strftime("%H:%M"), "version": winners[0]["version"]}


def verify_pack(pack_dir: Path = PACK_DIR) -> dict:
    """고정 정답 조건과 원본 데이터에서 계산한 값의 불일치를 탐지한다."""
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    if pack["pack_version"]["premises"]["timezone"] != "Asia/Seoul":
        raise ValueError("This reference calculator supports Asia/Seoul only")
    snapshot = pack["data_snapshots"][0]
    data = json.loads((pack_dir / snapshot["location"]).read_text(encoding="utf-8"))
    answers = {}
    for task in pack["tasks"]:
        if task["template"] != "DEPLOY_LATEST_SUCCESS":
            continue
        values = task["slot_values"]
        answer = deployment_answer(
            data["deployments"], repo=values["repo"], environment=values["environment"], day=values["date"]
        )
        stored = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if stored != answer:
            raise ValueError(f"{task['code']}: answer conditions differ from snapshot: {stored} != {answer}")
        answers[task["code"]] = answer
    return answers


if __name__ == "__main__":
    print(json.dumps(verify_pack(), ensure_ascii=False, indent=2))
