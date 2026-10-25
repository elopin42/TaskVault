"""Reputation: what freelances say about companies, and wallets bound to a GitHub account.

- `CompanyRating`: the assignee of a settled task rates the company (1–5), once per task. The other
  direction (company → freelance) is `projects.Rating`; it feeds the score, this one never does.
- `GithubIdentity`: a wallet proved it controls a GitHub account (a public gist holding a Freighter
  signature of `lowbid:<G…>`, see `reputation.services.verify_github`). One GitHub account = one
  wallet (unique `github_id`), one wallet = one GitHub account (the 1-1).

Everything else (the "Reliable payer" figures, "New account", "No history") is computed on read from
`payments.Escrow` rows with a confirmed on-chain hash: nothing is cached here.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class CompanyRating(models.Model):
    task = models.OneToOneField("projects.Task", on_delete=models.CASCADE, related_name="company_rating")
    freelancer = models.ForeignKey(
        "accounts.WalletUser", on_delete=models.PROTECT, related_name="company_ratings_given"
    )
    company = models.ForeignKey(
        "accounts.WalletUser", on_delete=models.PROTECT, related_name="company_ratings_received"
    )
    note = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Company rating {self.note}/5 on task #{self.task_id}"


class GithubIdentity(models.Model):
    wallet = models.OneToOneField("accounts.WalletUser", on_delete=models.PROTECT, related_name="github_identity")
    github_id = models.PositiveBigIntegerField(unique=True)
    github_login = models.CharField(max_length=39)
    gist_id = models.CharField(max_length=64)
    account_created_at = models.DateTimeField()
    verified_at = models.DateTimeField(auto_now_add=True)
    # The accounts.signing scheme that validated the gist signature (sep53 / raw / sha256).
    scheme = models.CharField(max_length=8)

    class Meta:
        ordering = ["-verified_at"]
        verbose_name_plural = "GitHub identities"

    def __str__(self) -> str:
        return f"GitHub {self.github_login} ↔ wallet #{self.wallet_id}"

    @property
    def profile_url(self) -> str:
        return f"https://github.com/{self.github_login}"
