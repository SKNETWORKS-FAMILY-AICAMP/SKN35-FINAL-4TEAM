"""전처리 표 검사. 잘못된 표는 학습 전에 멈춥니다."""
import numpy as np
import pandas as pd

import config as C


def check_features(features):
    bad = sorted(set(features) & C.FORBIDDEN)
    if bad:
        raise ValueError(f"정답이 샐 수 있는 칸이 특징에 있습니다: {bad}")
    if len(features) != len(set(features)) or not features:
        raise ValueError("FEATURES가 비었거나 중복됐습니다")


def check_table(df):
    check_features(C.FEATURES)
    missing = [c for c in [*C.META, C.LABEL, *C.FEATURES] if c not in df.columns]
    if missing:
        raise ValueError(f"표에 없는 칸: {missing}")
    if df.empty:
        raise ValueError("표가 비었습니다")
    if df[[*C.META, C.LABEL]].isna().any().any():
        raise ValueError("관리용 칸·라벨에 빈 값이 있습니다")
    if df["run_id"].duplicated().any():
        raise ValueError("run_id가 중복됐습니다")
    if set(df[C.LABEL].unique()) != {0, 1}:
        raise ValueError(f"{C.LABEL}은 0과 1이 모두 있어야 하고 다른 값이 없어야 합니다")
    if (df.groupby("task_id")["template_id"].nunique() > 1).any():
        raise ValueError("한 문항이 여러 유형에 속합니다")
    for c in C.FEATURES:
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise ValueError(f"숫자가 아닌 특징: {c}")
        if np.isinf(df[c].astype(float)).any():
            raise ValueError(f"무한대 값이 있는 특징: {c}")
        if df[c].isna().all():
            raise ValueError(f"값이 하나도 없는 특징: {c}")


def check_no_overlap(train, final):
    for c in ("run_id", "task_id", "template_id"):
        same = set(train[c].astype(str)) & set(final[c].astype(str))
        if same:
            raise ValueError(f"학습과 최종 평가에 같은 {c}가 있습니다: {sorted(same)[:5]}")


def load(path):
    if not path.exists():
        raise FileNotFoundError(f"{path}가 없습니다. 전처리 결과를 넣거나 make_sample.py로 연습용 표를 만드세요")
    df = pd.read_csv(path, dtype={c: str for c in C.META})
    check_table(df)
    return df
