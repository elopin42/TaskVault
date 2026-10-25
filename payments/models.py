"""Escrow — one payment record per TASK, from "escrow created" to "funds released" / "paid" / "resolved".

Why per task: Trustless Work v1 fixes the milestone receiver at deploy and freezes the escrow once
it holds funds, so a project-wide escrow funded before the freelances are chosen could never pay
them. Each task therefore gets its own single-release escrow, deployed + funded by the company once
a freelance is chosen (amount = task.price, payer = project.company, payee = task.assigned_to).

The row exists from the FIRST prepare call (deploy in escrow mode, deliver / direct_pay in direct
mode) or from `on_task_validated`, so `mode` is frozen there via `payments.stellar.payment_mode()`.
Hashes are written by `payments.services.confirm_<step>`; nothing in this module talks to the
network. The state table for both modes lives in the docstring of `payments/services.py`.

Dispute (escrow mode only): a party signs Trustless Work's dispute-escrow (`disputed`, funds stay
locked), then the arbiter wallet (`resolver_address` = LOWBID_DISPUTE_RESOLVER, the contract's
disputeResolver fixed at deploy) signs resolve-dispute with the split (`resolved`, terminal).
"""

from django.db import models

from payments import stellar

STATUS_LABELS = {
    "created": "Preparing",
    "deployed": "Escrow created",
    "funded": "Funds locked",
    "delivered": "Delivered",
    "approved": "Delivery validated",
    "released": "Funds released",
    "paid": "Paid",
    "disputed": "In dispute",
    "resolved": "Resolved by the arbiter",
    "failed": "Failed",
}
STATUS_BADGES = {
    "created": "ui-badge-neutral",
    "deployed": "ui-badge-info",
    "funded": "ui-badge-info",
    "delivered": "ui-badge-attn",
    "approved": "ui-badge-attn",
    "released": "ui-badge-ok",
    "paid": "ui-badge-ok",
    "disputed": "ui-badge-danger",
    "resolved": "ui-badge-brand",
    "failed": "ui-badge-danger",
}


class Escrow(models.Model):
    class Mode(models.TextChoices):
        ESCROW = "escrow", "Trustless Work escrow"
        DIRECT = "direct", "Direct payment (no escrow)"

    class Status(models.TextChoices):
        CREATED = "created", "Preparing"
        DEPLOYED = "deployed", "Escrow created"
        FUNDED = "funded", "Funds locked"
        DELIVERED = "delivered", "Delivered"
        APPROVED = "approved", "Delivery validated"
        RELEASED = "released", "Funds released"
        PAID = "paid", "Paid"  # direct mode terminal state
        DISPUTED = "disputed", "In dispute"  # escrow mode: dispute-escrow confirmed, funds locked until the arbiter decides
        RESOLVED = "resolved", "Resolved by the arbiter"  # escrow mode terminal state: resolve-dispute confirmed
        FAILED = "failed", "Failed"

    task = models.OneToOneField("projects.Task", on_delete=models.CASCADE, related_name="escrow")
    mode = models.CharField(max_length=8, choices=Mode.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=7)
    payer_address = models.CharField(max_length=56)
    payee_address = models.CharField(max_length=56)
    platform_address = models.CharField(max_length=56, blank=True)
    # The arbiter wallet (Trustless Work `disputeResolver`, fixed at deploy): LOWBID_DISPUTE_RESOLVER, else the
    # platform address, else the company (same fallback as platform_address). Signs resolve-dispute.
    resolver_address = models.CharField(max_length=56, blank=True)
    # Trustless Work single-release contract (C…); empty in direct mode / before deploy.
    contract_id = models.CharField(max_length=64, blank=True, null=True)
    engagement_id = models.CharField(max_length=40, blank=True)
    deploy_tx_hash = models.CharField(max_length=64, blank=True)
    fund_tx_hash = models.CharField(max_length=64, blank=True)
    deliver_tx_hash = models.CharField(max_length=64, blank=True)
    approve_tx_hash = models.CharField(max_length=64, blank=True)
    release_tx_hash = models.CharField(max_length=64, blank=True)
    payment_tx_hash = models.CharField(max_length=64, blank=True)  # direct mode
    dispute_tx_hash = models.CharField(max_length=64, blank=True)  # escrow mode: dispute-escrow signed by a party
    resolve_tx_hash = models.CharField(max_length=64, blank=True)  # escrow mode: resolve-dispute signed by the arbiter
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED, db_index=True)
    # The milestone evidence as sent to Trustless Work (`newEvidence`, ≤ 280 chars): payments.services.build_evidence
    # (`sha256:<hash> <link>` / `git:<hash> <link>` / `<link>`); Task keeps the full link, hash and source link.
    delivery_note = models.CharField(max_length=280, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Escrow task#{self.task_id} {self.mode} {self.status}"

    # --- presentation helpers ----------------------------------------------------

    @property
    def is_direct(self) -> bool:
        return self.mode == self.Mode.DIRECT

    @property
    def is_done(self) -> bool:
        return self.status in (self.Status.RELEASED, self.Status.PAID, self.Status.RESOLVED)

    @property
    def is_disputed(self) -> bool:
        return self.status == self.Status.DISPUTED

    @property
    def holds_funds(self) -> bool:
        """Escrow mode: the amount is locked on chain (or already released / split by the arbiter — the
        money is accounted for either way). Direct mode: paid."""
        if self.mode == self.Mode.DIRECT:
            return self.status == self.Status.PAID
        return self.status in (
            self.Status.FUNDED,
            self.Status.DELIVERED,
            self.Status.APPROVED,
            self.Status.RELEASED,
            self.Status.DISPUTED,
            self.Status.RESOLVED,
        )

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def badge_class(self) -> str:
        return STATUS_BADGES.get(self.status, "ui-badge-neutral")

    def explorer_links(self) -> list[dict]:
        """Every stored on-chain reference, in flow order: [{key, label, url, value, at}] — `at` is the
        step's stored time (funded_at / delivered_at / released_at / disputed_at / resolved_at, None otherwise):
        the transaction's time."""
        links: list[dict] = []
        if self.contract_id:
            links.append(
                {
                    "key": "contract",
                    "label": "Escrow contract",
                    "url": stellar.explorer_contract_url(self.contract_id),
                    "value": self.contract_id,
                }
            )
        labels = (
            ("deploy_tx_hash", "Escrow creation", None),
            ("fund_tx_hash", "Funds locking", self.funded_at),
            ("deliver_tx_hash", "Delivery declaration", self.delivered_at),
            ("approve_tx_hash", "Validation", None),
            ("release_tx_hash", "Funds release", self.released_at),
            ("payment_tx_hash", "Direct payment", self.released_at),
            ("dispute_tx_hash", "Dispute opened", self.disputed_at),
            ("resolve_tx_hash", "Dispute resolved", self.resolved_at),
        )
        for field, label, at in labels:
            value = getattr(self, field)
            if value:
                links.append({"key": field, "label": label, "url": stellar.explorer_tx_url(value), "value": value, "at": at})
        return links


# --- publication deposit (payments/deposits.py) -------------------------------------------------

DEPOSIT_STATUS_LABELS = {
    "created": "Preparing",
    "deployed": "Deposit escrow created",
    "funded": "Deposit locked",
    "refunded": "Deposit refunded",
    "forfeited": "Forfeited to the guarantee fund",
}
DEPOSIT_STATUS_BADGES = {
    "created": "ui-badge-neutral",
    "deployed": "ui-badge-info",
    "funded": "ui-badge-attn",
    "refunded": "ui-badge-ok",
    "forfeited": "ui-badge-danger",
}


class ProjectDeposit(models.Model):
    """One publication (or top-up) deposit of a project: a Trustless Work single-release escrow the
    COMPANY deploys + funds in Freighter, settled by the SERVER keys — refunded to the company
    (milestone → approve → release, platform key) or forfeited to the guarantee fund (dispute with the
    platform key, resolve with the deposit resolver key). The state table and every rule live in
    payments/deposits.py; nothing here talks to the network.

    `covered_budget` is the part of the project budget this row covers (the whole budget for the
    publication deposit, the uncovered gap for a top-up), so Σ covered_budget of the funded / settled
    rows is the budget covered so far. The per-step hashes record the progress of the server chains
    (status only moves created → deployed → funded → refunded | forfeited)."""

    class Kind(models.TextChoices):
        PUBLICATION = "publication", "Publication deposit"
        TOPUP = "topup", "Deposit top-up"

    class Status(models.TextChoices):
        CREATED = "created", "Preparing"
        DEPLOYED = "deployed", "Deposit escrow created"
        FUNDED = "funded", "Deposit locked"
        REFUNDED = "refunded", "Deposit refunded"
        FORFEITED = "forfeited", "Forfeited to the guarantee fund"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="deposits")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.PUBLICATION)
    amount = models.DecimalField(max_digits=18, decimal_places=7)
    covered_budget = models.DecimalField(max_digits=18, decimal_places=7)
    payer_address = models.CharField(max_length=56)  # the company (receiver of a refund)
    platform_address = models.CharField(max_length=56)  # approver = serviceProvider = releaseSigner = platformAddress
    resolver_address = models.CharField(max_length=56)  # disputeResolver (second server key)
    fund_address = models.CharField(max_length=56, blank=True)  # guarantee fund, frozen at creation
    contract_id = models.CharField(max_length=64, blank=True)
    engagement_id = models.CharField(max_length=64, blank=True)
    deploy_tx_hash = models.CharField(max_length=64, blank=True)
    fund_tx_hash = models.CharField(max_length=64, blank=True)
    milestone_tx_hash = models.CharField(max_length=64, blank=True)
    approve_tx_hash = models.CharField(max_length=64, blank=True)
    release_tx_hash = models.CharField(max_length=64, blank=True)
    dispute_tx_hash = models.CharField(max_length=64, blank=True)
    resolve_tx_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED, db_index=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Deposit project#{self.project_id} {self.kind} {self.status}"

    @property
    def holds_funds(self) -> bool:
        return self.status == self.Status.FUNDED

    @property
    def is_settled(self) -> bool:
        return self.status in (self.Status.REFUNDED, self.Status.FORFEITED)

    @property
    def status_label(self) -> str:
        return DEPOSIT_STATUS_LABELS.get(self.status, self.status)

    @property
    def badge_class(self) -> str:
        return DEPOSIT_STATUS_BADGES.get(self.status, "ui-badge-neutral")

    def explorer_links(self) -> list[dict]:
        """Every stored on-chain reference, in flow order: [{key, label, url, value, at}] (same shape as
        Escrow.explorer_links)."""
        links: list[dict] = []
        if self.contract_id:
            links.append(
                {
                    "key": "contract",
                    "label": "Deposit escrow contract",
                    "url": stellar.explorer_contract_url(self.contract_id),
                    "value": self.contract_id,
                    "at": None,
                }
            )
        labels = (
            ("deploy_tx_hash", "Deposit escrow creation", None),
            ("fund_tx_hash", "Deposit locking", self.funded_at),
            ("milestone_tx_hash", "Refund: milestone", None),
            ("approve_tx_hash", "Refund: approval", None),
            ("release_tx_hash", "Refund: release", self.settled_at),
            ("dispute_tx_hash", "Ghost listing: dispute", None),
            ("resolve_tx_hash", "Ghost listing: sent to the fund", self.settled_at),
        )
        for field, label, at in labels:
            value = getattr(self, field)
            if value:
                links.append({"key": field, "label": label, "url": stellar.explorer_tx_url(value), "value": value, "at": at})
        return links
