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
    """Live figures for the hero: open needs, bids placed, USDC actually paid out (escrow released / direct paid)."""
    from django.db.models import Sum

    from auctions.models import Bid, Need
    from payments.models import Escrow

    paid = Escrow.objects.filter(status__in=(Escrow.Status.RELEASED, Escrow.Status.PAID)).aggregate(s=Sum("amount"))["s"]
    return {
        "open_needs": Need.objects.open_now().count(),
        "bids": Bid.objects.count(),
        "paid_usdc": paid or 0,
    }


def landing(request: HttpRequest) -> HttpResponse:
    from auctions.models import Need  # local import: core must stay importable without the domain apps

    latest_needs = Need.objects.with_stats().select_related("client").open_now().order_by("bidding_ends_at")[:3]
    return render(
        request,
        "core/landing.html",
        {"next_url": safe_next(request, request.GET.get("next")), "latest_needs": latest_needs, "stats": landing_stats()},
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
