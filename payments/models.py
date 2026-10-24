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
    "created": "En préparation",
    "deployed": "Escrow créé",
    "funded": "Fonds bloqués",
    "delivered": "Livré",
    "approved": "Livraison validée",
    "released": "Fonds libérés",
    "paid": "Payé",
    "failed": "Échec",
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
        ESCROW = "escrow", "Escrow Trustless Work"
        DIRECT = "direct", "Paiement direct (sans escrow)"

    class Status(models.TextChoices):
        CREATED = "created", "En préparation"
        DEPLOYED = "deployed", "Escrow créé"
        FUNDED = "funded", "Fonds bloqués"
        DELIVERED = "delivered", "Livré"
        APPROVED = "approved", "Livraison validée"
        RELEASED = "released", "Fonds libérés"
        PAID = "paid", "Payé"  # direct mode terminal state
        FAILED = "failed", "Échec"

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
    # The delivery link as sent to Trustless Work (`newEvidence`, ≤ 280 chars); Task.delivery_link keeps the full link.
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
        """Every stored on-chain reference, in flow order: [{key, label, url, value}]."""
        links: list[dict] = []
        if self.contract_id:
            links.append(
                {
                    "key": "contract",
                    "label": "Contrat escrow",
                    "url": stellar.explorer_contract_url(self.contract_id),
                    "value": self.contract_id,
                }
            )
        labels = (
            ("deploy_tx_hash", "Création de l’escrow"),
            ("fund_tx_hash", "Blocage des fonds"),
            ("deliver_tx_hash", "Déclaration de livraison"),
            ("approve_tx_hash", "Validation"),
            ("release_tx_hash", "Libération des fonds"),
            ("payment_tx_hash", "Paiement direct"),
        )
        for field, label in labels:
            value = getattr(self, field)
            if value:
                links.append({"key": field, "label": label, "url": stellar.explorer_tx_url(value), "value": value})
        return links
