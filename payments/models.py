"""Escrow — one payment record per TASK, from "escrow created" to "funds released" / "paid".

Why per task: Trustless Work v1 fixes the milestone receiver at deploy and freezes the escrow once
it holds funds, so a project-wide escrow funded before the freelances are chosen could never pay
them. Each task therefore gets its own single-release escrow, deployed + funded by the company once
a freelance is chosen (amount = task.price, payer = project.company, payee = task.assigned_to).

The row exists from the FIRST prepare call (deploy in escrow mode, deliver / direct_pay in direct
mode) or from `on_task_validated`, so `mode` is frozen there via `payments.stellar.payment_mode()`.
Hashes are written by `payments.services.confirm_<step>`; nothing in this module talks to the
network. The state table for both modes lives in the docstring of `payments/services.py`.
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
        FAILED = "failed", "Failed"

    task = models.OneToOneField("projects.Task", on_delete=models.CASCADE, related_name="escrow")
    mode = models.CharField(max_length=8, choices=Mode.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=7)
    payer_address = models.CharField(max_length=56)
    payee_address = models.CharField(max_length=56)
    platform_address = models.CharField(max_length=56, blank=True)
    # Trustless Work single-release contract (C…); empty in direct mode / before deploy.
    contract_id = models.CharField(max_length=64, blank=True, null=True)
    engagement_id = models.CharField(max_length=40, blank=True)
    deploy_tx_hash = models.CharField(max_length=64, blank=True)
    fund_tx_hash = models.CharField(max_length=64, blank=True)
    deliver_tx_hash = models.CharField(max_length=64, blank=True)
    approve_tx_hash = models.CharField(max_length=64, blank=True)
    release_tx_hash = models.CharField(max_length=64, blank=True)
    payment_tx_hash = models.CharField(max_length=64, blank=True)  # direct mode
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
        return self.status in (self.Status.RELEASED, self.Status.PAID)

    @property
    def holds_funds(self) -> bool:
        """Escrow mode: the amount is locked on chain (or already released). Direct mode: paid."""
        if self.mode == self.Mode.DIRECT:
            return self.status == self.Status.PAID
        return self.status in (self.Status.FUNDED, self.Status.DELIVERED, self.Status.APPROVED, self.Status.RELEASED)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def badge_class(self) -> str:
        return STATUS_BADGES.get(self.status, "ui-badge-neutral")

    def explorer_links(self) -> list[dict]:
        """Every stored on-chain reference, in flow order: [{key, label, url, value, at}] — `at` is the
        step's stored time (funded_at / delivered_at / released_at, None otherwise): the transaction's time."""
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
        )
        for field, label, at in labels:
            value = getattr(self, field)
            if value:
                links.append({"key": field, "label": label, "url": stellar.explorer_tx_url(value), "value": value, "at": at})
        return links
