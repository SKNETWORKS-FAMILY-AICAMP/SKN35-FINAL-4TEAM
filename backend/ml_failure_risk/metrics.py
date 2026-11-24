import numpy as np
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

import config as C


def pick_threshold(y, p):
    """오답을 TARGET_RECALL 이상 잡는 가장 높은 기준점. 학습 데이터의 교차검증 예측으로만 정합니다."""
    for t in np.unique(p)[::-1]:
        if recall_score(y, p >= t) >= C.TARGET_RECALL:
            return float(t)
    return float(p.min())


def score(y, p, t):
    q = p >= t
    return {"pr_auc": average_precision_score(y, p), "roc_auc": roc_auc_score(y, p),
            "recall": recall_score(y, q, zero_division=0), "precision": precision_score(y, q, zero_division=0),
            "f1": f1_score(y, q, zero_division=0), "flagged_rate": float(q.mean()),
            "accuracy": float((q == y).mean())}


def pr_auc_interval(y, p, groups):
    """문항을 통째로 다시 뽑는 95% 구간. 같은 문항의 반복을 독립으로 세지 않습니다.
    유형끼리의 비슷함과 모델을 다시 학습할 때의 흔들림은 들어 있지 않아 실제보다 좁을 수 있습니다."""
    rng = np.random.default_rng(C.SEED)
    idx = [np.flatnonzero(groups == g) for g in np.unique(groups)]
    out = []
    for _ in range(C.N_BOOT):
        i = np.concatenate([idx[k] for k in rng.integers(0, len(idx), len(idx))])
        if 0 < y[i].sum() < len(i):
            out.append(average_precision_score(y[i], p[i]))
    return [float(v) for v in np.percentile(out, [2.5, 97.5])] if out else [None, None]
