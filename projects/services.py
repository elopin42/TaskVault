"""Business rules of the task board in one place. Views only translate
ProjectError codes into HTTP; templates never decide a rule.

Payment hooks (wired to the payments app, imported lazily to avoid an import cycle):
  - `mark_paid(task)`       the ONLY function that flips a task to `paid` (idempotent); payments
    calls it once the escrow release / direct payment is confirmed on chain;
  - `_after_validate(task)` called by `validate()` once the Rating is stored → it hands over to
    `payments.services.on_task_validated(task)`, which does NOT pay: the page then chains the
    Freighter signatures (approve → release, or direct_pay);
  - `_before_deliver(task)` a DB-only delivery is refused in escrow mode (the freelance signs the
    milestone change instead; payments calls `deliver(..., on_chain=True)` after that);
  - `_after_request_changes(task)` called by `request_changes()` once the task is back to `taken` →
    `payments.services.on_changes_requested(task)` moves the Escrow row back as well;
  - `mark_disputed(task, opened_by, reason)` called by payments once a party's dispute-escrow
    transaction is confirmed (Task `delivered → disputed`, a `Dispute` row);
  - `mark_resolved(task, freelance_share)` the ONLY function that flips a task to `resolved`
    (idempotent); payments calls it once the arbiter's resolve-dispute transaction is confirmed.

Disputes (escrow mode only — the mode gate is payments'): `can_dispute(task, wallet)` says who may
open one: the company while the task is `delivered` and not rated yet, the chosen freelance once the
review window is over (`is_review_overdue`, "dispute for no response"). A disputed task can no longer
be validated nor sent back for changes; the arbiter's split (`Dispute.freelance_pct`) settles it and
a project closes when every task is `paid` OR `resolved`.

Review window and revisions: once delivered, the company has `LOWBID_REVIEW_DAYS` days
(`review_deadline`, computed at read time — no timer anywhere) to validate or to send the delivery
back for changes (`request_changes`, at most `LOWBID_MAX_REVISIONS` times, only before the Rating).
A change request puts the task back to `taken` and the freelance delivers again; every (re)delivery is
a `Delivery` row and every request a `RevisionRequest` row (`delivery_history`).

Two-step delivery: `Task.delivery_link` (demo / preview, required) is public once delivered;
`Task.source_link` (the full deliverable, optional) is revealed to the company only once the task is
`paid` (`source_visible`); `Task.delivery_hash` (git commit SHA or SHA-256, optional) is the
fingerprint that lets the company check later that the revealed work is the one declared — in
escrow mode payments puts it on chain inside the milestone evidence.
"""

import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import SETTLED_STATUSES, Application, Delivery, Dispute, Project, Rating, RevisionRequest, Task
from .scoring import company_history, score_application

logger = logging.getLogger(__name__)

MAX_TAGS = 3
MAX_TAG_LENGTH = 24
MAX_MESSAGE = 280
MAX_LINK = 500
HASH_LENGTHS = (40, 64)  # git commit SHA-1 / SHA-256, lowercase hex
USDC_PLACES = 7
TITLE_MIN = 3
TITLE_MAX = 120
LINK_DISPLAY_MAX = 120

__all__ = [
    "ProjectError",
    "add_task",
    "apply",
    "can_dispute",
    "cancel_project",
    "can_request_changes",
    "choose",
    "clean_hash",
    "clean_link",
    "clean_reason",
    "clean_source_link",
    "clean_tags",
    "company_history",
    "create_project",
    "dec_str",
    "delete_task",
    "deliver",
    "delivery_history",
    "is_review_overdue",
    "link_info",
    "mark_disputed",
    "mark_paid",
    "mark_resolved",
    "max_revisions",
    "parse_note",
    "parse_price",
    "request_changes",
    "rescore",
    "review_deadline",
    "revisions_left",
    "source_visible",
    "validate",
]


class ProjectError(Exception):
    """A refused action. `code` is stable (JS/tests), `message` is English UI copy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- parsing helpers ------------------------------------------------------------------

def dec_str(value) -> str:
    """'450', '400.5' — never '4.5E+2' (data-* attributes, JSON)."""
    return f"{Decimal(value).normalize():f}"


def clean_tags(raw) -> list[str]:
    """Accept a list or a comma/space-separated string → ≤3 unique lowercase slugs."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,\s;]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        raise ProjectError("bad_tags", "Skills must be a list of words.")
    tags: list[str] = []
    for part in parts:
        slug = slugify(part.strip().lower())
        if not slug:
            continue
        if len(slug) > MAX_TAG_LENGTH:
            raise ProjectError("bad_tags", f"A skill is at most {MAX_TAG_LENGTH} characters.")
        if slug not in tags:
            tags.append(slug)
    if len(tags) > MAX_TAGS:
        raise ProjectError("bad_tags", f"At most {MAX_TAGS} skills.")
    return tags


def parse_price(raw) -> Decimal:
    """Strictly positive, at most 7 decimals (USDC precision on Stellar)."""
    try:
        price = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        raise ProjectError("invalid", "Invalid price.") from None
    if not price.is_finite() or price <= 0:
        raise ProjectError("invalid", "The price must be strictly positive.")
    exponent = price.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > USDC_PLACES:
        raise ProjectError("invalid", f"At most {USDC_PLACES} decimals (USDC precision).")
    if price >= Decimal(10) ** 11:
        raise ProjectError("invalid", "Price too high.")
    return price


def parse_note(raw) -> int:
    try:
        note = int(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        raise ProjectError("invalid", "The rating must be a whole number from 1 to 5.") from None
    if note < 1 or note > 5:
        raise ProjectError("invalid", "The rating must be between 1 and 5.")
    return note


def _clean_title(raw, label: str) -> str:
    title = str(raw or "").strip()
    if len(title) < TITLE_MIN:
        raise ProjectError("invalid", f"The {label} title is too short.")
    if len(title) > TITLE_MAX:
        raise ProjectError("invalid", f"The {label} title is at most {TITLE_MAX} characters.")
    return title


def _check_url(link: str, label: str) -> str:
    if len(link) > MAX_LINK:
        raise ProjectError("invalid", f"The {label} is at most {MAX_LINK} characters.")
    if not re.match(r"^https?://", link, re.IGNORECASE):
        raise ProjectError("invalid", f"The {label} must start with http:// or https://.")
    return link


def clean_link(raw) -> str:
    """The delivery link: required, ≤500 chars, http(s)://. Raises ProjectError('invalid')."""
    link = str(raw or "").strip()
    if not link:
        raise ProjectError("invalid", "Enter the delivery link (PR, demo, repository…).")
    return _check_url(link, "link")


def clean_source_link(raw) -> str:
    """The full deliverable link: optional ("" allowed), else the same rules as `clean_link`."""
    link = str(raw or "").strip()
    if not link:
        return ""
    return _check_url(link, "full deliverable link")


def _host_matches(host: str, entry: str) -> bool:
    entry = entry.strip().lower().rstrip(".")
    return bool(entry) and (host == entry or host.endswith("." + entry))


def link_info(url) -> dict:
    """How a user-supplied link (delivery link, full deliverable) is rendered — the one rule, read by
    `templates/components/ext_link.html` through the view / inclusion tag / history rows:
    {url, href, host, display, trusted}. `host` is the lowercase ASCII host (an IDN shows as its
    punycode, so a look-alike domain cannot pass for a known one); `trusted` is True when it equals a
    `LOWBID_TRUSTED_LINK_HOSTS` entry or is a subdomain of one. `href` is "" for anything that is not
    an http(s) URL with a host (`clean_link` already refuses those upstream; this never raises), and
    the include then renders no anchor. `display` is the full URL, cut at LINK_DISPLAY_MAX characters."""
    raw = str(url or "").strip()
    display = raw if len(raw) <= LINK_DISPLAY_MAX else raw[: LINK_DISPLAY_MAX - 1] + "…"
    info = {"url": raw, "href": "", "host": "", "display": display, "trusted": False}
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").rstrip(".")
    except ValueError:  # e.g. an unbalanced IPv6 bracket
        return info
    if parts.scheme.lower() not in ("http", "https") or not host:
        return info
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        host = host.lower()  # not encodable: shown as typed, never trusted unless it is plain ASCII
    trusted_hosts = getattr(settings, "LOWBID_TRUSTED_LINK_HOSTS", []) or []
    info.update(
        href=raw,
        host=host,
        trusted=host.isascii() and any(_host_matches(host, entry) for entry in trusted_hosts),
    )
    return info


def clean_hash(raw) -> str:
    """The delivery fingerprint: "" allowed; else a git commit SHA (40 hex) or a SHA-256 (64 hex),
    normalised to lowercase. Raises ProjectError('invalid') otherwise."""
    value = str(raw or "").strip().lower()
    if not value:
        return ""
    if len(value) not in HASH_LENGTHS or not re.fullmatch(r"[0-9a-f]+", value):
        raise ProjectError(
            "invalid",
            "The fingerprint must be a 40-character git commit SHA or a 64-character SHA-256 (hex).",
        )
    return value


def clean_reason(raw) -> str:
    """The dispute reason: required, 1–280 characters once stripped. Raises ProjectError('invalid')."""
    reason = str(raw or "").strip()
    if not reason:
        raise ProjectError("invalid", "Explain why you open the dispute (a few words are enough).")
    if len(reason) > MAX_MESSAGE:
        raise ProjectError("invalid", f"The reason is at most {MAX_MESSAGE} characters.")
    return reason


def _require_company(project: Project, wallet) -> None:
    if wallet is None or project.company_id != wallet.pk:
        raise ProjectError("forbidden", "Only the company that created the project can do this.")


def _locked_task(task: Task) -> Task:
    return Task.objects.select_for_update().select_related("project").get(pk=task.pk)


# --- company: project + tasks -------------------------------------------------------------

def create_project(company, title, description) -> Project:
    title = _clean_title(title, "project")
    description = str(description or "").strip()
    if not description:
        raise ProjectError("invalid", "Describe the project in a few lines.")
    project = Project.objects.create(
        company=company, title=title, description=description, published_at=initial_published_at()
    )
    logger.info("project created project=%s company=%s published=%s", project.pk, company.pk, project.published_at is not None)
    return project


def initial_published_at():
    """`published_at` of a new project: now when publication deposits are NOT active (direct mode keeps
    today's behaviour), None otherwise — funding the deposit publishes it (payments.deposits)."""
    from payments.deposits import deposits_active  # lazy: payments imports this module

    return None if deposits_active() else timezone.now()


def cancel_project(project: Project, company) -> Project:
    """Only the company (`forbidden`); refused (`wrong_state`) once closed / cancelled or as soon as a
    freelance was chosen for any task. The project becomes `cancelled`; once committed, payments settles
    its deposit (refund without application, forfeit otherwise — payments.deposits.on_project_saved)."""
    _require_company(project, company)
    with transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project.pk)
        if locked.status in (Project.Status.CLOSED, Project.Status.CANCELLED):
            raise ProjectError("wrong_state", f"The project is already {locked.get_status_display().lower()}.")
        if locked.tasks.exclude(status=Task.Status.OPEN).exists():
            raise ProjectError("wrong_state", "A freelancer has been chosen: the project can no longer be cancelled.")
        locked.status = Project.Status.CANCELLED
        locked.save(update_fields=["status", "updated_at"])
    logger.info("project cancelled project=%s company=%s", locked.pk, company.pk)
    return locked


def add_task(project: Project, company, title, description, price, tags) -> Task:
    """Only the company, until the project is `closed`. One escrow per task: funding a task locks
    THAT task's price, never the project, so new tasks can be added at any time before closing."""
    _require_company(project, company)
    title = _clean_title(title, "task")
    price = parse_price(price)
    tags = clean_tags(tags)
    description = str(description or "").strip()
    with transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project.pk)
        if locked.status in (Project.Status.CLOSED, Project.Status.CANCELLED):
            raise ProjectError("wrong_state", f"The project is {locked.get_status_display().lower()}: no new tasks.")
        position = (locked.tasks.count() or 0) + 1
        task = Task.objects.create(
            project=locked, title=title, description=description, price=price, tags=tags, position=position
        )
    logger.info("task added project=%s task=%s price=%s", project.pk, task.pk, price)
    return task


def delete_task(task: Task, company) -> None:
    """Only the company, only an OPEN task (nothing chosen, nothing funded); its applications go with it."""
    _require_company(task.project, company)
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status != Task.Status.OPEN:
            raise ProjectError("wrong_state", "Only an open task can be deleted.")
        _check_can_delete(locked)
        pk = locked.pk
        locked.delete()
    logger.info("task deleted task=%s", pk)


# --- freelance: apply / deliver ------------------------------------------------------------

def apply(task: Task, freelancer, message, tags) -> Application:
    """Anyone with a wallet (validated or not) may apply once to an open task — except the company."""
    tags = clean_tags(tags)
    message = str(message or "").strip()
    if len(message) > MAX_MESSAGE:
        raise ProjectError("invalid", f"The message is at most {MAX_MESSAGE} characters.")
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status != Task.Status.OPEN:
            raise ProjectError("wrong_state", "This task is no longer open to applications.")
        _check_applications_open(locked)
        if locked.project.company_id == freelancer.pk:
            raise ProjectError("own_task", "You cannot apply to your own task.")
        if locked.applications.filter(freelancer=freelancer).exists():
            raise ProjectError("duplicate", "You have already applied to this task.")
        score = score_application(locked, freelancer, tags)
        try:
            with transaction.atomic():
                app = Application.objects.create(
                    task=locked, freelancer=freelancer, message=message, tags=tags, score=score
                )
        except IntegrityError:
            raise ProjectError("duplicate", "You have already applied to this task.") from None
    logger.info("application created task=%s application=%s freelancer=%s score=%s", task.pk, app.pk, freelancer.pk, score)
    return app


def choose(task: Task, application: Application, company) -> Task:
    """The company picks ANY candidate of an open task (the score is only a hint)."""
    _require_company(task.project, company)
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status != Task.Status.OPEN:
            raise ProjectError("wrong_state", "A freelancer has already been chosen for this task.")
        if locked.project.status == Project.Status.CANCELLED:
            raise ProjectError("wrong_state", "This project was cancelled.")
        fresh = Application.objects.filter(pk=application.pk, task=locked).select_related("freelancer").first()
        if fresh is None:
            raise ProjectError("invalid", "This application does not exist on this task.")
        locked.applications.exclude(pk=fresh.pk).update(status=Application.Status.REJECTED)
        Application.objects.filter(pk=fresh.pk).update(status=Application.Status.CHOSEN)
        locked.status = Task.Status.TAKEN
        locked.assigned_to = fresh.freelancer
        locked.save(update_fields=["status", "assigned_to", "updated_at"])
        _after_choose(locked)
    logger.info("task taken task=%s application=%s freelancer=%s", locked.pk, fresh.pk, fresh.freelancer_id)
    return locked


def deliver(
    task: Task,
    freelancer,
    delivery_link,
    *,
    delivery_hash="",
    source_link="",
    on_chain: bool = False,
    tx_hash: str = "",
) -> Task:
    """Only the assignee, only a `taken` task; the link must be http(s), ≤500 chars. The optional
    `delivery_hash` (git SHA / SHA-256, see `clean_hash`) and `source_link` (full deliverable, see
    `clean_source_link`) are stored with it. `on_chain=True` is payments confirming the Trustless
    Work milestone change (`tx_hash` = that transaction); otherwise the `_before_deliver` hook refuses
    a DB-only delivery in escrow mode. The single write point of a delivery: the Task holds the latest
    one, a `Delivery` row keeps every one (a re-delivery after `request_changes` adds a row)."""
    link = clean_link(delivery_link)
    fingerprint = clean_hash(delivery_hash)
    source = clean_source_link(source_link)
    with transaction.atomic():
        locked = _locked_task(task)
        if freelancer is None or locked.assigned_to_id != freelancer.pk:
            raise ProjectError("not_assigned", "Only the chosen freelancer can deliver this task.")
        if locked.status != Task.Status.TAKEN:
            raise ProjectError("wrong_state", "This task is not in progress: nothing to deliver.")
        if not on_chain:
            _before_deliver(locked)
        locked.status = Task.Status.DELIVERED
        locked.delivery_link = link
        locked.delivery_hash = fingerprint
        locked.source_link = source
        locked.delivered_at = timezone.now()
        locked.save(
            update_fields=["status", "delivery_link", "delivery_hash", "source_link", "delivered_at", "updated_at"]
        )
        Delivery.objects.create(
            task=locked,
            freelancer=freelancer,
            delivery_link=link,
            delivery_hash=fingerprint,
            source_link=source,
            tx_hash=(tx_hash or "")[:64],
        )
    logger.info(
        "task delivered task=%s freelancer=%s hash=%s source=%s revision=%s tx=%s",
        locked.pk, freelancer.pk, fingerprint or "-", "yes" if source else "no", locked.revision_count, tx_hash or "-",
    )
    return locked


def source_visible(task: Task, wallet) -> bool:
    """Who may see `Task.source_link` (the full deliverable): the assignee always, the company only
    once the task is settled (`paid`, or `resolved` by the arbiter — the company then paid its share),
    anyone else never. Views pass the result to the templates."""
    if wallet is None:
        return False
    if task.assigned_to_id is not None and task.assigned_to_id == wallet.pk:
        return True
    if task.project.company_id == wallet.pk:
        return task.status in SETTLED_STATUSES
    return False


# --- review window + change requests ------------------------------------------------------------

def max_revisions() -> int:
    return int(getattr(settings, "LOWBID_MAX_REVISIONS", 2))


def revisions_left(task: Task) -> int:
    """How many change requests the company may still make on this task (never negative)."""
    return max(0, max_revisions() - task.revision_count)


def review_deadline(task: Task) -> datetime | None:
    """End of the company's review window: `delivered_at` + LOWBID_REVIEW_DAYS days while the task is
    `delivered`, None otherwise. Computed at read time — nothing runs on a timer."""
    if task.status != Task.Status.DELIVERED or task.delivered_at is None:
        return None
    return task.delivered_at + timedelta(days=int(getattr(settings, "LOWBID_REVIEW_DAYS", 7)))


def is_review_overdue(task: Task) -> bool:
    """Delivered, not rated yet, and the review window is over (the freelance's protection: Phase 3
    lets them open a dispute from here)."""
    deadline = review_deadline(task)
    if deadline is None or Rating.objects.filter(task=task).exists():
        return False
    return timezone.now() > deadline


def can_request_changes(task: Task, wallet) -> bool:
    """Whether the "Request changes" control is shown to this viewer: the company, while the task is
    `delivered` and not rated yet (so never once disputed or resolved). The max-revisions gate is
    `request_changes`' (the button is disabled with a hint when `revisions_left` is 0). Views pass the
    result to the templates."""
    if wallet is None or task.project.company_id != wallet.pk or task.status != Task.Status.DELIVERED:
        return False
    return not Rating.objects.filter(task=task).exists()


def request_changes(task: Task, company, message) -> Task:
    """The company sends a delivery back: only the company (`forbidden`), only a `delivered` task that
    is not rated yet (`wrong_state`), at most LOWBID_MAX_REVISIONS times (`too_many_revisions`), with a
    non-empty message ≤ 280 chars telling the freelance what to change (`invalid`). The task goes
    `delivered → taken`, `revision_count` += 1, `delivered_at` is cleared (the window restarts at the
    next delivery; the history stays in Delivery / RevisionRequest), then the payments hook moves the
    Escrow row back (`delivered → funded` in escrow mode, `delivered → created` in direct mode)."""
    _require_company(task.project, company)
    message = str(message or "").strip()
    if not message:
        raise ProjectError("invalid", "Tell the freelancer what to change.")
    if len(message) > MAX_MESSAGE:
        raise ProjectError("invalid", f"The message is at most {MAX_MESSAGE} characters.")
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status == Task.Status.DISPUTED:
            raise ProjectError("wrong_state", "This task is in dispute: the arbiter decides, nothing can be sent back.")
        if locked.status != Task.Status.DELIVERED:
            raise ProjectError("wrong_state", "Only a delivered task can be sent back for changes.")
        if Rating.objects.filter(task=locked).exists():
            raise ProjectError("wrong_state", "This delivery has already been validated: it cannot be sent back.")
        limit = max_revisions()
        if locked.revision_count >= limit:
            raise ProjectError(
                "too_many_revisions",
                f"At most {limit} change request{'s' if limit != 1 else ''} per task: validate this delivery.",
            )
        RevisionRequest.objects.create(task=locked, company=company, message=message)
        locked.status = Task.Status.TAKEN
        locked.revision_count += 1
        locked.delivered_at = None
        locked.save(update_fields=["status", "revision_count", "delivered_at", "updated_at"])
        _after_request_changes(locked)
    logger.info(
        "changes requested task=%s company=%s revision=%s/%s", locked.pk, company.pk, locked.revision_count, limit
    )
    return locked


def _escrow_hashes(task: Task) -> dict:
    """The dispute / resolve tx hashes of the task's Escrow row (payments), read through the reverse
    one-to-one — no payments import needed; {} without a row."""
    try:
        escrow = task.escrow
    except ObjectDoesNotExist:
        return {}
    return {"dispute": escrow.dispute_tx_hash, "resolve": escrow.resolve_tx_hash}


def delivery_history(task: Task, *, source_visible: bool = False) -> list[dict]:
    """Every Delivery, RevisionRequest and the Dispute (opening + resolution) of the task, newest
    first, as plain dicts for the templates: {kind: "delivery" | "revision" | "dispute" | "resolution",
    when, who, ...}. `source_link` (and its `source_info`) is included only when the caller may see it
    (`source_visible`), so it never reaches the markup otherwise; a delivery row carries `info` =
    `link_info(delivery_link)` for the link component."""
    rows: list[dict] = []
    for d in task.deliveries.select_related("freelancer"):
        rows.append(
            {
                "kind": "delivery",
                "when": d.created_at,
                "who": d.freelancer,
                "delivery_link": d.delivery_link,
                "info": link_info(d.delivery_link),
                "delivery_hash": d.delivery_hash,
                "source_link": d.source_link if source_visible else "",
                "source_info": link_info(d.source_link) if source_visible and d.source_link else None,
                "tx_hash": d.tx_hash,
            }
        )
    for r in task.revision_requests.select_related("company"):
        rows.append({"kind": "revision", "when": r.created_at, "who": r.company, "message": r.message})
    dispute = Dispute.objects.filter(task=task).select_related("opened_by").first()
    if dispute is not None:
        hashes = _escrow_hashes(task)
        rows.append(
            {
                "kind": "dispute",
                "when": dispute.created_at,
                "who": dispute.opened_by,
                "reason": dispute.reason,
                "by_company": dispute.opened_by_id == task.project.company_id,
                "tx_hash": hashes.get("dispute", ""),
            }
        )
        if dispute.resolved_at is not None:
            rows.append(
                {
                    "kind": "resolution",
                    "when": dispute.resolved_at,
                    "who": None,
                    "freelance_pct": dispute.freelance_pct,
                    "company_pct": dispute.company_pct,
                    "tx_hash": hashes.get("resolve", ""),
                }
            )
    rows.sort(key=lambda row: row["when"], reverse=True)
    return rows


# --- disputes (escrow mode; payments owns the on-chain side and the mode gate) --------------------

def can_dispute(task: Task, wallet) -> tuple[bool, str]:
    """Who may open a dispute and, when not, why (English UI copy): the company while the task is
    `delivered` and NOT rated yet (a rated delivery is validated: release the funds); the chosen
    freelance only once the review window is over (`is_review_overdue` — "dispute for no response");
    nobody else, and nothing outside `delivered`. The payment mode is payments' business
    (`payments.services.can_dispute` wraps this one and refuses direct mode)."""
    if wallet is None:
        return False, "Connect your wallet to open a dispute."
    is_company = task.project.company_id == wallet.pk
    is_assignee = task.assigned_to_id is not None and task.assigned_to_id == wallet.pk
    if not (is_company or is_assignee):
        return False, "Only the company or the chosen freelancer can open a dispute."
    if task.status == Task.Status.DISPUTED:
        return False, "A dispute is already open on this task: the arbiter decides."
    if task.status == Task.Status.RESOLVED:
        return False, "This dispute has been resolved by the arbiter."
    if task.status != Task.Status.DELIVERED:
        return False, "Only a delivered task can be disputed."
    if is_company:
        if Rating.objects.filter(task=task).exists():
            return False, "You validated this delivery: release the funds instead of disputing it."
        return True, ""
    if not is_review_overdue(task):
        deadline = review_deadline(task)
        when = f" until {timezone.localtime(deadline):%b %d, %Y %H:%M}" if deadline else ""
        return False, f"The company still has{when} to answer: a dispute for no response opens once the review window is over."
    return True, ""


def mark_disputed(task: Task, opened_by, reason: str) -> Task:
    """Called by payments (`confirm_dispute`) once the dispute-escrow transaction is confirmed: Task
    `delivered → disputed` and the `Dispute` row (who, why). `opened_by` must be a party and the
    task `delivered` (`wrong_state` otherwise — payments gates before signing, this is the last check)."""
    reason = clean_reason(reason)
    with transaction.atomic():
        locked = _locked_task(task)
        allowed, why = can_dispute(locked, opened_by)
        if not allowed:
            raise ProjectError("wrong_state", why)
        Dispute.objects.create(task=locked, opened_by=opened_by, reason=reason)
        locked.status = Task.Status.DISPUTED
        locked.save(update_fields=["status", "updated_at"])
    logger.info("task disputed task=%s opened_by=%s", locked.pk, opened_by.pk)
    return locked


def mark_resolved(task: Task, freelance_share) -> Task:
    """The ONLY way a task becomes `resolved` (idempotent). `freelance_share` is the percentage of the
    escrow balance the arbiter sent to the freelance (int 0–100); the company got the rest. Stores it
    on the Dispute row with `resolved_at`, flips the task `disputed → resolved`, closes the project when
    every task is paid or resolved, and refreshes the company's open tasks' scores. Called by payments
    once the resolve-dispute transaction is confirmed."""
    try:
        pct = int(str(freelance_share).strip())
    except (TypeError, ValueError):
        raise ProjectError("invalid", "The freelancer's share must be a whole percentage (0–100).") from None
    if pct < 0 or pct > 100:
        raise ProjectError("invalid", "The freelancer's share must be between 0 and 100 %.")
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status == Task.Status.RESOLVED:
            return locked
        if locked.status != Task.Status.DISPUTED:
            raise ProjectError("wrong_state", "Only a disputed task can be resolved.")
        now = timezone.now()
        dispute = Dispute.objects.select_for_update().filter(task=locked).first()
        if dispute is None:  # defensive: a disputed task always has its row (mark_disputed)
            dispute = Dispute.objects.create(task=locked, opened_by=locked.project.company, reason="")
        dispute.freelance_pct = pct
        dispute.resolved_at = now
        dispute.save(update_fields=["freelance_pct", "resolved_at"])
        locked.status = Task.Status.RESOLVED
        locked.resolved_at = now
        locked.save(update_fields=["status", "resolved_at", "updated_at"])
        _close_if_settled(locked.project_id)
        logger.info("task resolved task=%s freelance_pct=%s", locked.pk, pct)
        _rescore_company(locked.project.company_id)
    return locked


def _close_if_settled(project_id: int) -> None:
    """A project closes when every task is `paid` or `resolved` (the money of each task left its escrow)."""
    project = Project.objects.select_for_update().get(pk=project_id)
    if project.status != Project.Status.CLOSED and not project.tasks.exclude(status__in=SETTLED_STATUSES).exists():
        project.status = Project.Status.CLOSED
        project.save(update_fields=["status", "updated_at"])
        logger.info("project closed project=%s", project.pk)


# --- company: validate + rate → payment hook ----------------------------------------------------

def validate(task: Task, company, note, comment: str = "") -> Task:
    """Store the Rating (one per task) then hand over to the payment hook (`_after_validate`)."""
    _require_company(task.project, company)
    note = parse_note(note)
    comment = str(comment or "").strip()[:MAX_MESSAGE]
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status != Task.Status.DELIVERED:
            raise ProjectError("wrong_state", "The task must be delivered before it can be validated.")
        if Rating.objects.filter(task=locked).exists():
            raise ProjectError("duplicate", "This task has already been rated.")
        Rating.objects.create(task=locked, company=company, freelancer=locked.assigned_to, note=note, comment=comment)
        logger.info("task validated task=%s note=%s freelancer=%s", locked.pk, note, locked.assigned_to_id)
        _rescore_company(locked.project.company_id)
        _after_validate(locked)
    locked.refresh_from_db()
    return locked


def _after_choose(task: Task) -> None:
    """Payment hook: the new assignee has no locked funds yet, payments re-syncs the project status."""
    from payments import services as payments  # lazy: payments.services imports this module

    payments.on_task_chosen(task)


def _after_validate(task: Task) -> None:
    """Payment hook: the Rating is stored, payments decides what the company signs next
    (approve → release in escrow mode, direct_pay in direct mode). Nothing is paid here."""
    from payments import services as payments  # lazy: payments.services imports this module

    payments.on_task_validated(task)


def _check_can_delete(task: Task) -> None:
    """Deposit hook, inside delete_task()'s transaction: while a deposit is locked, a task with
    applications cannot be deleted (payments.deposits.check_can_delete)."""
    from payments import deposits  # lazy: payments imports this module

    try:
        deposits.check_can_delete(task)
    except deposits.PaymentError as exc:
        raise ProjectError(exc.code, exc.message) from None


def _check_applications_open(task: Task) -> None:
    """Deposit hook, inside apply()'s transaction: payments.deposits.check_can_apply refuses a cancelled
    project, an unpublished one (`not_published`) and a task the deposit does not cover (`not_covered`)."""
    from payments import deposits  # lazy: payments imports this module

    try:
        deposits.check_can_apply(task)
    except deposits.PaymentError as exc:
        raise ProjectError(exc.code, exc.message) from None


def _before_deliver(task: Task) -> None:
    """Payment hook: a DB-only delivery is only possible in direct mode."""
    from payments import services as payments  # lazy: payments.services imports this module

    try:
        payments.check_db_deliver(task)
    except payments.PaymentError as exc:
        raise ProjectError("wrong_state", exc.message) from None


def _after_request_changes(task: Task) -> None:
    """Payment hook, inside request_changes()'s transaction: the Escrow row follows the task back
    (`delivered → funded` | `delivered → created`); any other escrow stage refuses the request."""
    from payments import services as payments  # lazy: payments.services imports this module

    try:
        payments.on_changes_requested(task)
    except payments.PaymentError as exc:
        raise ProjectError("wrong_state", exc.message) from None


def mark_paid(task: Task) -> Task:
    """Flip a task to `paid` (idempotent). Closes the project when every task is paid or resolved.
    Called by payments once the on-chain release / direct payment is confirmed."""
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status == Task.Status.PAID:
            return locked
        locked.status = Task.Status.PAID
        locked.paid_at = timezone.now()
        locked.save(update_fields=["status", "paid_at", "updated_at"])
        _close_if_settled(locked.project_id)
        logger.info("task paid task=%s freelancer=%s", locked.pk, locked.assigned_to_id)
        _rescore_company(locked.project.company_id)
    return locked


# --- scoring maintenance ----------------------------------------------------------------------

def rescore(task: Task) -> int:
    """Recompute the score of every PENDING application of `task`. Returns the row count."""
    company_id = task.project.company_id
    cache: dict[int, dict] = {}
    n = 0
    for app in task.applications.filter(status=Application.Status.PENDING):
        history = cache.get(app.freelancer_id)
        if history is None:
            history = cache[app.freelancer_id] = company_history(company_id, app.freelancer_id)
        score = score_application(task, app.freelancer_id, app.tags, history)
        if score != app.score:
            Application.objects.filter(pk=app.pk).update(score=score)
        n += 1
    return n


def _rescore_company(company_id: int) -> None:
    """A Rating / paid task changed the history with this company: refresh its open tasks."""
    for task in Task.objects.filter(project__company_id=company_id, status=Task.Status.OPEN).select_related("project"):
        rescore(task)
