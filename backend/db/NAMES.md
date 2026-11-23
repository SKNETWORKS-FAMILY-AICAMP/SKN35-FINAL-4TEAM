# DB 이름 대응표 (ERD v1.2 이름 → 지금 DB 이름, 11/23 6차)

규칙은 `db/README.md`. 코드에서는 `slotagent.common.db_names` 의 `col(테이블, 짧은 칸)`·`plain(테이블, 행)` 을 씀.
6차부터 칸 이름은 ERD 이름과 거의 같음 — 다른 것은 PK(`id` → `<단수>_id`)와 `domains.code`, `exp_candidate_id`(trials·grader_checks), `condition_id` 뿐.
ERD·테이블 정의서를 고칠 때 이 표를 그대로 쓰면 됨. 이 파일은 db_names.py 와 같은 표에서 만듦.

## users → `sa_users`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `user_id` | PK |
| email | `email` |  |
| name | `name` |  |
| org_id | `org_id` |  |
| created_at | `created_at` |  |

## domains → `sa_domains`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| code | `domain_code` | PK |
| name | `name` |  |
| status | `status` |  |
| validated_at | `validated_at` |  |
| created_at | `created_at` |  |

## settings → `sa_settings`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `setting_id` | PK |
| scope | `scope` |  |
| scope_ref | `scope_ref` |  |
| key | `key` |  |
| value | `value` |  |
| valid_from | `valid_from` |  |
| note | `note` |  |

## agents → `sa_agents`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `agent_id` | PK |
| owner_id | `owner_id` | FK(역할) |
| name | `name` |  |
| purpose | `purpose` |  |
| created_at | `created_at` |  |
| expected_monthly_calls | `expected_monthly_calls` |  |
| domain_code | `domain_code` | FK |

## agent_versions → `sa_agent_versions`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `agent_version_id` | PK |
| agent_id | `agent_id` | FK |
| version_no | `version_no` |  |
| connection_type | `connection_type` |  |
| control_level | `control_level` |  |
| model | `model` |  |
| temperature | `temperature` |  |
| instructions | `instructions` |  |
| spec | `spec` |  |
| spec_schema_version | `spec_schema_version` |  |
| spec_hash | `spec_hash` |  |
| connection | `connection` |  |
| created_at | `created_at` |  |
| questions_used | `questions_used` |  |

## slots → `sa_slots`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `slot_id` | PK |
| agent_version_id | `agent_version_id` | FK |
| name | `name` |  |
| service | `service` |  |
| access | `access` |  |
| comparable | `comparable` |  |
| not_comparable_reason | `not_comparable_reason` |  |

## candidates → `sa_candidates`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `candidate_id` | PK |
| slot_id | `slot_id` | FK |
| label | `label` |  |
| name | `name` |  |
| component_kind | `component_kind` |  |
| component_spec | `component_spec` |  |
| spec_schema_version | `spec_schema_version` |  |
| spec_hash | `spec_hash` |  |
| is_baseline | `is_baseline` |  |
| created_at | `created_at` |  |

## pack_versions → `sa_pack_versions`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `pack_version_id` | PK |
| domain_code | `domain_code` | FK |
| pack_code | `pack_code` |  |
| version | `version` |  |
| status | `status` |  |
| premises | `premises` |  |
| locked_at | `locked_at` |  |
| created_at | `created_at` |  |

## data_snapshots → `sa_data_snapshots`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `data_snapshot_id` | PK |
| pack_version_id | `pack_version_id` | FK |
| source_kind | `source_kind` |  |
| location | `location` |  |
| design | `design` |  |
| content_hash | `content_hash` |  |
| frozen_at | `frozen_at` |  |

## templates → `sa_templates`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `template_id` | PK |
| pack_version_id | `pack_version_id` | FK |
| code | `code` |  |
| question_pattern | `question_pattern` |  |
| value_rule | `value_rule` |  |
| is_representative | `is_representative` |  |
| split | `split` |  |

## tasks → `sa_tasks`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `task_id` | PK |
| template_id | `template_id` | FK |
| code | `code` |  |
| prompt | `prompt` |  |
| slot_values | `slot_values` |  |
| seed | `seed` |  |

## answer_conditions → `sa_answer_conditions`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `answer_condition_id` | PK |
| task_id | `task_id` | FK |
| seq | `seq` |  |
| kind | `kind` |  |
| spec | `spec` |  |
| spec_schema_version | `spec_schema_version` |  |

## golden_trajectories → `sa_golden_trajectories`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `golden_trajectory_id` | PK |
| template_id | `template_id` | FK |
| kind | `kind` |  |
| trace | `trace` |  |
| expected | `expected` |  |

## env_checks → `sa_env_checks`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `env_check_id` | PK |
| pack_version_id | `pack_version_id` | FK |
| kind | `kind` |  |
| target | `target` |  |
| result | `result` |  |
| detail | `detail` |  |
| checked_by | `checked_by` | FK(역할) |
| checked_at | `checked_at` |  |

## task_exposures → `sa_task_exposures`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `task_exposure_id` | PK |
| task_id | `task_id` | FK |
| seen_by | `seen_by` | FK(역할) |
| reason | `reason` |  |
| seen_at | `seen_at` |  |

## experiments → `sa_experiments`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `experiment_id` | PK |
| derived_from | `derived_from` | FK(역할, 원본 실험) |
| kind | `kind` |  |
| agent_version_id | `agent_version_id` | FK |
| slot_id | `slot_id` | FK |
| pack_version_id | `pack_version_id` | FK |
| reps | `reps` |  |
| prereg | `prereg` |  |
| prereg_schema_version | `prereg_schema_version` |  |
| plan | `plan` |  |
| budget_krw | `budget_krw` |  |
| status | `status` |  |
| stop_reason | `stop_reason` |  |
| exploratory | `exploratory` |  |
| locked_at | `locked_at` |  |
| created_by | `created_by` | FK(역할) |
| created_at | `created_at` |  |

## experiment_candidates → `sa_experiment_candidates`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `experiment_candidate_id` | PK |
| experiment_id | `experiment_id` | FK |
| candidate_id | `candidate_id` | FK |
| label | `label` |  |
| role | `role` |  |
| variant | `variant` |  |
| config_snapshot | `config_snapshot` |  |
| config_hash | `config_hash` |  |

## jobs → `sa_jobs`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `job_id` | PK |
| kind | `kind` |  |
| payload | `payload` |  |
| status | `status` |  |
| priority | `priority` |  |
| attempts | `attempts` |  |
| leased_by | `leased_by` |  |
| lease_until | `lease_until` |  |
| last_error | `last_error` |  |
| created_at | `created_at` |  |
| updated_at | `updated_at` |  |

## trials → `sa_trials`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `trial_id` | PK |
| experiment_id | `experiment_id` | FK |
| exp_candidate_id | `experiment_candidate_id` | FK |
| task_id | `task_id` | FK |
| rep | `rep` |  |
| batch_no | `batch_no` |  |
| status | `status` |  |
| run_outcome | `run_outcome` |  |
| outcome_reason | `outcome_reason` |  |
| run_no | `run_no` |  |
| api_retries | `api_retries` |  |
| attempt | `attempt` |  |
| record_source | `record_source` |  |
| signature | `signature` |  |
| started_at | `started_at` |  |
| finished_at | `finished_at` |  |
| in_tokens | `in_tokens` |  |
| out_tokens | `out_tokens` |  |
| tool_desc_tokens | `tool_desc_tokens` |  |
| cost_krw | `cost_krw` |  |
| llm_sec | `llm_sec` |  |
| tool_sec | `tool_sec` |  |
| wait_sec | `wait_sec` |  |
| final_answer | `final_answer` |  |
| harness_version | `harness_version` |  |

## spans → `sa_spans`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `span_id` | PK |
| trial_id | `trial_id` | FK |
| attempt | `attempt` |  |
| seq | `seq` |  |
| kind | `kind` |  |
| name | `name` |  |
| started_at | `started_at` |  |
| duration_sec | `duration_sec` |  |
| wait_sec | `wait_sec` |  |
| in_tokens | `in_tokens` |  |
| out_tokens | `out_tokens` |  |
| tool_args | `tool_args` |  |
| tool_result | `tool_result` |  |
| error | `error` |  |
| attributes | `attributes` |  |
| output | `output` |  |

## write_intents → `sa_write_intents`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `write_intent_id` | PK |
| trial_id | `trial_id` | FK |
| span_id | `span_id` | FK |
| tool_name | `tool_name` |  |
| payload | `payload` |  |
| in_rule_list | `in_rule_list` |  |
| user_confirmed | `user_confirmed` |  |
| created_at | `created_at` |  |

## grading_runs → `sa_grading_runs`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `grading_run_id` | PK |
| experiment_id | `experiment_id` | FK |
| pack_version_id | `pack_version_id` | FK |
| grader_version | `grader_version` |  |
| judge_model | `judge_model` |  |
| judge_settings | `judge_settings` |  |
| purpose | `purpose` |  |
| upto_batch_no | `upto_batch_no` |  |
| started_at | `started_at` |  |
| finished_at | `finished_at` |  |

## condition_results → `sa_condition_results`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `condition_result_id` | PK |
| grading_run_id | `grading_run_id` | FK |
| trial_id | `trial_id` | FK |
| condition_id | `answer_condition_id` | FK |
| passed | `passed` |  |
| evidence | `evidence` |  |

## llm_votes → `sa_llm_votes`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `llm_vote_id` | PK |
| grading_run_id | `grading_run_id` | FK |
| trial_id | `trial_id` | FK |
| question_kind | `question_kind` |  |
| vote_no | `vote_no` |  |
| model | `model` |  |
| answer | `answer` |  |
| quote | `quote` |  |

## trial_grades → `sa_trial_grades`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `trial_grade_id` | PK |
| grading_run_id | `grading_run_id` | FK |
| trial_id | `trial_id` | FK |
| grade_status | `grade_status` |  |
| success | `success` |  |
| result_class | `result_class` |  |
| first_fail_type | `first_fail_type` |  |
| fail_tags | `fail_tags` |  |
| out_of_scope | `out_of_scope` |  |
| forbidden_action | `forbidden_action` |  |
| judge_status | `judge_status` |  |
| unmeasurable | `unmeasurable` |  |
| metrics | `metrics` |  |

## labels → `sa_labels`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `label_id` | PK |
| grading_run_id | `grading_run_id` | FK |
| trial_id | `trial_id` | FK |
| labeler_id | `labeler_id` | FK(역할) |
| sampled_as | `sampled_as` |  |
| human_success | `human_success` |  |
| human_result_class | `human_result_class` |  |
| blind | `blind` |  |
| created_at | `created_at` |  |

## grader_checks → `sa_grader_checks`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `grader_check_id` | PK |
| grading_run_id | `grading_run_id` | FK |
| kind | `kind` |  |
| exp_candidate_id | `experiment_candidate_id` | FK |
| question_kind | `question_kind` |  |
| n | `n` |  |
| value | `value` |  |
| passed | `passed` |  |
| created_at | `created_at` |  |

## analyses → `sa_analyses`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `analysis_id` | PK |
| experiment_id | `experiment_id` | FK |
| grading_run_id | `grading_run_id` | FK |
| method | `method` |  |
| code_version | `code_version` |  |
| input_hash | `input_hash` |  |
| is_interim | `is_interim` |  |
| batch_no | `batch_no` |  |
| created_at | `created_at` |  |

## comparisons → `sa_comparisons`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `comparison_id` | PK |
| analysis_id | `analysis_id` | FK |
| exp_candidate_id | `exp_candidate_id` | FK(역할) |
| baseline_id | `baseline_id` | FK(역할) |
| metric | `metric` |  |
| diff | `diff` |  |
| ci_low | `ci_low` |  |
| ci_high | `ci_high` |  |
| ci_level | `ci_level` |  |
| p_value | `p_value` |  |
| n_tasks | `n_tasks` |  |
| n_templates | `n_templates` |  |
| regression_rate | `regression_rate` |  |
| verdict | `verdict` |  |
| reason | `reason` |  |
| extra_needed | `extra_needed` |  |
| exclusions | `exclusions` |  |

## reports → `sa_reports`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `report_id` | PK |
| experiment_id | `experiment_id` | FK |
| analysis_id | `analysis_id` | FK |
| kind | `kind` |  |
| content | `content` |  |
| file_path | `file_path` |  |
| share_token_hash | `share_token_hash` |  |
| share_revoked_at | `share_revoked_at` |  |
| share_expires_at | `share_expires_at` |  |
| created_at | `created_at` |  |

## chat_messages → `sa_chat_messages`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `chat_message_id` | PK |
| conversation_id | `conversation_id` |  |
| user_id | `user_id` | FK |
| role | `role` |  |
| content | `content` |  |
| function_name | `function_name` |  |
| function_args | `function_args` |  |
| cited_experiment_ids | `cited_experiment_ids` |  |
| user_confirmed | `user_confirmed` |  |
| created_at | `created_at` |  |

## validation_runs → `sa_validation_runs`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `validation_run_id` | PK |
| domain_code | `domain_code` | FK |
| kind | `kind` |  |
| experiment_id | `experiment_id` | FK |
| pack_version_id | `pack_version_id` | FK |
| params | `params` |  |
| result | `result` |  |
| passed | `passed` |  |
| started_at | `started_at` |  |
| finished_at | `finished_at` |  |

## cost_ledger → `sa_cost_ledger`

| ERD v1.2 | 지금 DB | 종류 |
|---|---|---|
| id | `cost_ledger_id` | PK |
| occurred_at | `occurred_at` |  |
| source | `source` |  |
| ref_id | `ref_id` |  |
| experiment_id | `experiment_id` | FK |
| model | `model` |  |
| in_tokens | `in_tokens` |  |
| out_tokens | `out_tokens` |  |
| cost_krw | `cost_krw` |  |
| price_setting_id | `price_setting_id` | FK(역할) |
