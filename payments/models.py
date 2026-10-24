"""Escrow — one payment record per Need, from "escrow created" to "funds released".

The row exists from the FIRST prepare call (deploy in escrow mode, deliver / direct_pay in
direct mode), so `mode` is frozen there via `payments.stellar.payment_mode()`. Hashes are
written by `payments.services.confirm_<step>`; nothing in this module talks to the network.
The state table for both modes lives in the docstring of `payments/services.py`.
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
        DIRECT = "direct", "Paiement direct USDC (Plan B)"

    class Status(models.TextChoices):
        CREATED = "created", "En préparation"
        DEPLOYED = "deployed", "Escrow créé"
        FUNDED = "funded", "Fonds bloqués"
        DELIVERED = "delivered", "Livré"
        APPROVED = "approved", "Livraison validée"
        RELEASED = "released", "Fonds libérés"
        PAID = "paid", "Payé"  # direct mode terminal state
        FAILED = "failed", "Échec"

    need = models.OneToOneField("auctions.Need", on_delete=models.CASCADE, related_name="escrow")
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
    payment_tx_hash = models.CharField(max_length=64, blank=True)  # Plan B
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED, db_index=True)
    # Short delivery evidence typed by the freelancer (also sent to TW as `newEvidence` in escrow mode).
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
        return f"Escrow need#{self.need_id} {self.mode} {self.status}"

    # --- presentation helpers ----------------------------------------------------

    @property
    def is_direct(self) -> bool:
        return self.mode == self.Mode.DIRECT

    @property
    def is_done(self) -> bool:
        return self.status in (self.Status.RELEASED, self.Status.PAID)

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
            ("payment_tx_hash", "Paiement USDC"),
        )
        for field, label in labels:
            value = getattr(self, field)
            if value:
                links.append({"key": field, "label": label, "url": stellar.explorer_tx_url(value), "value": value})
        return links
