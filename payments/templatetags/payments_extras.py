"""`{% escrow_panel need wallet %}` — renders templates/payments/_escrow_panel.html with the
payment view-model (escrow row, mode, stepper, next action for this viewer, explorer links).
Keeps the auctions view free of payment logic."""

from django import template
from django.conf import settings

from payments import services, stellar
from payments.models import Escrow

register = template.Library()


@register.inclusion_tag("payments/_escrow_panel.html", takes_context=True)
def escrow_panel(context, need, wallet=None):
    escrow = services.get_escrow(need)
    mode = services.effective_mode(escrow)
    status = escrow.status if escrow is not None else Escrow.Status.CREATED
    role = services.viewer_role(need, wallet)
    winning_bid = need.winning_bid
    payee = winning_bid.freelancer.stellar_address if winning_bid else ""
    amount = escrow.amount if escrow is not None else (winning_bid.price if winning_bid else None)
    action = services.next_action(need, wallet)
    return {
        "request": context.get("request"),
        "need": need,
        "winning_bid": winning_bid,
        "escrow": escrow,
        "mode": mode,
        "is_direct": mode == Escrow.Mode.DIRECT,
        "status": status,
        "status_label": escrow.status_label if escrow is not None else "En attente",
        "badge_class": escrow.badge_class if escrow is not None else "ui-badge-neutral",
        "is_done": escrow.is_done if escrow is not None else False,
        "steps": services.stepper(mode, status),
        "action": action,
        "role": role,
        "is_party": role in ("client", "winner"),
        "amount": amount,
        "payee": payee,
        "payer": need.client.stellar_address,
        "payee_explorer_url": stellar.explorer_account_url(payee) if payee else "",
        "links": escrow.explorer_links() if escrow is not None else [],
        "last_error": escrow.last_error if escrow is not None else "",
        "pending_hash": bool(escrow and escrow.payment_tx_hash and escrow.status != Escrow.Status.PAID),
        "usdc_code": settings.STELLAR_USDC_CODE,
    }
