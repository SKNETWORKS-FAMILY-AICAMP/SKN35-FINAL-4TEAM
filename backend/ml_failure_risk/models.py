from lightgbm import LGBMClassifier
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import config as C


def build(name):
    if name == "majority":     # 비교 기준: 전부 정답이라고 함
        return DummyClassifier(strategy="prior")
    if name == "logistic":     # 결측 채우기·크기 맞추기는 학습 묶음 안에서만 배움
        return make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                             LogisticRegression(max_iter=2000, class_weight="balanced"))
    if name == "lightgbm":     # 빈 값은 LightGBM이 그대로 다룸
        return LGBMClassifier(random_state=C.SEED, verbose=-1, n_jobs=1, deterministic=True,
                              force_row_wise=True, **C.LGBM_PARAMS)
    raise ValueError(f"모르는 모델: {name}")
    # [채울 곳 3] 비교할 모델을 더하려면 여기에 추가하고 NAMES에 이름을 넣습니다.


NAMES = ["majority", "logistic", "lightgbm"]
