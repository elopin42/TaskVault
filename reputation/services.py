"""Reputation rules in one place (views only map ReputationError codes to HTTP).

Three signals, all computed on read and never fed into `projects.scoring` (the « Validated » /
« Recommended » hints stay exactly what they were):

1. Company ratings — the assignee of a settled task (`SETTLED_STATUSES`) rates the company 1–5,
   once per task (`rate_company`, `company_rating_summary`).
2. Payer profile — the « Reliable payer » view-model (`payer_profile`) is built ONLY from
   `payments.Escrow` rows whose payout is confirmed on chain (`_confirmed_escrows`): a release hash
   (escrow mode), or a payment hash on an escrow row in status `paid` (direct mode; a pending hash
   kept after a Horizon timeout does not count). Every figure carries the stellar.expert links of the
   transactions behind it, so anybody can check the number.
3. GitHub-verified wallet — `verify_github` binds a wallet to a GitHub account through a public gist
   signed with Freighter (format below). Badges (`wallet_badges`) and the « No history » signal
   (`has_history`) are pure reads, no network.

Gist format (the profile page fills it for the owner; any file name, the content of every file of
the gist is read, blank lines and surrounding spaces ignored):

    lowbid:<the wallet's G… address>
    signature: <base64 signature returned by Freighter signMessage for line 1>

Line 1 must be exactly `github_message(wallet)`; the signature is checked with
`accounts.signing.verify_signature` (SEP-53, raw or sha256 scheme, the one the login accepts).
"""

import logging
import re
from datetime import timedelta
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.signing import decode_signature, verify_signature
from payments import stellar
from payments.models import Escrow
from projects.models import Project, Task
from projects.services import ProjectError, parse_note

from .models import CompanyRating, GithubIdentity

logger = logging.getLogger(__name__)

# Strings on purpose: `resolved` (a dispute settled on chain) arrives with a later merge.
SETTLED_STATUSES = ("paid", "resolved")
MAX_COMMENT = 280
GITHUB_API = "https://api.github.com"
GITHUB_TIMEOUT = 10
GIST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
GIST_URL_RE = re.compile(r"^https://gist\.github\.com/[A-Za-z0-9-]{1,39}/([0-9a-f]{32})/?$")
MESSAGE_PREFIX = "lowbid:"
SIGNATURE_PREFIX = "signature:"
ZERO = Decimal("0")
TENTH = Decimal("0.1")

__all__ = [
    "SETTLED_STATUSES",
    "ReputationError",
    "company_rating_summary",
    "github_message",
    "has_history",
    "parse_gist_ref",
    "payer_profile",
    "rate_company",
    "unlink_github",
    "verify_github",
    "wallet_badges",
]


class ReputationError(Exception):
    """A refused action. `code` is stable (JS/tests), `message` is English UI copy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _one_decimal(value) -> Decimal:
    return Decimal(value).quantize(TENTH, rounding=ROUND_HALF_UP)


# --- 1. company ratings ---------------------------------------------------------------------

def rate_company(task: Task, freelancer, note, comment: str = "") -> CompanyRating:
    """Only the task's assignee, only a settled task (paid / resolved), once per task."""
    if freelancer is None or task.assigned_to_id != freelancer.pk:
        raise ReputationError("forbidden", "Only the freelancer who did this task can rate the company.")
    try:
        note = parse_note(note)
    except ProjectError as exc:
        raise ReputationError("invalid", exc.message) from None
    comment = str(comment or "").strip()[:MAX_COMMENT]
    with transaction.atomic():
        locked = Task.objects.select_for_update().select_related("project").get(pk=task.pk)
        if locked.assigned_to_id != freelancer.pk:
            raise ReputationError("forbidden", "Only the freelancer who did this task can rate the company.")
        if locked.status not in SETTLED_STATUSES:
            raise ReputationError("wrong_state", "You can rate the company once the task is paid.")
        if CompanyRating.objects.filter(task=locked).exists():
            raise ReputationError("duplicate", "You have already rated the company for this task.")
        try:
            with transaction.atomic():
                rating = CompanyRating.objects.create(
                    task=locked, freelancer=freelancer, company_id=locked.project.company_id, note=note, comment=comment
                )
        except IntegrityError:
            raise ReputationError("duplicate", "You have already rated the company for this task.") from None
    logger.info("company rated task=%s note=%s company=%s", locked.pk, note, locked.project.company_id)
    return rating


def company_rating_summary(wallet) -> dict:
    """{avg: Decimal with 1 decimal or None, count} of the ratings freelances gave this company."""
    agg = CompanyRating.objects.filter(company=wallet).aggregate(avg=Avg("note"), count=Count("pk"))
    avg = agg["avg"]
    return {"avg": _one_decimal(avg) if avg is not None else None, "count": agg["count"] or 0}


# --- 2. payer profile (confirmed on-chain payouts only) ------------------------------------

_CONFIRMED = Q(release_tx_hash__gt="") | Q(payment_tx_hash__gt="", status=Escrow.Status.PAID)


def _confirmed_escrows():
    """Escrow rows whose payout is confirmed on chain (see the module docstring)."""
    return Escrow.objects.filter(_CONFIRMED)


def _payout_hash(escrow: Escrow) -> str:
    return escrow.release_tx_hash or escrow.payment_tx_hash


def _link(escrow: Escrow) -> dict:
    tx = _payout_hash(escrow)
    return {"label": f"task #{escrow.task_id}", "url": stellar.explorer_tx_url(tx), "tx": tx, "task_id": escrow.task_id}


def _disputes_lost(wallet) -> dict:
    """Disputes resolved against this company, with their on-chain resolution links."""
    # merge hook (step 3): will read Escrow.resolve_tx_hash on tasks resolved against the company.
    return {"count": 0, "links": []}


def _deposits_forfeited(wallet) -> dict:
    """Project deposits this company forfeited, with their on-chain links."""
    # merge hook (step 4): will read payments.ProjectDeposit rows in status `forfeited`.
    return {"count": 0, "links": []}


def payer_profile(wallet) -> dict:
    """The « Reliable payer » view-model of a company wallet. Every figure comes with `links`
    (stellar.expert tx URLs labelled "task #pk") so it can be checked on chain.

    reliable_payer = partners ≥ LOWBID_RELIABLE_PAYER_MIN_PARTNERS, no dispute lost, no deposit
    forfeited. avg_delay_days (release − delivery) is informational only."""
    escrows = list(
        _confirmed_escrows()
        .filter(task__project__company=wallet)
        .select_related("task")
        .order_by("released_at", "pk")
    )
    paid_links = [_link(e) for e in escrows]
    paid_total = sum((e.amount for e in escrows), ZERO)

    partners: dict[int, dict] = {}
    for e in escrows:
        if e.task.assigned_to_id is not None:
            partners[e.task.assigned_to_id] = _link(e)  # the latest payout to each partner

    delays = []
    delay_links = []
    for e in escrows:
        if e.released_at and e.task.delivered_at:
            delays.append((e.released_at - e.task.delivered_at).total_seconds() / 86400)
            delay_links.append(_link(e))
    avg_delay = _one_decimal(Decimal(str(sum(delays) / len(delays)))) if delays else None
    if avg_delay is not None and avg_delay < 0:
        avg_delay = ZERO

    disputes = _disputes_lost(wallet)
    deposits = _deposits_forfeited(wallet)
    minimum = int(getattr(settings, "LOWBID_RELIABLE_PAYER_MIN_PARTNERS", 3))
    profile = {
        "paid_tasks": len(escrows),
        "partners": len(partners),
        "paid_total": paid_total,
        "avg_delay_days": avg_delay,
        "disputes_lost": disputes,
        "deposits_forfeited": deposits,
        "min_partners": minimum,
        "links": {
            "paid_tasks": paid_links,
            "partners": list(partners.values()),
            "paid_total": paid_links,
            "avg_delay_days": delay_links,
            "disputes_lost": disputes["links"],
            "deposits_forfeited": deposits["links"],
        },
    }
    profile["reliable_payer"] = len(partners) >= minimum and disputes["count"] == 0 and deposits["count"] == 0
    return profile


def has_history(wallet) -> bool:
    """Any confirmed on-chain payout where this wallet paid (company) or was paid (freelance)."""
    if wallet is None:
        return False
    return _confirmed_escrows().filter(Q(task__project__company=wallet) | Q(task__assigned_to=wallet)).exists()


def wallet_badges(wallet) -> list[dict]:
    """[{key, label, tone, title, href?}] — pure read, no network."""
    badges: list[dict] = []
    if wallet is None:
        return badges
    if Project.objects.filter(company=wallet).exists() and payer_profile(wallet)["reliable_payer"]:
        badges.append(
            {
                "key": "reliable-payer",
                "label": "Reliable payer",
                "tone": "ok",
                "title": "Paid enough different freelancers on chain, no dispute lost, no deposit forfeited",
            }
        )
    if not has_history(wallet):
        badges.append(
            {
                "key": "new-account",
                "label": "New account",
                "tone": "neutral",
                "title": "No task paid with a confirmed Stellar transaction yet, as company or as freelancer",
            }
        )
    identity = GithubIdentity.objects.filter(wallet=wallet).first()
    if identity is not None:
        badges.append(
            {
                "key": "github-verified",
                "label": "Verified GitHub",
                "tone": "info",
                "title": f"Controls the GitHub account {identity.github_login} (signed gist)",
                "href": identity.profile_url,
            }
        )
    return badges


# --- 3. GitHub-verified wallet ------------------------------------------------------------

def github_message(wallet) -> str:
    return f"{MESSAGE_PREFIX}{wallet.stellar_address}"


def parse_gist_ref(raw) -> str:
    """A gist URL (https://gist.github.com/<login>/<32 hex>) or a bare 32-hex id → the id."""
    ref = str(raw or "").strip()
    match = GIST_URL_RE.match(ref)
    if match:
        return match.group(1)
    if GIST_ID_RE.match(ref):
        return ref
    raise ReputationError("invalid", "Paste the gist URL (https://gist.github.com/<login>/<id>) or its 32-character id.")


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = getattr(settings, "LOWBID_GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(path: str) -> tuple[int, dict | None]:
    """GET api.github.com<path> → (status, JSON dict or None). Network / JSON failures → `provider`."""
    try:
        resp = requests.get(f"{GITHUB_API}{path}", headers=_github_headers(), timeout=GITHUB_TIMEOUT)
    except Exception:
        logger.exception("github request failed path=%s", path)
        raise ReputationError("provider", "GitHub could not be reached. Try again in a minute.") from None
    if resp.status_code == 404:
        return 404, None
    if resp.status_code != 200:
        logger.warning("github request refused path=%s status=%s", path, resp.status_code)
        raise ReputationError("provider", f"GitHub answered HTTP {resp.status_code}. Try again in a minute.")
    try:
        data = resp.json()
    except Exception:
        logger.exception("github answer is not JSON path=%s", path)
        raise ReputationError("provider", "GitHub sent an unreadable answer. Try again in a minute.") from None
    if not isinstance(data, dict):
        logger.warning("github answer is not an object path=%s", path)
        raise ReputationError("provider", "GitHub sent an unreadable answer. Try again in a minute.")
    return 200, data


def _read_proof(gist: dict) -> tuple[str, str]:
    """(message line, signature) found in the gist files; empty strings when missing."""
    files = gist.get("files") or {}
    content = "\n".join(str((f or {}).get("content") or "") for f in files.values() if isinstance(f, dict))
    message = signature = ""
    for line in content.splitlines():
        line = line.strip()
        if not message and line.startswith(MESSAGE_PREFIX):
            message = line
        elif not signature and line.lower().startswith(SIGNATURE_PREFIX):
            signature = line[len(SIGNATURE_PREFIX):].strip()
    return message, signature


def verify_github(wallet, gist_ref) -> GithubIdentity:
    """Bind `wallet` to the GitHub account owning a public gist signed with Freighter (format in
    the module docstring). Codes: invalid · duplicate · not_found · not_public · bad_signature ·
    already_used · too_recent · provider."""
    gist_id = parse_gist_ref(gist_ref)
    if GithubIdentity.objects.filter(wallet=wallet).exists():
        raise ReputationError("duplicate", "This wallet is already linked to a GitHub account. Unlink it first.")

    status, gist = _github_get(f"/gists/{gist_id}")
    if status == 404 or gist is None:
        raise ReputationError("not_found", "No gist with this id on GitHub.")
    if not gist.get("public"):
        raise ReputationError("not_public", "The gist is secret: create it as a public gist.")
    owner = gist.get("owner") or {}
    login = str(owner.get("login") or "")
    try:
        github_id = int(owner.get("id"))
    except (TypeError, ValueError):
        github_id = 0
    if not login or github_id <= 0:
        raise ReputationError("not_found", "This gist has no GitHub owner.")

    message, raw_signature = _read_proof(gist)
    expected = github_message(wallet)
    if message != expected:
        raise ReputationError("bad_signature", f"The gist must start with the line {expected}")
    signature = decode_signature(raw_signature)
    scheme = verify_signature(wallet.stellar_address, expected, signature) if signature else None
    if scheme is None:
        logger.warning("github proof rejected wallet=%s gist=%s reason=bad_signature", wallet.pk, gist_id)
        raise ReputationError("bad_signature", "The signature in the gist does not match this wallet.")

    if GithubIdentity.objects.filter(github_id=github_id).exclude(wallet=wallet).exists():
        raise ReputationError("already_used", "This GitHub account is already linked to another wallet.")

    status, user = _github_get(f"/users/{login}")
    if status == 404 or user is None:
        raise ReputationError("not_found", "The gist owner's GitHub account was not found.")
    created = parse_datetime(str(user.get("created_at") or ""))
    if created is None:
        logger.warning("github user without created_at login=%s", login)
        raise ReputationError("provider", "GitHub did not say when this account was created.")
    if timezone.is_naive(created):
        created = timezone.make_aware(created, dt_timezone.utc)
    min_days = int(getattr(settings, "LOWBID_GITHUB_MIN_AGE_DAYS", 365))
    if timezone.now() - created < timedelta(days=min_days):
        raise ReputationError("too_recent", f"The GitHub account must be at least {min_days} days old.")

    try:
        with transaction.atomic():
            identity = GithubIdentity.objects.create(
                wallet=wallet,
                github_id=github_id,
                github_login=login[:39],
                gist_id=gist_id,
                account_created_at=created,
                scheme=scheme,
            )
    except IntegrityError:
        if GithubIdentity.objects.filter(wallet=wallet).exists():
            raise ReputationError("duplicate", "This wallet is already linked to a GitHub account.") from None
        raise ReputationError("already_used", "This GitHub account is already linked to another wallet.") from None
    logger.info("github verified wallet=%s login=%s github_id=%s scheme=%s", wallet.pk, login, github_id, scheme)
    return identity


def unlink_github(wallet) -> None:
    """The owner removes their GitHub link (`not_found` when there is none)."""
    deleted, _ = GithubIdentity.objects.filter(wallet=wallet).delete()
    if not deleted:
        raise ReputationError("not_found", "This wallet is not linked to a GitHub account.")
    logger.info("github unlinked wallet=%s", wallet.pk)
