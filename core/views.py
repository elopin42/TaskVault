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
        {"next_url": safe_next(request, request.GET.get("next")), "latest_projects": latest_projects, "stats": landing_stats()},
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
