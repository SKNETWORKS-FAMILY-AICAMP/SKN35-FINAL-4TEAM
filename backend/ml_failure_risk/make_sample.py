"""연습용 가짜 표. 뼈대가 도는지 보는 용도이며 수치에 의미가 없습니다.  실행: python make_sample.py"""
import numpy as np
import pandas as pd

import config as C


def sample(prefix, n_tpl, seed):
    rng, rows = np.random.default_rng(seed), []
    for t in range(n_tpl):
        for q in range(4):
            for r in range(12):
                wrong = int(rng.random() < 0.25)
                rows.append({"run_id": f"{prefix}{t}-{q}-{r}", "task_id": f"{prefix}{t}-{q}", "template_id": f"{prefix}{t}",
                             "candidate": "ABC"[r % 3], "config": "sample", C.LABEL: wrong,
                             "n_tool_calls": rng.integers(1, 6), "n_tool_errors": rng.integers(0, 2),
                             "n_empty_results": rng.poisson(0.3 + wrong), "n_repeat_calls": rng.integers(0, 2),
                             "in_tokens": rng.integers(400, 4000), "out_tokens": rng.integers(20, 120),
                             "answer_len": rng.integers(20, 300), "says_none": int(rng.random() < 0.2 + 0.3 * wrong),
                             "asks_back": int(rng.random() < 0.05),
                             "grounded_ratio": np.nan if rng.random() < 0.1 else rng.random()})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    for path in (C.TRAIN_CSV, C.FINAL_CSV):
        if path.exists():
            raise SystemExit(f"{path.name}이 이미 있어 덮어쓰지 않습니다")
    C.TRAIN_CSV.parent.mkdir(exist_ok=True)
    sample("S", 11, 1).to_csv(C.TRAIN_CSV, index=False)
    sample("F", 6, 2).to_csv(C.FINAL_CSV, index=False)
    print("data/train.csv, data/final.csv 생성 (가짜 데이터)")
