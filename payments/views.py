"""JSON endpoints driven by static/js/lowbid-pay.js, plus a redirect to the task's panel.

    POST /pay/prepare/<task_pk>/<step>/   -> {ok, xdr, send_url, extra}  (or {ok, redirect, message, next} when nothing to sign)
    POST /pay/send/<task_pk>/<step>/      {signed_xdr, ...extra} -> {ok, redirect, tx_hash, explorer_url, message, pending, next}
    POST /pay/trustline/prepare/          -> same prepare shape (no xdr + message when the trustline exists)
    POST /pay/trustline/send/             {signed_xdr} -> {ok, tx_hash, explorer_url, message}
    GET  /pay/project/<pk>/pending.json   -> {ok, tasks: [{task, title, amount, next}]} (company; "Fund the project")
    GET  /pay/<task_pk>/                  -> 302 to the task detail #paiement

`next` is the viewer's following step ({step, label, prepare_url, mine, …} or null) so the page
can chain the signatures (deploy → fund, approve → release) without a reload in between.
Business refusals are HTTP 200 `{ok: false, error: <code>, message}` so `Lowbid.api` resolves
and the JS shows `message`. Anonymous callers get the decorator's 401 JSON.
"""

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from projects.models import Project, Task
from projects.services import dec_str

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


def _task(task_pk: int) -> Task:
    return get_object_or_404(Task.objects.select_related("project__company", "assigned_to"), pk=task_pk)


def _detail_url(task: Task) -> str:
    return reverse("projects:task_detail", kwargs={"pk": task.pk}) + "#paiement"


def next_json(action: dict | None) -> dict | None:
    """The wire shape of a next_action() entry (what lowbid-pay.js chains on)."""
    if not action:
        return None
    return {
        "step": action["step"],
        "label": action["label"],
        "prepare_url": action["prepare_url"],
        "mine": action["mine"],
        "who": action["who"],
        "evidence": action["evidence"],
        "no_tx": action["no_tx"],
        "hint": action["hint"],
        "task": action["task"],
    }


def _prepared_json(prepared: dict, send_url: str | None, redirect_url: str, task: Task, wallet) -> JsonResponse:
    if prepared["done"]:
        return JsonResponse(
            {
                "ok": True,
                "redirect": redirect_url,
                "message": prepared.get("message") or "",
                "next": next_json(services.next_action(task, wallet)),
            }
        )
    return JsonResponse({"ok": True, "xdr": prepared["xdr"], "send_url": send_url, "extra": prepared.get("extra") or {}})


@require_POST
@wallet_required
def prepare(request: HttpRequest, task_pk: int, step: str) -> JsonResponse:
    task = _task(task_pk)
    wallet = get_wallet(request)
    try:
        prepared = services.prepare(task, wallet, step, _json_body(request))
    except PaymentError as err:
        logger.info("payments: prepare refused task=%s step=%s wallet=%s code=%s", task.pk, step, wallet.stellar_address, err.code)
        return _refused(err)
    send_url = reverse("payments:send", kwargs={"task_pk": task.pk, "step": step})
    task.refresh_from_db()
    return _prepared_json(prepared, send_url, _detail_url(task), task, wallet)


@require_POST
@wallet_required
def send(request: HttpRequest, task_pk: int, step: str) -> JsonResponse:
    task = _task(task_pk)
    wallet = get_wallet(request)
    data = _json_body(request)
    signed_xdr = str(data.get("signed_xdr") or "")
    try:
        result = services.confirm(task, wallet, step, signed_xdr, data)
    except PaymentError as err:
        logger.info("payments: send refused task=%s step=%s wallet=%s code=%s", task.pk, step, wallet.stellar_address, err.code)
        return _refused(err)
    task.refresh_from_db()
    return JsonResponse(
        {
            "ok": True,
            "redirect": _detail_url(task),
            "status": result.get("status"),
            "task_status": task.status,
            "tx_hash": result.get("tx_hash"),
            "hash": result.get("tx_hash"),
            "contract_id": result.get("contract_id"),
            "explorer_url": result.get("explorer_url"),
            "message": result.get("message") or "",
            "pending": bool(result.get("pending")),
            "next": next_json(services.next_action(task, wallet)),
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


@require_GET
@wallet_required
def project_pending(request: HttpRequest, pk: int) -> JsonResponse:
    """What "Fund the project" chains: the company's deploy/fund step of every assigned, unfunded task."""
    project = get_object_or_404(Project.objects.select_related("company"), pk=pk)
    wallet = get_wallet(request)
    if not project.is_company(wallet):
        return _refused(PaymentError("forbidden", "Only the company can fund its project."))
    funding = services.project_funding(project, wallet)
    return JsonResponse(
        {
            "ok": True,
            "project": project.pk,
            "mode": funding["mode"],
            "total": dec_str(funding["total"]),
            "funded": dec_str(funding["funded"]),
            "can_fund": funding["can_fund"],
            "hint": funding["fund_hint"],
            "tasks": [
                {"task": p["task"].pk, "title": p["title"], "amount": dec_str(p["amount"]), "next": next_json(p["next"])}
                for p in funding["pending"]
            ],
        }
    )


def task_pay(request: HttpRequest, task_pk: int):
    """`/pay/<pk>/` — the panel lives on the task page; this just lands the user on it."""
    task = get_object_or_404(Task, pk=task_pk)
    return redirect(_detail_url(task))
