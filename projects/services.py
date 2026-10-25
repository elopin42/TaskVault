"""Business rules of the task board in one place (SPEC §3). Views only translate
ProjectError codes into HTTP; templates never decide a rule.

Payment hooks (wired to the payments app, imported lazily to avoid an import cycle):
  - `mark_paid(task)`       the ONLY function that flips a task to `paid` (idempotent); payments
    calls it once the escrow release / direct payment is confirmed on chain;
  - `_after_validate(task)` called by `validate()` once the Rating is stored → it hands over to
    `payments.services.on_task_validated(task)`, which does NOT pay: the page then chains the
    Freighter signatures (approve → release, or direct_pay);
  - `_before_deliver(task)` a DB-only delivery is refused in escrow mode (the freelance signs the
    milestone change instead; payments calls `deliver(..., on_chain=True)` after that).
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Application, Project, Rating, Task
from .scoring import company_history, score_application

logger = logging.getLogger(__name__)

MAX_TAGS = 3
MAX_TAG_LENGTH = 24
MAX_MESSAGE = 280
MAX_LINK = 500
USDC_PLACES = 7
TITLE_MIN = 3
TITLE_MAX = 120

__all__ = [
    "ProjectError",
    "add_task",
    "apply",
    "choose",
    "clean_link",
    "clean_tags",
    "company_history",
    "create_project",
    "dec_str",
    "delete_task",
    "deliver",
    "mark_paid",
    "parse_note",
    "parse_price",
    "rescore",
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


def clean_link(raw) -> str:
    """The delivery link: required, ≤500 chars, http(s)://. Raises ProjectError('invalid')."""
    link = str(raw or "").strip()
    if not link:
        raise ProjectError("invalid", "Enter the delivery link (PR, demo, repository…).")
    if len(link) > MAX_LINK:
        raise ProjectError("invalid", f"The link is at most {MAX_LINK} characters.")
    if not re.match(r"^https?://", link, re.IGNORECASE):
        raise ProjectError("invalid", "The link must start with http:// or https://.")
    return link


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
    project = Project.objects.create(company=company, title=title, description=description)
    logger.info("project created project=%s company=%s", project.pk, company.pk)
    return project


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
        if locked.status == Project.Status.CLOSED:
            raise ProjectError("wrong_state", "The project is closed: no new tasks.")
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
        fresh = Application.objects.filter(pk=application.pk, task=locked).select_related("freelancer").first()
        if fresh is None:
            raise ProjectError("invalid", "This application does not exist on this task.")
        locked.applications.exclude(pk=fresh.pk).update(status=Application.Status.REJECTED)
        Application.objects.filter(pk=fresh.pk).update(status=Application.Status.CHOSEN)
        locked.status = Task.Status.TAKEN
        locked.assigned_to = fresh.freelancer
        locked.save(update_fields=["status", "assigned_to", "updated_at"])
    logger.info("task taken task=%s application=%s freelancer=%s", locked.pk, fresh.pk, fresh.freelancer_id)
    return locked


def deliver(task: Task, freelancer, delivery_link, *, on_chain: bool = False) -> Task:
    """Only the assignee, only a `taken` task; the link must be http(s), ≤500 chars.
    `on_chain=True` is payments confirming the Trustless Work milestone change; otherwise the
    `_before_deliver` hook refuses a DB-only delivery in escrow mode."""
    link = clean_link(delivery_link)
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
        locked.delivered_at = timezone.now()
        locked.save(update_fields=["status", "delivery_link", "delivered_at", "updated_at"])
    logger.info("task delivered task=%s freelancer=%s", locked.pk, freelancer.pk)
    return locked


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


def _after_validate(task: Task) -> None:
    """Payment hook: the Rating is stored, payments decides what the company signs next
    (approve → release in escrow mode, direct_pay in direct mode). Nothing is paid here."""
    from payments import services as payments  # lazy: payments.services imports this module

    payments.on_task_validated(task)


def _before_deliver(task: Task) -> None:
    """Payment hook: a DB-only delivery is only possible in direct mode."""
    from payments import services as payments  # lazy: payments.services imports this module

    try:
        payments.check_db_deliver(task)
    except payments.PaymentError as exc:
        raise ProjectError("wrong_state", exc.message) from None


def mark_paid(task: Task) -> Task:
    """Flip a task to `paid` (idempotent). Closes the project when every task is paid.
    Called by payments once the on-chain release / direct payment is confirmed."""
    with transaction.atomic():
        locked = _locked_task(task)
        if locked.status == Task.Status.PAID:
            return locked
        locked.status = Task.Status.PAID
        locked.paid_at = timezone.now()
        locked.save(update_fields=["status", "paid_at", "updated_at"])
        project = Project.objects.select_for_update().get(pk=locked.project_id)
        if not project.tasks.exclude(status=Task.Status.PAID).exists():
            project.status = Project.Status.CLOSED
            project.save(update_fields=["status", "updated_at"])
            logger.info("project closed project=%s", project.pk)
        logger.info("task paid task=%s freelancer=%s", locked.pk, locked.assigned_to_id)
        _rescore_company(project.company_id)
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
