import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import config as C  # noqa: E402
import evaluate  # noqa: E402
import make_sample  # noqa: E402
import metrics  # noqa: E402
import table  # noqa: E402
import train  # noqa: E402


@pytest.fixture
def df():
    return make_sample.sample("S", 11, 1)


def test_ok(df):
    table.check_table(df)


@pytest.mark.parametrize("name", sorted(C.FORBIDDEN))
def test_forbidden(name):
    with pytest.raises(ValueError):
        table.check_features([*C.FEATURES, name])


@pytest.mark.parametrize("change", [
    lambda d: d.drop(columns="in_tokens"),
    lambda d: d.assign(is_wrong=0),
    lambda d: d.assign(is_wrong=d["is_wrong"] * 2),
    lambda d: d.assign(run_id="x"),
    lambda d: d.assign(template_id=None),
    lambda d: d.assign(answer_len="길다"),
    lambda d: d.assign(in_tokens=np.inf),
    lambda d: d.assign(grounded_ratio=np.nan),
    lambda d: d.assign(task_id="같은문항"),
    lambda d: d.iloc[:0],
])
def test_bad_table(df, change):
    with pytest.raises(ValueError):
        table.check_table(change(df))


def test_folds_do_not_share_template(df):
    parts = list(train.folds(df))
    assert len(parts) == C.N_SPLITS
    assert sorted(i for _, te in parts for i in te) == list(range(len(df)))
    for tr, te in parts:
        assert not set(df.iloc[tr].template_id) & set(df.iloc[te].template_id)


def test_final_overlap(df):
    table.check_no_overlap(df, make_sample.sample("F", 3, 2))
    with pytest.raises(ValueError):
        table.check_no_overlap(df, df)


def test_threshold_reaches_target():
    y, p = np.array([0, 0, 1, 1, 1]), np.array([.1, .6, .5, .7, .9])
    t = metrics.pick_threshold(y, p)
    assert (p[y == 1] >= t).mean() >= C.TARGET_RECALL


def test_final_needs_flag():
    with pytest.raises(SystemExit):
        evaluate.main([])


def test_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "TRAIN_CSV", tmp_path / "train.csv")
    monkeypatch.setattr(C, "FINAL_CSV", tmp_path / "final.csv")
    monkeypatch.setattr(C, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(C, "MODELS", tmp_path / "models")
    monkeypatch.setattr(C, "N_BOOT", 50)
    make_sample.sample("S", 11, 1).to_csv(C.TRAIN_CSV, index=False)
    make_sample.sample("F", 6, 2).to_csv(C.FINAL_CSV, index=False)
    train.main()
    evaluate.main(["--final"])
    evaluate.main(["--final"])
    assert len((C.REPORTS / "final_opened.log").read_text(encoding="utf-8").splitlines()) == 2
    for f in ("cv_metrics.json", "cv_pr_curve.html", "cv_by_template.csv", "importance.csv", "final_metrics.json"):
        assert (C.REPORTS / f).exists()
    C.TRAIN_CSV.write_text(C.TRAIN_CSV.read_text() + "\n")
    with pytest.raises(SystemExit):
        evaluate.main(["--final"])
