"""Payment orchestration for one Need — pure state logic, no HTTP of its own.

Network calls go through `payments.trustless_work` (escrow mode) and `payments.stellar`
(Plan B + Horizon). Every step is a `prepare_<step>(need, wallet, data)` /
`confirm_<step>(need, wallet, signed_xdr)` pair: prepare builds the unsigned XDR the
session wallet must sign in Freighter, confirm submits the signed XDR and persists the
result. Role and state gates run in BOTH halves, pinned to the session wallet.

State table — Escrow.status (payments) and Need.status (auctions):

    ESCROW mode (Trustless Work single-release, one milestone)
    step        who     Escrow: before → after     Need: before → after     on chain / persisted
    deploy      client  (none|created) → deployed  awarded → awarded        TW deployer → contract_id, deploy_tx_hash
    fund        client  deployed → funded          awarded → funded         TW fund-escrow → fund_tx_hash, funded_at
    deliver     winner  funded → delivered         funded → delivered       TW change-milestone-status → deliver_tx_hash, delivered_at
    approve     client  delivered → approved       delivered → delivered    TW approve-milestone → approve_tx_hash
    release     client  approved → released        delivered → released     TW release-funds → release_tx_hash, released_at

    DIRECT mode (Plan B: one USDC `payment` op; "funded" and "approved" do not exist)
    deliver     winner  created → delivered        awarded → delivered      NO transaction, DB only (delivery_note)
    direct_pay  client  created|delivered → paid   awarded|delivered → released
                                                                            Django builds the payment XDR, Freighter signs,
                                                                            Django checks it (source/destination/amount/issuer)
                                                                            and submits to Horizon → payment_tx_hash, released_at
    trustline   anyone  —                          —                        changeTrust XDR, or nothing when Horizon already shows it

Direct flow in words: awarded → (deliver, optional) → direct_pay → released. "Valider" for the
client in direct mode IS the payment. The mode is frozen on the Escrow row at the first prepare
(`stellar.payment_mode()`), but may be re-frozen while the row is still `created` (nothing is
on chain yet), so flipping `LOWBID_PAYMENT_MODE=direct` after a failed deploy just works.

Errors: `PaymentError(code, message)` with codes `not_awarded · forbidden · wrong_state ·
wrong_mode · unknown_step · tampered · provider · stellar`. A provider failure never flips the
status (the user retries); the vendor/Horizon message is kept in `Escrow.last_error`.
"""

import logging
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import TransactionEnvelope

from auctions.models import Need
from payments import stellar
from payments import trustless_work as tw
from payments.models import Escrow

logger = logging.getLogger(__name__)

EVIDENCE_MAX = 280
PENDING_MESSAGE = "Transaction envoyée, confirmation en attente — vérifiez sur l’explorateur."
MSG_TRUSTLINE_PRESENT = "Trustline USDC déjà présente."

S = Escrow.Status
M = Escrow.Mode


class PaymentError(Exception):
    """A refused payment action. `code` is stable (JS/tests), `message` is French UI copy."""

    def __init__(self, code: str, message: str, *, persist: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        # True → the confirm_* decorator stores the message in Escrow.last_error AFTER the
        # transaction rolled back (a write inside the atomic block would vanish with it).
        self.persist = persist


# --- flow definition -------------------------------------------------------------
# One row per step: who acts, which Escrow statuses allow it, UI copy.

FLOW = {
    M.ESCROW: [
        {
            "step": "deploy",
            "who": "client",
            "allowed": (S.CREATED,),
            "label": "Créer l’escrow",
            "icon": "fa-file-signature",
            "hint": "Déploie le contrat Trustless Work (une signature Freighter).",
            "waiting": "En attente de la création de l’escrow par le client.",
        },
        {
            "step": "fund",
            "who": "client",
            "allowed": (S.DEPLOYED,),
            "label": "Bloquer les fonds",
            "icon": "fa-lock",
            "hint": "Transfère le montant en USDC dans l’escrow.",
            "waiting": "En attente du blocage des fonds par le client.",
        },
        {
            "step": "deliver",
            "who": "winner",
            "allowed": (S.FUNDED,),
            "label": "Déclarer la livraison",
            "icon": "fa-box-open",
            "hint": "Marque le jalon comme livré (lien ou note de livraison).",
            "waiting": "En attente de la livraison du freelance.",
            "evidence": True,
        },
        {
            "step": "approve",
            "who": "client",
            "allowed": (S.DELIVERED,),
            "label": "Valider la livraison",
            "icon": "fa-check-double",
            "hint": "Approuve le jalon — les fonds restent bloqués jusqu’à la libération.",
            "waiting": "En attente de la validation du client.",
        },
        {
            "step": "release",
            "who": "client",
            "allowed": (S.APPROVED,),
            "label": "Libérer les fonds",
            "icon": "fa-money-bill-transfer",
            "hint": "L’escrow verse le montant au freelance (moins les frais).",
            "waiting": "En attente de la libération des fonds par le client.",
        },
    ],
    M.DIRECT: [
        {
            "step": "direct_pay",
            "who": "client",
            "allowed": (S.CREATED, S.DELIVERED),
            "label": "Payer le freelance",
            "label_after_delivery": "Valider et payer",
            "icon": "fa-money-bill-transfer",
            "hint": "Un paiement USDC direct, signé dans Freighter (sans escrow).",
            "waiting": "En attente du paiement par le client.",
        },
        {
            "step": "deliver",
            "who": "winner",
            "allowed": (S.CREATED,),
            "label": "Déclarer la livraison",
            "icon": "fa-box-open",
            "hint": "Sans escrow : une simple déclaration, aucune transaction.",
            "waiting": "En attente de la livraison du freelance.",
            "evidence": True,
            "no_tx": True,
        },
    ],
}

# Stepper milestones per mode (status that marks each one as reached, in order).
STEPPER = {
    M.ESCROW: [
        (S.DEPLOYED, "Escrow créé"),
        (S.FUNDED, "Fonds bloqués"),
        (S.DELIVERED, "Livré"),
        (S.RELEASED, "Fonds libérés"),
    ],
    M.DIRECT: [
        (S.DELIVERED, "Livré"),
        (S.PAID, "Payé"),
    ],
}
STATUS_ORDER = {
    M.ESCROW: [S.CREATED, S.DEPLOYED, S.FUNDED, S.DELIVERED, S.APPROVED, S.RELEASED],
    M.DIRECT: [S.CREATED, S.DELIVERED, S.PAID],
}
HASH_FIELD = {
    "deploy": "deploy_tx_hash",
    "fund": "fund_tx_hash",
    "deliver": "deliver_tx_hash",
    "approve": "approve_tx_hash",
    "release": "release_tx_hash",
    "direct_pay": "payment_tx_hash",
}
STEPS = tuple(HASH_FIELD)


def _flow_entry(mode: str, step: str) -> dict | None:
    for entry in FLOW[mode]:
        if entry["step"] == step:
            return entry
    return None


# --- helpers ---------------------------------------------------------------------


def viewer_role(need: Need, wallet) -> str:
    """'client' | 'winner' | 'other' | 'anonymous' for the panel and the gates."""
    if wallet is None:
        return "anonymous"
    if need.client_id == wallet.pk:
        return "client"
    if need.winning_bid_id and need.winning_bid.freelancer_id == wallet.pk:
        return "winner"
    return "other"


def get_escrow(need: Need) -> Escrow | None:
    return Escrow.objects.filter(need=need).first()


def _require_awarded(need: Need) -> None:
    if need.status not in (Need.Status.AWARDED, Need.Status.FUNDED, Need.Status.DELIVERED, Need.Status.RELEASED):
        raise PaymentError("not_awarded", "Le paiement n’est possible qu’une fois une offre retenue.")
    if need.winning_bid_id is None:
        raise PaymentError("not_awarded", "Aucune offre retenue sur ce besoin.")


def _platform_address(need: Need) -> str:
    address = (getattr(settings, "LOWBID_PLATFORM_ADDRESS", "") or "").strip()
    if not address:
        address = need.client.stellar_address
        logger.warning(
            "payments: LOWBID_PLATFORM_ADDRESS is empty — using the CLIENT wallet as disputeResolver AND platformAddress "
            "need=%s; Trustless Work may refuse identical roles, set LOWBID_PLATFORM_ADDRESS in .env",
            need.pk,
        )
    return address


def platform_fallback_in_use(need: Need, escrow: Escrow | None, mode: str) -> bool:
    """True when escrow mode will (or did) merge the platform roles onto the client wallet."""
    if mode != M.ESCROW:
        return False
    if escrow is not None and escrow.platform_address:
        return escrow.platform_address == need.client.stellar_address
    return not (getattr(settings, "LOWBID_PLATFORM_ADDRESS", "") or "").strip()


def ensure_escrow(need: Need) -> Escrow:
    """The Escrow row for this need, created at the first prepare. Mode frozen here
    (re-frozen while still `created`, so Plan B can be switched on after a failed deploy)."""
    _require_awarded(need)
    mode = stellar.payment_mode()
    bid = need.winning_bid
    escrow, created = Escrow.objects.get_or_create(
        need=need,
        defaults={
            "mode": mode,
            "amount": bid.price,
            "payer_address": need.client.stellar_address,
            "payee_address": bid.freelancer.stellar_address,
            "platform_address": _platform_address(need) if mode == M.ESCROW else "",
            "engagement_id": f"lowbid-{need.pk}",
        },
    )
    if created:
        logger.info("payments: escrow row created need=%s mode=%s amount=%s", need.pk, mode, bid.price)
    elif escrow.status == S.CREATED and escrow.mode != mode:
        logger.warning("payments: mode re-frozen need=%s %s -> %s", need.pk, escrow.mode, mode)
        escrow.mode = mode
        escrow.platform_address = _platform_address(need) if mode == M.ESCROW else ""
        escrow.save(update_fields=["mode", "platform_address", "updated_at"])
    return escrow


def _gate(need: Need, wallet, step: str) -> tuple[Escrow, dict]:
    """Role + mode + state check shared by prepare and confirm. Returns (escrow, flow entry)."""
    escrow = ensure_escrow(need)
    if step not in STEPS:
        raise PaymentError("unknown_step", "Étape de paiement inconnue.")
    entry = _flow_entry(escrow.mode, step)
    if entry is None:
        label = "direct" if escrow.mode == M.DIRECT else "escrow"
        raise PaymentError("wrong_mode", f"Cette étape n’existe pas en mode {label}.")
    role = viewer_role(need, wallet)
    if role != entry["who"]:
        who = "le client" if entry["who"] == "client" else "le freelance retenu"
        raise PaymentError("forbidden", f"Seul {who} peut faire cette action.")
    if escrow.status not in entry["allowed"]:
        raise PaymentError(
            "wrong_state",
            f"Étape « {entry['label']} » impossible à ce stade ({escrow.status_label}).",
        )
    return escrow, entry


def _xdr_hash(signed_xdr: str) -> str | None:
    try:
        return TransactionEnvelope.from_xdr(signed_xdr, stellar.network_passphrase()).hash_hex()
    except Exception:
        logger.warning("payments: unparsable signed xdr")
        return None


def _unsigned_xdr(env: dict) -> str:
    """The unsigned XDR of a Trustless Work build envelope, or PaymentError('provider')."""
    if not env.get("ok"):
        raise PaymentError("provider", env.get("error") or tw.ERR_UNEXPECTED)
    xdr = (env.get("data") or {}).get("unsignedTransaction")
    if not xdr:
        raise PaymentError("provider", tw.ERR_UNEXPECTED)
    return xdr


def _set_need_status(need: Need, status: str) -> None:
    if need.status != status:
        need.status = status
        need.save(update_fields=["status", "updated_at"])


def _record_error(escrow: Escrow, message: str) -> None:
    escrow.last_error = (message or "")[:1000]
    escrow.save(update_fields=["last_error", "updated_at"])


def _already_done(escrow: Escrow, step: str, tx_hash: str | None) -> bool:
    """Idempotent send: the same signed XDR arriving twice must not fail nor double-write."""
    if not tx_hash:
        return False
    if getattr(escrow, HASH_FIELD[step]) != tx_hash:
        return False
    entry = _flow_entry(escrow.mode, step)
    return entry is not None and escrow.status not in entry["allowed"]


def _records_errors(fn):
    """confirm_* wrapper: a PaymentError flagged `persist` lands in Escrow.last_error once the
    atomic block has rolled back, so the user sees the vendor message and can retry."""

    @wraps(fn)
    def wrapper(need, wallet, *args, **kwargs):
        try:
            return fn(need, wallet, *args, **kwargs)
        except PaymentError as exc:
            if exc.persist:
                Escrow.objects.filter(need=need).update(last_error=exc.message[:1000], updated_at=timezone.now())
            raise

    return wrapper


def _begin(need: Need, wallet, step: str, signed_xdr: str) -> tuple[Escrow, str | None, dict | None]:
    """Shared opening of every confirm_*: (escrow, local tx hash, idempotent result or None).
    The duplicate check runs BEFORE the state gate: a replayed send for a step already
    recorded with this very hash answers ok instead of `wrong_state`."""
    escrow = ensure_escrow(need)
    tx_hash = _xdr_hash(signed_xdr)
    entry = _flow_entry(escrow.mode, step)
    if entry is not None and viewer_role(need, wallet) == entry["who"] and _already_done(escrow, step, tx_hash):
        return escrow, tx_hash, _result(escrow, step, tx_hash, "Étape déjà confirmée.")
    escrow, _ = _gate(need, wallet, step)
    return escrow, tx_hash, None


def _tw_send(need: Need, escrow: Escrow, step: str, signed_xdr: str) -> tuple[str, dict]:
    """send-transaction; on failure raise a persisted provider error. Returns (local tx hash, data)."""
    tx_hash = _xdr_hash(signed_xdr)
    if tx_hash is None:
        raise PaymentError("tampered", stellar.ERR_BAD_XDR)
    env = tw.send_transaction(signed_xdr=signed_xdr)
    if not env.get("ok"):
        message = env.get("error") or tw.ERR_UNEXPECTED
        logger.warning("payments: provider refused need=%s step=%s hash=%s error=%s", need.pk, step, tx_hash, message)
        raise PaymentError("provider", message, persist=True)
    return tx_hash, env.get("data") or {}


def _result(escrow: Escrow, step: str, tx_hash: str, message: str, *, pending: bool = False) -> dict:
    return {
        "step": step,
        "status": escrow.status,
        "tx_hash": tx_hash,
        "contract_id": escrow.contract_id,
        "explorer_url": stellar.explorer_tx_url(tx_hash) if tx_hash else None,
        "message": message,
        "pending": pending,
    }


def _prepared(xdr: str | None, *, extra: dict | None = None, message: str | None = None) -> dict:
    """prepare_* return shape. `xdr` None means nothing to sign (the step is already done)."""
    return {"xdr": xdr, "extra": extra or {}, "message": message, "done": xdr is None}


# --- escrow mode: deploy / fund / deliver / approve / release ---------------------------


def prepare_deploy(need: Need, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(need, wallet, "deploy")
    env = tw.deploy_single_release(
        signer=escrow.payer_address,
        engagement_id=escrow.engagement_id,
        title=need.title,
        description=need.description,
        amount=escrow.amount,
        approver=escrow.payer_address,
        service_provider=escrow.payee_address,
        receiver=escrow.payee_address,
        release_signer=escrow.payer_address,
        dispute_resolver=escrow.platform_address,
        platform_address=escrow.platform_address,
        platform_fee=settings.LOWBID_PLATFORM_FEE,
        milestone_description=f"Livraison du besoin #{need.pk}",
    )
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_deploy(need: Need, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(need, wallet, "deploy", signed_xdr)
        if done:
            return done
        tx_hash, data = _tw_send(need, escrow, "deploy", signed_xdr)
        contract_id = data.get("contractId") or (data.get("escrow") or {}).get("contractId") or ""
        if not contract_id:
            logger.error("payments: deploy sent but no contractId need=%s hash=%s keys=%s", need.pk, tx_hash, list(data))
            raise PaymentError("provider", "Escrow envoyé mais identifiant de contrat manquant — contactez le support.", persist=True)
        escrow.contract_id = contract_id
        escrow.deploy_tx_hash = tx_hash
        escrow.status = S.DEPLOYED
        escrow.last_error = ""
        escrow.save(update_fields=["contract_id", "deploy_tx_hash", "status", "last_error", "updated_at"])
    logger.info("payments: confirm need=%s step=deploy wallet=%s hash=%s contract=%s", need.pk, wallet.stellar_address, tx_hash, contract_id)
    return _result(escrow, "deploy", tx_hash, "Escrow créé sur Stellar.")


def prepare_fund(need: Need, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(need, wallet, "fund")
    env = tw.fund_escrow(contract_id=escrow.contract_id, signer=escrow.payer_address, amount=escrow.amount)
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_fund(need: Need, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(need, wallet, "fund", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(need, escrow, "fund", signed_xdr)
        escrow.fund_tx_hash = tx_hash
        escrow.status = S.FUNDED
        escrow.funded_at = timezone.now()
        escrow.last_error = ""
        escrow.save(update_fields=["fund_tx_hash", "status", "funded_at", "last_error", "updated_at"])
        _set_need_status(need, Need.Status.FUNDED)
    logger.info("payments: confirm need=%s step=fund wallet=%s hash=%s", need.pk, wallet.stellar_address, tx_hash)
    return _result(escrow, "fund", tx_hash, "Fonds bloqués dans l’escrow.")


def _evidence(data: dict | None) -> str:
    return str((data or {}).get("evidence") or "").strip()[:EVIDENCE_MAX]


def prepare_deliver(need: Need, wallet, data: dict | None = None) -> dict:
    """Escrow mode: TW change-milestone-status XDR (freelancer signs).
    Direct mode: no transaction — the delivery is recorded right here."""
    evidence = _evidence(data)
    with transaction.atomic():
        escrow, entry = _gate(need, wallet, "deliver")
        if entry.get("no_tx"):
            escrow.status = S.DELIVERED
            escrow.delivered_at = timezone.now()
            escrow.delivery_note = evidence
            escrow.last_error = ""
            escrow.save(update_fields=["status", "delivered_at", "delivery_note", "last_error", "updated_at"])
            _set_need_status(need, Need.Status.DELIVERED)
            logger.info("payments: confirm need=%s step=deliver wallet=%s hash=- (direct, no tx)", need.pk, wallet.stellar_address)
            return _prepared(None, message="Livraison déclarée. Le client peut valider et payer.")
    env = tw.change_milestone_status(
        contract_id=escrow.contract_id, evidence=evidence, service_provider=escrow.payee_address
    )
    try:
        return _prepared(_unsigned_xdr(env), extra={"evidence": evidence})
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_deliver(need: Need, wallet, signed_xdr: str, data: dict | None = None) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(need, wallet, "deliver", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(need, escrow, "deliver", signed_xdr)
        escrow.deliver_tx_hash = tx_hash
        escrow.status = S.DELIVERED
        escrow.delivered_at = timezone.now()
        escrow.delivery_note = _evidence(data)
        escrow.last_error = ""
        escrow.save(update_fields=["deliver_tx_hash", "status", "delivered_at", "delivery_note", "last_error", "updated_at"])
        _set_need_status(need, Need.Status.DELIVERED)
    logger.info("payments: confirm need=%s step=deliver wallet=%s hash=%s", need.pk, wallet.stellar_address, tx_hash)
    return _result(escrow, "deliver", tx_hash, "Livraison déclarée. Le client peut valider.")


def prepare_approve(need: Need, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(need, wallet, "approve")
    env = tw.approve_milestone(contract_id=escrow.contract_id, approver=escrow.payer_address)
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_approve(need: Need, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(need, wallet, "approve", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(need, escrow, "approve", signed_xdr)
        escrow.approve_tx_hash = tx_hash
        escrow.status = S.APPROVED
        escrow.last_error = ""
        escrow.save(update_fields=["approve_tx_hash", "status", "last_error", "updated_at"])
    logger.info("payments: confirm need=%s step=approve wallet=%s hash=%s", need.pk, wallet.stellar_address, tx_hash)
    return _result(escrow, "approve", tx_hash, "Livraison validée. Vous pouvez libérer les fonds.")


def prepare_release(need: Need, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(need, wallet, "release")
    env = tw.release_funds(contract_id=escrow.contract_id, release_signer=escrow.payer_address)
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_release(need: Need, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(need, wallet, "release", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(need, escrow, "release", signed_xdr)
        escrow.release_tx_hash = tx_hash
        escrow.status = S.RELEASED
        escrow.released_at = timezone.now()
        escrow.last_error = ""
        escrow.save(update_fields=["release_tx_hash", "status", "released_at", "last_error", "updated_at"])
        _set_need_status(need, Need.Status.RELEASED)
    logger.info("payments: confirm need=%s step=release wallet=%s hash=%s", need.pk, wallet.stellar_address, tx_hash)
    return _result(escrow, "release", tx_hash, "Fonds libérés vers le freelance.")


# --- direct mode (Plan B): direct_pay ---------------------------------------------------


def _finalize_direct_pay(need: Need, escrow: Escrow, tx_hash: str) -> None:
    escrow.payment_tx_hash = tx_hash
    escrow.status = S.PAID
    escrow.released_at = timezone.now()
    escrow.last_error = ""
    escrow.save(update_fields=["payment_tx_hash", "status", "released_at", "last_error", "updated_at"])
    _set_need_status(need, Need.Status.RELEASED)


def prepare_direct_pay(need: Need, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(need, wallet, "direct_pay")
    if escrow.payment_tx_hash:
        # A previous submit timed out (Horizon 504) — reconcile before asking for a new signature.
        applied = stellar.transaction_status(escrow.payment_tx_hash)
        if applied is True:
            with transaction.atomic():
                _finalize_direct_pay(need, escrow, escrow.payment_tx_hash)
            logger.info("payments: confirm need=%s step=direct_pay wallet=%s hash=%s (reconciled)", need.pk, wallet.stellar_address, escrow.payment_tx_hash)
            return _prepared(None, message="Paiement confirmé sur le réseau.")
        if applied is None:
            raise PaymentError("provider", stellar.ERR_HORIZON_UNREACHABLE)
        logger.info("payments: pending hash not on chain, rebuilding need=%s hash=%s", need.pk, escrow.payment_tx_hash)
    try:
        xdr = stellar.build_payment_xdr(
            source=escrow.payer_address,
            destination=escrow.payee_address,
            amount=escrow.amount,
            memo=f"lowbid:{need.pk}",
        )
    except stellar.StellarError as exc:
        _record_error(escrow, str(exc))
        raise PaymentError("stellar", str(exc)) from exc
    return _prepared(xdr)


def _check_payment_xdr(escrow: Escrow, signed_xdr: str) -> dict:
    """The signed XDR must be exactly the payment we built: one USDC payment payer → payee for the bid amount."""
    info = stellar.parse_payment_xdr(signed_xdr)
    asset = stellar.usdc_asset()
    if (
        info is None
        or info.get("op_type") != "payment"
        or info.get("source") != escrow.payer_address
        or info.get("destination") != escrow.payee_address
        or info.get("asset_code") != asset.code
        or info.get("asset_issuer") != asset.issuer
        or info.get("amount") is None
        or Decimal(info["amount"]) != Decimal(escrow.amount)
    ):
        logger.warning("payments: tampered payment xdr need=%s parsed=%s", escrow.need_id, info)
        raise PaymentError("tampered", "La transaction signée ne correspond pas au paiement attendu.")
    return info


@_records_errors
def confirm_direct_pay(need: Need, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(need, wallet, "direct_pay", signed_xdr)
        if done:
            return done
        _check_payment_xdr(escrow, signed_xdr)
        env = stellar.submit_xdr(signed_xdr)
        if env.get("ok"):
            _finalize_direct_pay(need, escrow, env.get("hash") or tx_hash)
            logger.info("payments: confirm need=%s step=direct_pay wallet=%s hash=%s", need.pk, wallet.stellar_address, escrow.payment_tx_hash)
            return _result(escrow, "direct_pay", escrow.payment_tx_hash, "Paiement USDC confirmé.")
        if env.get("status") == 504 and env.get("hash"):
            escrow.payment_tx_hash = env["hash"]
            escrow.last_error = PENDING_MESSAGE
            escrow.save(update_fields=["payment_tx_hash", "last_error", "updated_at"])
            logger.warning("payments: horizon timeout need=%s step=direct_pay hash=%s", need.pk, env["hash"])
            return _result(escrow, "direct_pay", env["hash"], PENDING_MESSAGE, pending=True)
        message = env.get("error") or stellar.ERR_HORIZON_UNREACHABLE
        logger.warning("payments: horizon refused need=%s step=direct_pay hash=%s error=%s", need.pk, tx_hash, message)
        raise PaymentError("provider", message, persist=True)


# --- trustline (any wallet, no need) ----------------------------------------------------


def prepare_trustline(address: str) -> dict:
    present = stellar.has_usdc_trustline(address)
    if present is True:
        return _prepared(None, message=MSG_TRUSTLINE_PRESENT)
    try:
        return _prepared(stellar.build_change_trust_xdr(source=address))
    except stellar.StellarError as exc:
        raise PaymentError("stellar", str(exc)) from exc


def confirm_trustline(address: str, signed_xdr: str) -> dict:
    info = stellar.parse_payment_xdr(signed_xdr)
    asset = stellar.usdc_asset()
    if (
        info is None
        or info.get("op_type") != "change_trust"
        or info.get("source") != address
        or info.get("asset_issuer") != asset.issuer
    ):
        raise PaymentError("tampered", "La transaction signée n’est pas la trustline attendue.")
    env = stellar.submit_xdr(signed_xdr)
    tx_hash = env.get("hash") or info["hash"]
    if env.get("ok"):
        logger.info("payments: trustline added wallet=%s hash=%s", address, tx_hash)
        return {"tx_hash": tx_hash, "explorer_url": stellar.explorer_tx_url(tx_hash), "message": "Trustline USDC ajoutée.", "pending": False}
    if env.get("status") == 504:
        return {"tx_hash": tx_hash, "explorer_url": stellar.explorer_tx_url(tx_hash), "message": PENDING_MESSAGE, "pending": True}
    raise PaymentError("provider", env.get("error") or stellar.ERR_HORIZON_UNREACHABLE)


# --- dispatch + view-model ---------------------------------------------------------------

PREPARE = {
    "deploy": prepare_deploy,
    "fund": prepare_fund,
    "deliver": prepare_deliver,
    "approve": prepare_approve,
    "release": prepare_release,
    "direct_pay": prepare_direct_pay,
}
CONFIRM = {
    "deploy": confirm_deploy,
    "fund": confirm_fund,
    "deliver": confirm_deliver,
    "approve": confirm_approve,
    "release": confirm_release,
    "direct_pay": confirm_direct_pay,
}


def prepare(need: Need, wallet, step: str, data: dict | None = None) -> dict:
    if step not in PREPARE:
        raise PaymentError("unknown_step", "Étape de paiement inconnue.")
    return PREPARE[step](need, wallet, data or {})


def confirm(need: Need, wallet, step: str, signed_xdr: str, data: dict | None = None) -> dict:
    if step not in CONFIRM:
        raise PaymentError("unknown_step", "Étape de paiement inconnue.")
    if not signed_xdr:
        raise PaymentError("tampered", "Transaction signée manquante.")
    if step == "deliver":
        return confirm_deliver(need, wallet, signed_xdr, data or {})
    return CONFIRM[step](need, wallet, signed_xdr)


def effective_mode(escrow: Escrow | None) -> str:
    return escrow.mode if escrow is not None else stellar.payment_mode()


def next_action(need: Need, wallet) -> dict | None:
    """The pending step, as the panel should show it to THIS viewer. None when the flow is
    finished or the need is not awarded. Keys: step, who, label, hint, icon, prepare_url,
    mine (this wallet must act), waiting (copy for everyone else), evidence (needs the form)."""
    if need.status not in (Need.Status.AWARDED, Need.Status.FUNDED, Need.Status.DELIVERED, Need.Status.RELEASED):
        return None
    if need.winning_bid_id is None:
        return None
    escrow = get_escrow(need)
    mode = effective_mode(escrow)
    status = escrow.status if escrow is not None else S.CREATED
    candidates = [e for e in FLOW[mode] if status in e["allowed"]]
    if not candidates:
        return None
    role = viewer_role(need, wallet)
    entry = next((e for e in candidates if e["who"] == role), candidates[0])
    label = entry["label"]
    if status == S.DELIVERED and entry.get("label_after_delivery"):
        label = entry["label_after_delivery"]
    return {
        "step": entry["step"],
        "who": entry["who"],
        "label": label,
        "hint": entry["hint"],
        "icon": entry["icon"],
        "waiting": entry["waiting"],
        "evidence": bool(entry.get("evidence")),
        "no_tx": bool(entry.get("no_tx")),
        "mine": role == entry["who"],
        "prepare_url": reverse("payments:prepare", kwargs={"need_pk": need.pk, "step": entry["step"]}),
    }


def stepper(mode: str, status: str) -> list[dict]:
    """[{label, state: done|current|todo}] for the panel's progress strip."""
    order = STATUS_ORDER[mode]
    reached = order.index(status) if status in order else -1
    steps = []
    current_marked = False
    for milestone, label in STEPPER[mode]:
        idx = order.index(milestone)
        if idx <= reached:
            state = "done"
        elif not current_marked:
            state = "current"
            current_marked = True
        else:
            state = "todo"
        steps.append({"label": label, "state": state, "status": milestone})
    return steps
