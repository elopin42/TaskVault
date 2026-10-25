"""Django system checks for the publication deposit's server-held keys (`manage.py check`, Tags.security).

While deposits are active (LOWBID_DEPOSIT_ENABLED and payment_mode() == "escrow") the server signs the
refund / forfeit chains itself, so a missing, invalid or overlapping key must stop the boot instead of
failing at the first settlement. The messages name the setting, never its value.
"""

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, Warning, register
from stellar_sdk import Keypair, StrKey


def _public_key(secret: str) -> str | None:
    try:
        return Keypair.from_secret(secret).public_key
    except Exception:  # an invalid secret is reported below, without its value
        return None


def _valid_address(address: str) -> bool:
    try:
        return StrKey.is_valid_ed25519_public_key(address)
    except Exception:
        return False


@register(Tags.security)
def check_deposit_keys(app_configs=None, **kwargs) -> list[CheckMessage]:
    """Publication deposits enabled in escrow mode: a MISSING key is a Warning (deposits stay off,
    `deposits_active()` is False), an invalid / mismatched / overlapping key is an Error. Messages never
    carry a secret."""
    from payments.deposits import deposits_enabled  # lazy: the app registry must be ready

    if not deposits_enabled():
        return []
    errors: list[CheckMessage] = []
    platform_address = (getattr(settings, "LOWBID_PLATFORM_ADDRESS", "") or "").strip()
    platform_secret = (getattr(settings, "LOWBID_PLATFORM_SECRET", "") or "").strip()
    resolver_secret = (getattr(settings, "LOWBID_DEPOSIT_RESOLVER_SECRET", "") or "").strip()
    fund_address = (getattr(settings, "LOWBID_GUARANTEE_FUND_ADDRESS", "") or "").strip()

    platform_public = _public_key(platform_secret) if platform_secret else None
    if not platform_secret:
        errors.append(Warning("LOWBID_PLATFORM_SECRET is not set: publication deposits stay disabled.", id="payments.W001"))
    elif platform_public is None:
        errors.append(Error("LOWBID_PLATFORM_SECRET is not a valid Stellar secret key.", id="payments.E002"))
    elif platform_public != platform_address:
        errors.append(
            Error("The public key of LOWBID_PLATFORM_SECRET does not match LOWBID_PLATFORM_ADDRESS.", id="payments.E003")
        )

    resolver_public = _public_key(resolver_secret) if resolver_secret else None
    if not resolver_secret:
        errors.append(
            Warning("LOWBID_DEPOSIT_RESOLVER_SECRET is not set: publication deposits stay disabled.", id="payments.W004")
        )
    elif resolver_public is None:
        errors.append(Error("LOWBID_DEPOSIT_RESOLVER_SECRET is not a valid Stellar secret key.", id="payments.E005"))
    elif resolver_public in (platform_public, platform_address):
        errors.append(
            Error(
                "LOWBID_DEPOSIT_RESOLVER_SECRET must be a different key from the platform key "
                "(the contract refuses a dispute opened by the resolver).",
                id="payments.E006",
            )
        )

    if not fund_address:
        errors.append(Warning("LOWBID_GUARANTEE_FUND_ADDRESS is not set: publication deposits stay disabled.", id="payments.W007"))
    elif not _valid_address(fund_address):
        errors.append(Error("LOWBID_GUARANTEE_FUND_ADDRESS is not a valid Stellar public key (G…).", id="payments.E008"))
    elif fund_address in (platform_address, platform_public):
        errors.append(Error("LOWBID_GUARANTEE_FUND_ADDRESS must differ from the platform address.", id="payments.E009"))
    return errors
