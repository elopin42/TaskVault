"""Plan B (direct USDC payment) + Horizon helpers, built with the python `stellar_sdk`.

Spec: docs/STELLAR_NOTES.md §2. Django builds the UNSIGNED XDR, Freighter signs it
in the browser (`Lowbid.pay.signAndSend`), Django submits it to Horizon so the
result lands in the DB whatever the browser does.

THE Plan B switch is :func:`payment_mode`: ``settings.LOWBID_PAYMENT_MODE`` =
``"escrow"`` (Trustless Work) | ``"direct"`` (one `payment` op) | ``""`` (auto:
escrow when the Trustless Work key is configured, else direct). Views pick the
flow from it; both flows end on the same stellar.expert link.

Horizon is reached with plain `requests` (one dependency to mock, same error
envelope shape as `payments.trustless_work`). XDR building is offline when the
caller injects `sequence` (tests, retries); otherwise the source account is loaded
from Horizon.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings
from stellar_sdk import Account, Asset, TextMemo, TransactionBuilder, TransactionEnvelope
from stellar_sdk.operation import ChangeTrust, Payment

logger = logging.getLogger(__name__)

DEFAULT_BASE_FEE = 100  # stroops per operation
TX_TIMEOUT_SECONDS = 300
MEMO_MAX_BYTES = 28
HORIZON_TIMEOUT = 8.0
USDC_DECIMALS = 7

ERR_HORIZON_UNREACHABLE = "Horizon est injoignable, réessayez dans un instant."
ERR_ACCOUNT_NOT_FOUND = "Compte Stellar introuvable sur le réseau : financez-le d’abord (friendbot sur testnet)."
ERR_BAD_XDR = "Transaction signée illisible."
ERR_TIMEOUT = "Horizon n’a pas confirmé à temps — vérifiez la transaction sur l’explorateur avant de réessayer."

# Horizon `extras.result_codes` → French user message. Operation codes win over the
# transaction code (`tx_failed` alone says nothing useful).
RESULT_CODE_MESSAGES = {
    "op_no_trust": "Le destinataire n’a pas de trustline USDC.",
    "op_underfunded": "Solde USDC insuffisant.",
    "op_no_destination": "Le compte destinataire n’existe pas encore sur le réseau (financez-le via friendbot).",
    "op_line_full": "La trustline du destinataire est pleine.",
    "op_not_authorized": "Le destinataire n’est pas autorisé à détenir cet actif.",
    "op_no_issuer": "Émetteur USDC introuvable (mauvais réseau ?).",
    "op_low_reserve": "Réserve XLM insuffisante pour ajouter la trustline (≈ 0,5 XLM).",
    "op_malformed": "Opération mal formée.",
    "tx_bad_seq": "Réessayez (numéro de séquence dépassé).",
    "tx_bad_auth": "Transaction signée par une autre adresse que le compte source.",
    "tx_insufficient_fee": "Frais réseau insuffisants, réessayez.",
    "tx_insufficient_balance": "Solde XLM insuffisant pour payer les frais réseau.",
    "tx_too_late": "La transaction a expiré, recommencez la signature.",
    "tx_too_early": "La transaction n’est pas encore valide, réessayez.",
    "tx_no_source_account": "Le compte source n’existe pas sur le réseau.",
    "tx_failed": "La transaction a été rejetée par le réseau.",
}

Envelope = dict[str, Any]


class StellarError(Exception):
    """Raised by the XDR builders when the transaction cannot be assembled (message is user-facing French)."""


# --- settings accessors --------------------------------------------------------


def network_passphrase() -> str:
    return settings.STELLAR_NETWORK_PASSPHRASE


def horizon_url() -> str:
    return settings.STELLAR_HORIZON_URL.rstrip("/")


def usdc_asset() -> Asset:
    """The USDC asset from settings (Circle testnet issuer by default)."""
    return Asset(settings.STELLAR_USDC_CODE, settings.STELLAR_USDC_ISSUER)


def payment_mode() -> str:
    """THE Plan B switch: "escrow" (Trustless Work) or "direct" (single payment op)."""
    mode = (getattr(settings, "LOWBID_PAYMENT_MODE", "") or "").strip().lower()
    if mode in ("escrow", "direct"):
        return mode
    from payments.trustless_work import is_configured  # local import: no import cycle at module load

    return "escrow" if is_configured() else "direct"


# --- stellar.expert links -----------------------------------------------------


def _explorer_base() -> str:
    net = "public" if getattr(settings, "STELLAR_NETWORK", "testnet") == "public" else "testnet"
    return f"https://stellar.expert/explorer/{net}"


def explorer_tx_url(tx_hash: str) -> str:
    return f"{_explorer_base()}/tx/{tx_hash}"


def explorer_account_url(address: str) -> str:
    return f"{_explorer_base()}/account/{address}"


def explorer_contract_url(contract_id: str) -> str:
    return f"{_explorer_base()}/contract/{contract_id}"


# --- Horizon reads -----------------------------------------------------------------


def _horizon_get(path: str, timeout: float = HORIZON_TIMEOUT) -> tuple[int, dict]:
    """GET Horizon; (status, json). status 0 = transport failure (already logged)."""
    url = f"{horizon_url()}{path}"
    try:
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("stellar: horizon transport error path=%s err=%s", path, exc.__class__.__name__)
        return 0, {}
    except Exception:
        logger.exception("stellar: unexpected horizon error path=%s", path)
        return 0, {}
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    if resp.status_code >= 500:
        logger.warning("stellar: horizon path=%s status=%s", path, resp.status_code)
    return int(resp.status_code), data if isinstance(data, dict) else {}


def load_account(address: str) -> dict | None:
    """Horizon `/accounts/{id}` JSON, or None when the account is unknown or Horizon failed."""
    status, data = _horizon_get(f"/accounts/{address}")
    if status == 200 and data.get("sequence") is not None:
        return data
    if status == 404:
        logger.info("stellar: account not found address=%s", address)
    return None


def load_sequence(address: str) -> int | None:
    data = load_account(address)
    if not data:
        return None
    try:
        return int(data["sequence"])
    except (KeyError, TypeError, ValueError):
        logger.warning("stellar: bad sequence in horizon account payload address=%s", address)
        return None


def horizon_base_fee() -> int:
    """Current base fee from `/fee_stats` (`last_ledger_base_fee`), 100 stroops when unavailable."""
    status, data = _horizon_get("/fee_stats", timeout=4.0)
    if status == 200:
        try:
            return max(int(data.get("last_ledger_base_fee", DEFAULT_BASE_FEE)), DEFAULT_BASE_FEE)
        except (TypeError, ValueError):
            pass
    return DEFAULT_BASE_FEE


def _usdc_balance_entry(account: dict) -> dict | None:
    asset = usdc_asset()
    for bal in account.get("balances") or []:
        if bal.get("asset_code") == asset.code and bal.get("asset_issuer") == asset.issuer:
            return bal
    return None


def has_usdc_trustline(address: str) -> bool | None:
    """True/False from Horizon; None when Horizon could not be reached. An unfunded account → False."""
    status, data = _horizon_get(f"/accounts/{address}")
    if status == 200:
        return _usdc_balance_entry(data) is not None
    if status == 404:
        return False
    return None


def transaction_status(tx_hash: str) -> bool | None:
    """Horizon `/transactions/{hash}` → True (applied, successful) / False (unknown or failed) / None (Horizon down).

    Used to reconcile a submit that timed out (504): the hash is known locally, so the
    service can finish the step without asking the user to sign again.
    """
    status, data = _horizon_get(f"/transactions/{tx_hash}")
    if status == 200:
        return bool(data.get("successful", True))
    if status == 404:
        return False
    return None


def usdc_balance(address: str) -> Decimal | None:
    """USDC balance as Decimal (0 without trustline / unfunded); None when Horizon could not be reached."""
    status, data = _horizon_get(f"/accounts/{address}")
    if status == 404:
        return Decimal("0")
    if status != 200:
        return None
    entry = _usdc_balance_entry(data)
    if not entry:
        return Decimal("0")
    try:
        return Decimal(str(entry.get("balance", "0")))
    except InvalidOperation:
        logger.warning("stellar: unparsable balance address=%s raw=%r", address, entry.get("balance"))
        return None


# --- XDR builders (unsigned) -----------------------------------------------------


def _amount_str(amount: Decimal | int | str) -> str:
    try:
        d = Decimal(str(amount))
    except InvalidOperation as exc:
        raise StellarError("Montant invalide.") from exc
    if d <= 0:
        raise StellarError("Le montant doit être supérieur à zéro.")
    q = d.quantize(Decimal(1).scaleb(-USDC_DECIMALS))
    if q != d:
        raise StellarError("Le montant ne peut pas avoir plus de 7 décimales.")
    text = format(q, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _memo_text(memo: str | None) -> str | None:
    """Trim to 28 UTF-8 bytes (Stellar text memo limit) without cutting a multibyte char."""
    if not memo:
        return None
    raw = memo.encode("utf-8")[:MEMO_MAX_BYTES]
    return raw.decode("utf-8", errors="ignore") or None


def _sequence_or_raise(source: str) -> int:
    """Current sequence from Horizon; 404 → ERR_ACCOUNT_NOT_FOUND, anything else that is
    not a 200 → ERR_HORIZON_UNREACHABLE (a proxy 403 or a 5xx is not an unfunded account)."""
    status, data = _horizon_get(f"/accounts/{source}")
    if status == 404:
        logger.info("stellar: account not found address=%s", source)
        raise StellarError(ERR_ACCOUNT_NOT_FOUND)
    if status != 200:
        raise StellarError(ERR_HORIZON_UNREACHABLE)
    try:
        return int(data["sequence"])
    except (KeyError, TypeError, ValueError):
        logger.warning("stellar: bad sequence in horizon account payload address=%s", source)
        raise StellarError(ERR_HORIZON_UNREACHABLE) from None


def _builder(source: str, sequence: int | None, base_fee: int | None) -> TransactionBuilder:
    if sequence is None:
        sequence = _sequence_or_raise(source)
        if base_fee is None:
            base_fee = horizon_base_fee()
    if base_fee is None:
        base_fee = DEFAULT_BASE_FEE  # offline build: no extra Horizon round trip
    account = Account(source, sequence)
    return TransactionBuilder(account, network_passphrase=network_passphrase(), base_fee=int(base_fee))


def build_payment_xdr(
    *,
    source: str,
    destination: str,
    amount: Decimal,
    memo: str | None = None,
    sequence: int | None = None,
    base_fee: int | None = None,
) -> str:
    """Unsigned XDR: one USDC `payment` op `source` → `destination`, optional text memo (≤ 28 bytes).

    `sequence` = the source account's CURRENT sequence (as Horizon reports it; the SDK
    increments). Omit it to load the account from Horizon. Raises StellarError.
    """
    amount_str = _amount_str(amount)
    try:
        builder = _builder(source, sequence, base_fee)
        builder.append_payment_op(destination=destination, asset=usdc_asset(), amount=amount_str)
        text = _memo_text(memo)
        if text:
            builder.add_text_memo(text)
        tx = builder.set_timeout(TX_TIMEOUT_SECONDS).build()
    except StellarError:
        raise
    except Exception as exc:
        logger.exception("stellar: build_payment_xdr failed source=%s destination=%s", source, destination)
        raise StellarError("Impossible de préparer la transaction de paiement.") from exc
    return tx.to_xdr()


def build_change_trust_xdr(*, source: str, sequence: int | None = None, base_fee: int | None = None) -> str:
    """Unsigned XDR adding the USDC trustline on `source` (limit = max). Raises StellarError."""
    try:
        builder = _builder(source, sequence, base_fee)
        tx = builder.append_change_trust_op(asset=usdc_asset()).set_timeout(TX_TIMEOUT_SECONDS).build()
    except StellarError:
        raise
    except Exception as exc:
        logger.exception("stellar: build_change_trust_xdr failed source=%s", source)
        raise StellarError("Impossible de préparer la transaction de trustline.") from exc
    return tx.to_xdr()


def parse_payment_xdr(xdr: str) -> dict | None:
    """Describe a (signed or unsigned) single-payment XDR so a view can check it matches the job.

    Returns {source, destination, amount (Decimal), asset_code, asset_issuer, memo, hash, op_type}
    or None when the XDR does not parse on this network. `op_type` is "payment" / "change_trust" / other.
    """
    try:
        env = TransactionEnvelope.from_xdr(xdr, network_passphrase())
    except Exception:
        logger.warning("stellar: unparsable xdr")
        return None
    tx = env.transaction
    if len(tx.operations) != 1:
        return None
    op = tx.operations[0]
    info: dict[str, Any] = {
        "source": tx.source.account_id,
        "hash": env.hash_hex(),
        "memo": tx.memo.memo_text.decode("utf-8", errors="ignore") if isinstance(tx.memo, TextMemo) else None,
        "op_type": op.__class__.__name__.lower(),
        "destination": None,
        "amount": None,
        "asset_code": None,
        "asset_issuer": None,
    }
    if isinstance(op, Payment):
        info.update(
            op_type="payment",
            destination=op.destination.account_id,
            amount=Decimal(str(op.amount)),
            asset_code=op.asset.code,
            asset_issuer=op.asset.issuer,
        )
    elif isinstance(op, ChangeTrust):
        asset = op.asset
        info.update(op_type="change_trust", asset_code=getattr(asset, "code", None), asset_issuer=getattr(asset, "issuer", None))
    return info


# --- submit --------------------------------------------------------------------------


def explain_result_codes(codes: dict | None) -> str:
    """Pick the most specific Horizon result code and translate it."""
    codes = codes or {}
    for op_code in codes.get("operations") or []:
        if op_code and op_code != "op_success":
            return RESULT_CODE_MESSAGES.get(op_code, f"Opération rejetée ({op_code}).")
    tx_code = codes.get("transaction")
    if tx_code:
        return RESULT_CODE_MESSAGES.get(tx_code, f"Transaction rejetée ({tx_code}).")
    return RESULT_CODE_MESSAGES["tx_failed"]


def submit_xdr(signed_xdr: str, timeout: float = 30.0) -> Envelope:
    """POST the signed XDR to Horizon `/transactions`.

    Envelope: {"ok", "status", "data", "error", "hash"}. `hash` is computed locally from the
    envelope so it is known even when Horizon times out (504) — show the explorer link then.
    """
    try:
        env = TransactionEnvelope.from_xdr(signed_xdr, network_passphrase())
        tx_hash = env.hash_hex()
    except Exception:
        logger.warning("stellar: submit_xdr got an unparsable xdr")
        return {"ok": False, "status": 0, "data": {}, "error": ERR_BAD_XDR, "hash": None}

    url = f"{horizon_url()}/transactions"
    try:
        resp = requests.post(url, data={"tx": signed_xdr}, headers={"Accept": "application/json"}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("stellar: horizon submit transport error hash=%s err=%s", tx_hash, exc.__class__.__name__)
        return {"ok": False, "status": 0, "data": {}, "error": ERR_HORIZON_UNREACHABLE, "hash": tx_hash}
    except Exception:
        logger.exception("stellar: unexpected error submitting hash=%s", tx_hash)
        return {"ok": False, "status": 0, "data": {}, "error": ERR_HORIZON_UNREACHABLE, "hash": tx_hash}

    status = int(resp.status_code)
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    if 200 <= status < 300:
        logger.info("stellar: tx submitted hash=%s ledger=%s", data.get("hash", tx_hash), data.get("ledger"))
        return {"ok": True, "status": status, "data": data, "error": None, "hash": data.get("hash") or tx_hash}

    extras = data.get("extras") or {}
    if status == 504:
        error = ERR_TIMEOUT
    elif extras.get("result_codes"):
        error = explain_result_codes(extras.get("result_codes"))
    else:
        error = data.get("detail") or data.get("title") or f"Horizon a répondu {status}."
    logger.warning("stellar: horizon rejected hash=%s status=%s codes=%s", tx_hash, status, extras.get("result_codes"))
    return {"ok": False, "status": status, "data": data, "error": error, "hash": tx_hash}


__all__ = [
    "StellarError",
    "build_change_trust_xdr",
    "build_payment_xdr",
    "explain_result_codes",
    "explorer_account_url",
    "explorer_contract_url",
    "explorer_tx_url",
    "has_usdc_trustline",
    "horizon_base_fee",
    "load_account",
    "load_sequence",
    "network_passphrase",
    "parse_payment_xdr",
    "payment_mode",
    "submit_xdr",
    "transaction_status",
    "usdc_asset",
    "usdc_balance",
]
