"""Payment orchestration for one TASK — pure state logic, no HTTP of its own.

Network calls go through `payments.trustless_work` (escrow mode) and `payments.stellar`
(direct mode + Horizon). Every step is a `prepare_<step>(task, wallet, data)` /
`confirm_<step>(task, wallet, signed_xdr)` pair: prepare builds the unsigned XDR the
session wallet must sign in Freighter, confirm submits the signed XDR and persists the
result. Role and state gates run in BOTH halves, pinned to the session wallet.

Why one escrow PER TASK (SPEC §7bis): Trustless Work v1 fixes the receiver of an escrow at
deploy and freezes it once funded, so a project-wide escrow funded before the freelances are
chosen could not pay them. The company deploys + funds a single-release escrow for each task
once a freelance is chosen; "Fund the project" simply chains those steps task after task.

State table — Escrow.status (payments) and Task.status (projects):

    ESCROW mode (Trustless Work single-release, one milestone)
    step        who        Escrow: before → after     Task                 on chain / persisted
    choose      company    —                          open → taken         (projects) no tx
    deploy      company    (none|created) → deployed  taken                TW deployer → contract_id, deploy_tx_hash
    fund        company    deployed → funded          taken                TW fund-escrow → fund_tx_hash, funded_at;
                                                                           project draft → funded when every assigned task holds funds
    deliver     freelance  funded → delivered         taken → delivered    TW change-milestone-status (delivery link = evidence);
                                                                           confirm calls projects.services.deliver(link)
    validate    company    —                          delivered (+Rating)  (projects) saves the Rating, answers `next` = approve
    approve     company    delivered → approved       delivered            TW approve-milestone → approve_tx_hash
    release     company    approved → released        delivered → paid     TW release-funds → release_tx_hash, released_at;
                                                                           confirm calls projects.services.mark_paid(task)

    DIRECT mode (fallback: one `payment` op; "funded" and "approved" do not exist)
    deliver     freelance  created → delivered        taken → delivered    NO transaction: projects.services.deliver(link)
    validate    company    —                          delivered (+Rating)  (projects) saves the Rating, answers `next` = direct_pay
    direct_pay  company    created|delivered → paid   delivered → paid     Django builds the payment XDR, Freighter signs,
                                                                           Django checks it (source/destination/amount/asset)
                                                                           and submits to Horizon → payment_tx_hash, released_at;
                                                                           mark_paid(task); project draft → funded on the first payment
    trustline   anyone     —                          —                    changeTrust XDR, or nothing when Horizon already shows it

The validate view saves the Rating FIRST (DB), then the page chains the signatures (approve →
release, or direct_pay) from the `next` it gets back; stopping half-way is fine, the panel
shows the remaining step ("Release the funds"). `mark_paid` is the ONLY way a task becomes paid.

The mode is frozen on the Escrow row at the first prepare (`stellar.payment_mode()`), but may be
re-frozen while the row is still `created` (nothing is on chain yet), so flipping
`LOWBID_PAYMENT_MODE=direct` after a failed deploy just works.

Errors: `PaymentError(code, message)` with codes `not_chosen · forbidden · wrong_state ·
wrong_mode · unknown_step · tampered · provider · stellar · invalid · not_assigned`. A provider
failure never flips the status (the user retries); the vendor/Horizon message is kept in
`Escrow.last_error`.
"""

import logging
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import TransactionEnvelope

from payments import stellar
from payments import trustless_work as tw
from payments.models import STATUS_BADGES, STATUS_LABELS, Escrow
from projects import services as projects
from projects.models import Project, Rating, Task

logger = logging.getLogger(__name__)

EVIDENCE_MAX = 280
PENDING_MESSAGE = "Transaction sent, confirmation pending — check the explorer."
ZERO = Decimal("0")

S = Escrow.Status
M = Escrow.Mode
T = Task.Status


class PaymentError(Exception):
    """A refused payment action. `code` is stable (JS/tests), `message` is English UI copy."""

    def __init__(self, code: str, message: str, *, persist: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        # True → the confirm_* decorator stores the message in Escrow.last_error AFTER the
        # transaction rolled back (a write inside the atomic block would vanish with it).
        self.persist = persist


# --- flow definition -------------------------------------------------------------
# One row per step: who acts, which Escrow / Task statuses allow it, whether a Rating must
# exist (`rated`), UI copy.

FLOW = {
    M.ESCROW: [
        {
            "step": "deploy",
            "who": "company",
            "allowed": (S.CREATED,),
            "task": (T.TAKEN,),
            "label": "Create the escrow",
            "icon": "fa-file-signature",
            "hint": "Deploys this task's Trustless Work contract (one Freighter signature).",
            "waiting": "Waiting for the company to create the escrow.",
        },
        {
            "step": "fund",
            "who": "company",
            "allowed": (S.DEPLOYED,),
            "task": (T.TAKEN,),
            "label": "Lock the funds",
            "icon": "fa-lock",
            "hint": "Moves the task's price into the escrow.",
            "waiting": "Waiting for the company to lock the funds.",
        },
        {
            "step": "deliver",
            "who": "freelance",
            "allowed": (S.FUNDED,),
            "task": (T.TAKEN,),
            "label": "Declare the delivery",
            "icon": "fa-truck-fast",
            "hint": "Marks the milestone as delivered on Stellar (the link is recorded as evidence).",
            "waiting": "Waiting for the freelancer's delivery.",
            "evidence": True,
        },
        {
            "step": "approve",
            "who": "company",
            "allowed": (S.DELIVERED,),
            "task": (T.DELIVERED,),
            "rated": True,
            "label": "Validate the delivery",
            "icon": "fa-check-double",
            "hint": "Approves the milestone — the funds stay locked until the release.",
            "waiting": "Waiting for the company's on-chain validation.",
        },
        {
            "step": "release",
            "who": "company",
            "allowed": (S.APPROVED,),
            "task": (T.DELIVERED,),
            "rated": True,
            "label": "Release the funds",
            "icon": "fa-money-bill-transfer",
            "hint": "The escrow pays the amount to the freelancer (minus fees).",
            "waiting": "Waiting for the company to release the funds.",
        },
    ],
    M.DIRECT: [
        {
            "step": "deliver",
            "who": "freelance",
            "allowed": (S.CREATED,),
            "task": (T.TAKEN,),
            "label": "Declare the delivery",
            "icon": "fa-truck-fast",
            "hint": "No escrow: a simple declaration, no transaction.",
            "waiting": "Waiting for the freelancer's delivery.",
            "evidence": True,
            "no_tx": True,
        },
        {
            "step": "direct_pay",
            "who": "company",
            "allowed": (S.CREATED, S.DELIVERED),
            "task": (T.DELIVERED,),
            "rated": True,
            "label": "Pay the freelancer",
            "icon": "fa-money-bill-transfer",
            "hint": "A direct payment signed in Freighter (no escrow).",
            "waiting": "Waiting for the company's payment.",
        },
    ],
}

# The non-payment step between deliver and approve/direct_pay: the company rates the delivery
# (projects.services.validate). Surfaced by next_action() so the panel and the dashboard agree.
VALIDATE = {
    "step": "validate",
    "who": "company",
    "label": "Validate + rate",
    "icon": "fa-star",
    "hint": "Check the delivery and rate the freelancer: once the rating is saved, the payment follows.",
    "waiting": "Waiting for the company's validation.",
}

# Stepper milestones per mode (status that marks each one as reached, in order).
STEPPER = {
    M.ESCROW: [
        (S.DEPLOYED, "Escrow created"),
        (S.FUNDED, "Funds locked"),
        (S.DELIVERED, "Delivered"),
        (S.RELEASED, "Funds released"),
    ],
    M.DIRECT: [
        (S.DELIVERED, "Delivered"),
        (S.PAID, "Paid"),
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
FUNDING_STEPS = ("deploy", "fund")


def _flow_entry(mode: str, step: str) -> dict | None:
    for entry in FLOW[mode]:
        if entry["step"] == step:
            return entry
    return None


# --- helpers ---------------------------------------------------------------------


def viewer_role(task: Task, wallet) -> str:
    """'company' | 'freelance' | 'other' | 'anonymous' for the panel and the gates."""
    if wallet is None:
        return "anonymous"
    if task.project.company_id == wallet.pk:
        return "company"
    if task.assigned_to_id and task.assigned_to_id == wallet.pk:
        return "freelance"
    return "other"


def get_escrow(task: Task) -> Escrow | None:
    return Escrow.objects.filter(task=task).first()


def is_rated(task: Task) -> bool:
    return Rating.objects.filter(task=task).exists()


def _require_chosen(task: Task) -> None:
    if task.status not in (T.TAKEN, T.DELIVERED, T.PAID) or task.assigned_to_id is None:
        raise PaymentError("not_chosen", "Payment is only possible once a freelancer has been chosen for the task.")


def _platform_address(task: Task) -> str:
    address = (getattr(settings, "LOWBID_PLATFORM_ADDRESS", "") or "").strip()
    if not address:
        address = task.project.company.stellar_address
        logger.warning(
            "payments: LOWBID_PLATFORM_ADDRESS is empty — using the COMPANY wallet as disputeResolver AND platformAddress "
            "task=%s; Trustless Work may refuse identical roles, set LOWBID_PLATFORM_ADDRESS in .env",
            task.pk,
        )
    return address


def platform_fallback_in_use(task: Task, escrow: Escrow | None, mode: str) -> bool:
    """True when escrow mode will (or did) merge the platform roles onto the company wallet."""
    if mode != M.ESCROW:
        return False
    if escrow is not None and escrow.platform_address:
        return escrow.platform_address == task.project.company.stellar_address
    return not (getattr(settings, "LOWBID_PLATFORM_ADDRESS", "") or "").strip()


def ensure_escrow(task: Task) -> Escrow:
    """The Escrow row for this task, created at the first prepare. Mode frozen here
    (re-frozen while still `created`, so the fallback can be switched on after a failed deploy)."""
    _require_chosen(task)
    mode = stellar.payment_mode()
    escrow, created = Escrow.objects.get_or_create(
        task=task,
        defaults={
            "mode": mode,
            "amount": task.price,
            "payer_address": task.project.company.stellar_address,
            "payee_address": task.assigned_to.stellar_address,
            "platform_address": _platform_address(task) if mode == M.ESCROW else "",
            "engagement_id": f"lowbid-task-{task.pk}",
        },
    )
    if created:
        logger.info("payments: escrow row created task=%s mode=%s amount=%s", task.pk, mode, task.price)
    elif escrow.status == S.CREATED and escrow.mode != mode:
        logger.warning("payments: mode re-frozen task=%s %s -> %s", task.pk, escrow.mode, mode)
        escrow.mode = mode
        escrow.platform_address = _platform_address(task) if mode == M.ESCROW else ""
        escrow.save(update_fields=["mode", "platform_address", "updated_at"])
    return escrow


def _gate(task: Task, wallet, step: str) -> tuple[Escrow, dict]:
    """Role + mode + state check shared by prepare and confirm. Returns (escrow, flow entry)."""
    escrow = ensure_escrow(task)
    if step not in STEPS:
        raise PaymentError("unknown_step", "Unknown payment step.")
    entry = _flow_entry(escrow.mode, step)
    if entry is None:
        label = "direct" if escrow.mode == M.DIRECT else "escrow"
        raise PaymentError("wrong_mode", f"This step does not exist in {label} mode.")
    role = viewer_role(task, wallet)
    if role != entry["who"]:
        who = "the company" if entry["who"] == "company" else "the chosen freelancer"
        raise PaymentError("forbidden", f"Only {who} can do this.")
    if escrow.status not in entry["allowed"] or task.status not in entry["task"]:
        raise PaymentError(
            "wrong_state",
            f"Step \"{entry['label']}\" is not possible at this stage ({escrow.status_label}, task {task.status_label.lower()}).",
        )
    if entry.get("rated") and not is_rated(task):
        raise PaymentError("wrong_state", "Validate and rate the delivery before the payment.")
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


def _record_error(escrow: Escrow, message: str) -> None:
    escrow.last_error = (message or "")[:1000]
    escrow.save(update_fields=["last_error", "updated_at"])


def _already_done(escrow: Escrow, task: Task, step: str, tx_hash: str | None) -> bool:
    """Idempotent send: the same signed XDR arriving twice must not fail nor double-write."""
    if not tx_hash:
        return False
    if getattr(escrow, HASH_FIELD[step]) != tx_hash:
        return False
    entry = _flow_entry(escrow.mode, step)
    return entry is not None and (escrow.status not in entry["allowed"] or task.status not in entry["task"])


def _records_errors(fn):
    """confirm_* wrapper: a PaymentError flagged `persist` lands in Escrow.last_error once the
    atomic block has rolled back, so the user sees the vendor message and can retry."""

    @wraps(fn)
    def wrapper(task, wallet, *args, **kwargs):
        try:
            return fn(task, wallet, *args, **kwargs)
        except PaymentError as exc:
            if exc.persist:
                Escrow.objects.filter(task=task).update(last_error=exc.message[:1000], updated_at=timezone.now())
            raise

    return wrapper


def _begin(task: Task, wallet, step: str, signed_xdr: str) -> tuple[Escrow, str | None, dict | None]:
    """Shared opening of every confirm_*: (escrow, local tx hash, idempotent result or None).
    The duplicate check runs BEFORE the state gate: a replayed send for a step already
    recorded with this very hash answers ok instead of `wrong_state`."""
    escrow = ensure_escrow(task)
    tx_hash = _xdr_hash(signed_xdr)
    entry = _flow_entry(escrow.mode, step)
    if entry is not None and viewer_role(task, wallet) == entry["who"] and _already_done(escrow, task, step, tx_hash):
        return escrow, tx_hash, _result(escrow, step, tx_hash, "Step already confirmed.")
    escrow, _ = _gate(task, wallet, step)
    return escrow, tx_hash, None


def _tw_send(task: Task, escrow: Escrow, step: str, signed_xdr: str) -> tuple[str, dict]:
    """send-transaction; on failure raise a persisted provider error. Returns (local tx hash, data)."""
    tx_hash = _xdr_hash(signed_xdr)
    if tx_hash is None:
        raise PaymentError("tampered", stellar.ERR_BAD_XDR)
    env = tw.send_transaction(signed_xdr=signed_xdr)
    if not env.get("ok"):
        message = env.get("error") or tw.ERR_UNEXPECTED
        logger.warning("payments: provider refused task=%s step=%s hash=%s error=%s", task.pk, step, tx_hash, message)
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


def _log_confirm(task: Task, step: str, wallet, tx_hash: str | None, extra: str = "") -> None:
    logger.info(
        "payments: confirm task=%s step=%s wallet=%s hash=%s%s",
        task.pk, step, getattr(wallet, "stellar_address", "-"), tx_hash or "-", extra,
    )


# --- project status: draft → funded ----------------------------------------------------------


def sync_project_status(project: Project) -> Project:
    """draft → funded when every assigned (non-open) task holds its money on chain (escrow mode:
    funded / delivered / approved / released) — or, in direct mode, on the first payment, since
    nothing is locked before. Closing (every task paid) is projects.services.mark_paid's job."""
    locked = Project.objects.select_for_update().get(pk=project.pk)
    if locked.status != Project.Status.DRAFT:
        return locked
    tasks = list(locked.tasks.exclude(status=T.OPEN))
    if not tasks:
        return locked
    escrows = {e.task_id: e for e in Escrow.objects.filter(task__in=tasks)}
    first_direct_payment = any(e.mode == M.DIRECT and e.status == S.PAID for e in escrows.values())
    all_locked = all(t.pk in escrows and escrows[t.pk].holds_funds for t in tasks)
    if first_direct_payment or all_locked:
        locked.status = Project.Status.FUNDED
        locked.save(update_fields=["status", "updated_at"])
        logger.info("payments: project funded project=%s tasks=%s", locked.pk, len(tasks))
    return locked


# --- escrow mode: deploy / fund / deliver / approve / release ---------------------------


def prepare_deploy(task: Task, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(task, wallet, "deploy")
    env = tw.deploy_single_release(
        signer=escrow.payer_address,
        engagement_id=escrow.engagement_id,
        title=task.title,
        description=task.description or task.project.title,
        amount=escrow.amount,
        approver=escrow.payer_address,
        service_provider=escrow.payee_address,
        receiver=escrow.payee_address,
        release_signer=escrow.payer_address,
        dispute_resolver=escrow.platform_address,
        platform_address=escrow.platform_address,
        platform_fee=settings.LOWBID_PLATFORM_FEE,
        milestone_description=f"Delivery of task #{task.pk} — {task.title}"[:200],
    )
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_deploy(task: Task, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(task, wallet, "deploy", signed_xdr)
        if done:
            return done
        tx_hash, data = _tw_send(task, escrow, "deploy", signed_xdr)
        contract_id = data.get("contractId") or (data.get("escrow") or {}).get("contractId") or ""
        if not contract_id:
            logger.error("payments: deploy sent but no contractId task=%s hash=%s keys=%s", task.pk, tx_hash, list(data))
            raise PaymentError("provider", "Escrow sent but the contract id is missing — contact support.", persist=True)
        escrow.contract_id = contract_id
        escrow.deploy_tx_hash = tx_hash
        escrow.status = S.DEPLOYED
        escrow.last_error = ""
        escrow.save(update_fields=["contract_id", "deploy_tx_hash", "status", "last_error", "updated_at"])
    _log_confirm(task, "deploy", wallet, tx_hash, f" contract={contract_id}")
    return _result(escrow, "deploy", tx_hash, "Escrow created on Stellar.")


def prepare_fund(task: Task, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(task, wallet, "fund")
    env = tw.fund_escrow(contract_id=escrow.contract_id, signer=escrow.payer_address, amount=escrow.amount)
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_fund(task: Task, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(task, wallet, "fund", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(task, escrow, "fund", signed_xdr)
        escrow.fund_tx_hash = tx_hash
        escrow.status = S.FUNDED
        escrow.funded_at = timezone.now()
        escrow.last_error = ""
        escrow.save(update_fields=["fund_tx_hash", "status", "funded_at", "last_error", "updated_at"])
        sync_project_status(task.project)
    _log_confirm(task, "fund", wallet, tx_hash)
    return _result(escrow, "fund", tx_hash, "Funds locked in the escrow.")


def _delivery_link(data: dict | None) -> str:
    return str((data or {}).get("delivery_link") or (data or {}).get("evidence") or "").strip()


def _project_error(exc: projects.ProjectError) -> PaymentError:
    return PaymentError(exc.code, exc.message)


def check_db_deliver(task: Task) -> None:
    """Called by projects.services.deliver for a DB-only delivery: refused in escrow mode, where
    the delivery is an on-chain milestone change signed by the freelance (prepare/confirm_deliver)."""
    escrow = get_escrow(task)
    if effective_mode(escrow) == M.ESCROW:
        raise PaymentError(
            "wrong_state",
            "Escrow task: declare the delivery from the payment panel (Freighter signature), "
            "once the company has locked the funds.",
        )


def prepare_deliver(task: Task, wallet, data: dict | None = None) -> dict:
    """Escrow mode: TW change-milestone-status XDR (freelance signs), the delivery link as evidence.
    Direct mode: no transaction — projects.services.deliver records the link right here."""
    link = _delivery_link(data)
    with transaction.atomic():
        escrow, entry = _gate(task, wallet, "deliver")
        try:
            if entry.get("no_tx"):
                projects.deliver(task, wallet, link)
                escrow.status = S.DELIVERED
                escrow.delivered_at = timezone.now()
                escrow.delivery_note = link[:EVIDENCE_MAX]
                escrow.last_error = ""
                escrow.save(update_fields=["status", "delivered_at", "delivery_note", "last_error", "updated_at"])
                _log_confirm(task, "deliver", wallet, None, " (direct, no tx)")
                return _prepared(None, message="Delivery declared. The company validates, rates and pays.")
            link = projects.clean_link(link)
        except projects.ProjectError as exc:
            raise _project_error(exc) from None
    env = tw.change_milestone_status(
        contract_id=escrow.contract_id, evidence=link[:EVIDENCE_MAX], service_provider=escrow.payee_address
    )
    try:
        return _prepared(_unsigned_xdr(env), extra={"delivery_link": link})
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_deliver(task: Task, wallet, signed_xdr: str, data: dict | None = None) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(task, wallet, "deliver", signed_xdr)
        if done:
            return done
        try:
            link = projects.clean_link(_delivery_link(data))
        except projects.ProjectError as exc:
            raise _project_error(exc) from None
        tx_hash, _ = _tw_send(task, escrow, "deliver", signed_xdr)
        try:
            projects.deliver(task, wallet, link, on_chain=True)
        except projects.ProjectError as exc:
            raise _project_error(exc) from None
        escrow.deliver_tx_hash = tx_hash
        escrow.status = S.DELIVERED
        escrow.delivered_at = timezone.now()
        escrow.delivery_note = link[:EVIDENCE_MAX]
        escrow.last_error = ""
        escrow.save(update_fields=["deliver_tx_hash", "status", "delivered_at", "delivery_note", "last_error", "updated_at"])
    _log_confirm(task, "deliver", wallet, tx_hash)
    return _result(escrow, "deliver", tx_hash, "Delivery declared on Stellar. The company validates and rates.")


def prepare_approve(task: Task, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(task, wallet, "approve")
    env = tw.approve_milestone(contract_id=escrow.contract_id, approver=escrow.payer_address)
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_approve(task: Task, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(task, wallet, "approve", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(task, escrow, "approve", signed_xdr)
        escrow.approve_tx_hash = tx_hash
        escrow.status = S.APPROVED
        escrow.last_error = ""
        escrow.save(update_fields=["approve_tx_hash", "status", "last_error", "updated_at"])
    _log_confirm(task, "approve", wallet, tx_hash)
    return _result(escrow, "approve", tx_hash, "Delivery validated on-chain. Now release the funds.")


def prepare_release(task: Task, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(task, wallet, "release")
    env = tw.release_funds(contract_id=escrow.contract_id, release_signer=escrow.payer_address)
    try:
        return _prepared(_unsigned_xdr(env))
    except PaymentError as exc:
        _record_error(escrow, exc.message)
        raise


@_records_errors
def confirm_release(task: Task, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(task, wallet, "release", signed_xdr)
        if done:
            return done
        tx_hash, _ = _tw_send(task, escrow, "release", signed_xdr)
        escrow.release_tx_hash = tx_hash
        escrow.status = S.RELEASED
        escrow.released_at = timezone.now()
        escrow.last_error = ""
        escrow.save(update_fields=["release_tx_hash", "status", "released_at", "last_error", "updated_at"])
        projects.mark_paid(task)
        sync_project_status(task.project)
    _log_confirm(task, "release", wallet, tx_hash)
    return _result(escrow, "release", tx_hash, "Funds released to the freelancer. Task paid.")


# --- direct mode: direct_pay -------------------------------------------------------------


def _finalize_direct_pay(task: Task, escrow: Escrow, tx_hash: str) -> None:
    escrow.payment_tx_hash = tx_hash
    escrow.status = S.PAID
    escrow.released_at = timezone.now()
    escrow.last_error = ""
    escrow.save(update_fields=["payment_tx_hash", "status", "released_at", "last_error", "updated_at"])
    projects.mark_paid(task)
    sync_project_status(task.project)


def prepare_direct_pay(task: Task, wallet, data: dict | None = None) -> dict:
    escrow, _ = _gate(task, wallet, "direct_pay")
    if escrow.payment_tx_hash:
        # A previous submit timed out (Horizon 504) — reconcile before asking for a new signature.
        applied = stellar.transaction_status(escrow.payment_tx_hash)
        if applied is True:
            with transaction.atomic():
                _finalize_direct_pay(task, escrow, escrow.payment_tx_hash)
            _log_confirm(task, "direct_pay", wallet, escrow.payment_tx_hash, " (reconciled)")
            return _prepared(None, message="Payment confirmed on the network.")
        if applied is None:
            raise PaymentError("provider", stellar.ERR_HORIZON_UNREACHABLE)
        logger.info("payments: pending hash not on chain, rebuilding task=%s hash=%s", task.pk, escrow.payment_tx_hash)
    try:
        xdr = stellar.build_payment_xdr(
            source=escrow.payer_address,
            destination=escrow.payee_address,
            amount=escrow.amount,
            memo=f"lowbid:task:{task.pk}",
        )
    except stellar.StellarError as exc:
        _record_error(escrow, str(exc))
        raise PaymentError("stellar", str(exc)) from exc
    return _prepared(xdr)


def _check_payment_xdr(escrow: Escrow, signed_xdr: str) -> dict:
    """The signed XDR must be exactly the payment we built: one payment payer → payee for the task price."""
    info = stellar.parse_payment_xdr(signed_xdr)
    asset = stellar.asset()
    if (
        info is None
        or info.get("op_type") != "payment"
        or info.get("source") != escrow.payer_address
        or info.get("destination") != escrow.payee_address
        or info.get("asset_code") != asset.code
        or (info.get("asset_issuer") or None) != (asset.issuer or None)
        or info.get("amount") is None
        or Decimal(info["amount"]) != Decimal(escrow.amount)
    ):
        logger.warning("payments: tampered payment xdr task=%s parsed=%s", escrow.task_id, info)
        raise PaymentError("tampered", "The signed transaction does not match the expected payment.")
    return info


@_records_errors
def confirm_direct_pay(task: Task, wallet, signed_xdr: str) -> dict:
    with transaction.atomic():
        escrow, tx_hash, done = _begin(task, wallet, "direct_pay", signed_xdr)
        if done:
            return done
        _check_payment_xdr(escrow, signed_xdr)
        env = stellar.submit_xdr(signed_xdr)
        if env.get("ok"):
            _finalize_direct_pay(task, escrow, env.get("hash") or tx_hash)
            _log_confirm(task, "direct_pay", wallet, escrow.payment_tx_hash)
            return _result(escrow, "direct_pay", escrow.payment_tx_hash, f"{stellar.asset_code()} payment confirmed. Task paid.")
        if env.get("status") == 504 and env.get("hash"):
            escrow.payment_tx_hash = env["hash"]
            escrow.last_error = PENDING_MESSAGE
            escrow.save(update_fields=["payment_tx_hash", "last_error", "updated_at"])
            logger.warning("payments: horizon timeout task=%s step=direct_pay hash=%s", task.pk, env["hash"])
            return _result(escrow, "direct_pay", env["hash"], PENDING_MESSAGE, pending=True)
        message = env.get("error") or stellar.ERR_HORIZON_UNREACHABLE
        logger.warning("payments: horizon refused task=%s step=direct_pay hash=%s error=%s", task.pk, tx_hash, message)
        raise PaymentError("provider", message, persist=True)


# --- trustline (any wallet, no task) ----------------------------------------------------


def trustline_present_message() -> str:
    return f"{stellar.asset_code()} trustline already present."


def prepare_trustline(address: str) -> dict:
    if stellar.is_native():
        return _prepared(None, message="The native XLM asset needs no trustline.")
    present = stellar.has_trustline(address)
    if present is True:
        return _prepared(None, message=trustline_present_message())
    try:
        return _prepared(stellar.build_change_trust_xdr(source=address))
    except stellar.StellarError as exc:
        raise PaymentError("stellar", str(exc)) from exc


def confirm_trustline(address: str, signed_xdr: str) -> dict:
    info = stellar.parse_payment_xdr(signed_xdr)
    asset = stellar.asset()
    if (
        info is None
        or info.get("op_type") != "change_trust"
        or info.get("source") != address
        or info.get("asset_issuer") != asset.issuer
    ):
        raise PaymentError("tampered", "The signed transaction is not the expected trustline.")
    env = stellar.submit_xdr(signed_xdr)
    tx_hash = env.get("hash") or info["hash"]
    if env.get("ok"):
        logger.info("payments: trustline added wallet=%s hash=%s", address, tx_hash)
        return {"tx_hash": tx_hash, "explorer_url": stellar.explorer_tx_url(tx_hash), "message": f"{asset.code} trustline added.", "pending": False}
    if env.get("status") == 504:
        return {"tx_hash": tx_hash, "explorer_url": stellar.explorer_tx_url(tx_hash), "message": PENDING_MESSAGE, "pending": True}
    raise PaymentError("provider", env.get("error") or stellar.ERR_HORIZON_UNREACHABLE)


# --- hooks called by projects.services -----------------------------------------------------


def on_task_validated(task: Task) -> Escrow:
    """Inside validate()'s transaction, right after the Rating is stored. Does NOT pay: it makes
    sure the Escrow row exists (so the next step is known) and logs what the company signs next
    — approve → release in escrow mode, direct_pay in direct mode. `mark_paid` happens in
    confirm_release / confirm_direct_pay only."""
    escrow = ensure_escrow(task)
    nxt = next_action(task, task.project.company)
    logger.info(
        "payments: task validated task=%s mode=%s escrow=%s next=%s",
        task.pk, escrow.mode, escrow.status, nxt["step"] if nxt else None,
    )
    return escrow


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


def prepare(task: Task, wallet, step: str, data: dict | None = None) -> dict:
    if step not in PREPARE:
        raise PaymentError("unknown_step", "Unknown payment step.")
    return PREPARE[step](task, wallet, data or {})


def confirm(task: Task, wallet, step: str, signed_xdr: str, data: dict | None = None) -> dict:
    if step not in CONFIRM:
        raise PaymentError("unknown_step", "Unknown payment step.")
    if not signed_xdr:
        raise PaymentError("tampered", "Signed transaction missing.")
    if step == "deliver":
        return confirm_deliver(task, wallet, signed_xdr, data or {})
    return CONFIRM[step](task, wallet, signed_xdr)


def effective_mode(escrow: Escrow | None) -> str:
    """The row's frozen mode, except while nothing is on chain yet (`created` / no row): the
    configured mode, which ensure_escrow will re-freeze at the next prepare."""
    if escrow is None or escrow.status == S.CREATED:
        return stellar.payment_mode()
    return escrow.mode


def display_status(task: Task, escrow: Escrow | None, mode: str) -> str:
    """Escrow status for the panel. Without a row, a direct-mode task delivered through the
    DB-only endpoint still reads as `delivered`; a paid task always reads as terminal."""
    status = escrow.status if escrow is not None else S.CREATED
    if task.status == T.PAID:
        return S.PAID if mode == M.DIRECT else S.RELEASED
    if mode == M.DIRECT and status == S.CREATED and task.status == T.DELIVERED:
        return S.DELIVERED
    return status


def _action_dict(task: Task, entry: dict, role: str, status: str) -> dict:
    step = entry["step"]
    label = entry["label"]
    if status == S.DELIVERED and entry.get("label_after_delivery"):
        label = entry["label_after_delivery"]
    return {
        "step": step,
        "who": entry["who"],
        "label": label,
        "hint": entry["hint"],
        "icon": entry["icon"],
        "waiting": entry["waiting"],
        "evidence": bool(entry.get("evidence")),
        "no_tx": bool(entry.get("no_tx")),
        "mine": role == entry["who"],
        "prepare_url": (
            reverse("payments:prepare", kwargs={"task_pk": task.pk, "step": step}) if step in STEPS else None
        ),
        "task": task.pk,
    }


def next_action(task: Task, wallet) -> dict | None:
    """The pending step, as the panel / dashboard should show it to THIS viewer. None when the
    task is open, or paid. Keys: step (a payment step, or "validate" for the rating form), who,
    label, hint, icon, prepare_url (None for "validate"), mine (this wallet must act), waiting
    (copy for everyone else), evidence (needs the delivery-link form), no_tx."""
    if task.status in (T.OPEN, T.PAID) or task.assigned_to_id is None:
        return None
    escrow = get_escrow(task)
    mode = effective_mode(escrow)
    status = display_status(task, escrow, mode)
    role = viewer_role(task, wallet)
    if task.status == T.DELIVERED and not is_rated(task):
        return _action_dict(task, VALIDATE, role, status)
    rated = is_rated(task)
    candidates = [
        e for e in FLOW[mode]
        if status in e["allowed"] and task.status in e["task"] and (not e.get("rated") or rated)
    ]
    if not candidates:
        return None
    entry = next((e for e in candidates if e["who"] == role), candidates[0])
    return _action_dict(task, entry, role, status)


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


def project_funding(project: Project, wallet=None) -> dict:
    """View-model of the project banner + the "Fund the project" button.

    total: sum of task prices · funded: prices of tasks whose escrow holds the money (escrow
    mode: funded or later; direct: paid) · paid: prices of paid tasks · pending: the assigned
    tasks still to deploy/fund (escrow mode; what the button chains, with the company's next
    step each) · rows: one per task with its escrow status + explorer links · links: every
    stored hash across the project · can_fund / fund_hint for the button.
    """
    mode = stellar.payment_mode()
    tasks = list(project.tasks.select_related("assigned_to").order_by("position", "pk"))
    escrows = {e.task_id: e for e in Escrow.objects.filter(task__in=tasks)}
    rows, pending, links = [], [], []
    total = funded = paid = ZERO
    assigned = 0
    for task in tasks:
        escrow = escrows.get(task.pk)
        task_mode = escrow.mode if escrow is not None and escrow.status != S.CREATED else mode
        status = display_status(task, escrow, task_mode)
        total += task.price
        if task.status != T.OPEN:
            assigned += 1
        if task.status == T.PAID or (escrow is not None and escrow.holds_funds):
            funded += task.price
        if task.status == T.PAID:
            paid += task.price
        task_links = escrow.explorer_links() if escrow is not None else []
        for link in task_links:
            links.append({**link, "task": task})
        if task.status == T.TAKEN and mode == M.ESCROW and status in (S.CREATED, S.DEPLOYED):
            nxt = next_action(task, project.company)
            if nxt and nxt["step"] in FUNDING_STEPS:
                pending.append({"task": task, "title": task.title, "amount": task.price, "next": nxt})
        has_payment_state = escrow is not None or task.status != T.OPEN
        rows.append(
            {
                "task": task,
                "escrow": escrow,
                "mode": task_mode,
                "status": status,
                "status_label": STATUS_LABELS.get(status, status) if has_payment_state else "",
                "badge_class": STATUS_BADGES.get(status, "ui-badge-neutral") if has_payment_state else "ui-badge-neutral",
                "links": task_links,
            }
        )
    if mode == M.DIRECT:
        can_fund, hint = False, (
            "Direct payment mode: each validation triggers a "
            f"{stellar.asset_code()} payment signed in Freighter — nothing to lock in advance."
        )
    elif pending:
        n = len(pending)
        can_fund, hint = True, f"{n} assigned task{'s' if n > 1 else ''} to fund (two Freighter signatures per task: create the escrow, lock the funds)."
    elif assigned == 0:
        can_fund, hint = False, (
            "Choose a freelancer first: Trustless Work fixes the escrow recipient at deploy, "
            "so an open task cannot be funded yet."
        )
    else:
        can_fund, hint = False, "Every assigned task is funded. Open tasks will be funded once a freelancer is chosen."
    return {
        "mode": mode,
        "is_direct": mode == M.DIRECT,
        "total": total,
        "funded": funded,
        "paid": paid,
        "pending": pending,
        "rows": rows,
        "links": links,
        "can_fund": can_fund,
        "fund_hint": hint,
        "assigned": assigned,
    }
