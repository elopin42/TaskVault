"""JSON endpoints driven by static/js/lowbid-pay.js, plus a redirect to the need's panel.

    POST /pay/prepare/<need_pk>/<step>/   -> {ok, xdr, send_url, extra}  (or {ok, redirect, message} when nothing to sign)
    POST /pay/send/<need_pk>/<step>/      {signed_xdr, ...extra} -> {ok, redirect, tx_hash, explorer_url, message, pending}
    POST /pay/trustline/prepare/          -> same prepare shape (no xdr + message when the trustline exists)
    POST /pay/trustline/send/             {signed_xdr} -> {ok, tx_hash, explorer_url, message}
    GET  /pay/<need_pk>/                  -> 302 to the need detail #paiement

Business refusals are HTTP 200 `{ok: false, error: <code>, message}` so `Lowbid.api` resolves
and the JS shows `message`. Anonymous callers get the decorator's 401 JSON.
"""

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from auctions.models import Need

from . import services
from .services import PaymentError

logger = logging.getLogger(__name__)


def _json_body(request: HttpRequest) -> dict:
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST.dict()


def _refused(err: PaymentError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": err.code, "message": err.message})


def _need(need_pk: int) -> Need:
    return get_object_or_404(Need.objects.select_related("client", "winning_bid__freelancer"), pk=need_pk)


def _detail_url(need: Need) -> str:
    return reverse("auctions:need_detail", kwargs={"pk": need.pk}) + "#paiement"


def _prepared_json(prepared: dict, send_url: str | None, redirect_url: str) -> JsonResponse:
    if prepared["done"]:
        return JsonResponse({"ok": True, "redirect": redirect_url, "message": prepared.get("message") or ""})
    return JsonResponse({"ok": True, "xdr": prepared["xdr"], "send_url": send_url, "extra": prepared.get("extra") or {}})


@require_POST
@wallet_required
def prepare(request: HttpRequest, need_pk: int, step: str) -> JsonResponse:
    need = _need(need_pk)
    wallet = get_wallet(request)
    try:
        prepared = services.prepare(need, wallet, step, _json_body(request))
    except PaymentError as err:
        logger.info("payments: prepare refused need=%s step=%s wallet=%s code=%s", need.pk, step, wallet.stellar_address, err.code)
        return _refused(err)
    send_url = reverse("payments:send", kwargs={"need_pk": need.pk, "step": step})
    return _prepared_json(prepared, send_url, _detail_url(need))


@require_POST
@wallet_required
def send(request: HttpRequest, need_pk: int, step: str) -> JsonResponse:
    need = _need(need_pk)
    wallet = get_wallet(request)
    data = _json_body(request)
    signed_xdr = str(data.get("signed_xdr") or "")
    try:
        result = services.confirm(need, wallet, step, signed_xdr, data)
    except PaymentError as err:
        logger.info("payments: send refused need=%s step=%s wallet=%s code=%s", need.pk, step, wallet.stellar_address, err.code)
        return _refused(err)
    return JsonResponse(
        {
            "ok": True,
            "redirect": _detail_url(need),
            "status": result.get("status"),
            "tx_hash": result.get("tx_hash"),
            "hash": result.get("tx_hash"),
            "contract_id": result.get("contract_id"),
            "explorer_url": result.get("explorer_url"),
            "message": result.get("message") or "",
            "pending": bool(result.get("pending")),
        }
    )


@require_POST
@wallet_required
def trustline_prepare(request: HttpRequest) -> JsonResponse:
    wallet = get_wallet(request)
    try:
        prepared = services.prepare_trustline(wallet.stellar_address)
    except PaymentError as err:
        return _refused(err)
    if prepared["done"]:
        return JsonResponse({"ok": True, "message": prepared["message"]})
    return JsonResponse({"ok": True, "xdr": prepared["xdr"], "send_url": reverse("payments:trustline_send"), "extra": {}})


@require_POST
@wallet_required
def trustline_send(request: HttpRequest) -> JsonResponse:
    wallet = get_wallet(request)
    signed_xdr = str(_json_body(request).get("signed_xdr") or "")
    try:
        result = services.confirm_trustline(wallet.stellar_address, signed_xdr)
    except PaymentError as err:
        logger.info("payments: trustline refused wallet=%s code=%s", wallet.stellar_address, err.code)
        return _refused(err)
    return JsonResponse(
        {
            "ok": True,
            "tx_hash": result["tx_hash"],
            "hash": result["tx_hash"],
            "explorer_url": result["explorer_url"],
            "message": result["message"],
            "pending": result["pending"],
        }
    )


def need_pay(request: HttpRequest, need_pk: int):
    """`/pay/<pk>/` — the panel lives on the need page; this just lands the user on it."""
    need = get_object_or_404(Need, pk=need_pk)
    return redirect(_detail_url(need))
