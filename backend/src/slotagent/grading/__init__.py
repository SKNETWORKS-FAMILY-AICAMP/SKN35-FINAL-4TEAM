"""[①② 채점] 한 grading_run 안에서: ① 규칙 채점 → ② LLM 판정·결과 3분류·첫 실패 단계 → trial_grades.

여러 역할이 함께 쓰는 폴더라 파일 이름 앞에 역할 접두사:
  eng_pipeline.py·eng_rules.py = ①, pack_judge.py·pack_classify.py·pack_validate.py(채점 검증) = ②
넘겨주는 것: grading_runs.finished_at (DB가 빠진 채점이 없는지 확인) → analyze 작업
"""
