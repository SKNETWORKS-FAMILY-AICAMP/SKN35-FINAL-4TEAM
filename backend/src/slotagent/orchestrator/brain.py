"""오케스트레이터의 LLM 부분: 목표 정리·후보 고른 이유·결과 설명. common/llm.py 의 ChatModel 로만 부릅니다.

숫자는 만들지 않습니다. 후보 ID 는 그래프가 거른 목록 안에서만 쓰고, 설명의 숫자는 넘겨준 DB 값 그대로 + 근거 ID.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from slotagent.common.llm import ChatModel, ModelError, Price

FOCUS = ("cost", "accuracy", "latency")
# 숫자는 facts 로 코드가 보여 주므로 모델 글에는 "숫자 값을 가진 글자"(아라비아·전각·분수·첨자·원 문자·로마·한자 수)와
# 퍼센트 표기를 두지 않음. 말로 쓴 수량("절반", "두 배", "twice")은 글자 검사로 보증할 수 없어 막지 않음 —
# 글은 참고 설명이고 수치·판정의 원본은 facts (설계 3절). 단어 목록은 정상 용어(프로세스·CLI 등)까지 막아 쓰지 않음.
_PERCENT = re.compile(r"[%％]|퍼센트|percent", re.IGNORECASE)


def prose_problems(text: str) -> list[str]:
    """모델 설명 글을 저장해도 되는지. 비면 통과."""
    hits = sorted({c for c in text if unicodedata.numeric(c, None) is not None}
                  | {m.group(0) for m in _PERCENT.finditer(text)})
    return [f"설명 글에 숫자·수치 표현: {', '.join(hits)}"] if hits else []


NUMBERS = "숫자·퍼센트를 쓰지 마세요. 수치와 근거 ID 는 화면이 저장된 값으로 따로 보여 줍니다. 판정 이름(verdict)으로 설명하세요."


@dataclass
class LLMBrain:
    model: ChatModel
    provider: str
    model_name: str
    price: Price = field(default_factory=Price)

    def _ask(self, system: str, payload: dict) -> str:
        reply = self.model.chat(
            provider=self.provider, model=self.model_name,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
            tools=[], temperature=0, seed=0, max_tokens=None, max_api_retries=2, timeout_sec=60, price=self.price,
        )
        if not isinstance(reply.text, str):
            raise ModelError("bad_reply")
        return reply.text

    def _json(self, system: str, payload: dict) -> dict:
        try:
            out = json.loads(self._ask(system + " JSON 객체 하나만 답하세요.", payload))
        except ValueError:
            return {}
        return out if isinstance(out, dict) else {}

    def goal(self, text: str) -> dict:
        out = self._json('사용자의 비교 목표에서 관심 축을 고르세요. {"focus": ["cost"|"accuracy"|"latency", ...]}',
                         {"text": text})
        focus = out.get("focus") if isinstance(out.get("focus"), list) else []
        return {"focus": [f for f in FOCUS if f in focus], "text": text}

    def pick(self, goal: dict, candidates: list[dict]) -> dict:
        out = self._json('목표에 맞는 후보를 최대 2개 고르고 이유를 쓰세요. {"candidate_ids": [...], "reason": "..."}',
                         {"goal": goal, "candidates": candidates})
        ids = out.get("candidate_ids")
        return {"candidate_ids": [i for i in ids if type(i) is int] if isinstance(ids, list) else [],
                "reason": str(out.get("reason", ""))}

    def explain(self, goal: dict, result: dict) -> str:
        return self._ask("저장된 통계 판정과 리포트를 근거로 목표에 맞춰 결과를 설명하세요. " + NUMBERS,
                         {"goal": goal, "result": result})

