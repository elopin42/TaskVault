"""JSON endpoints of the trust network, called by `Lowbid.api` from the profile page.
Rules live in services.py; this module only maps NetworkError codes to HTTP.
"""

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from accounts.models import WalletUser

from . import services
from .models import Follow, Recommendation
from .services import NetworkError

logger = logging.getLogger(__name__)

# HTTP status for a refused action, by error code (anything else → 400).
ERROR_STATUS = {
    "self": 400,
    "invalid": 400,
    "not_found": 404,
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


def _error_response(err: NetworkError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=ERROR_STATUS.get(err.code, 400))


def _target(address: str) -> WalletUser:
    wallet = WalletUser.objects.filter(stellar_address=address).first()
    if wallet is None:
        raise NetworkError("not_found", "Unknown wallet.")
    return wallet


def _state(viewer: WalletUser, target: WalletUser, message: str) -> JsonResponse:
    """The success body every endpoint returns: the viewer's relation to the target + the target's counters."""
    rec = Recommendation.objects.filter(author=viewer, subject=target).first()
    return JsonResponse(
        {
            "ok": True,
            "following": Follow.objects.filter(follower=viewer, followed=target).exists(),
            "followers_count": Follow.objects.filter(followed=target).count(),
            "recommendation": {"message": rec.message} if rec else None,
            "recommendations_count": Recommendation.objects.filter(subject=target).count(),
            "message": message,
        }
    )


@require_POST
@wallet_required
def follow_view(request: HttpRequest, address: str) -> JsonResponse:
    viewer = get_wallet(request)
    try:
        target = _target(address)
        services.follow(viewer, target)
    except NetworkError as err:
        return _error_response(err)
    return _state(viewer, target, f"Following {services.wallet_name(target)}.")


@require_POST
@wallet_required
def unfollow_view(request: HttpRequest, address: str) -> JsonResponse:
    viewer = get_wallet(request)
    try:
        target = _target(address)
        services.unfollow(viewer, target)
    except NetworkError as err:
        return _error_response(err)
    return _state(viewer, target, f"No longer following {services.wallet_name(target)}.")


@require_POST
@wallet_required
def recommend_view(request: HttpRequest, address: str) -> JsonResponse:
    viewer = get_wallet(request)
    data = _json_body(request)
    try:
        target = _target(address)
        services.recommend(viewer, target, data.get("message", ""))
    except NetworkError as err:
        return _error_response(err)
    return _state(viewer, target, "Recommendation saved.")


@require_POST
@wallet_required
def unrecommend_view(request: HttpRequest, address: str) -> JsonResponse:
    viewer = get_wallet(request)
    try:
        target = _target(address)
        services.unrecommend(viewer, target)
    except NetworkError as err:
        return _error_response(err)
    return _state(viewer, target, "Recommendation withdrawn.")
