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
    ("approve_tx_hash", "DELIVERY VALIDATED", "released_at"),
    ("release_tx_hash", "FUNDS RELEASED", "released_at"),
    ("payment_tx_hash", "DIRECT PAYMENT", "released_at"),
)


def ledger_tape(limit: int = 10) -> list[dict]:
    """The latest real on-chain events (one per stored tx hash), newest first: [{label, title, amount, tx, at}]."""
    from payments.models import Escrow

    events: list[dict] = []
    for escrow in Escrow.objects.select_related("task").order_by("-updated_at")[:limit]:
        for hash_field, label, time_field in TAPE_EVENTS:
            tx = getattr(escrow, hash_field)
            if tx:
                events.append(
                    {
                        "label": label,
                        "title": escrow.task.title,
                        "amount": escrow.amount,
                        "tx": tx,
                        "at": getattr(escrow, time_field) or escrow.updated_at,
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


def hero_receipt() -> dict | None:
    """The escrow receipt shown in the hero: the most recently active escrow, else the newest open task
    (steps all ahead). None on an empty database."""
    from payments import services as pay
    from payments import stellar
    from payments.models import Escrow
    from projects.models import Task

    escrow = Escrow.objects.select_related("task__project").exclude(status=Escrow.Status.FAILED).order_by("-updated_at").first()
    if escrow:
        return {
            "task": escrow.task,
            "amount": escrow.amount,
            "steps": pay.stepper(escrow.mode, escrow.status),
            "status_label": escrow.status_label,
            "payer": escrow.payer_address,
            "payee": escrow.payee_address,
            "contract": escrow.contract_id or "",
            "links": escrow.explorer_links(),
            "live": not escrow.is_done,
        }
    task = Task.objects.select_related("project__company").filter(status=Task.Status.OPEN).order_by("-created_at").first()
    if not task:
        return None
    steps = [dict(step, state="todo") for step in pay.stepper(stellar.payment_mode(), "")]
    return {
        "task": task,
        "amount": task.price,
        "steps": steps,
        "status_label": "Waiting for a freelancer",
        "payer": task.project.company.stellar_address,
        "payee": "",
        "contract": "",
        "links": [],
        "live": False,
    }


def landing(request: HttpRequest) -> HttpResponse:
    from projects.models import Project  # local import: core must stay importable without the domain apps

    latest_projects = list(
        Project.objects.with_totals()
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
            "receipt": hero_receipt(),
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
