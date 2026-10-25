"""JSON endpoints of the publication deposit (static/js/lowbid-deposit.js) + the public guarantee-fund page.

    POST /pay/caution/<project_pk>/prepare/<step>/  company   -> {ok, xdr, send_url, extra}            (deploy | fund)
    POST /pay/caution/<project_pk>/send/<step>/     company   {signed_xdr} -> {ok, hash, explorer_url, message, next}
    GET  /pay/caution/<project_pk>/pending.json     company   -> {ok, amount, next}   (the next deposit step to chain)
    POST /pay/caution/<project_pk>/recuperer/       company   verdict refund  -> settle (refund chain, server keys)
    POST /pay/caution/<project_pk>/signaler/        any wallet verdict forfeit -> settle (forfeit chain, server keys)
    GET  /fonds/                                    public    guarantee fund: balance, forfeited deposits

Business refusals are HTTP 200 `{ok: false, error, message}` (payments/views.py convention). The acting
address always comes from the session; nothing in the body is ever used as an address.
"""

import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from projects.models import Project
from projects.services import dec_str

from . import deposits, stellar
from .models import ProjectDeposit
from .services import PaymentError
from .views import _json_body, _refused

logger = logging.getLogger(__name__)


def _project(project_pk: int) -> Project:
    return get_object_or_404(Project.objects.select_related("company"), pk=project_pk)


def _next_json(project: Project, wallet) -> dict | None:
    action = deposits.next_deposit_action(project, wallet)
    if not action:
        return None
    return {**action, "amount": dec_str(action["amount"])}


def _detail_url(project: Project) -> str:
    return reverse("projects:project_detail", kwargs={"pk": project.pk}) + "#deposit-panel"


@require_POST
@wallet_required
def deposit_prepare(request: HttpRequest, project_pk: int, step: str) -> JsonResponse:
    project = _project(project_pk)
    wallet = get_wallet(request)
    try:
        prepared = deposits.prepare_deposit(project, wallet, step)
    except PaymentError as err:
        logger.info("deposits: prepare refused project=%s step=%s wallet=%s code=%s", project.pk, step, wallet.stellar_address, err.code)
        return _refused(err)
    send_url = reverse("payments:deposit_send", kwargs={"project_pk": project.pk, "step": step})
    return JsonResponse({"ok": True, "xdr": prepared["xdr"], "send_url": send_url, "extra": {}})


@require_POST
@wallet_required
def deposit_send(request: HttpRequest, project_pk: int, step: str) -> JsonResponse:
    project = _project(project_pk)
    wallet = get_wallet(request)
    signed_xdr = str(_json_body(request).get("signed_xdr") or "")
    try:
        result = deposits.confirm_deposit(project, wallet, step, signed_xdr)
    except PaymentError as err:
        logger.info("deposits: send refused project=%s step=%s wallet=%s code=%s", project.pk, step, wallet.stellar_address, err.code)
        return _refused(err)
    project.refresh_from_db()
    return JsonResponse(
        {
            "ok": True,
            "redirect": _detail_url(project),
            "status": result["status"],
            "tx_hash": result["tx_hash"],
            "hash": result["tx_hash"],
            "contract_id": result["contract_id"],
            "explorer_url": result["explorer_url"],
            "message": result["message"],
            "pending": False,
            "published": project.published_at is not None,
            "next": _next_json(project, wallet),
        }
    )


@require_GET
@wallet_required
def deposit_pending(request: HttpRequest, project_pk: int) -> JsonResponse:
    project = _project(project_pk)
    wallet = get_wallet(request)
    if not project.is_company(wallet):
        return _refused(PaymentError("forbidden", "Only the company can lock its project's deposit."))
    nxt = _next_json(project, wallet)
    return JsonResponse(
        {
            "ok": True,
            "project": project.pk,
            "active": deposits.deposits_active(),
            "amount": nxt["amount"] if nxt else "0",
            "next": nxt,
        }
    )


def _settled_json(project: Project, rows: list[ProjectDeposit], wallet, done_message: str) -> JsonResponse:
    failed = next((r for r in rows if r.status == ProjectDeposit.Status.FUNDED), None)
    if failed is not None:
        return JsonResponse(
            {
                "ok": False,
                "error": "provider",
                "message": failed.last_error or "The settlement did not complete: retry in a moment.",
                "explorer_urls": [link["url"] for r in rows for link in r.explorer_links()],
            }
        )
    return JsonResponse(
        {
            "ok": True,
            "redirect": _detail_url(project),
            "status": rows[-1].status if rows else "",
            "message": done_message,
            "explorer_urls": [link["url"] for r in rows for link in r.explorer_links()],
            "next": _next_json(project, wallet),
        }
    )


def _settle(request: HttpRequest, project_pk: int, verdict: str) -> JsonResponse:
    project = _project(project_pk)
    wallet = get_wallet(request)
    if verdict == "refund" and not project.is_company(wallet):
        return _refused(PaymentError("forbidden", "Only the company can reclaim its deposit."))
    if not ProjectDeposit.objects.filter(project=project, status=ProjectDeposit.Status.FUNDED).exists():
        return _refused(PaymentError("wrong_state", "No locked deposit on this project."))
    current = deposits.deposit_verdict(project)
    if current["verdict"] != verdict:
        message = (
            "The deposit cannot be reclaimed: " if verdict == "refund" else "This is not a ghost listing: "
        ) + current["reason"]
        return _refused(PaymentError("wrong_state", message))
    try:
        rows = deposits.settle_project(project)
    except PaymentError as err:
        return _refused(err)
    logger.info(
        "deposits: %s requested project=%s wallet=%s rows=%s",
        verdict, project.pk, wallet.stellar_address, ",".join(f"{r.pk}:{r.status}" for r in rows),
    )
    done = "Deposit refunded to your wallet." if verdict == "refund" else "Deposit sent to the guarantee fund. Thank you."
    return _settled_json(project, rows, wallet, done)


@require_POST
@wallet_required
def deposit_refund(request: HttpRequest, project_pk: int) -> JsonResponse:
    """"Reclaim my deposit" (company only, verdict refund) — also the retry after a failure."""
    return _settle(request, project_pk, "refund")


@require_POST
@wallet_required
def deposit_report(request: HttpRequest, project_pk: int) -> JsonResponse:
    """"Report a ghost listing" (any connected wallet, verdict forfeit) — also the retry after a failure."""
    return _settle(request, project_pk, "forfeit")


def fund_page(request: HttpRequest) -> HttpResponse:
    """`/fonds/` — the guarantee fund in public: balance (Horizon), forfeited deposits with their tx."""
    address = deposits.fund_address()
    balance = stellar.asset_balance(address) if address else None
    rows = list(
        ProjectDeposit.objects.filter(status=ProjectDeposit.Status.FORFEITED)
        .select_related("project")
        .order_by("-settled_at", "-pk")
    )
    forfeited = [
        {
            "project": r.project,
            "amount": r.amount,
            "settled_at": r.settled_at,
            "resolve_tx_hash": r.resolve_tx_hash,
            "resolve_url": stellar.explorer_tx_url(r.resolve_tx_hash) if r.resolve_tx_hash else "",
        }
        for r in rows
    ]
    return render(
        request,
        "payments/fund.html",
        {
            "fund_address": address,
            "fund_explorer_url": stellar.explorer_account_url(address) if address else "",
            "balance": balance,
            "forfeited": forfeited,
            "forfeited_total": sum((r.amount for r in rows), deposits.ZERO),
        },
    )
