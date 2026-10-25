import logging

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


def safe_next(request: HttpRequest, raw: str | None) -> str:
    """Return `raw` if it is a relative path on this host, else ''."""
    raw = (raw or "").strip()
    if raw and url_has_allowed_host_and_scheme(raw, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return raw
    return ""


def landing_stats() -> dict:
    """Live figures for the hero: open tasks, projects, USDC actually paid to freelances."""
    from django.db.models import Sum

    from projects.models import Project, Task

    paid = Task.objects.filter(status=Task.Status.PAID).aggregate(s=Sum("price"))["s"]
    return {
        "open_tasks": Task.objects.filter(status=Task.Status.OPEN).count(),
        "projects": Project.objects.count(),
        "paid_usdc": paid or 0,
    }


# On-chain events shown on the landing's ledger tape, in flow order: (tx hash field, label, timestamp field).
TAPE_EVENTS = (
    ("deploy_tx_hash", "ESCROW CREATED", "created_at"),
    ("fund_tx_hash", "FUNDS LOCKED", "funded_at"),
    ("deliver_tx_hash", "DELIVERY", "delivered_at"),
    ("approve_tx_hash", "DELIVERY VALIDATED", "rating"),  # the Rating is stored right before the approve
    ("release_tx_hash", "FUNDS RELEASED", "released_at"),
    ("payment_tx_hash", "DIRECT PAYMENT", "released_at"),
)


def _event_time(escrow, time_field: str):
    if time_field == "rating":
        rating = getattr(escrow.task, "rating", None)
        return rating.created_at if rating is not None else escrow.updated_at
    return getattr(escrow, time_field) or escrow.updated_at


def ledger_tape(limit: int = 10) -> list[dict]:
    """The latest real on-chain events (one per stored tx hash), newest first: [{label, title, amount, tx, at}]."""
    from payments.models import Escrow

    events: list[dict] = []
    for escrow in Escrow.objects.select_related("task", "task__rating").order_by("-updated_at")[:limit]:
        for hash_field, label, time_field in TAPE_EVENTS:
            tx = getattr(escrow, hash_field)
            if tx:
                events.append(
                    {
                        "label": label,
                        "title": escrow.task.title,
                        "amount": escrow.amount,
                        "tx": tx,
                        "at": _event_time(escrow, time_field),
                    }
                )
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


def tape_loop(events: list[dict], minimum: int = 8) -> list[dict]:
    """Repeat a short event list so one copy of the tape is wider than the viewport (the marquee loops two copies)."""
    if not events:
        return []
    looped = list(events)
    while len(looped) < minimum:
        looped.extend(events)
    return looped


# Decorative content of the landing's scroll story (the 3D "project cube" in core/landing.html): one
# project split into four tasks with a budget, three applications per task, the chosen one first. Not read
# from the database: the figures are a worked example, the live numbers live in landing_stats(). Every
# score is reachable with projects.scoring (40 · paid history + 8 · avg note + 20 · tag ratio): e.g.
# 92 = 40 + 8 × 4.5 + 20 × 0.8, and 20 / 15 / 10 / 5 are newcomers scored on matching skills only.
STORY_TASKS = (
    {"title": "Brand & logo", "price": "350", "bids": ({"name": "Freelancer A", "score": 92}, {"name": "Freelancer B", "score": 64}, {"name": "Freelancer C", "score": 20})},
    {"title": "Landing page", "price": "450", "bids": ({"name": "Freelancer D", "score": 88}, {"name": "Freelancer E", "score": 15}, {"name": "Freelancer F", "score": 10})},
    {"title": "Soroban contract", "price": "900", "bids": ({"name": "Freelancer G", "score": 96}, {"name": "Freelancer H", "score": 76}, {"name": "Freelancer I", "score": 20})},
    {"title": "QA & launch", "price": "300", "bids": ({"name": "Freelancer J", "score": 80}, {"name": "Freelancer K", "score": 20}, {"name": "Freelancer L", "score": 5})},
)


def landing_facts() -> dict:
    """The configured rules quoted by the landing's chapters (security, money path), read from the settings so
    the copy never drifts from what the task board enforces: {challenge_minutes, review_days, max_revisions,
    deposit_active, deposit_pct, deposit_min, trusted_host}."""
    from decimal import Decimal

    from payments import deposits

    def plain(value: Decimal) -> str:  # "1", "5", "12.5": never "1E+1"
        return format(value.normalize(), "f")

    return {
        "challenge_minutes": max(1, int(settings.WALLET_CHALLENGE_TTL_SECONDS) // 60),
        "review_days": settings.LOWBID_REVIEW_DAYS,
        "max_revisions": settings.LOWBID_MAX_REVISIONS,
        "deposit_active": deposits.deposits_active(),
        "deposit_pct": plain(Decimal(settings.LOWBID_DEPOSIT_RATE) * 100),
        "deposit_min": plain(Decimal(settings.LOWBID_DEPOSIT_MIN)),
        "deposit_example": plain(deposits.deposit_amount(Decimal("1200"))),
        "choice_days": deposits.choice_days(),
        "trusted_host": (settings.LOWBID_TRUSTED_LINK_HOSTS or ["github.com"])[0],
    }


# The worked example of the landing's chapter 01 (after the cube): one project, one expert per task, each at
# their own price under the task's budget (the figures of the pitch deck, not database rows).
STORY_PRICES = (
    {"task": "Landing page", "budget": "300", "expert": "Léa", "price": "280"},
    {"task": "Freighter integration", "budget": "500", "expert": "Yanis", "price": "480"},
    {"task": "Dashboard", "budget": "400", "expert": "Nora", "price": "400"},
)


def landing(request: HttpRequest) -> HttpResponse:
    from projects.models import Project  # local import: core must stay importable without the domain apps

    latest_projects = list(
        Project.objects.published().exclude(status=Project.Status.CANCELLED).with_totals()
        .select_related("company")
        .prefetch_related("tasks")
        .filter(open_total__gt=0)
        .order_by("-created_at")[:3]
    )
    for project in latest_projects:
        seen: list[str] = []
        for task in project.tasks.all():
            seen.extend(t for t in (task.tags or []) if t not in seen)
        project.tag_list = seen
    return render(
        request,
        "core/landing.html",
        {
            "next_url": safe_next(request, request.GET.get("next")),
            "latest_projects": latest_projects,
            "stats": landing_stats(),
            "tape": tape_loop(ledger_tape()),
            "story_tasks": STORY_TASKS,
            "story_prices": STORY_PRICES,
            "facts": landing_facts(),
        },
    )


def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness + DB probe. 200 when the database answers, 503 otherwise."""
    db_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        logger.exception("healthz: database unreachable")
        db_ok = False
    payload = {"ok": db_ok, "db": db_ok, "network": settings.STELLAR_NETWORK}
    return JsonResponse(payload, status=200 if db_ok else 503)


# --- Error pages ----------------------------------------------------------------

def error_400(request, exception=None):
    return render(request, "400.html", status=400)


def error_403(request, exception=None):
    return render(request, "403.html", status=403)


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
