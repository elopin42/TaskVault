"""Publication deposit → guarantee fund: every rule of the anti ghost-listing deposit lives here.

A company proves it means to hire before its project takes applications: it locks a deposit
(max(LOWBID_DEPOSIT_RATE × budget, LOWBID_DEPOSIT_MIN)) in a Trustless Work single-release escrow it
deploys and funds itself in Freighter. Funding it PUBLISHES the project (`Project.published_at`).
Tasks added later are covered by a top-up (max(rate × gap, LOWBID_DEPOSIT_TOPUP_MIN)) before they
take applications. The deposit comes back to the company when the project is closed (every task paid)
or nobody applied; it goes to the guarantee fund (LOWBID_GUARANTEE_FUND_ADDRESS) when the company let
candidates wait LOWBID_CHOICE_DAYS days without choosing anyone, or cancelled after receiving
applications. Every delay is evaluated when a request reads it (`deposit_verdict(project, now)`) —
there is no timer: settling happens on the commit that closes / cancels the project, or when someone
asks ("Reclaim my deposit", "Report a ghost listing").

Active iff LOWBID_DEPOSIT_ENABLED and payments.stellar.payment_mode() == "escrow". Otherwise
projects are published at creation and nothing here applies (direct mode is unprotected).

Escrow roles at deploy (one address may hold several roles in TW v1):
    signer + receiver                                  company (session wallet, Freighter)
    approver = serviceProvider = releaseSigner
             = platformAddress                         platform key   (LOWBID_PLATFORM_SECRET)
    disputeResolver                                    resolver key   (LOWBID_DEPOSIT_RESOLVER_SECRET)
    platformFee 0, amount = deposit_due, one milestone "Deposit for project #pk"

State table — ProjectDeposit.status (payments) and the project effect:

    step       who signs          deposit: before → after   TW call                            project / persisted
    deploy     company (Freighter) (none|created) → deployed deployer/single-release            contract_id, deploy_tx_hash
    fund       company (Freighter) deployed → funded         fund-escrow                        fund_tx_hash, funded_at;
                                                                                                published_at = now if None
    -- refund chain (verdict "refund": closed project, cancelled w/o application, no application for
       LOWBID_NO_APPLICATION_DAYS) — server keys, each step skipped when its hash is stored --
    milestone  platform key        funded                    change-milestone-status            milestone_tx_hash
    approve    platform key        funded                    approve-milestone                  approve_tx_hash
    release    platform key        funded → refunded         release-funds (→ company)          release_tx_hash, settled_at
    -- forfeit chain (verdict "forfeit": candidates left waiting LOWBID_CHOICE_DAYS with nobody chosen,
       or cancelled with applications) — needs the fund's trustline --
    dispute    platform key        funded                    dispute-escrow                     dispute_tx_hash
    resolve    resolver key        funded → forfeited        resolve-dispute, [(fund, balance)] resolve_tx_hash, settled_at

A provider / Horizon failure never moves the status: the message lands in `last_error`, the step is
retried later (same endpoint) and only the missing steps are sent again. The company steps follow
the escrow prepare/confirm pattern (gates in both halves, idempotent replay of the same signed XDR).
The server chains build → sign → send in one request (a TW XDR is single use, valid about a minute);
the network calls run OUTSIDE any transaction, the row is re-read under `select_for_update` before
every write. Errors: PaymentError codes `wrong_mode · forbidden · wrong_state · unknown_step ·
tampered · provider · not_published · not_covered`.
"""

import copy
import logging
from datetime import datetime, timedelta
from decimal import ROUND_UP, Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import TransactionEnvelope

from payments import signer, stellar
from payments import trustless_work as tw
from payments.models import DEPOSIT_STATUS_BADGES, DEPOSIT_STATUS_LABELS, ProjectDeposit
from payments.services import PaymentError, _unsigned_xdr, _xdr_hash
from projects.models import Application, Project, Task

logger = logging.getLogger(__name__)

D = ProjectDeposit.Status
P = Project.Status
ZERO = Decimal("0")
PLACES = Decimal("0.0000001")  # 7 decimals, the asset precision on Stellar
COVERING = (D.FUNDED, D.REFUNDED, D.FORFEITED)
PENDING = (D.CREATED, D.DEPLOYED)
COMPANY_STEPS = ("deploy", "fund")
HASH_FIELD = {"deploy": "deploy_tx_hash", "fund": "fund_tx_hash"}
STEP_FLOW = {
    "deploy": {"allowed": (D.CREATED,), "label": "Create the deposit escrow"},
    "fund": {"allowed": (D.DEPLOYED,), "label": "Lock the deposit"},
}
REFUND_STEPS = (("milestone", "milestone_tx_hash"), ("approve", "approve_tx_hash"), ("release", "release_tx_hash"))
REFUND_EVIDENCE = "deposit refund"


# --- configuration -----------------------------------------------------------------------------


def deposits_active() -> bool:
    """Deposits apply only when enabled AND payments run through Trustless Work escrows."""
    return bool(getattr(settings, "LOWBID_DEPOSIT_ENABLED", False)) and stellar.payment_mode() == "escrow"


def _setting_decimal(name: str, default: str) -> Decimal:
    try:
        return Decimal(str(getattr(settings, name, default)))
    except (InvalidOperation, ValueError):
        logger.warning("deposits: %s is not a number, using %s", name, default)
        return Decimal(default)


def _quantize(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PLACES, rounding=ROUND_UP)


def deposit_amount(budget) -> Decimal:
    """max(rate × budget, LOWBID_DEPOSIT_MIN), 7 decimals (rounded up: never below the rate)."""
    rate = _setting_decimal("LOWBID_DEPOSIT_RATE", "0.01")
    minimum = _setting_decimal("LOWBID_DEPOSIT_MIN", "5")
    return _quantize(max(rate * Decimal(budget), minimum))


def topup_amount(gap) -> Decimal:
    """max(rate × gap, LOWBID_DEPOSIT_TOPUP_MIN), 7 decimals."""
    rate = _setting_decimal("LOWBID_DEPOSIT_RATE", "0.01")
    minimum = _setting_decimal("LOWBID_DEPOSIT_TOPUP_MIN", "1")
    return _quantize(max(rate * Decimal(gap), minimum))


def choice_days() -> int:
    return int(getattr(settings, "LOWBID_CHOICE_DAYS", 14))


def no_application_days() -> int:
    return int(getattr(settings, "LOWBID_NO_APPLICATION_DAYS", 30))


def fund_address() -> str:
    return (getattr(settings, "LOWBID_GUARANTEE_FUND_ADDRESS", "") or "").strip()


# --- coverage ------------------------------------------------------------------------------------


def _project_total(project: Project) -> Decimal:
    return project.tasks.aggregate(s=Sum("price"))["s"] or ZERO


def covered_budget(project: Project) -> Decimal:
    """The budget covered by funded or settled deposits (Σ covered_budget of those rows)."""
    total = ProjectDeposit.objects.filter(project=project, status__in=COVERING).aggregate(s=Sum("covered_budget"))["s"]
    return total or ZERO


def _has_covering_row(project: Project) -> bool:
    return ProjectDeposit.objects.filter(project=project, status__in=COVERING).exists()


def deposit_due(project: Project) -> Decimal:
    """What the company must lock now: 0 when inactive or already covered; the publication deposit on
    the whole budget when nothing was ever funded; else the top-up on the uncovered gap."""
    if not deposits_active():
        return ZERO
    total = _project_total(project)
    covered = covered_budget(project)
    if covered >= total:
        return ZERO
    if not _has_covering_row(project):
        return deposit_amount(total)
    return topup_amount(total - covered)


def task_covered(task: Task) -> bool:
    """The task is covered when the funded deposits cover the prices of the project's tasks in creation
    order up to and including this one — so a task added after the last funded deposit waits for a top-up."""
    covered = covered_budget(task.project)
    running = ZERO
    for pk, price in task.project.tasks.order_by("created_at", "pk").values_list("pk", "price"):
        running += price
        if pk == task.pk:
            return covered >= running
    return False


def check_can_apply(task: Task) -> None:
    """Called by projects.services.apply (inside its transaction): refuses applications to a cancelled
    project, to an unpublished one, and to a task its deposit does not cover yet."""
    project = task.project
    if project.status == P.CANCELLED:
        raise PaymentError("wrong_state", "This project was cancelled: it takes no more applications.")
    if not deposits_active():
        return
    if project.published_at is None:
        raise PaymentError("not_published", "This project is not published yet.")
    if not task_covered(task):
        raise PaymentError("not_covered", "This task is not covered by the project's deposit yet.")


# --- verdict (pure) ------------------------------------------------------------------------------


def deposit_verdict(project: Project, now: datetime | None = None) -> dict:
    """{verdict: refund|forfeit|locked, reason, deadline} — no write. `deadline` is when the verdict
    changes if nothing happens (None when no clock runs)."""
    now = now or timezone.now()
    apps = Application.objects.filter(task__project=project)
    first = apps.order_by("created_at", "pk").values_list("created_at", flat=True).first()
    if project.status == P.CLOSED:
        return {"verdict": "refund", "reason": "The project is closed: every task was paid.", "deadline": None}
    if first is None:
        if project.status == P.CANCELLED:
            return {"verdict": "refund", "reason": "The project was cancelled before any application.", "deadline": None}
        if project.published_at is None:
            return {"verdict": "locked", "reason": "The project is not published yet.", "deadline": None}
        deadline = project.published_at + timedelta(days=no_application_days())
        if now >= deadline:
            return {"verdict": "refund", "reason": f"No application in {no_application_days()} days.", "deadline": None}
        return {"verdict": "locked", "reason": "Refundable if no application arrives.", "deadline": deadline}
    chosen_ever = (
        project.tasks.exclude(status=Task.Status.OPEN).exists() or apps.filter(status=Application.Status.CHOSEN).exists()
    )
    if not chosen_ever:
        deadline = first + timedelta(days=choice_days())
        if now >= deadline:
            return {
                "verdict": "forfeit",
                "reason": f"Candidates waited {choice_days()} days and no freelancer was chosen.",
                "deadline": None,
            }
        if project.status == P.CANCELLED:
            return {"verdict": "forfeit", "reason": "The project was cancelled after receiving applications.", "deadline": None}
        return {"verdict": "locked", "reason": "Choose a freelancer to keep the deposit safe.", "deadline": deadline}
    if project.status == P.CANCELLED:  # not reachable through cancel_project (it refuses once someone is chosen)
        return {"verdict": "forfeit", "reason": "The project was cancelled after receiving applications.", "deadline": None}
    return {"verdict": "locked", "reason": "A freelancer was chosen: refunded once the project is closed.", "deadline": None}


def cancel_outcome(project: Project, now: datetime | None = None) -> str:
    """What cancelling right now would do to the funded deposit: "refund" | "forfeit" | "none"."""
    if not ProjectDeposit.objects.filter(project=project, status=D.FUNDED).exists():
        return "none"
    hypothetical = copy.copy(project)
    hypothetical.status = P.CANCELLED
    return deposit_verdict(hypothetical, now)["verdict"]


# --- company steps: deploy + fund (Freighter) ------------------------------------------------------


def _pending_row(project: Project) -> ProjectDeposit | None:
    return ProjectDeposit.objects.filter(project=project, status__in=PENDING).order_by("-created_at", "-pk").first()


def _company_gate(project: Project, wallet) -> None:
    if not deposits_active():
        raise PaymentError("wrong_mode", "Publication deposits are not active (direct mode or disabled).")
    if not project.is_company(wallet):
        raise PaymentError("forbidden", "Only the company can lock its project's deposit.")


def _state_gate(project: Project) -> None:
    if project.status in (P.CLOSED, P.CANCELLED):
        raise PaymentError("wrong_state", f"The project is {project.get_status_display().lower()}: no deposit to lock.")


def _record_error(row_pk: int, message: str, *, only_if_empty: str | None = None) -> None:
    qs = ProjectDeposit.objects.filter(pk=row_pk)
    if only_if_empty:
        qs = qs.filter(**{only_if_empty: ""})
    qs.update(last_error=(message or "")[:1000], updated_at=timezone.now())


def _ensure_row(project: Project) -> ProjectDeposit:
    """The pending row for the next deploy, created (or refreshed while still `created`) under the
    project lock. Its amount / coverage are frozen once deployed."""
    locked = Project.objects.select_for_update().get(pk=project.pk)
    _state_gate(locked)
    row = _pending_row(locked)
    if row is not None and row.status == D.DEPLOYED:
        raise PaymentError("wrong_state", "The deposit escrow already exists: lock the deposit.")
    due = deposit_due(locked)
    if due <= 0:
        raise PaymentError("wrong_state", "No deposit is due for this project.")
    gap = _project_total(locked) - covered_budget(locked)
    kind = ProjectDeposit.Kind.TOPUP if _has_covering_row(locked) else ProjectDeposit.Kind.PUBLICATION
    platform = signer.platform_address()
    resolver = signer.deposit_resolver_address()
    values = {
        "kind": kind,
        "amount": due,
        "covered_budget": gap,
        "payer_address": locked.company.stellar_address,
        "platform_address": platform,
        "resolver_address": resolver,
        "fund_address": fund_address(),
    }
    if row is None:
        n = ProjectDeposit.objects.filter(project=locked).count() + 1
        row = ProjectDeposit.objects.create(project=locked, engagement_id=f"taskvault-deposit-{locked.pk}-{n}", **values)
        logger.info("deposits: row created project=%s deposit=%s kind=%s amount=%s covers=%s", locked.pk, row.pk, kind, due, gap)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.save(update_fields=[*values, "updated_at"])
    return row


def prepare_deposit(project: Project, wallet, step: str) -> dict:
    """Build the unsigned XDR the company signs in Freighter: {xdr, extra, message, done}."""
    if step not in COMPANY_STEPS:
        raise PaymentError("unknown_step", "Unknown deposit step.")
    _company_gate(project, wallet)
    with transaction.atomic():
        if step == "deploy":
            row = _ensure_row(project)
        else:
            locked = Project.objects.select_for_update().get(pk=project.pk)
            _state_gate(locked)
            row = _pending_row(locked)
            if row is None or row.status != D.DEPLOYED:
                raise PaymentError("wrong_state", "Create the deposit escrow first.")
    if step == "deploy":
        env = tw.deploy_single_release(
            signer=row.payer_address,
            engagement_id=row.engagement_id,
            title=f"Publication deposit — {project.title}"[:100],
            description=f"TaskVault publication deposit for project #{project.pk}",
            amount=row.amount,
            approver=row.platform_address,
            service_provider=row.platform_address,
            receiver=row.payer_address,
            release_signer=row.platform_address,
            dispute_resolver=row.resolver_address,
            platform_address=row.platform_address,
            platform_fee=0,
            milestone_description=f"Deposit for project #{project.pk}",
        )
    else:
        env = tw.fund_escrow(contract_id=row.contract_id, signer=row.payer_address, amount=row.amount)
    try:
        xdr = _unsigned_xdr(env)
    except PaymentError as exc:
        _record_error(row.pk, exc.message)
        raise
    return {"xdr": xdr, "extra": {}, "message": None, "done": False}


def _result(row: ProjectDeposit, step: str, tx_hash: str | None, message: str) -> dict:
    return {
        "step": step,
        "status": row.status,
        "tx_hash": tx_hash,
        "contract_id": row.contract_id,
        "explorer_url": stellar.explorer_tx_url(tx_hash) if tx_hash else None,
        "message": message,
        "pending": False,
    }


def _replayed(project: Project, step: str, tx_hash: str | None) -> ProjectDeposit | None:
    """A row that already recorded this signed XDR for `step` and moved past it."""
    if not tx_hash:
        return None
    row = ProjectDeposit.objects.filter(project=project, **{HASH_FIELD[step]: tx_hash}).first()
    if row is not None and row.status not in STEP_FLOW[step]["allowed"]:
        return row
    return None


def _xdr_source(signed_xdr: str) -> str | None:
    try:
        return TransactionEnvelope.from_xdr(signed_xdr, stellar.network_passphrase()).transaction.source.account_id
    except Exception:
        return None


def confirm_deposit(project: Project, wallet, step: str, signed_xdr: str) -> dict:
    """Submit the company-signed XDR and persist the step. Replaying the same signed XDR answers ok."""
    if step not in COMPANY_STEPS:
        raise PaymentError("unknown_step", "Unknown deposit step.")
    if not signed_xdr:
        raise PaymentError("tampered", "Signed transaction missing.")
    _company_gate(project, wallet)
    tx_hash = _xdr_hash(signed_xdr)
    done = _replayed(project, step, tx_hash)
    if done is not None:
        return _result(done, step, tx_hash, "Step already confirmed.")
    if tx_hash is None:
        raise PaymentError("tampered", stellar.ERR_BAD_XDR)
    with transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project.pk)
        _state_gate(locked)
        row = _pending_row(locked)
        if row is None or row.status not in STEP_FLOW[step]["allowed"]:
            raise PaymentError("wrong_state", f"Step \"{STEP_FLOW[step]['label']}\" is not possible at this stage.")
        if _xdr_source(signed_xdr) != row.payer_address:
            logger.warning("deposits: signed xdr source is not the company project=%s step=%s", project.pk, step)
            raise PaymentError("tampered", "The signed transaction is not the company's.")
    env = tw.send_transaction(signed_xdr=signed_xdr)  # outside the transaction: no lock held over the network
    if not env.get("ok"):
        message = env.get("error") or tw.ERR_UNEXPECTED
        logger.warning("deposits: provider refused project=%s step=%s hash=%s error=%s", project.pk, step, tx_hash, message)
        _record_error(row.pk, message, only_if_empty=HASH_FIELD[step])
        raise PaymentError("provider", message)
    data = env.get("data") or {}
    contract_id = data.get("contractId") or (data.get("escrow") or {}).get("contractId") or ""
    if step == "deploy" and not contract_id:
        logger.error("deposits: deploy sent but no contractId project=%s hash=%s keys=%s", project.pk, tx_hash, list(data))
        missing = "Deposit escrow sent but the contract id is missing — contact support."
        _record_error(row.pk, missing)
        raise PaymentError("provider", missing)
    with transaction.atomic():
        row = ProjectDeposit.objects.select_for_update().get(pk=row.pk)
        if getattr(row, HASH_FIELD[step]) == tx_hash:
            return _result(row, step, tx_hash, "Step already confirmed.")
        if row.status not in STEP_FLOW[step]["allowed"]:
            raise PaymentError("wrong_state", "The deposit moved on in the meantime: reload the page.")
        if step == "deploy":
            row.contract_id = contract_id
            row.deploy_tx_hash = tx_hash
            row.status = D.DEPLOYED
            row.last_error = ""
            row.save(update_fields=["contract_id", "deploy_tx_hash", "status", "last_error", "updated_at"])
            message = "Deposit escrow created on Stellar. Now lock the deposit."
        else:
            now = timezone.now()
            row.fund_tx_hash = tx_hash
            row.status = D.FUNDED
            row.funded_at = now
            row.last_error = ""
            row.save(update_fields=["fund_tx_hash", "status", "funded_at", "last_error", "updated_at"])
            published = Project.objects.filter(pk=project.pk, published_at__isnull=True).update(published_at=now, updated_at=now)
            if published:
                logger.info("deposits: project published project=%s deposit=%s", project.pk, row.pk)
            message = "Deposit locked: the project is published." if published else "Deposit top-up locked."
    logger.info(
        "deposits: confirm project=%s deposit=%s step=%s wallet=%s hash=%s",
        project.pk, row.pk, step, wallet.stellar_address, tx_hash,
    )
    return _result(row, step, tx_hash, message)


def next_deposit_action(project: Project, wallet) -> dict | None:
    """The company's next deposit signature: {step, label, prepare_url, mine, amount, who, evidence,
    no_tx, hint, task} (the wire shape lowbid-pay.js understands) or None."""
    if not deposits_active() or project.status in (P.CLOSED, P.CANCELLED):
        return None
    row = _pending_row(project)
    if row is not None:
        step = "deploy" if row.status == D.CREATED else "fund"
        amount = row.amount if step == "fund" else deposit_due(project)
    else:
        amount = deposit_due(project)
        step = "deploy"
    if amount <= 0:
        return None
    return {
        "step": step,
        "label": STEP_FLOW[step]["label"],
        "prepare_url": reverse("payments:deposit_prepare", kwargs={"project_pk": project.pk, "step": step}),
        "mine": project.is_company(wallet),
        "amount": amount,
        "who": "company",
        "evidence": False,
        "no_tx": False,
        "hint": "",
        "task": None,
    }


# --- server chains: refund + forfeit -------------------------------------------------------------


def _reload(row_pk: int) -> ProjectDeposit:
    return ProjectDeposit.objects.select_related("project").get(pk=row_pk)


def _server_step(row: ProjectDeposit, step: str, field: str, keypair, build) -> bool:
    """build → sign (server key) → send → store the hash. False (last_error set) on any failure."""
    try:
        xdr = _unsigned_xdr(build())
        signed = signer.sign_xdr(xdr, keypair)
    except PaymentError as exc:
        logger.warning("deposits: %s build/sign failed deposit=%s error=%s", step, row.pk, exc.message)
        _record_error(row.pk, exc.message, only_if_empty=field)
        return False
    tx_hash = _xdr_hash(signed)
    env = tw.send_transaction(signed_xdr=signed)
    if not env.get("ok"):
        message = env.get("error") or tw.ERR_UNEXPECTED
        logger.warning("deposits: %s refused deposit=%s hash=%s error=%s", step, row.pk, tx_hash, message)
        _record_error(row.pk, message, only_if_empty=field)
        return False
    with transaction.atomic():
        locked = ProjectDeposit.objects.select_for_update().get(pk=row.pk)
        if not getattr(locked, field):
            setattr(locked, field, tx_hash or "")
            locked.save(update_fields=[field, "updated_at"])
    logger.info("deposits: %s sent deposit=%s hash=%s signer=%s", step, row.pk, tx_hash, keypair.public_key)
    return True


def _keys_match(row: ProjectDeposit, keypair, role: str) -> bool:
    expected = row.platform_address if role == "platform" else row.resolver_address
    if keypair.public_key == expected:
        return True
    logger.error("deposits: server %s key does not match the deposit's role deposit=%s", role, row.pk)
    _record_error(row.pk, f"The server {role} key does not match this deposit escrow's role.")
    return False


def _finalize(row_pk: int, status: str) -> ProjectDeposit:
    with transaction.atomic():
        locked = ProjectDeposit.objects.select_for_update().get(pk=row_pk)
        if locked.status == D.FUNDED:
            locked.status = status
            locked.settled_at = timezone.now()
            locked.last_error = ""
            locked.save(update_fields=["status", "settled_at", "last_error", "updated_at"])
            logger.info("deposits: settled deposit=%s project=%s status=%s", locked.pk, locked.project_id, status)
    return _reload(row_pk)


def _start(deposit: ProjectDeposit, terminal: str) -> ProjectDeposit | None:
    """Fresh row, or None when already in `terminal`; wrong_state unless funded."""
    row = _reload(deposit.pk)
    if row.status == terminal:
        return None
    if row.status != D.FUNDED:
        raise PaymentError("wrong_state", f"This deposit cannot be settled ({row.status_label}).")
    return row


def refund(deposit: ProjectDeposit) -> ProjectDeposit:
    """Platform key: milestone → approve → release (pays the receiver = the company). Idempotent:
    a stored hash skips its step; any failure stores last_error and returns the row unchanged."""
    row = _start(deposit, D.REFUNDED)
    if row is None:
        return _reload(deposit.pk)
    try:
        platform = signer.platform_keypair()
    except PaymentError as exc:
        _record_error(row.pk, exc.message)
        return _reload(row.pk)
    if not _keys_match(row, platform, "platform"):
        return _reload(row.pk)
    builders = {
        "milestone": lambda: tw.change_milestone_status(
            contract_id=row.contract_id, evidence=REFUND_EVIDENCE, service_provider=row.platform_address
        ),
        "approve": lambda: tw.approve_milestone(contract_id=row.contract_id, approver=row.platform_address),
        "release": lambda: tw.release_funds(contract_id=row.contract_id, release_signer=row.platform_address),
    }
    for step, field in REFUND_STEPS:
        row = _reload(row.pk)
        if row.status != D.FUNDED:
            return row
        if getattr(row, field):
            continue
        if not _server_step(row, step, field, platform, builders[step]):
            return _reload(row.pk)
    return _finalize(row.pk, D.REFUNDED)


def _escrow_balance(row: ProjectDeposit) -> Decimal | None:
    env = tw.get_escrow(contract_id=row.contract_id, validate_on_chain=True)
    if not env.get("ok"):
        _record_error(row.pk, env.get("error") or tw.ERR_UNEXPECTED)
        return None
    try:
        balance = Decimal(str((env.get("data") or {}).get("balance")))
    except (InvalidOperation, ValueError):
        balance = None
    if balance is None or not balance.is_finite() or balance <= 0:
        logger.warning("deposits: unusable escrow balance deposit=%s", row.pk)
        _record_error(row.pk, "The deposit escrow balance could not be read (or is empty).")
        return None
    return balance


def forfeit(deposit: ProjectDeposit) -> ProjectDeposit:
    """Platform key opens the dispute, the resolver key sends the whole balance to the guarantee fund.
    Needs the fund's trustline (checked first: no call at all without it)."""
    row = _start(deposit, D.FORFEITED)
    if row is None:
        return _reload(deposit.pk)
    fund = row.fund_address or fund_address()
    if not fund:
        _record_error(row.pk, "The guarantee fund address is not configured.")
        return _reload(row.pk)
    trust = stellar.has_trustline(fund)
    if trust is not True:
        message = (
            stellar.ERR_HORIZON_UNREACHABLE if trust is None else f"The guarantee fund has no {stellar.asset_code()} trustline."
        )
        logger.warning("deposits: forfeit blocked deposit=%s fund=%s trustline=%s", row.pk, fund, trust)
        _record_error(row.pk, message)
        return _reload(row.pk)
    try:
        platform = signer.platform_keypair()
        resolver = signer.deposit_resolver_keypair()
    except PaymentError as exc:
        _record_error(row.pk, exc.message)
        return _reload(row.pk)
    if not (_keys_match(row, platform, "platform") and _keys_match(row, resolver, "resolver")):
        return _reload(row.pk)
    if not row.dispute_tx_hash:
        ok = _server_step(
            row, "dispute", "dispute_tx_hash", platform,
            lambda: tw.dispute_escrow(contract_id=row.contract_id, signer=row.platform_address),
        )
        if not ok:
            return _reload(row.pk)
    row = _reload(row.pk)
    if not row.resolve_tx_hash:
        balance = _escrow_balance(row)
        if balance is None:
            return _reload(row.pk)
        ok = _server_step(
            row, "resolve", "resolve_tx_hash", resolver,
            lambda: tw.resolve_dispute(
                contract_id=row.contract_id, dispute_resolver=row.resolver_address, distributions=[{"address": fund, "amount": balance}]
            ),
        )
        if not ok:
            return _reload(row.pk)
    if row.fund_address != fund:
        ProjectDeposit.objects.filter(pk=row.pk).update(fund_address=fund)
    return _finalize(row.pk, D.FORFEITED)


def settle(deposit: ProjectDeposit, now: datetime | None = None) -> ProjectDeposit:
    """Refund or forfeit this funded deposit as `deposit_verdict` says; wrong_state while locked."""
    verdict = deposit_verdict(deposit.project, now)
    if verdict["verdict"] == "refund":
        return refund(deposit)
    if verdict["verdict"] == "forfeit":
        return forfeit(deposit)
    raise PaymentError("wrong_state", f"The deposit stays locked: {verdict['reason']}")


def settle_project(project: Project, now: datetime | None = None) -> list[ProjectDeposit]:
    """Settle every funded deposit of the project (oldest first)."""
    return [settle(row, now) for row in ProjectDeposit.objects.filter(project=project, status=D.FUNDED).order_by("created_at", "pk")]


# --- automatic trigger: the commit that closes / cancels the project --------------------------------


def _settle_after_commit(project_id: int) -> None:
    try:
        project = Project.objects.get(pk=project_id)
        rows = settle_project(project)
        logger.info(
            "deposits: auto settle project=%s status=%s rows=%s",
            project_id, project.status, ",".join(f"{r.pk}:{r.status}" for r in rows) or "-",
        )
    except Exception:
        logger.exception("deposits: auto settle failed project=%s", project_id)


def on_project_saved(sender, instance: Project, raw: bool = False, **kwargs) -> None:
    """post_save receiver (payments/apps.py): once a closed / cancelled project is committed, its funded
    deposits are settled (refund or forfeit, as the verdict says)."""
    if raw or instance.status not in (P.CLOSED, P.CANCELLED):
        return
    if not ProjectDeposit.objects.filter(project_id=instance.pk, status=D.FUNDED).exists():
        return
    project_id = instance.pk
    transaction.on_commit(lambda: _settle_after_commit(project_id))


# --- view-models -----------------------------------------------------------------------------------


def locked_amount(project: Project) -> Decimal:
    return ProjectDeposit.objects.filter(project=project, status=D.FUNDED).aggregate(s=Sum("amount"))["s"] or ZERO


def can_cancel(project: Project, wallet) -> bool:
    """Mirror of projects.services.cancel_project's gates (the button only)."""
    return (
        project.is_company(wallet)
        and project.status not in (P.CLOSED, P.CANCELLED)
        and not project.tasks.exclude(status=Task.Status.OPEN).exists()
    )


def deposit_panel_context(project: Project, wallet, now: datetime | None = None) -> dict:
    """Everything templates/payments/_deposit_panel.html reads (the template decides nothing)."""
    now = now or timezone.now()
    is_direct = stellar.payment_mode() != "escrow"
    rows = list(ProjectDeposit.objects.filter(project=project).order_by("created_at", "pk"))
    funded = [r for r in rows if r.status == D.FUNDED]
    pending = next((r for r in reversed(rows) if r.status in PENDING), None)
    due = deposit_due(project) if not is_direct else ZERO
    verdict = deposit_verdict(project, now)
    is_company = project.is_company(wallet)
    open_project = project.status not in (P.CLOSED, P.CANCELLED)
    if is_direct:
        status = "direct"
    elif not deposits_active() and not rows:
        status = "inactive"
    elif pending is not None:
        status = pending.status
    elif due > 0 and open_project:
        status = "due"
    elif funded:
        status = D.FUNDED
    elif rows:
        status = rows[-1].status
    else:
        status = "due"
    has_funded = bool(funded)
    can_reclaim = has_funded and verdict["verdict"] == "refund" and is_company
    can_report = has_funded and verdict["verdict"] == "forfeit" and wallet is not None
    action = next_deposit_action(project, wallet) if open_project else None
    deadline_kind = ""
    if has_funded and verdict["deadline"] is not None:
        has_apps = Application.objects.filter(task__project=project).exists()
        deadline_kind = "choose" if has_apps else "no_application"
    errored = next((r for r in reversed(rows) if r.last_error and r.status in (*PENDING, D.FUNDED)), None)
    retry = ""
    if errored is not None:
        if errored.status in PENDING and is_company and action:
            retry = "publish"
        elif errored.status == D.FUNDED and can_reclaim:
            retry = "refund"
        elif errored.status == D.FUNDED and can_report:
            retry = "report"
    links = [link for r in rows for link in r.explorer_links()]
    return {
        "project": project,
        "status": status,
        "status_label": DEPOSIT_STATUS_LABELS.get(status, ""),
        "badge_class": DEPOSIT_STATUS_BADGES.get(status, "ui-badge-neutral"),
        "is_direct": is_direct,
        "active": deposits_active(),
        "is_company": is_company,
        "rows": rows,
        "amount_due": action["amount"] if action else due,
        "locked": locked_amount(project),
        "refunded": sum((r.amount for r in rows if r.status == D.REFUNDED), ZERO),
        "forfeited": sum((r.amount for r in rows if r.status == D.FORFEITED), ZERO),
        "published": project.published_at is not None,
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
        "deadline": verdict["deadline"] if has_funded else None,
        "deadline_kind": deadline_kind,
        "action": action,
        "can_publish": bool(action and action["mine"]),
        "publish_is_topup": project.published_at is not None,
        "can_reclaim": can_reclaim,
        "can_report": can_report,
        "can_cancel": can_cancel(project, wallet),
        "cancel_outcome": cancel_outcome(project, now),
        "last_error": errored.last_error if errored is not None else "",
        "retry": retry,
        "links": links,
        "fund_address": fund_address(),
        "choice_days": choice_days(),
        "no_application_days": no_application_days(),
        "pending_url": reverse("payments:deposit_pending", kwargs={"project_pk": project.pk}),
        "refund_url": reverse("payments:deposit_refund", kwargs={"project_pk": project.pk}),
        "report_url": reverse("payments:deposit_report", kwargs={"project_pk": project.pk}),
        "cancel_url": reverse("projects:project_cancel", kwargs={"pk": project.pk}),
    }
