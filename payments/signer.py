"""Server-side signing with the two keys TaskVault holds for the publication deposit (testnet).

    LOWBID_PLATFORM_SECRET          public key = LOWBID_PLATFORM_ADDRESS: the deposit escrow's approver,
                                    serviceProvider, releaseSigner and platformAddress — signs the refund
                                    chain (milestone → approve → release) and OPENS the dispute
    LOWBID_DEPOSIT_RESOLVER_SECRET  a second key, the deposit escrow's disputeResolver — signs the resolve
                                    (the contract refuses a dispute opened by the resolver, so one key
                                    cannot do both)

Rules: Keypair objects are built on demand and never kept in a module global (nothing for a debug page
to print); only public addresses are logged — never a secret, never a signed XDR body. A Trustless
Work XDR is single use and short-lived: callers build → sign → send inside one request.
`payments/checks.py` refuses a misconfiguration at boot while deposits are active.
"""

import logging

from django.conf import settings
from stellar_sdk import Keypair, TransactionEnvelope

from payments import stellar
from payments.services import PaymentError

logger = logging.getLogger(__name__)

ERR_NOT_CONFIGURED = "Server signing key is not configured."
ERR_BAD_XDR = "The escrow service returned an unreadable transaction."


def _keypair(setting: str) -> Keypair:
    secret = (getattr(settings, setting, "") or "").strip()
    if not secret:
        logger.warning("signer: %s is empty", setting)
        raise PaymentError("provider", ERR_NOT_CONFIGURED)
    try:
        return Keypair.from_secret(secret)
    except Exception:
        # Never log the value (nor the exception text, which may echo it).
        logger.warning("signer: %s is not a valid Stellar secret", setting)
        raise PaymentError("provider", ERR_NOT_CONFIGURED) from None


def platform_keypair() -> Keypair:
    """The platform key (LOWBID_PLATFORM_SECRET); PaymentError('provider') when missing / invalid."""
    return _keypair("LOWBID_PLATFORM_SECRET")


def deposit_resolver_keypair() -> Keypair:
    """The deposit disputeResolver key (LOWBID_DEPOSIT_RESOLVER_SECRET); PaymentError('provider') when missing / invalid."""
    return _keypair("LOWBID_DEPOSIT_RESOLVER_SECRET")


def platform_address() -> str:
    return platform_keypair().public_key


def deposit_resolver_address() -> str:
    return deposit_resolver_keypair().public_key


def sign_xdr(unsigned_xdr: str, keypair: Keypair) -> str:
    """Sign a Trustless Work-built XDR with `keypair` (testnet passphrase from settings) and return the
    signed XDR. PaymentError('tampered') when the XDR cannot be parsed, ('provider') when signing fails."""
    try:
        envelope = TransactionEnvelope.from_xdr(unsigned_xdr, stellar.network_passphrase())
    except Exception:
        logger.warning("signer: unparsable unsigned xdr signer=%s", keypair.public_key)
        raise PaymentError("tampered", ERR_BAD_XDR) from None
    try:
        envelope.sign(keypair)
        signed = envelope.to_xdr()
    except Exception:
        logger.exception("signer: signing failed signer=%s", keypair.public_key)
        raise PaymentError("provider", "The server could not sign the transaction.") from None
    logger.info("signer: signed tx hash=%s signer=%s", envelope.hash_hex(), keypair.public_key)
    return signed
