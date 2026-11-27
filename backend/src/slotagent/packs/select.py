"""[②] 실험에 쓸 문항 고르기 — plan-proposal API 가 부름 (11/22 검토 3). ④는 이걸 직접 부르지 않고 API 로 받음.

    select_tasks(conn, pack_version_id, n_templates, split="held") -> [{task_id, batch_no}]
규칙: templates.split 이 같은 것만 (기본 held), 같은 문항 유형의 문항은 한 묶음에, 묶음은 1부터.
task_exposures 에 있는 문항(실패 내용을 본 문항)은 효과 판정의 '새 문항'에서 뺌.
"""

from datetime import datetime
from hashlib import sha256


def plan_rows(rows, n_templates: int, looks: int = 1, *, seed: str | None = None,
              allow_shortfall: bool = False) -> list[dict]:
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
    if allow_shortfall and available:
        n_templates = min(n_templates, len(available))
        if looks > n_templates:
            raise ValueError("looks cannot exceed available templates")
    if len(available) < n_templates:
        raise ValueError(f"Need {n_templates} fresh templates, only {len(available)} available")
    if seed is not None:
        available.sort(key=lambda template_id: sha256(f"{seed}:{template_id}".encode()).digest())
    return [{"task_id": task_id, "batch_no": index * looks // n_templates + 1}
            for index, template_id in enumerate(available[:n_templates]) for task_id in sorted(groups[template_id])]


def select_tasks(conn, pack_version_id: int, n_templates: int, *, split: str = "held", looks: int = 1,
                 as_of: datetime | None = None, seed: str | None = None,
                 allow_shortfall: bool = False) -> list[dict]:
    if split not in {"dev", "held"}:
        raise ValueError("split must be dev or held")
    status = conn.execute("SELECT status FROM sa_pack_versions WHERE pack_version_id=%s", (pack_version_id,)).fetchone()
    if status is None or status[0] != "locked":
        raise ValueError("Only a locked pack can be selected for experiments")
    rows = conn.execute(
        "SELECT t.template_id,k.task_id,EXISTS(SELECT 1 FROM sa_task_exposures e "
        "WHERE e.task_id=k.task_id AND (%s::timestamptz IS NULL OR e.seen_at <= %s)) "
        "FROM sa_templates t JOIN sa_tasks k USING(template_id) WHERE t.pack_version_id=%s AND t.split=%s "
        "ORDER BY t.template_id,k.task_id", (as_of, as_of, pack_version_id, split),
    ).fetchall()
    return plan_rows(rows, n_templates, looks, seed=seed, allow_shortfall=allow_shortfall)
