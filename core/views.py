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


def landing(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "core/landing.html",
        {"next_url": safe_next(request, request.GET.get("next"))},
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
