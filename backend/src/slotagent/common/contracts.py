"""contracts/schemas 의 JSON Schema 로 검사 (담당 ①, 모두 사용).

    validate("component_spec", obj)
    validate("grading", obj, part="judge_settings")      # $defs 안의 모양
    validate("answer_condition", spec, part=kind)         # answer_conditions.kind 칸 값

DB에 jsonb 를 넣기 전에 반드시 부른다. 틀리면 ContractError (api 에서 code=invalid_spec 로 바뀜).
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[4] / "contracts" / "schemas"
BASE = "https://slotagent.local/schemas/"


class ContractError(ValueError):
    def __init__(self, name: str, errors: list[str]):
        self.name, self.errors = name, errors
        super().__init__(f"{name} 형식 오류: " + "; ".join(errors[:5]))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for p in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def schema_names() -> list[str]:
    return sorted(p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json"))


@lru_cache(maxsize=None)
def _validator(name: str, part: str | None) -> Draft202012Validator:
    ref = BASE + f"{name}.schema.json" + (f"#/$defs/{part}" if part else "")
    return Draft202012Validator({"$ref": ref}, registry=_registry(), format_checker=FormatChecker())


def errors(name: str, obj: Any, part: str | None = None) -> list[str]:
    v = _validator(name, part)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(맨 위)'}: {e.message}" for e in v.iter_errors(obj)]


def validate(name: str, obj: Any, part: str | None = None) -> Any:
    errs = errors(name, obj, part)
    if errs:
        raise ContractError(name + (f".{part}" if part else ""), errs)
    return obj
