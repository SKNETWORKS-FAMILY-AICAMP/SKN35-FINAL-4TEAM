"""pack.json을 기준으로 단일 전체 문항 목록을 갱신한다. --check는 수정 없이 최신성 검사."""

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render_catalog(root=ROOT):
    packs_dir = Path(root) / "packs"
    packs = [(path, json.loads(path.read_text(encoding="utf-8")))
             for path in sorted(packs_dir.glob("*/v*/pack.json"))]
    totals = [sum(len(pack[key]) for _, pack in packs) for key in ("templates", "tasks", "golden")]
    lines = ["# 전체 평가팩 문항 목록", "",
             "자동 생성 파일. 원본은 각 pack.json이며 이 파일을 직접 수정하지 않는다.", "",
             "정답·승인 정책을 포함한 검수용 자료다. 에이전트·러너·연습 서버에 전달하지 않는다.", "",
             f"평가팩 {len(packs)}개 · 템플릿 {totals[0]}개 · 문항 {totals[1]}개 · 골든 {totals[2]}개.", "",
             "수량은 파일 등록 기준이며 제품 검증·독립 검수·DB 잠금 완료를 뜻하지 않는다.", "",
             "재생성: `.venv/Scripts/python.exe scripts/update_pack_catalog.py`", "",
             "최신성 검사: `.venv/Scripts/python.exe scripts/update_pack_catalog.py --check`", ""]
    for path, pack in packs:
        version = pack["pack_version"]
        relative = path.relative_to(packs_dir).as_posix()
        counts = Counter(task["template"] for task in pack["tasks"])
        lines += [f"## {version['pack_code']} / {version['version']}", "",
                  f"원본: [pack.json]({relative}) · 도메인: `{version['domain_code']}`", "",
                  f"템플릿 {len(pack['templates'])}개 · 문항 {len(pack['tasks'])}개 · 골든 {len(pack['golden'])}개", "",
                  "| 템플릿 | 문항 수 | 구분 |", "|---|---:|---|"]
        lines += [f"| {t['code']} | {counts[t['code']]} | {t.get('split', 'held')} |" for t in pack["templates"]]
        lines += [""]
        for task in pack["tasks"]:
            lines += [f"### {task['code']}", "", f"유형: `{task['template']}`", "", task["prompt"], "",
                      "정답 조건:", "", "```json", json.dumps(task["conditions"], ensure_ascii=False, indent=2), "```", ""]
            if task.get("confirmation") is not None:
                lines += ["고정 사용자 응답 정책(엔진 전용):", "", "```json",
                          json.dumps(task["confirmation"], ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_catalog(root=ROOT):
    path = Path(root) / "packs/QUESTIONS.md"
    path.write_text(render_catalog(root), encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        path = ROOT / "packs/QUESTIONS.md"
        if not path.exists() or path.read_text(encoding="utf-8") != render_catalog():
            raise SystemExit("문항 목록이 오래되었습니다. update_pack_catalog.py를 실행하세요.")
        print("전체 문항 목록이 pack.json과 일치합니다.")
    else:
        print(write_catalog())
