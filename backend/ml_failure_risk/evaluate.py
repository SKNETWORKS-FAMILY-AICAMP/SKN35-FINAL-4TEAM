"""최종 평가. 모델을 다 정한 뒤 마지막에만 실행합니다.  실행: python evaluate.py --final"""
import hashlib
import json
import sys
from datetime import datetime

import joblib

import config as C
import metrics
import table


def main(argv):
    if "--final" not in argv:
        raise SystemExit("최종 평가 데이터는 마지막에만 엽니다. 준비됐으면 --final을 붙이세요")
    path = C.MODELS / "model.joblib"
    if not path.exists():
        raise SystemExit("먼저 train.py를 실행하세요")
    b = joblib.load(path)
    if b["features"] != C.FEATURES:
        raise SystemExit("FEATURES가 학습 때와 다릅니다. train.py를 다시 실행하세요")
    if hashlib.sha256(C.TRAIN_CSV.read_bytes()).hexdigest() != b["train_sha256"]:
        raise SystemExit("학습 표가 바뀌었습니다. train.py를 다시 실행하세요")
    train, final = table.load(C.TRAIN_CSV), table.load(C.FINAL_CSV)
    table.check_no_overlap(train, final)
    log = C.REPORTS / "final_opened.log"     # 몇 번 열었는지 남김. 2번 이상이면 결과서에 적음
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {b['name']} {hashlib.sha256(path.read_bytes()).hexdigest()[:12]}\n")
    y = final[C.LABEL].to_numpy()
    p = b["model"].predict_proba(final[C.FEATURES])[:, 1]
    out = {"model": b["name"], "rows": len(final), "wrong_rate": float(y.mean()),
           "opened": len(log.read_text(encoding="utf-8").splitlines()),
           **metrics.score(y, p, b["threshold"]),
           "pr_auc_95": metrics.pr_auc_interval(y, p, final["task_id"].to_numpy())}
    (C.REPORTS / "final_metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    final[[*C.META, C.LABEL]].assign(p=p, flagged=p >= b["threshold"]) \
        .to_csv(C.REPORTS / "final_predictions.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
