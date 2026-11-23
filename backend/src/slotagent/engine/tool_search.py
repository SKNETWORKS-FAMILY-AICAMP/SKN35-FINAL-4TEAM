"""[①] 도구 검색 후보 실행 자리 (W5). config_snapshot.tool_search 가 있으면 deferred 도구를 숨기고
검색 도구 하나를 열어, BM25(rank-bm25)로 찾은 top_k 개의 설명만 모델에게 넣는다. 계약: component_spec.tool_search."""
