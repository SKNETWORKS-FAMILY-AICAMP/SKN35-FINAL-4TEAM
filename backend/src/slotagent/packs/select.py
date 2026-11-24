"""[②] 실험에 쓸 문항 고르기 — plan-proposal API 가 부름 (11/22 검토 3). ④는 이걸 직접 부르지 않고 API 로 받음.

    select_tasks(conn, pack_version_id, n_templates, split="held") -> [{task_id, batch_no}]
규칙: templates.split 이 같은 것만 (기본 held), 같은 문항 유형의 문항은 한 묶음에, 묶음은 1부터.
task_exposures 에 있는 문항(실패 내용을 본 문항)은 효과 판정의 '새 문항'에서 뺌.
"""


def plan_rows(rows, n_templates: int, looks: int = 1) -> list[dict]:
    """rows=(template_id, task_id, exposed). 노출된 문항이 있는 유형 전체를 제외한다."""
    for value in (n_templates, looks):
        if type(value) is not int or value < 1:
            raise ValueError("n_templates and looks must be positive integers")
    if looks > n_templates:
        raise ValueError("looks cannot exceed n_templates")
    groups = {}
    exposed_templates = set()
    for template_id, task_id, exposed in rows:
        groups.setdefault(template_id, set()).add(task_id)
        if exposed:
            exposed_templates.add(template_id)
    available = sorted(t for t in groups if t not in exposed_templates)
    if len(available) < n_templates:
        raise ValueError(f"Need {n_templates} fresh templates, only {len(available)} available")
    return [{"task_id": task_id, "batch_no": index * looks // n_templates + 1}
            for index, template_id in enumerate(available[:n_templates]) for task_id in sorted(groups[template_id])]


def select_tasks(conn, pack_version_id: int, n_templates: int, *, split: str = "held", looks: int = 1) -> list[dict]:
    if split not in {"dev", "held"}:
        raise ValueError("split must be dev or held")
    status = conn.execute("SELECT status FROM sa_pack_versions WHERE pack_version_id=%s", (pack_version_id,)).fetchone()
    if status is None or status[0] != "locked":
        raise ValueError("Only a locked pack can be selected for experiments")
    rows = conn.execute(
        "SELECT t.template_id,k.task_id,EXISTS(SELECT 1 FROM sa_task_exposures e WHERE e.task_id=k.task_id) "
        "FROM sa_templates t JOIN sa_tasks k USING(template_id) WHERE t.pack_version_id=%s AND t.split=%s "
        "ORDER BY t.template_id,k.task_id", (pack_version_id, split),
    ).fetchall()
    return plan_rows(rows, n_templates, looks)
