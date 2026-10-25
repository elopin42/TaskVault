"""The candidate score — deterministic, no AI (SPEC §4).

    score = 40 · [≥1 task `paid` for THIS company]
          + 8 · avg_note given by THIS company (0 without rating)
          + 20 · (common tags / task tags)      (0 when the task has no tags)

Max 100, stored rounded to 1 decimal. "Validated" = paid_count ≥ 1 AND avg_note ≥ 3 for the
company looking at the candidate; "Recommended" = the single best score among the task's
pending applications (ties → the earliest application), only while the task is open.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count

from .models import Rating, Task

HISTORY_POINTS = Decimal("40")
RATING_FACTOR = Decimal("8")
TAGS_POINTS = Decimal("20")
VALIDATED_MIN_NOTE = Decimal("3")
ONE_PLACE = Decimal("0.1")


def company_history(company, freelancer) -> dict:
    """{paid_count, avg_note} of `freelancer` with THIS `company` (avg_note is a Decimal or None)."""
    paid_count = Task.objects.filter(
        project__company=company, assigned_to=freelancer, status=Task.Status.PAID
    ).count()
    agg = Rating.objects.filter(company=company, freelancer=freelancer).aggregate(avg=Avg("note"), n=Count("pk"))
    avg = Decimal(str(agg["avg"])) if agg["n"] else None
    return {"paid_count": paid_count, "avg_note": avg, "ratings_count": agg["n"]}


def tag_ratio(task_tags, applicant_tags) -> Decimal:
    wanted = [t for t in (task_tags or []) if t]
    if not wanted:
        return Decimal("0")
    common = len(set(applicant_tags or []) & set(wanted))
    return Decimal(common) / Decimal(len(wanted))


def score_parts(task_tags, applicant_tags, history: dict) -> dict:
    """→ {history_part, rating_part, tags_part, total} (Decimals, total rounded to 1 place)."""
    history_part = HISTORY_POINTS if history.get("paid_count", 0) >= 1 else Decimal("0")
    avg = history.get("avg_note")
    rating_part = (avg * RATING_FACTOR) if avg is not None else Decimal("0")
    tags_part = TAGS_POINTS * tag_ratio(task_tags, applicant_tags)
    rating_part = rating_part.quantize(ONE_PLACE, rounding=ROUND_HALF_UP)
    tags_part = tags_part.quantize(ONE_PLACE, rounding=ROUND_HALF_UP)
    # Sum of the DISPLAYED parts, so the score bar segments always add up to the printed total.
    total = history_part + rating_part + tags_part
    return {
        "history_part": history_part,
        "rating_part": rating_part,
        "tags_part": tags_part,
        "total": min(total, Decimal("100.0")),
    }


def is_validated(history: dict) -> bool:
    avg = history.get("avg_note")
    return history.get("paid_count", 0) >= 1 and avg is not None and avg >= VALIDATED_MIN_NOTE


def score_application(task: Task, freelancer, tags, history: dict | None = None) -> Decimal:
    """The stored score of an application by `freelancer` (with `tags`) on `task`."""
    if history is None:
        history = company_history(task.project.company_id, freelancer)
    return score_parts(task.tags, tags, history)["total"]


def recommended_pk(applications) -> int | None:
    """pk of the single "Recommended" application among PENDING ones: best score, then earliest."""
    best = None
    for app in applications:
        if app.status != app.Status.PENDING:
            continue
        key = (-app.score, app.created_at, app.pk)
        if best is None or key < best[0]:
            best = (key, app.pk)
    return best[1] if best else None
