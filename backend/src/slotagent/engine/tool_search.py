"""① 도구 검색 후보 실행. 계약: config_snapshot.tool_search (component_spec.tool_search).

deferred 도구를 처음에는 숨기고 검색 도구 하나를 엽니다. 검색으로 찾은 도구는 다음 모델 호출부터 보입니다.
검색은 LLM 없이 BM25(rank-bm25)로만 하므로 같은 질의에는 항상 같은 순서가 나옵니다.
"""

from __future__ import annotations

import re
import unicodedata

from rank_bm25 import BM25Plus

SEARCH = "search_tools"
SEARCH_TOOL = {
    "name": SEARCH,
    "description": "지금 보이는 도구로 할 수 없는 일이 있을 때 다른 도구를 찾습니다. "
    "하려는 일의 핵심 낱말을 query 에 적습니다 (도구 설명이 영어일 수 있으니 영어 낱말도 함께). "
    "찾은 도구는 다음 응답부터 쓸 수 있습니다.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 500}},
    },
    "service": "slotagent",
    "access": "read",
    "origin": "builtin",
}


def tokenize(text: str) -> list[str]:
    """영문·숫자는 낱말(camelCase·snake_case 나눔, 복수형 s 뗌), 한글은 두 글자씩. 조사가 붙어도 겹치는 조각이 남습니다."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text).casefold()
    tokens = []
    for run in re.findall(r"[a-z0-9]+|[가-힣]+", text):
        if run[0] >= "가" and len(run) > 2:
            tokens += [run[i : i + 2] for i in range(len(run) - 1)]
        else:
            tokens.append(run[:-1] if len(run) > 3 and run.endswith("s") and not run.endswith("ss") else run)
    return tokens


def _document(tool: dict) -> list[str]:
    """모델이 볼 수 있는 이름·설명·인자만 씁니다. 이름표(capabilities)는 채점용이라 넣지 않습니다."""
    parts = [tool["name"], tool["description"]]
    for name, child in tool["parameters"].get("properties", {}).items():
        parts.append(name)
        if isinstance(child, dict) and isinstance(child.get("description"), str):
            parts.append(child["description"])
    return tokenize(" ".join(parts))


class ToolSearch:
    """풀이(시도) 하나에 객체 하나입니다. 불러온 도구 목록이 시도마다 비어 있어야 합니다."""

    def __init__(self, snapshot: dict):
        config = snapshot["tool_search"]
        if config["method"] != "bm25":
            raise NotImplementedError("도구 검색은 bm25 만 지원합니다.")
        tools = {t["name"]: t for t in snapshot["tools"]}
        if SEARCH in tools:
            raise ValueError(f"후보 도구 이름이 검색 도구와 겹칩니다: {SEARCH}")
        missing = sorted(set(config["deferred"]) - set(tools))
        if missing:
            raise ValueError("검색할 도구가 스냅숏에 없습니다: " + ", ".join(missing))
        self.top_k = config["top_k"]
        self.names = sorted(config["deferred"])
        self.hidden = set(self.names)
        documents = [_document(tools[name]) for name in self.names]
        self._words = [set(d) for d in documents]
        # Okapi 는 도구가 2~3개일 때 idf 가 0 이나 음수가 되어 순서가 뒤집힙니다. Plus 의 idf 는 항상 양수입니다.
        self._index = BM25Plus([d or [""] for d in documents])

    def search(self, query: str) -> list[str]:
        """점수순 top_k 개. 겹치는 낱말이 없는 도구는 빼고, 동점은 이름순입니다."""
        words = tokenize(query)
        scores = self._index.get_scores(words)
        ranked = [
            (-round(float(score), 9), name)
            for name, score, own in zip(self.names, scores, self._words, strict=True)
            if own & set(words)
        ]
        return [name for _, name in sorted(ranked)[: self.top_k]]

    def run(self, args: dict) -> tuple[dict, dict]:
        """(모델이 받을 결과, span attributes). 찾은 도구는 다음 모델 호출부터 보입니다."""
        found = self.search(args["query"])
        loaded = [name for name in found if name in self.hidden]
        self.hidden -= set(found)
        answer = {"tools": found} if found else {"tools": [], "note": "맞는 도구가 없습니다. 다른 낱말로 찾아보세요."}
        return answer, {"origin": "builtin", "tool_search.found": found, "tool_search.loaded": loaded}
