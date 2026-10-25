"""Trust network: a wallet follows and recommends other wallets.

Follow        follower → followed   (one row per pair, never yourself)
Recommendation author → subject    (one row per pair, optional 280-char message, never yourself)

Both are public. The rules (idempotent follow, upsert of the recommendation, one-hop signals)
live in services.py; the constraints below are the last line of defence at the DB level.
"""

from django.db import models
from django.db.models import F, Q

MAX_MESSAGE = 280


class Follow(models.Model):
    follower = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="following")
    followed = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="followers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["follower", "followed"], name="network_follow_unique_pair"),
            models.CheckConstraint(condition=~Q(follower=F("followed")), name="network_follow_not_self"),
        ]

    def __str__(self) -> str:
        return f"{self.follower} follows {self.followed}"


class Recommendation(models.Model):
    author = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="recommendations_given")
    subject = models.ForeignKey(
        "accounts.WalletUser", on_delete=models.PROTECT, related_name="recommendations_received"
    )
    message = models.CharField(max_length=MAX_MESSAGE, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["author", "subject"], name="network_recommendation_unique_pair"),
            models.CheckConstraint(condition=~Q(author=F("subject")), name="network_recommendation_not_self"),
        ]

    def __str__(self) -> str:
        return f"{self.author} recommends {self.subject}"
