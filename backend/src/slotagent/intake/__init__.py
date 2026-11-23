"""[④ 연결] 에이전트·자리·후보 등록, 실험 초안.

쓰는 테이블: agents, agent_versions, slots, candidates, experiments(status=draft), experiment_candidates
넘겨주는 것: experiment_id 하나 (① 실행 API 가 받음)
지킬 것: 저장 전에 contracts.validate() + common.checks, 후보를 넣을 때 common.snapshot.build_config_snapshot() 호출
prereg·plan 값은 직접 만들지 않음 → POST /api/experiments/plan-proposal 응답을 그대로 저장
"""
