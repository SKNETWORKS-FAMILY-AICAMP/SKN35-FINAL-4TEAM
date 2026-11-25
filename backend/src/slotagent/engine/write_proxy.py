"""① 쓰기 도구와 엔진 내장 도구를 외부로 보내지 않고 처리합니다 (FR-RUN-03, P-05).

풀이(시도) 하나에 객체 하나입니다. 승인 여부는 저장한 boolean 이 아니라 지금 시도의 trace 를 다시 읽어 정합니다.
승인 없는 쓰기는 막고 기록하며, 승인된 쓰기도 실제로 보내지 않습니다.
"""

from __future__ import annotations

import copy
import json
import math

from slotagent.common import contracts
from slotagent.common.confirmation import approved_write, argument_values, fixed_response
from slotagent.engine import write_scenario

CONFIRM = "request_user_confirmation"
WRITE_RESULT = "get_write_result"
WORK_STATE = "get_work_state"


def _builtin(name, description, properties):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        },
        "service": "slotagent",
        "access": "read",
        "origin": "builtin",
    }


_TEXT = {"type": "string", "minLength": 1}
CONFIRM_TOOL = _builtin(
    CONFIRM,
    "쓰기 도구를 부르기 전에 사용자에게 확인을 요청합니다. 실행하려는 도구 이름과 전체 인자를 그대로 적습니다. "
    "decision 이 approve 이면 승인한 도구와 인자 그대로 다음 쓰기 한 번만 실행할 수 있습니다.",
    {
        "action": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tool_name", "arguments"],
            "properties": {"tool_name": _TEXT, "arguments": {"type": "object"}},
        }
    },
)
WRITE_RESULT_TOOL = _builtin(
    WRITE_RESULT, "쓰기 응답의 write_ref 로 그 쓰기가 실제로 반영됐는지 조회합니다.", {"write_ref": _TEXT}
)
WORK_STATE_TOOL = _builtin(WORK_STATE, "업무 대상의 지금 상태와 버전을 조회합니다.", {"subject": _TEXT})


class InvalidCall(ValueError):
    """모델이 만든 호출이 계약에 맞지 않습니다. 풀이를 끝내지 않고 모델에 돌려줍니다."""


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


def fill_defaults(schema, value):
    """도구 스키마의 properties.default 만 채웁니다. 확인 요청과 실제 쓰기에 같이 씁니다."""
    if not isinstance(schema, dict) or not isinstance(value, dict):
        return copy.deepcopy(value)
    result = copy.deepcopy(value)
    for name, child in schema.get("properties", {}).items():
        if not isinstance(child, dict):
            continue
        if name in result:
            result[name] = fill_defaults(child, result[name])
        elif "default" in child:
            result[name] = copy.deepcopy(child["default"])
    return result


class WriteProxy:
    def __init__(self, snapshot: dict, confirmation: dict | None = None, scenario: dict | None = None):
        if confirmation is not None:
            contracts.validate("confirmation", confirmation, part="policy")
        self.policy = copy.deepcopy(confirmation)
        self.scenario = write_scenario.validate(scenario)
        self.definitions = {t["name"]: t for t in snapshot["tools"]}
        self.capabilities = {t["name"]: list(t.get("capabilities", [])) for t in snapshot["tools"]}
        self.rule_list = set(snapshot["write_tools"])
        self.writes = {t["name"] for t in snapshot["tools"] if t["access"] == "write"} | self.rule_list
        for name in self.writes:
            mode = self.definitions.get(name, {}).get("write_mode", "fake")
            if mode not in {"fake", "exclude_tasks"}:
                raise NotImplementedError(f"{mode} 쓰기 실행은 러너·API 연결에서 다룹니다.")
        # 확인 도구는 모든 후보에, 상태 도구는 시나리오 문항에만 줍니다. 같은 문항이면 후보가 달라도 같습니다.
        self.tools = [CONFIRM_TOOL]
        if self.scenario is not None:
            self.tools.append(WRITE_RESULT_TOOL)
            if self.scenario.get("states"):
                self.tools.append(WORK_STATE_TOOL)
        self.builtins = {t["name"]: t for t in self.tools}
        clash = sorted({CONFIRM, WRITE_RESULT, WORK_STATE} & set(self.definitions))
        if clash:
            raise ValueError("후보 도구 이름이 엔진 내장 도구와 겹칩니다: " + ", ".join(clash))
        self.intents: list[dict] = []
        self.ledger: dict[str, dict] = {}
        self.used: dict[int, int] = {}
        self.approvals = 0

    def handles(self, name: str) -> bool:
        return name in self.builtins or name in self.writes

    def normalize(self, name: str, args: dict) -> dict:
        """기록과 승인 비교에 쓰는 전체 인자. 모델이 낸 원문은 llm span 의 tool_calls 에 남습니다."""
        if not _finite(args):
            raise InvalidCall("유한하지 않은 숫자")
        if name in self.writes:
            return fill_defaults(self.definitions[name]["parameters"], args)
        if name == CONFIRM:
            try:
                contracts.validate("confirmation", args, part="request")
            except contracts.ContractError as exc:
                raise InvalidCall(str(exc)) from None
            target = self.definitions.get(args["action"]["tool_name"])
            if target is not None:
                args = copy.deepcopy(args)
                args["action"]["arguments"] = fill_defaults(target["parameters"], args["action"]["arguments"])
        return args

    def run(self, name: str, args: dict, span: dict, spans: list[dict]) -> tuple[str, dict]:
        """(모델이 받을 결과, span attributes). span 은 아직 넣지 않은 예정 span(seq·started_at)입니다."""
        if name in self.builtins:
            return _dump(self._builtin(name, args, spans)), {"origin": "builtin"}
        return self._write(name, args, span, spans)

    def _builtin(self, name, args, spans):
        if name == CONFIRM:
            # 형식이 틀린 요청도 순번을 하나 씁니다 (P-05). 순번은 이 시도의 기록에서 셉니다.
            index = sum(s["kind"] == "tool" and s["name"] == CONFIRM for s in spans)
            answer = fixed_response(self.policy, args, index, self.capabilities)
            self.approvals += answer["decision"] == "approve"
            return answer
        if name == WRITE_RESULT:
            entry = self.ledger.get(args["write_ref"])
            if entry is None:
                return {"write_ref": args["write_ref"], "status": "not_found"}
            answer = {"write_ref": args["write_ref"], "status": "applied" if entry["applied"] else "not_applied"}
            if entry["applied"] and entry["result"]:
                answer["result"] = entry["result"]
            return answer
        for state in self.scenario["states"]:
            if state["subject"] == args["subject"]:
                visible = [v["value"] for v in state["versions"] if v["from_approvals"] <= self.approvals]
                return {"subject": args["subject"], "status": "found", "value": visible[-1]}
        return {"subject": args["subject"], "status": "not_found"}

    def _write(self, name, args, span, spans):
        seq = span["seq"]
        confirms = [s["seq"] for s in spans if s["kind"] == "tool" and s["name"] == CONFIRM]
        attributes = {"write_mode": self.definitions[name].get("write_mode", "fake")}
        planned = {**span, "kind": "tool", "name": name, "duration_sec": 0, "tool_args": args}
        planned["attributes"] = dict(attributes)
        if confirms:
            planned["attributes"]["confirmation_span_seq"] = confirms[-1]
        trace = {"schema_version": 1, "spans": [*spans, planned], "write_intents": [], "final_answer": None}
        approved = name in self.rule_list and approved_write(self.policy, trace, seq, self.writes, self.capabilities)
        self.intents.append(
            {
                "span_seq": seq,
                "tool_name": name,
                "payload": copy.deepcopy(args),
                "in_rule_list": name in self.rule_list,
                "user_confirmed": approved,
            }
        )
        if not approved:
            attributes.update(write_status="blocked", write_applied=False)
            return _dump({"fake": True, "status": "blocked", "reason": "user_confirmation_required"}), attributes
        attributes["confirmation_span_seq"] = confirms[-1]
        ref = f"w{len(self.ledger) + 1}"
        outcome = self._outcome(name, args)
        status = outcome["status"]
        applied = outcome.get("applied", status == "ok")
        self.ledger[ref] = {"applied": applied, "result": outcome.get("result")}
        attributes.update(write_status=status, write_applied=applied, write_ref=ref)
        if outcome.get("raw") is not None:
            return outcome["raw"], attributes
        answer = {"fake": True, "status": status}
        if self.scenario is not None:
            answer["write_ref"] = ref
        if outcome.get("reason"):
            answer["reason"] = outcome["reason"]
        if status == "ok" and outcome.get("result"):
            answer["result"] = outcome["result"]
        return _dump(answer), attributes

    def _outcome(self, name, args):
        values = set(argument_values(args))
        for number, rule in enumerate((self.scenario or {}).get("writes", [])):
            if rule["capability"] in self.capabilities[name] and set(rule["target"]) <= values:
                count = self.used.get(number, 0)
                self.used[number] = count + 1
                return rule["outcomes"][min(count, len(rule["outcomes"]) - 1)]
        for fixed in self.definitions[name].get("fixed_responses", []):
            # tool_def: 인자가 맞는 첫 항목. 시나리오 문항에서는 write_ref 가 있는 공통 응답을 씁니다.
            if self.scenario is None and all(k in args and args[k] == v for k, v in fixed["when"].items()):
                return {"status": "ok", "raw": fixed["result"]}
        return {"status": "ok"}
