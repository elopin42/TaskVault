"""Need (un besoin) and Bid (une enchère) — the reverse-auction domain.

Timer semantics are lazy: nothing runs a cron. `Need.objects.close_expired()`
flips `open` needs whose deadline passed to `closed` and is called at the top of
the list/detail views; `effective_status()` gives the same answer without a write.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Count, Min, Q
from django.utils import timezone

NOT_OUTBID = ~Q(bids__status="outbid")

STATUS_LABELS = {
    "open": "Ouvert",
    "closed": "Terminé",
    "awarded": "Attribué",
    "funded": "Financé",
    "delivered": "Livré",
    "released": "Payé",
    "cancelled": "Annulé",
}
STATUS_BADGES = {
    "open": "ui-badge-info",
    "closed": "ui-badge-attn",
    "awarded": "ui-badge-brand",
    "funded": "ui-badge-ok",
    "delivered": "ui-badge-ok",
    "released": "ui-badge-ok",
    "cancelled": "ui-badge-neutral",
}


class NeedQuerySet(models.QuerySet):
    def close_expired(self) -> int:
        """Flip every `open` need whose timer ran out to `closed`. Returns the row count."""
        return self.filter(status=Need.Status.OPEN, bidding_ends_at__lte=timezone.now()).update(
            status=Need.Status.CLOSED, updated_at=timezone.now()
        )

    def with_stats(self):
        """Annotate `bid_count` and `lowest_price` over non-outbid bids (one query for list pages)."""
        return self.annotate(
            bid_count=Count("bids", filter=NOT_OUTBID),
            lowest_price=Min("bids__price", filter=NOT_OUTBID),
        )

    def open_now(self):
        return self.filter(status=Need.Status.OPEN, bidding_ends_at__gt=timezone.now())


class Need(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        CLOSED = "closed", "Terminé"
        AWARDED = "awarded", "Attribué"
        FUNDED = "funded", "Financé"  # payments app
        DELIVERED = "delivered", "Livré"  # payments app
        RELEASED = "released", "Payé"  # payments app
        CANCELLED = "cancelled", "Annulé"

    client = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="needs")
    title = models.CharField(max_length=120)
    description = models.TextField()
    budget_max = models.DecimalField(max_digits=18, decimal_places=7)
    delay_max_days = models.PositiveSmallIntegerField()
    tags = models.JSONField(default=list, blank=True)
    bidding_ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    winning_bid = models.OneToOneField(
        "auctions.Bid", on_delete=models.SET_NULL, null=True, blank=True, related_name="won_need"
    )
    awarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NeedQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"

    # --- status helpers -----------------------------------------------------

    def is_bidding_open(self) -> bool:
        return self.status == self.Status.OPEN and timezone.now() < self.bidding_ends_at

    def effective_status(self) -> str:
        """`closed` for an `open` need whose timer ran out, else the stored status."""
        if self.status == self.Status.OPEN and timezone.now() >= self.bidding_ends_at:
            return self.Status.CLOSED
        return self.status

    @property
    def effective_status_label(self) -> str:
        return STATUS_LABELS[self.effective_status()]

    @property
    def badge_class(self) -> str:
        return STATUS_BADGES[self.effective_status()]

    @property
    def is_closed(self) -> bool:
        return self.effective_status() == self.Status.CLOSED

    @property
    def is_awarded_or_later(self) -> bool:
        return self.effective_status() in (
            self.Status.AWARDED,
            self.Status.FUNDED,
            self.Status.DELIVERED,
            self.Status.RELEASED,
        )

    @property
    def can_cancel(self) -> bool:
        return self.effective_status() in (self.Status.OPEN, self.Status.CLOSED, self.Status.AWARDED)

    def is_client(self, wallet) -> bool:
        return wallet is not None and wallet.pk == self.client_id

    # --- bids ---------------------------------------------------------------

    def ranked_bid_qs(self):
        """Bids that still count: everything but a freelancer's superseded (`outbid`) ones."""
        return self.bids.exclude(status=Bid.Status.OUTBID).select_related("freelancer")

    @property
    def best_price(self) -> Decimal | None:
        """Lowest price among counting bids, or None when nobody bid yet."""
        if hasattr(self, "lowest_price"):  # annotated by NeedQuerySet.with_stats()
            return self.lowest_price
        return self.ranked_bid_qs().aggregate(m=Min("price"))["m"]

    @property
    def current_price(self) -> Decimal:
        """Lowest counting bid, or the budget cap when nobody bid yet."""
        best = self.best_price
        return best if best is not None else self.budget_max

    @property
    def bids_count(self) -> int:
        cached = getattr(self, "bid_count", None)
        if cached is not None:
            return cached
        return self.ranked_bid_qs().count()

    def active_bid_for(self, wallet):
        if wallet is None:
            return None
        return self.bids.filter(freelancer=wallet, status=Bid.Status.ACTIVE).first()


class Bid(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        OUTBID = "outbid", "Remplacée"
        WON = "won", "Gagnée"
        LOST = "lost", "Non retenue"

    need = models.ForeignKey(Need, on_delete=models.CASCADE, related_name="bids")
    freelancer = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="bids")
    price = models.DecimalField(max_digits=18, decimal_places=7)
    delay_days = models.PositiveSmallIntegerField()
    tags = models.JSONField(default=list, blank=True)
    message = models.CharField(max_length=280, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["need", "freelancer"],
                condition=Q(status="active"),
                name="auctions_one_active_bid_per_freelancer",
            )
        ]

    def __str__(self) -> str:
        return f"Bid #{self.pk} {self.price} USDC on need #{self.need_id}"

    def matching_tags(self, need=None) -> list[str]:
        need = need or self.need
        wanted = set(need.tags or [])
        return [t for t in (self.tags or []) if t in wanted]
