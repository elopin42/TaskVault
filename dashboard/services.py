"""View-models for the dashboard and the public wallet profile.

Pure read helpers over auctions (Need / Bid) and payments (Escrow + next_action): no HTTP,
no writes. Every function takes a WalletUser and returns plain dicts / lists so the templates
stay dumb and the tests can assert on data rather than on markup.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from auctions.models import Bid, Need
from payments import services as pay
from payments.models import Escrow

NOT_OUTBID = ~Q(bids__status=Bid.Status.OUTBID)
LATER_THAN_AWARDED = (Need.Status.AWARDED, Need.Status.FUNDED, Need.Status.DELIVERED, Need.Status.RELEASED)
SOON = timedelta(hours=1)


def _detail(need: Need, anchor: str = "") -> str:
    return reverse("auctions:need_detail", kwargs={"pk": need.pk}) + anchor


# --- to-do ------------------------------------------------------------------------

def todo_items(wallet) -> list[dict]:
    """What this wallet should look at, `act` items first (then by date desc).

    Each item: {tone: act|wait, kicker, headline, body, href, cta, icon, when}.
    """
    Need.objects.close_expired()
    now = timezone.now()
    items: list[dict] = []

    my_needs = Need.objects.filter(client=wallet).with_stats().select_related("winning_bid__freelancer")
    for need in my_needs:
        status = need.effective_status()
        if status == Need.Status.CLOSED and need.bids_count:
            items.append(
                {
                    "tone": "act",
                    "kicker": "Enchères terminées",
                    "headline": f"Choisir un freelance pour « {need.title} »",
                    "body": f"{need.bids_count} offre{'s' if need.bids_count > 1 else ''}, la meilleure à "
                    f"{need.best_price:,.2f} USDC.",
                    "href": _detail(need, "#bids-panel"),
                    "cta": "Choisir",
                    "icon": "fa-check",
                    "when": need.bidding_ends_at,
                }
            )
        elif status in LATER_THAN_AWARDED:
            action = pay.next_action(need, wallet)
            if action and action["mine"]:
                items.append(
                    {
                        "tone": "act",
                        "kicker": "Paiement",
                        "headline": f"{action['label']} — « {need.title} »",
                        "body": action["hint"],
                        "href": _detail(need, "#paiement"),
                        "cta": action["label"],
                        "icon": action["icon"],
                        "when": need.awarded_at or need.updated_at,
                    }
                )
            elif action:
                items.append(
                    {
                        "tone": "wait",
                        "kicker": "Paiement",
                        "headline": f"« {need.title} » : {action['waiting'].rstrip('.')}",
                        "body": "",
                        "href": _detail(need, "#paiement"),
                        "cta": "Voir",
                        "icon": "fa-hourglass-half",
                        "when": need.awarded_at or need.updated_at,
                    }
                )
        elif status == Need.Status.OPEN and not need.bids_count and need.bidding_ends_at - now < SOON:
            items.append(
                {
                    "tone": "wait",
                    "kicker": "Bientôt fermé",
                    "headline": f"Aucune offre sur « {need.title} »",
                    "body": "Les enchères se terminent dans moins d’une heure. Partagez le lien ou prolongez via un nouveau besoin.",
                    "href": _detail(need),
                    "cta": "Voir",
                    "icon": "fa-clock",
                    "when": need.bidding_ends_at,
                }
            )

    my_bids = (
        Bid.objects.filter(freelancer=wallet, status__in=(Bid.Status.ACTIVE, Bid.Status.WON))
        .select_related("need", "need__client", "need__winning_bid__freelancer")
        .order_by("-created_at")
    )
    for bid in my_bids:
        need = bid.need
        if bid.status == Bid.Status.WON:
            action = pay.next_action(need, wallet)
            if action and action["mine"]:
                items.append(
                    {
                        "tone": "act",
                        "kicker": "Enchère gagnée",
                        "headline": f"{action['label']} — « {need.title} »",
                        "body": action["hint"],
                        "href": _detail(need, "#paiement"),
                        "cta": action["label"],
                        "icon": action["icon"],
                        "when": need.awarded_at or bid.created_at,
                    }
                )
            elif action:
                items.append(
                    {
                        "tone": "wait",
                        "kicker": "Enchère gagnée",
                        "headline": f"« {need.title} » : {action['waiting'].rstrip('.')}",
                        "body": "",
                        "href": _detail(need, "#paiement"),
                        "cta": "Voir",
                        "icon": "fa-hourglass-half",
                        "when": need.awarded_at or bid.created_at,
                    }
                )
        elif need.effective_status() == Need.Status.OPEN:
            best = need.best_price
            if best is not None and bid.price > best:
                items.append(
                    {
                        "tone": "act",
                        "kicker": "Offre dépassée",
                        "headline": f"Améliorer mon offre sur « {need.title} »",
                        "body": f"Votre offre : {bid.price:,.2f} USDC. Meilleure offre : {best:,.2f} USDC.",
                        "href": _detail(need, "#bid-form-panel"),
                        "cta": "Enchérir",
                        "icon": "fa-gavel",
                        "when": bid.created_at,
                    }
                )

    items.sort(key=lambda it: (0 if it["tone"] == "act" else 1, -(it["when"].timestamp() if it["when"] else 0)))
    return items


# --- stats ------------------------------------------------------------------------

def client_stats(wallet) -> dict:
    needs = list(Need.objects.filter(client=wallet).with_stats().select_related("winning_bid"))
    statuses = [n.effective_status() for n in needs]
    committed = sum((n.winning_bid.price for n in needs if n.winning_bid_id), Decimal("0"))
    done = Escrow.objects.filter(
        need__client=wallet, status__in=(Escrow.Status.RELEASED, Escrow.Status.PAID)
    ).count()
    return {
        "total": len(needs),
        "open": statuses.count(Need.Status.OPEN),
        "to_choose": sum(1 for n, s in zip(needs, statuses) if s == Need.Status.CLOSED and n.bids_count),
        "awarded": sum(1 for s in statuses if s in LATER_THAN_AWARDED),
        "paid": done,
        "committed_usdc": committed,
        "bids_received": sum(n.bids_count for n in needs),
    }


def freelancer_stats(wallet) -> dict:
    bids = list(
        Bid.objects.filter(freelancer=wallet)
        .exclude(status=Bid.Status.OUTBID)
        .select_related("need")
    )
    active = [b for b in bids if b.status == Bid.Status.ACTIVE and b.need.effective_status() == Need.Status.OPEN]
    leading = 0
    for b in active:
        best = b.need.best_price
        if best is not None and b.price <= best:
            leading += 1
    won = [b for b in bids if b.status == Bid.Status.WON]
    lost = [b for b in bids if b.status == Bid.Status.LOST]
    earned = Decimal("0")
    if won:
        earned = sum(
            (
                e.amount
                for e in Escrow.objects.filter(
                    need__winning_bid__in=[b.pk for b in won], status__in=(Escrow.Status.RELEASED, Escrow.Status.PAID)
                )
            ),
            Decimal("0"),
        )
    decided = len(won) + len(lost)
    return {
        "total": Bid.objects.filter(freelancer=wallet).count(),
        "active": len(active),
        "leading": leading,
        "won": len(won),
        "lost": len(lost),
        "earned_usdc": earned,
        "win_rate": int(round(100 * len(won) / decided)) if decided else None,
    }


# --- activity ---------------------------------------------------------------------

def recent_activity(wallet, limit: int = 12) -> list[dict]:
    """Merged, newest-first timeline: my bids, my needs (created / awarded), escrow milestones."""
    events: list[dict] = []

    for bid in Bid.objects.filter(freelancer=wallet).select_related("need").order_by("-created_at")[:limit]:
        events.append(
            {
                "when": bid.created_at,
                "icon": "fa-gavel",
                "tone": "brand",
                "text": f"Offre de {bid.price:,.2f} USDC sur « {bid.need.title} »",
                "href": _detail(bid.need),
            }
        )

    needs = Need.objects.filter(client=wallet).select_related("winning_bid__freelancer").order_by("-created_at")[:limit]
    for need in needs:
        events.append(
            {
                "when": need.created_at,
                "icon": "fa-pen-to-square",
                "tone": "",
                "text": f"Besoin publié : « {need.title} » (budget max {need.budget_max:,.2f} USDC)",
                "href": _detail(need),
            }
        )
        if need.awarded_at and need.winning_bid_id:
            events.append(
                {
                    "when": need.awarded_at,
                    "icon": "fa-trophy",
                    "tone": "brand",
                    "text": f"Offre de {need.winning_bid.freelancer.short_address} retenue sur « {need.title} »",
                    "href": _detail(need),
                }
            )

    escrows = Escrow.objects.filter(Q(need__client=wallet) | Q(need__winning_bid__freelancer=wallet)).select_related(
        "need"
    )
    for escrow in escrows:
        for when, text in (
            (escrow.funded_at, "Fonds bloqués en escrow"),
            (escrow.delivered_at, "Livraison déclarée"),
            (escrow.released_at, "Paiement envoyé" if escrow.is_direct else "Fonds libérés"),
        ):
            if when:
                events.append(
                    {
                        "when": when,
                        "icon": "fa-money-bill-transfer",
                        "tone": "ok",
                        "text": f"{text} — « {escrow.need.title} » ({escrow.amount:,.2f} USDC)",
                        "href": _detail(escrow.need, "#paiement"),
                    }
                )

    events.sort(key=lambda e: e["when"], reverse=True)
    return events[:limit]


# --- public profile ---------------------------------------------------------------

def profile_stats(wallet) -> dict:
    Need.objects.close_expired()
    needs = Need.objects.filter(client=wallet).exclude(status=Need.Status.CANCELLED).with_stats().select_related("client")
    bids = Bid.objects.filter(freelancer=wallet)
    won = (
        bids.filter(status=Bid.Status.WON)
        .select_related("need", "need__client")
        .order_by("-created_at")[:10]
    )
    counts = bids.aggregate(total=Count("pk"), won=Count("pk", filter=Q(status=Bid.Status.WON)))
    return {
        "needs_posted": needs.count(),
        "needs_completed": Need.objects.filter(client=wallet, status=Need.Status.RELEASED).count(),
        "bids_placed": counts["total"],
        "bids_won": counts["won"],
        "member_since": wallet.created_at,
        "last_login": wallet.last_login_at,
        "needs": list(needs.order_by("-created_at")[:10]),
        "won_bids": list(won),
    }
