"""Auctions pages (server-rendered) + the small JSON endpoints the detail page calls
through `Lowbid.api`. Rules live in services.py; this module only maps codes to HTTP.
"""

import json
import logging

from collections import Counter

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet

from . import services
from .forms import NeedForm
from .models import Bid, Need
from .scoring import DEFAULT_WEIGHTS, normalise_weights, rank_bids
from .services import AuctionError, BidError, NeedError, dec_str

logger = logging.getLogger(__name__)

LIST_TABS = (("open", "Ouverts"), ("closed", "Terminés"), ("all", "Tous"))
# ?sort= on the list page → (label, ordering). "ending" is the default on the open tab, "newest" elsewhere.
LIST_SORTS = (
    ("ending", "Fin la plus proche", ("bidding_ends_at", "-created_at")),
    ("newest", "Plus récents", ("-created_at",)),
    ("budget", "Budget le plus élevé", ("-budget_max", "-created_at")),
    ("bids", "Plus d’enchères", ("-bid_count", "-created_at")),
)
LIST_PAGE_SIZE = 24
POPULAR_TAGS = 8
MY_TABS = (("active", "En cours"), ("done", "Terminés"), ("all", "Tous"))
# HTTP status for a refused action, by error code (anything else → 400).
ERROR_STATUS = {"forbidden": 403, "not_open": 409, "not_closed": 409, "bad_bid": 409, "too_late": 409, "closed": 409}


# --- helpers ----------------------------------------------------------------------

def _weights_from_request(request: HttpRequest) -> tuple[int, int, int]:
    g = request.GET
    if not any(k in g for k in ("wp", "wd", "ws")):
        return DEFAULT_WEIGHTS
    return normalise_weights(g.get("wp"), g.get("wd"), g.get("ws"))


def _json_body(request: HttpRequest) -> dict:
    """JSON body from Lowbid.api, or a classic form POST (both are accepted)."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST.dict()


def _error_response(err: AuctionError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=ERROR_STATUS.get(err.code, 400))


def _bid_rows(need: Need, weights, wallet) -> list[dict]:
    """Ranked rows for the list partial + JSON. Flags are precomputed so templates stay dumb."""
    ranked = rank_bids(need, weights)
    best = need.best_price
    wanted = set(need.tags or [])
    rows = []
    for rank, (bid, score) in enumerate(ranked, start=1):
        rows.append(
            {
                "bid": bid,
                "rank": rank,
                "score": score,
                # Pre-formatted with "." regardless of the fr locale: these land in data-* attrs / style widths.
                "fmt": {
                    "price": f"{bid.price:,.2f}",
                    "total": f"{score['total']:.1f}",
                    "price_part": f"{score['price_part']:.1f}",
                    "delay_part": f"{score['delay_part']:.1f}",
                    "skills_part": f"{score['skills_part']:.1f}",
                    "price_ratio": f"{score['price_ratio']:.4f}",
                    "delay_ratio": f"{score['delay_ratio']:.4f}",
                    "skills_ratio": f"{score['skills_ratio']:.4f}",
                },
                "tags": [{"name": t, "match": t in wanted} for t in (bid.tags or [])],
                "is_best_price": best is not None and bid.price == best,
                "is_mine": wallet is not None and bid.freelancer_id == wallet.pk,
                "is_winner": need.winning_bid_id == bid.pk,
            }
        )
    return rows


def _fingerprint(need: Need, rows: list[dict]) -> str:
    ids = [r["bid"].pk for r in rows]
    return f"{need.effective_status()}:{len(ids)}:{max(ids) if ids else 0}:{need.best_price}:{need.winning_bid_id}"


def _bids_context(need: Need, weights, wallet) -> dict:
    status = need.effective_status()
    rows = _bid_rows(need, weights, wallet)
    is_client = need.is_client(wallet)
    return {
        "need": need,
        "rows": rows,
        "weights": weights,
        "status": status,
        "viewer_is_client": is_client,
        "bidding_open": status == Need.Status.OPEN,
        "show_recommended": status != Need.Status.OPEN and status != Need.Status.CANCELLED,
        "can_choose": is_client and status == Need.Status.CLOSED,
        "fingerprint": _fingerprint(need, rows),
    }


def _price_history(need: Need) -> list[Bid]:
    """Every bid ever placed (outbid ones included), oldest first — the price curve of the auction."""
    return list(need.bids.select_related("freelancer").order_by("created_at", "pk"))


def _points(bids: list[Bid]) -> str:
    """'500,450,400' — the sparkline input (dot decimals, no locale)."""
    return ",".join(dec_str(b.price) for b in bids)


def _savings_pct(need: Need) -> int | None:
    best = need.best_price
    if best is None or not need.budget_max:
        return None
    return max(0, min(100, int(round(100 * (1 - float(best) / float(need.budget_max))))))


def _bid_json(row: dict) -> dict:
    bid: Bid = row["bid"]
    s = row["score"]
    return {
        "id": bid.pk,
        "rank": row["rank"],
        "freelancer": bid.freelancer.stellar_address,
        "price": dec_str(bid.price),
        "delay_days": bid.delay_days,
        "tags": bid.tags,
        "message": bid.message,
        "status": bid.status,
        "created_at": bid.created_at.isoformat(),
        "score": {k: round(v, 3) for k, v in s.items()},
        "is_best_price": row["is_best_price"],
        "is_winner": row["is_winner"],
    }


# --- pages ------------------------------------------------------------------------

def need_list(request: HttpRequest) -> HttpResponse:
    Need.objects.close_expired()
    tab = request.GET.get("tab", "open")
    if tab not in dict(LIST_TABS):
        tab = "open"
    tag = (request.GET.get("tag") or "").strip().lower()[:24]
    q = (request.GET.get("q") or "").strip()[:80]
    sort_keys = [k for k, _, _ in LIST_SORTS]
    sort = request.GET.get("sort") or ("ending" if tab == "open" else "newest")
    if sort not in sort_keys:
        sort = "ending" if tab == "open" else "newest"
    ordering = next(o for k, _, o in LIST_SORTS if k == sort)

    qs = Need.objects.with_stats().select_related("client")
    now = timezone.now()
    if tab == "open":
        qs = qs.filter(status=Need.Status.OPEN, bidding_ends_at__gt=now)
    elif tab == "closed":
        qs = qs.exclude(status=Need.Status.OPEN, bidding_ends_at__gt=now)
    if q:
        # JSON containment is not portable to SQLite: tags are matched on their text repr.
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(tags__icontains=q))
    qs = qs.order_by(*ordering)
    if tag:  # the demo volume makes a Python filter fine
        needs = [n for n in qs if tag in (n.tags or [])]
    else:
        needs = list(qs)

    page = Paginator(needs, LIST_PAGE_SIZE).get_page(request.GET.get("page"))
    counter = Counter(t for n in Need.objects.open_now().values_list("tags", flat=True) for t in (n or []))
    popular_tags = [t for t, _ in counter.most_common(POPULAR_TAGS)]
    if tag and tag not in popular_tags:
        popular_tags.insert(0, tag)

    return render(
        request,
        "auctions/need_list.html",
        {
            "needs": page.object_list,
            "page": page,
            "total": page.paginator.count,
            "tab": tab,
            "tabs": LIST_TABS,
            "tag": tag,
            "q": q,
            "sort": sort,
            "sorts": [(k, label) for k, label, _ in LIST_SORTS],
            "popular_tags": popular_tags,
            "now": now,
        },
    )


@wallet_required
def need_create(request: HttpRequest) -> HttpResponse:
    wallet = get_wallet(request)
    demo = request.GET.get("demo") == "1"
    if request.method == "POST":
        form = NeedForm(request.POST, demo=demo)
        if form.is_valid():
            need = form.save(client=wallet)
            logger.info("need created need=%s client=%s", need.pk, wallet.pk)
            messages.success(request, "Besoin publié. Les freelances peuvent enchérir.")
            return redirect("auctions:need_detail", pk=need.pk)
    else:
        form = NeedForm(demo=demo)
    return render(request, "auctions/need_form.html", {"form": form, "demo": demo})


def need_detail(request: HttpRequest, pk: int) -> HttpResponse:
    Need.objects.close_expired()
    need = get_object_or_404(Need.objects.select_related("client", "winning_bid__freelancer"), pk=pk)
    wallet = get_wallet(request)
    weights = _weights_from_request(request)
    ctx = _bids_context(need, weights, wallet)
    status = ctx["status"]
    is_client = ctx["viewer_is_client"]
    history = _price_history(need)
    ctx.update(
        {
            "wallet": wallet,
            "history": history,
            "history_points": _points(history),
            "savings_pct": _savings_pct(need),
            "my_bid": None if is_client else need.active_bid_for(wallet),
            "can_bid": wallet is not None and not is_client and status == Need.Status.OPEN,
            "can_close": is_client and status == Need.Status.OPEN,
            "can_cancel": is_client and need.can_cancel,
            "winning_bid": need.winning_bid,
            "bids_json_url": reverse("auctions:need_bids_json", kwargs={"pk": need.pk}),
        }
    )
    return render(request, "auctions/need_detail.html", ctx)


@wallet_required
def my_bids(request: HttpRequest) -> HttpResponse:
    from payments import services as payment_services  # payments depends on auctions, not the reverse

    Need.objects.close_expired()
    wallet = get_wallet(request)
    tab = request.GET.get("tab", "active")
    if tab not in dict(MY_TABS):
        tab = "active"
    bids = Bid.objects.filter(freelancer=wallet).select_related("need", "need__client").order_by("-created_at")
    rows = []
    kpis = {"leading": 0, "outbid": 0, "won": 0}
    for bid in bids:
        need = bid.need
        best = need.best_price
        attention = False
        if bid.status == Bid.Status.ACTIVE:
            if need.effective_status() != Need.Status.OPEN:
                label, klass = "En attente du choix", "ui-badge-attn"
            elif best is not None and bid.price <= best:
                label, klass = "En tête", "ui-badge-info"
                kpis["leading"] += 1
            else:
                label, klass = "Dépassée", "ui-badge-attn"
                kpis["outbid"] += 1
                attention = True
        elif bid.status == Bid.Status.WON:
            label, klass = "Gagnée", "ui-badge-ok"
            kpis["won"] += 1
            action = payment_services.next_action(need, wallet)
            attention = bool(action and action["mine"])
        elif bid.status == Bid.Status.LOST:
            label, klass = "Non retenue", "ui-badge-neutral"
        else:
            label, klass = "Remplacée", "ui-badge-neutral"
        done = bid.status in (Bid.Status.LOST, Bid.Status.OUTBID) or (
            bid.status == Bid.Status.WON and need.effective_status() == Need.Status.RELEASED
        )
        if (tab == "active" and done) or (tab == "done" and not done):
            continue
        rows.append({"bid": bid, "need": need, "best_price": best, "label": label, "badge": klass, "attention": attention})
    return render(request, "auctions/my_bids.html", {"rows": rows, "tab": tab, "tabs": MY_TABS, "kpis": kpis})


@wallet_required
def my_needs(request: HttpRequest) -> HttpResponse:
    Need.objects.close_expired()
    wallet = get_wallet(request)
    tab = request.GET.get("tab", "active")
    if tab not in dict(MY_TABS):
        tab = "active"
    all_needs = list(
        Need.objects.filter(client=wallet)
        .with_stats()
        .select_related("winning_bid__freelancer")
        .annotate(active_count=Count("bids", filter=Q(bids__status=Bid.Status.ACTIVE)))
    )
    kpis = {"open": 0, "to_choose": 0, "awarded": 0}
    needs = []
    for need in all_needs:
        status = need.effective_status()
        need.attention = status == Need.Status.CLOSED and need.bids_count > 0
        if status == Need.Status.OPEN:
            kpis["open"] += 1
        elif status == Need.Status.CLOSED:
            kpis["to_choose"] += 1 if need.bids_count else 0
        elif need.is_awarded_or_later:
            kpis["awarded"] += 1
        done = status in (Need.Status.RELEASED, Need.Status.CANCELLED)
        if (tab == "active" and done) or (tab == "done" and not done):
            continue
        needs.append(need)
    return render(request, "auctions/my_needs.html", {"needs": needs, "tab": tab, "tabs": MY_TABS, "kpis": kpis})


# --- JSON -------------------------------------------------------------------------

@require_GET
def need_bids_json(request: HttpRequest, pk: int) -> JsonResponse:
    """Polled every 5 s by the detail page. Carries the ranked rows both as data and as
    the rendered `_bids_list.html` fragment so the page can swap the list in place."""
    Need.objects.close_expired()
    need = get_object_or_404(Need.objects.select_related("client", "winning_bid__freelancer"), pk=pk)
    wallet = get_wallet(request)
    ctx = _bids_context(need, _weights_from_request(request), wallet)
    history = _price_history(need)
    ctx.update({"history": history, "history_points": _points(history), "savings_pct": _savings_pct(need)})
    payload = {
        "ok": True,
        "need": need.pk,
        "status": ctx["status"],
        "bidding_ends_at": need.bidding_ends_at.isoformat(),
        "budget_max": dec_str(need.budget_max),
        "best_price": dec_str(need.best_price) if need.best_price is not None else None,
        "count": len(ctx["rows"]),
        "weights": list(ctx["weights"]),
        "fingerprint": ctx["fingerprint"],
        "bids": [_bid_json(r) for r in ctx["rows"]],
        "html": render_to_string("auctions/_bids_list.html", ctx, request=request),
        "history_points": ctx["history_points"],
        "history_count": len(history),
        "history_html": render_to_string("auctions/_history.html", ctx, request=request),
    }
    return JsonResponse(payload)


@require_POST
@wallet_required
def bid_create(request: HttpRequest, pk: int) -> JsonResponse:
    need = get_object_or_404(Need, pk=pk)
    wallet = get_wallet(request)
    data = _json_body(request)
    try:
        bid = services.place_bid(
            need,
            wallet,
            price=data.get("price"),
            delay_days=data.get("delay_days"),
            tags=data.get("tags"),
            message=str(data.get("message") or ""),
        )
    except BidError as e:
        return _error_response(e)
    need.refresh_from_db()
    return JsonResponse(
        {
            "ok": True,
            "bid": {"id": bid.pk, "price": dec_str(bid.price), "delay_days": bid.delay_days, "tags": bid.tags},
            "best_price": dec_str(need.best_price),
            "message": "Votre offre est enregistrée.",
        },
        status=201,
    )


@require_POST
@wallet_required
def need_close(request: HttpRequest, pk: int) -> JsonResponse:
    need = get_object_or_404(Need, pk=pk)
    try:
        need = services.close_bidding_now(need, get_wallet(request))
    except NeedError as e:
        return _error_response(e)
    return JsonResponse({"ok": True, "status": need.status, "message": "Enchères clôturées. À vous de choisir."})


@require_POST
@wallet_required
def need_award(request: HttpRequest, pk: int, bid_pk: int) -> JsonResponse:
    need = get_object_or_404(Need, pk=pk)
    bid = get_object_or_404(Bid.objects.select_related("freelancer"), pk=bid_pk, need=need)
    try:
        need = services.award(need, bid, get_wallet(request))
    except NeedError as e:
        return _error_response(e)
    return JsonResponse(
        {
            "ok": True,
            "status": need.status,
            "winning_bid": bid.pk,
            "payee": bid.freelancer.stellar_address,
            "amount": dec_str(bid.price),
            "message": f"Offre de {bid.freelancer.short_address} retenue.",
        }
    )


@require_POST
@wallet_required
def need_cancel(request: HttpRequest, pk: int) -> JsonResponse:
    need = get_object_or_404(Need, pk=pk)
    try:
        need = services.cancel(need, get_wallet(request))
    except NeedError as e:
        return _error_response(e)
    return JsonResponse({"ok": True, "status": need.status, "message": "Besoin annulé."})
