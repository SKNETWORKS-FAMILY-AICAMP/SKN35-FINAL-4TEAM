"""교차검증 비교 → 고른 모델 저장.  실행: python train.py"""
import hashlib
import json

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.metrics import precision_recall_curve
from sklearn.model_selection import StratifiedGroupKFold

import config as C
import metrics
import models
import table


def folds(df):
    cv = StratifiedGroupKFold(n_splits=C.N_SPLITS, shuffle=True, random_state=C.SEED)
    g = df["template_id"].to_numpy()
    for tr, te in cv.split(df, df[C.LABEL], g):
        if set(g[tr]) & set(g[te]):
            raise ValueError("같은 문항 유형이 학습과 검증에 함께 있습니다")
        if df[C.LABEL].iloc[tr].nunique() < 2:
            raise ValueError("학습 묶음에 한 종류 라벨만 있습니다. N_SPLITS를 줄이세요")
        yield tr, te


def main():
    if C.FINAL_MODEL not in models.NAMES:
        raise ValueError("FINAL_MODEL을 확인하세요")
    df = table.load(C.TRAIN_CSV)
    if df["template_id"].nunique() < C.N_SPLITS:
        raise ValueError("문항 유형 수가 N_SPLITS보다 적습니다")
    C.REPORTS.mkdir(exist_ok=True)
    C.MODELS.mkdir(exist_ok=True)
    X, y = df[C.FEATURES], df[C.LABEL].to_numpy()
    split = list(folds(df))
    result, oof, fig = {}, df[[*C.META, C.LABEL]].copy(), go.Figure()
    for name in models.NAMES:
        p = np.zeros(len(df))
        for tr, te in split:
            p[te] = models.build(name).fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
        # 다수 클래스는 정답이 많다는 정보만 쓰므로 묶음별 비율 차이가 점수에 끼지 않게 하나의 값으로 둠
        if name == "majority":
            p[:] = y.mean()
        t = 1.1 if name == "majority" else metrics.pick_threshold(y, p)
        result[name] = {**metrics.score(y, p, t), "threshold": t,
                        "pr_auc_95": metrics.pr_auc_interval(y, p, df["task_id"].to_numpy())}
        oof[f"p_{name}"] = p
        pr, rc, _ = precision_recall_curve(y, p)
        fig.add_scatter(x=rc, y=pr, name=name, mode="lines")
    fig.update_layout(title="정밀도-재현율 (교차검증)", xaxis_title="오답 재현율", yaxis_title="정밀도")
    fig.write_html(C.REPORTS / "cv_pr_curve.html", include_plotlyjs=True)
    oof.to_csv(C.REPORTS / "cv_predictions.csv", index=False, encoding="utf-8-sig")
    by = oof.assign(p=oof[f"p_{C.FINAL_MODEL}"])
    by["caught"] = np.where(by[C.LABEL] == 1, by["p"] >= result[C.FINAL_MODEL]["threshold"], np.nan)
    by.groupby("template_id").agg(n=("run_id", "size"), wrong=(C.LABEL, "sum"), recall=("caught", "mean")) \
        .to_csv(C.REPORTS / "cv_by_template.csv", encoding="utf-8-sig")

    model = models.build(C.FINAL_MODEL).fit(X, y)
    info = {"name": C.FINAL_MODEL, "features": C.FEATURES, "threshold": result[C.FINAL_MODEL]["threshold"],
            "train_sha256": hashlib.sha256(C.TRAIN_CSV.read_bytes()).hexdigest(), "seed": C.SEED}
    joblib.dump({"model": model, **info}, C.MODELS / "model.joblib")
    (C.MODELS / "model_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    if C.FINAL_MODEL == "lightgbm":
        pd.DataFrame({"feature": C.FEATURES, "gain": model.booster_.feature_importance("gain")}) \
            .sort_values("gain", ascending=False).to_csv(C.REPORTS / "importance.csv", index=False, encoding="utf-8-sig")
    summary = {"rows": len(df), "tasks": int(df["task_id"].nunique()), "templates": int(df["template_id"].nunique()),
               "wrong_rate": float(y.mean()), "models": result}
    (C.REPORTS / "cv_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(df)}건 · 문항 {summary['tasks']} · 유형 {summary['templates']} · 오답 {y.mean():.1%}")
    print(pd.DataFrame(result).T.drop(columns="pr_auc_95").astype(float).round(3).to_string())


if __name__ == "__main__":
    main()
