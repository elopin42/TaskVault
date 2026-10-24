"""Verify a Freighter `signMessage` signature server-side.

What Freighter signs has changed over time, so verification tries, in order:

1. ``sep53``  — Freighter >= 5.34 (SEP-53): Ed25519 over
                sha256(b"Stellar Signed Message:\\n" + message).
2. ``raw``    — older Freighter: Ed25519 over the raw UTF-8 message bytes.
3. ``sha256`` — Ed25519 over sha256(message), seen in some early wallets.

The matching scheme name is returned (and logged by the caller) so a drift in
the extension shows up in the logs instead of as a silent login failure.
"""

import base64
import binascii
import hashlib
import logging

from stellar_sdk import Keypair
from stellar_sdk.exceptions import BadSignatureError, Ed25519PublicKeyInvalidError

logger = logging.getLogger(__name__)

SCHEMES = ("sep53", "raw", "sha256")


def decode_signature(raw: str) -> bytes | None:
    """Accept the base64 string Freighter returns (also tolerates hex); 64 bytes or None."""
    s = (raw or "").strip()
    if not s:
        return None
    for decoder in (lambda v: base64.b64decode(v, validate=True), binascii.unhexlify):
        try:
            sig = decoder(s)
        except (ValueError, binascii.Error):
            continue
        if len(sig) == 64:
            return sig
    return None


def verify_signature(address: str, message: str, signature: bytes) -> str | None:
    """Return the scheme that validates `signature` for `message`, or None."""
    try:
        kp = Keypair.from_public_key(address)
    except (Ed25519PublicKeyInvalidError, ValueError):
        return None

    msg_bytes = message.encode("utf-8")
    candidates = {
        "sep53": lambda: kp.verify_message(msg_bytes, signature),
        "raw": lambda: kp.verify(msg_bytes, signature),
        "sha256": lambda: kp.verify(hashlib.sha256(msg_bytes).digest(), signature),
    }
    for scheme in SCHEMES:
        try:
            candidates[scheme]()
            return scheme
        except BadSignatureError:
            continue
    return None
