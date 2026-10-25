"""JSON endpoints of the reputation app. Rules live in services.py; views map codes to HTTP.
The acting wallet ALWAYS comes from the session (`get_wallet`), never from the body."""

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from projects.models import Task

from . import services
from .services import ReputationError

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "forbidden": 403,
    "wrong_state": 409,
    "duplicate": 409,
    "already_used": 409,
    "invalid": 400,
    "not_found": 404,
    "not_public": 400,
    "bad_signature": 400,
    "too_recent": 400,
    "provider": 502,
}


def _json_body(request: HttpRequest) -> dict:
    """JSON body from Lowbid.api, or a classic form POST (both are accepted)."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST.dict()


def _error_response(err: ReputationError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=ERROR_STATUS.get(err.code, 400))


@require_POST
@wallet_required
def rate_company(request: HttpRequest, pk: int) -> JsonResponse:
    task = get_object_or_404(Task.objects.select_related("project"), pk=pk)
    data = _json_body(request)
    try:
        rating = services.rate_company(task, get_wallet(request), data.get("note"), data.get("comment", ""))
    except ReputationError as e:
        return _error_response(e)
    summary = services.company_rating_summary(rating.company)
    return JsonResponse(
        {
            "ok": True,
            "note": rating.note,
            "avg": str(summary["avg"]) if summary["avg"] is not None else None,
            "count": summary["count"],
            "message": "Thanks: your rating of the company is saved.",
        }
    )


@require_GET
@wallet_required
def github_message(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, "message": services.github_message(get_wallet(request))})


@require_POST
@wallet_required
def github_verify(request: HttpRequest) -> JsonResponse:
    data = _json_body(request)
    try:
        identity = services.verify_github(get_wallet(request), data.get("gist"))
    except ReputationError as e:
        return _error_response(e)
    return JsonResponse(
        {
            "ok": True,
            "login": identity.github_login,
            "verified_at": identity.verified_at.isoformat(),
            "message": f"GitHub account {identity.github_login} linked to your wallet.",
        }
    )


@require_POST
@wallet_required
def github_unlink(request: HttpRequest) -> JsonResponse:
    try:
        services.unlink_github(get_wallet(request))
    except ReputationError as e:
        return _error_response(e)
    return JsonResponse({"ok": True, "message": "GitHub account unlinked."})
