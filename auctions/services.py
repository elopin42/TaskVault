"""Business rules R1–R14 (docs/PRODUCT.md) in one place. Views only translate
AuctionError codes into HTTP; templates never decide a rule.
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Bid, Need

logger = logging.getLogger(__name__)

MAX_TAGS = 3
MAX_TAG_LENGTH = 24
USDC_PLACES = 7


class AuctionError(Exception):
    """A refused action. `code` is stable (used by JS/tests), `message` is French UI copy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BidError(AuctionError):
    """R1–R7: a bid that cannot be placed."""


class NeedError(AuctionError):
    """Close / award / cancel refused."""


# --- helpers --------------------------------------------------------------------

def dec_str(value: Decimal) -> str:
    """'450', '400.5' — never '4.5E+2' (Decimal.normalize alone is not JSON/UI friendly)."""
    return f"{Decimal(value).normalize():f}"


def clean_tags(raw) -> list[str]:
    """Accept a list or a comma/space-separated string → ≤3 unique lowercase slugs.

    Raises BidError("bad_tags") when more than MAX_TAGS remain or a slug is empty/too long.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,\s;]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        raise BidError("bad_tags", "Les compétences doivent être une liste de mots.")
    tags: list[str] = []
    for part in parts:
        slug = slugify(part.strip().lower())
        if not slug:
            continue
        if len(slug) > MAX_TAG_LENGTH:
            raise BidError("bad_tags", f"Une compétence fait au plus {MAX_TAG_LENGTH} caractères.")
        if slug not in tags:
            tags.append(slug)
    if len(tags) > MAX_TAGS:
        raise BidError("bad_tags", f"Au plus {MAX_TAGS} compétences.")
    return tags


def parse_price(raw) -> Decimal:
    """R7: strictly positive, at most 7 decimals (USDC precision on Stellar)."""
    try:
        price = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        raise BidError("invalid", "Prix invalide.") from None
    if not price.is_finite() or price <= 0:
        raise BidError("invalid", "Le prix doit être strictement positif.")
    exponent = price.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > USDC_PLACES:
        raise BidError("invalid", f"Au plus {USDC_PLACES} décimales (précision USDC).")
    if price >= Decimal(10) ** 11:
        raise BidError("invalid", "Prix trop élevé.")
    return price


def parse_delay(raw) -> int:
    try:
        delay = int(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        raise BidError("invalid", "Délai invalide.") from None
    if delay <= 0 or delay > 32767:
        raise BidError("invalid", "Le délai doit être un nombre de jours strictement positif.")
    return delay


# --- bidding ----------------------------------------------------------------------

def place_bid(need: Need, freelancer, price, delay_days, tags, message: str = "") -> Bid:
    """Place (or replace) `freelancer`'s bid on `need`. Rules R1–R7.

    Runs inside one transaction with the need row locked (`select_for_update`) so two
    simultaneous bids cannot both read the same "current lowest" price.
    """
    price = parse_price(price)
    delay_days = parse_delay(delay_days)
    tags = clean_tags(tags)
    message = (message or "").strip()[:280]

    with transaction.atomic():
        locked = Need.objects.select_for_update().get(pk=need.pk)

        if not locked.is_bidding_open():
            raise BidError("closed", "Les enchères sont terminées pour ce besoin.")
        if locked.client_id == freelancer.pk:  # R5
            raise BidError("own_need", "Vous ne pouvez pas enchérir sur votre propre besoin.")
        if price > locked.budget_max:  # R2
            raise BidError("over_budget", f"Le prix dépasse le budget max ({dec_str(locked.budget_max)} USDC).")
        if delay_days > locked.delay_max_days:  # R3
            raise BidError("over_delay", f"Le délai dépasse le délai max ({locked.delay_max_days} jours).")

        lowest = locked.best_price  # includes the freelancer's own active bid → R6 falls out of R1
        if lowest is not None and price >= lowest:  # R1
            raise BidError("not_lower", f"Le prix doit être strictement inférieur à {dec_str(lowest)} USDC.")

        # R6: the freelancer's previous active bid is superseded, never deleted.
        locked.bids.filter(freelancer=freelancer, status=Bid.Status.ACTIVE).update(status=Bid.Status.OUTBID)

        bid = Bid.objects.create(
            need=locked,
            freelancer=freelancer,
            price=price,
            delay_days=delay_days,
            tags=tags,
            message=message,
        )
        logger.info("bid placed need=%s bid=%s freelancer=%s price=%s", locked.pk, bid.pk, freelancer.pk, price)
        return bid


# --- client actions ---------------------------------------------------------------

def _require_client(need: Need, client) -> None:
    if client is None or need.client_id != client.pk:  # R10
        raise NeedError("forbidden", "Seul l’auteur du besoin peut faire cela.")


def close_bidding_now(need: Need, client) -> Need:
    """Demo shortcut: the client ends bidding early (status `closed`, deadline = now)."""
    _require_client(need, client)
    with transaction.atomic():
        locked = Need.objects.select_for_update().get(pk=need.pk)
        if locked.effective_status() != Need.Status.OPEN:
            raise NeedError("not_open", "Les enchères ne sont plus ouvertes.")
        now = timezone.now()
        locked.status = Need.Status.CLOSED
        locked.bidding_ends_at = now
        locked.save(update_fields=["status", "bidding_ends_at", "updated_at"])
        logger.info("bidding closed early need=%s", locked.pk)
        return locked


def award(need: Need, bid: Bid, client) -> Need:
    """R9–R11: the client picks ANY counting bid once bidding is closed."""
    _require_client(need, client)
    with transaction.atomic():
        locked = Need.objects.select_for_update().get(pk=need.pk)
        if locked.effective_status() != Need.Status.CLOSED:
            raise NeedError("not_closed", "Attendez la fin des enchères avant de choisir une offre.")
        fresh = Bid.objects.filter(pk=bid.pk, need=locked).first()  # the caller's instance may be stale
        if fresh is None or fresh.status == Bid.Status.OUTBID:
            raise NeedError("bad_bid", "Cette offre ne peut pas être retenue.")
        now = timezone.now()
        locked.bids.exclude(pk=bid.pk).exclude(status=Bid.Status.OUTBID).update(status=Bid.Status.LOST)
        Bid.objects.filter(pk=bid.pk).update(status=Bid.Status.WON)
        if locked.status == Need.Status.OPEN:  # timer ran out but close_expired() has not run yet
            locked.bidding_ends_at = min(locked.bidding_ends_at, now)
        locked.status = Need.Status.AWARDED
        locked.winning_bid = bid
        locked.awarded_at = now
        locked.save(update_fields=["status", "winning_bid", "awarded_at", "bidding_ends_at", "updated_at"])
        logger.info("need awarded need=%s bid=%s", locked.pk, bid.pk)
        bid.refresh_from_db()
        return locked


def cancel(need: Need, client) -> Need:
    """R14: cancel while nothing is in escrow (open / closed / awarded)."""
    _require_client(need, client)
    with transaction.atomic():
        locked = Need.objects.select_for_update().get(pk=need.pk)
        if not locked.can_cancel:
            raise NeedError("too_late", "Ce besoin ne peut plus être annulé (fonds en escrow).")
        if locked.status == Need.Status.OPEN:
            locked.bidding_ends_at = min(locked.bidding_ends_at, timezone.now())
        locked.status = Need.Status.CANCELLED
        locked.save(update_fields=["status", "bidding_ends_at", "updated_at"])
        logger.info("need cancelled need=%s", locked.pk)
        return locked
