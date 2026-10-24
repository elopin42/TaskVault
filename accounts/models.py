from django.db import models


class WalletUser(models.Model):
    """One row per Stellar wallet that has signed in. The wallet IS the identity."""

    stellar_address = models.CharField(max_length=56, unique=True, db_index=True)
    display_name = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.display_name or self.short_address

    @property
    def short_address(self) -> str:
        a = self.stellar_address
        return f"{a[:4]}…{a[-4:]}" if len(a) > 9 else a
