"""11/18 실행 기록을 전처리한다. 학습/최종 평가를 실행하지 않고 원본을 보존한다.

사용: python preprocess.py --source <trace_main_20261118_152602.jsonl>
기존 결과는 덮어쓰지 않는다. 재현 확인은 --output-dir와 --report로 별도 경로를 지정한다.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import pandas as pd

import config as C
import table

SOURCE_NAME = "trace_main_20261118_152602.jsonl"
FINAL_TEMPLATES = frozenset({"T3", "T7", "C1"})
EXPECTED_FEATURES = (
    "n_tool_calls",
    "n_tool_errors",
    "n_empty_results",
    "n_repeat_calls",
    "in_tokens",
    "out_tokens",
    "answer_len",
    "says_none",
    "asks_back",
    "grounded_ratio",
)
COLLECTION_KEYS = ("items", "workflow_runs", "issues", "pull_requests", "releases", "tags", "jobs")
EMPTY_PREFIX = re.compile(
    r'^\s*\{\s*(?:"total_count"\s*:\s*\d+\s*,\s*)?"(?:' + "|".join(COLLECTION_KEYS) + r')"\s*:\s*\[\s*\]'
)
NONE_PATTERN = re.compile(
    r"없(?:습니다|어요|음|다)|존재하지\s*않|찾을\s*수\s*없|해당\s*(?:사항|항목)\s*없|\b(?:none|no results|not found)\b",
    re.I,
)
ASK_PATTERN = re.compile(
    r"알려\s*(?:주실|주시겠|주세요)|확인해\s*주|추가\s*정보.*(?:필요|요청)|어떤\s*(?:저장소|문항|이슈|버전|기간)|(?:가능|괜찮|맞)(?:할까요|을까요|나요|습니까)|\b(?:could you|can you|please clarify|which repository)\b",
    re.I,
)
VERSION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])v?\d+\.\d+\.\d+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?(?![A-Za-z0-9_.])", re.I
)
TIME_PATTERN = re.compile(r"(?<!\d)([01]?\d|2[0-3])(?:\s*:\s*|시\s*)([0-5]\d)(?:분)?(?!\d)")
DATE_PATTERN = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")
SHA_PATTERN = re.compile(r"\b(?=[a-f0-9]*[a-f])[a-f0-9]{7,40}\b", re.I)
ID_PATTERN = re.compile(r"(?<![A-Za-z0-9_.])(?:#(\d+)|(\d+)번|(\d{3,}))(?![A-Za-z0-9_.])")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("중복 JSON 키")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"유한하지 않은 JSON 숫자: {value}")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def run_id(row):
    return f"{row['cfg']}-{row['cand']}-{row['pid']}-{row['rep']}"


def validate_row(row, line):
    def require(ok, field):
        if not ok:
            raise ValueError(f"원본 {line}행 필드 오류: {field}")

    require(isinstance(row, dict), "record")
    for name in ("cfg", "cand", "pid", "tpl"):
        require(isinstance(row.get(name), str) and bool(row[name].strip()), name)
    for name in ("correct", "scope_a"):
        require(type(row.get(name)) is bool, name)
    for name in ("rep", "in_tokens", "out_tokens"):
        require(type(row.get(name)) is int and row[name] >= 0, name)
    require(isinstance(row.get("final"), str), "final")
    require(isinstance(row.get("steps"), list), "steps")
    for step in row["steps"]:
        require(isinstance(step, dict) and step.get("type") in {"llm", "tool"}, "step.type")
        if step["type"] != "tool":
            continue
        require(isinstance(step.get("name"), str) and bool(step["name"]), "tool.name")
        require(isinstance(step.get("args"), dict), "tool.args")
        require(isinstance(step.get("result"), str), "tool.result")
        require(
            type(step.get("result_chars")) is int and step["result_chars"] >= len(step["result"]), "tool.result_chars"
        )
    canonical(row)  # 중첩 인자를 포함해 NaN/Infinity를 거절한다.


def read_source(path):
    blob = path.read_bytes()
    rows, ids = [], set()
    for line, value in enumerate(blob.decode("utf-8-sig").splitlines(), 1):
        if not value.strip():
            raise ValueError(f"원본 {line}행 빈 줄: 임의 제거하지 않습니다")
        row = json.loads(value, object_pairs_hook=_object, parse_constant=_constant)
        validate_row(row, line)
        identity = run_id(row)
        if identity in ids:
            raise ValueError(f"원본 {line}행 중복 run_id")
        ids.add(identity)
        rows.append(row)
    if not rows:
        raise ValueError("원본이 비어 있습니다")
    return rows, hashlib.sha256(blob).hexdigest()


def truncated(step):
    return step["result_chars"] > len(step["result"])


def empty_result(text):
    """루트 빈 배열/알려진 루트 목록을 센다. 오류 객체·문자열 '[]'는 세지 않는다.

    600자 절단으로 JSON 파싱이 불가능할 때는 루트 목록의 문자열 접두부만 검사한다.
    """
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return bool(EMPTY_PREFIX.match(text))
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        lists = [value[k] for k in COLLECTION_KEYS if isinstance(value.get(k), list)]
        return bool(lists) and all(not items for items in lists)
    return False


def value_tokens(text):
    """번호·분 단위 시각·3부분 버전만 비교. 날짜/커밋/제목의 의미는 평가하지 않는다.

    번호: #숫자, 숫자번, 독립된 3자리 이상 정수. 시각은 HH:MM 또는 H시 MM분.
    날짜/버전/시각/커밋 내부의 숫자를 번호로 중복 계산하지 않는다. 고유 값 집합 사용.
    """
    tokens = {("version", m.group().lower().removeprefix("v")) for m in VERSION_PATTERN.finditer(text)}
    tokens |= {("time", f"{int(m[1]):02d}:{int(m[2]):02d}") for m in TIME_PATTERN.finditer(text)}
    for pattern in (VERSION_PATTERN, TIME_PATTERN, DATE_PATTERN, SHA_PATTERN):
        text = pattern.sub(" ", text)
    tokens |= {("id", str(int(next(v for v in m.groups() if v is not None)))) for m in ID_PATTERN.finditer(text)}
    return tokens


def extract_features(row):
    """라벨·문항·후보·설정 등 관리 값은 읽지 않고 특징만 추출한다."""
    tools = [s for s in row["steps"] if s["type"] == "tool"]
    calls = [(s["name"], canonical(s["args"])) for s in tools]
    wanted = value_tokens(row["final"])
    observed = set().union(*(value_tokens(s["result"]) for s in tools))
    ratio = math.nan
    if wanted and not any(truncated(s) for s in tools):
        ratio = len(wanted & observed) / len(wanted)
    return {
        "n_tool_calls": len(tools),
        "n_tool_errors": sum(bool(s.get("error")) for s in row["steps"]),
        "n_empty_results": sum(empty_result(s["result"]) for s in tools),
        "n_repeat_calls": len(calls) - len(set(calls)),
        "in_tokens": row["in_tokens"],
        "out_tokens": row["out_tokens"],
        "answer_len": len(row["final"]),
        "says_none": int(bool(NONE_PATTERN.search(row["final"]))),
        "asks_back": int(bool(ASK_PATTERN.search(row["final"]))),
        "grounded_ratio": ratio,
    }


def build_tables(rows):
    if tuple(C.FEATURES) != EXPECTED_FEATURES:
        raise ValueError("FEATURES가 전처리 정의와 다릅니다. 추출 규칙을 함께 검토하세요")
    kept, excluded = [], []
    for row in rows:
        (excluded if row["cand"] == "A_own" and row["scope_a"] is False else kept).append(row)
    records = [
        {
            "run_id": run_id(r),
            "task_id": r["pid"],
            "template_id": r["tpl"],
            "candidate": r["cand"],
            "config": r["cfg"],
            "is_wrong": int(not r["correct"]),
            **extract_features(r),
        }
        for r in kept
    ]
    frame = pd.DataFrame(records, columns=[*C.META, C.LABEL, *C.FEATURES])
    train = frame[~frame.template_id.isin(FINAL_TEMPLATES)].reset_index(drop=True)
    final = frame[frame.template_id.isin(FINAL_TEMPLATES)].reset_index(drop=True)
    for part in (train, final):
        table.check_table(part)
    table.check_no_overlap(train, final)
    return train, final, kept, excluded


def describe(frame):
    return {
        "rows": len(frame),
        "wrong": int(frame[C.LABEL].sum()),
        "wrong_rate": float(frame[C.LABEL].mean()),
        "tasks": int(frame.task_id.nunique()),
        "templates": sorted(frame.template_id.unique().tolist()),
        "missing_features": {k: int(frame[k].isna().sum()) for k in C.FEATURES},
    }


def verify_expected(rows, train, final, kept, excluded):
    actual = (
        len(rows),
        len(excluded),
        len(kept),
        sum(not r["correct"] for r in kept),
        len(train),
        int(train.is_wrong.sum()),
        len(final),
        int(final.is_wrong.sum()),
        sum(any(truncated(s) for s in r["steps"] if s["type"] == "tool") for r in kept),
    )
    expected = (1656, 108, 1548, 282, 1080, 226, 468, 56, 823)
    if actual != expected:
        raise ValueError(f"① 안내와 원본 집계 불일치: actual={actual}, expected={expected}")
    if len({r["tpl"] for r in kept}) != 11 or len({r["pid"] for r in kept}) != 46:
        raise ValueError("문항46개/유형11개와 불일치")
    if set(final.template_id) != FINAL_TEMPLATES or train.template_id.nunique() != 8:
        raise ValueError("지정된 유형 분할과 불일치")


def preprocess(source, output_dir, report_path):
    source, output_dir, report_path = Path(source), Path(output_dir), Path(report_path)
    if source.name != SOURCE_NAME:
        raise ValueError("지정된 main 원본만 사용합니다. dry/pilot은 입력하지 마세요")
    destinations = [output_dir / "train.csv", output_dir / "final.csv", report_path]
    if len({p.resolve() for p in destinations}) != 3 or source.resolve() in {p.resolve() for p in destinations}:
        raise ValueError("입출력 경로가 겹칩니다")
    if any(p.exists() for p in destinations):
        raise FileExistsError("기존 결과는 보존합니다. 별도 output-dir/report 경로로 실행하세요")
    rows, source_hash = read_source(source)
    train, final, kept, excluded = build_tables(rows)
    verify_expected(rows, train, final, kept, excluded)
    report = {
        "preprocess_version": "1.0",
        "source_name": source.name,
        "source_sha256": source_hash,
        "source_rows": len(rows),
        "retained_rows": len(kept),
        "excluded_rows": len(excluded),
        "exclusion_rule": "cand == A_own AND scope_a is false",
        "excluded_wrong": sum(not r["correct"] for r in excluded),
        "label_rule": "is_wrong = int(correct is false); original automatic label, not human-verified",
        "source_tasks": 46,
        "source_templates": 11,
        "splits": {"train": describe(train), "final": describe(final)},
        "truncated_result_rows": 823,
        "grounded_missing_reasons": {
            "truncated_result": sum(any(truncated(s) for s in r["steps"] if s["type"] == "tool") for r in kept),
            "no_answer_values_without_truncation": sum(
                not value_tokens(r["final"]) and not any(truncated(s) for s in r["steps"] if s["type"] == "tool")
                for r in kept
            ),
        },
        "feature_order": C.FEATURES,
        "rules": {
            "repeat": "extra occurrences of canonical(name,args), ignoring object key order",
            "empty": "root [] or known root collection lists; truncated JSON uses anchored prefix only; errors are not empty results",
            "says_none_regex": NONE_PATTERN.pattern,
            "asks_back_regex": ASK_PATTERN.pattern,
            "grounded": "unique (id,time,version) value coverage in recorded tool results; any truncation or no extracted answer values -> missing",
            "id_regex": ID_PATTERN.pattern,
            "time_regex": TIME_PATTERN.pattern,
            "version_regex": VERSION_PATTERN.pattern,
        },
        "checks": {
            "unique_run_ids": True,
            "no_run_task_template_overlap": True,
            "table_checks_passed": True,
            "expected_counts_match": True,
        },
        "limitations": [
            "Synthetic business environment; original gpt-4.1-mini experiment, not current 50-template pack.",
            "Original correct is an automatic substring label. No label recomputation or human confirmation performed.",
            "effect/data_fx.py and effect/run_fx.py were unavailable for this review.",
            "Expression regexes do not understand negation, quotations, or meaning; grounded_ratio is limited value occurrence, not factual correctness.",
            "600-character result truncation creates substantial missingness; missing is not zero.",
            "Only preprocessing completed. No model fitting, performance evaluation, or final-set model selection.",
        ],
    }
    payloads = [
        train.to_csv(index=False, na_rep="", lineterminator="\n"),
        final.to_csv(index=False, na_rep="", lineterminator="\n"),
    ]
    report["output_sha256"] = {
        p.name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for p, text in zip(destinations[:2], payloads, strict=True)
    }
    payloads.append(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise ValueError("원본이 전처리 중 바뀌었습니다")
    created = []
    try:
        for path, text in zip(destinations, payloads, strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="") as stream:
                created.append(path)
                stream.write(text)
    except Exception:
        for path in created:
            path.unlink()  # 이번 호출이 독점 생성한 불완전 결과만 제거한다.
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=C.ROOT / "data")
    parser.add_argument("--report", type=Path, default=C.REPORTS / "preprocessing_summary.json")
    args = parser.parse_args()
    summary = preprocess(args.source, args.output_dir, args.report)
    print(
        json.dumps(
            {
                "source_rows": summary["source_rows"],
                "excluded_rows": summary["excluded_rows"],
                "train_rows": summary["splits"]["train"]["rows"],
                "final_rows": summary["splits"]["final"]["rows"],
                "model_training_or_evaluation_run": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
