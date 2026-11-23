"""[④ chatbot] 정해진 함수 5개만: get_results, create_experiment, calc_sample_size, start_run, write_report.

start_run·create_experiment 는 user_confirmed 뒤에만 (DB도 막음). 답에 쓴 수치는 reports.content 와 대조, cited_experiment_ids 기록.
create_experiment → intake.service, start_run → engine.lock (API 를 거쳐), calc_sample_size → POST /api/experiments/plan-proposal (stats 를 직접 부르지 않음)
함수 인자(chat_messages.function_args)는 contracts chat 스키마 — validate("chat", args, part=function_name) (3차 2)
"""
