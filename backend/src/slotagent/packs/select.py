"""[②] 실험에 쓸 문항 고르기 — plan-proposal API 가 부름 (11/22 검토 3). ④는 이걸 직접 부르지 않고 API 로 받음.

    select_tasks(conn, pack_version_id, n_templates, split="held") -> [{task_id, batch_no}]
규칙: templates.split 이 같은 것만 (기본 held), 같은 문항 유형의 문항은 한 묶음에, 묶음은 1부터.
task_exposures 에 있는 문항(실패 내용을 본 문항)은 효과 판정의 '새 문항'에서 뺌.
"""


def select_tasks(conn, pack_version_id: int, n_templates: int, *, split: str = "held", looks: int = 1) -> list[dict]:
    raise NotImplementedError
