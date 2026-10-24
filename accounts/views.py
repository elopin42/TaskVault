"""Wallet login: challenge -> Freighter signMessage -> verify.

POST /auth/challenge/  -> {"ok": true, "message": "Lowbid login <nonce> <ts>"}
POST /auth/verify/     <- {"address": "G…", "signature": "<base64>", "next": "/…"}
                       -> {"ok": true, "address": "G…", "next": "/…"}
POST /auth/logout/     -> redirect to landing (JSON {"ok": true} for fetch callers)
"""

import json
import logging
import secrets
import time

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.views import safe_next

from .decorators import _wants_json
from .identity import SESSION_CHALLENGE_KEY, login_wallet, logout_wallet
from .models import WalletUser
from .signing import decode_signature, verify_signature

logger = logging.getLogger(__name__)


def _json_body(request: HttpRequest) -> dict:
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST.dict()


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


@require_POST
def auth_challenge(request: HttpRequest) -> JsonResponse:
    nonce = secrets.token_hex(16)
    issued = int(time.time())
    message = f"Lowbid login {nonce} {issued}"
    request.session[SESSION_CHALLENGE_KEY] = {"nonce": nonce, "message": message, "ts": issued}
    return JsonResponse({"ok": True, "message": message, "expires_in": settings.WALLET_CHALLENGE_TTL_SECONDS})


@require_POST
def auth_verify(request: HttpRequest) -> JsonResponse:
    data = _json_body(request)
    address = str(data.get("address", "")).strip().upper()
    signature_raw = str(data.get("signature", "")).strip()

    challenge = request.session.get(SESSION_CHALLENGE_KEY) or {}
    message = challenge.get("message")
    if not message:
        return _error("no_challenge")
    if time.time() - int(challenge.get("ts", 0)) > settings.WALLET_CHALLENGE_TTL_SECONDS:
        request.session.pop(SESSION_CHALLENGE_KEY, None)
        return _error("challenge_expired")

    if len(address) != 56 or not address.startswith("G"):
        return _error("invalid_address")
    signature = decode_signature(signature_raw)
    if signature is None:
        return _error("invalid_signature_encoding")

    scheme = verify_signature(address, message, signature)
    if scheme is None:
        logger.warning("wallet login rejected address=%s reason=bad_signature", address)
        return _error("bad_signature")

    wallet, created = WalletUser.objects.get_or_create(stellar_address=address)
    wallet.last_login_at = timezone.now()
    wallet.save(update_fields=["last_login_at"])
    login_wallet(request, wallet)
    logger.info("wallet login ok address=%s scheme=%s created=%s", address, scheme, created)

    return JsonResponse({"ok": True, "address": address, "created": created, "next": safe_next(request, data.get("next"))})


@require_POST
def auth_logout(request: HttpRequest):
    logout_wallet(request)
    if _wants_json(request):
        return JsonResponse({"ok": True})
    return redirect(reverse("core:landing"))
