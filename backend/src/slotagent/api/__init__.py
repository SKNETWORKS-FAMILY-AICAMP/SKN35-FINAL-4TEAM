"""[공동, 1차 ①] FastAPI. 여러 역할이 함께 쓰는 폴더라 파일 이름 앞에 역할 접두사 (eng_ ① · pack_ ② · stats_ ③ · intake_ ④):
  intake_agents.py(④)    POST /api/agents, POST /api/slots/{id}/candidates, POST /api/experiments
  pack_packs.py(②)       GET /api/packs
  eng_plan_proposal.py(①) POST /api/experiments/plan-proposal (본체는 common.proposal)
  eng_experiments.py(①)  POST /api/experiments/{id}/run, POST .../stop, GET .../status
  stats_results.py(③)    GET /api/experiments/{id}/results, GET /api/reports/{id}, GET /api/shared/{token}
  intake_chat.py(④)
요청·응답은 contracts api 스키마. DB 거절은 eng_errors.py 에서 api.error 로 (HINT → 제약 이름 순)."""
