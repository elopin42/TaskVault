"""Trust-network rules: the only place that decides who may follow / recommend whom, and how the
one-hop signals a viewer sees on a wallet are computed.

Signals for a viewer V looking at a target T go through the wallets V follows, ONE hop only:
  strong    someone V follows recommends T   → "Yanis recommends" / "Yanis and 2 others recommend"
  weak      someone V follows follows T      → "Followed by Yanis" / "Followed by Yanis and 1 other"
  following V follows T directly             → "Following"
An anonymous viewer, or T == V, gets no badge at all.

Reads `accounts.models` and `projects.models` only; `projects` never imports this module at module level.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from django.db import transaction
from django.urls import reverse

from accounts.models import WalletUser
from projects.models import Project

from .models import MAX_MESSAGE, Follow, Recommendation

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_MESSAGE",
    "NetworkError",
    "NetworkSignal",
    "follow",
    "unfollow",
    "recommend",
    "unrecommend",
    "signals",
    "network_feed",
    "profile_network",
]


class NetworkError(Exception):
    """A refused action. `code` is stable (JS/tests): "self" | "invalid" | "not_found"; `message` is English UI copy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def wallet_name(wallet: WalletUser) -> str:
    """How a wallet is named in a badge: its display name, else its short address."""
    return wallet.display_name or wallet.short_address


def _check_not_self(viewer: WalletUser, target: WalletUser, verb: str) -> None:
    if viewer.pk == target.pk:
        raise NetworkError("self", f"You cannot {verb} yourself.")


# --- writes ----------------------------------------------------------------------------

def follow(viewer: WalletUser, target: WalletUser) -> Follow:
    """V starts following T. Idempotent: following twice returns the existing row."""
    _check_not_self(viewer, target, "follow")
    row, created = Follow.objects.get_or_create(follower=viewer, followed=target)
    if created:
        logger.info("follow created follower=%s followed=%s", viewer.pk, target.pk)
    return row


def unfollow(viewer: WalletUser, target: WalletUser) -> bool:
    """V stops following T. True when a row was deleted."""
    deleted, _ = Follow.objects.filter(follower=viewer, followed=target).delete()
    if deleted:
        logger.info("follow deleted follower=%s followed=%s", viewer.pk, target.pk)
    return bool(deleted)


def clean_message(message) -> str:
    """Strip and bound the recommendation message; raise NetworkError("invalid") otherwise."""
    if message is None:
        return ""
    if not isinstance(message, str):
        raise NetworkError("invalid", "The message must be text.")
    message = message.strip()
    if len(message) > MAX_MESSAGE:
        raise NetworkError("invalid", f"The message is limited to {MAX_MESSAGE} characters.")
    return message


def recommend(viewer: WalletUser, target: WalletUser, message: str = "") -> Recommendation:
    """V recommends T with an optional message. Recommending again updates the message (upsert)."""
    _check_not_self(viewer, target, "recommend")
    message = clean_message(message)
    with transaction.atomic():
        row, created = Recommendation.objects.update_or_create(
            author=viewer, subject=target, defaults={"message": message}
        )
    logger.info(
        "recommendation %s author=%s subject=%s chars=%s",
        "created" if created else "updated",
        viewer.pk,
        target.pk,
        len(message),
    )
    return row


def unrecommend(viewer: WalletUser, target: WalletUser) -> bool:
    """V withdraws their recommendation of T. True when a row was deleted."""
    deleted, _ = Recommendation.objects.filter(author=viewer, subject=target).delete()
    if deleted:
        logger.info("recommendation deleted author=%s subject=%s", viewer.pk, target.pk)
    return bool(deleted)


# --- signals ---------------------------------------------------------------------------

def _others(names: list[str], verb: str) -> str:
    """'Yanis <verb>' / 'Yanis and 1 other <verb>' / 'Yanis and 2 others <verb>' (verb may be empty)."""
    first = names[0]
    rest = len(names) - 1
    if rest == 0:
        subject = first
    else:
        subject = f"{first} and {rest} other{'s' if rest > 1 else ''}"
    return f"{subject} {verb}".strip()


@dataclass
class NetworkSignal:
    """What a viewer knows about a target through the wallets they follow (one hop)."""

    recommenders: list[WalletUser] = field(default_factory=list)  # strong: V follows them, they recommend T
    followers: list[WalletUser] = field(default_factory=list)  # weak: V follows them, they follow T
    following: bool = False  # V follows T directly

    @property
    def level(self) -> str:
        if self.recommenders:
            return "strong"
        if self.followers:
            return "weak"
        if self.following:
            return "following"
        return ""

    @property
    def recommend_label(self) -> str:
        if not self.recommenders:
            return ""
        names = [wallet_name(w) for w in self.recommenders]
        return _others(names, "recommends" if len(names) == 1 else "recommend")

    @property
    def followed_by_label(self) -> str:
        if not self.followers:
            return ""
        return "Followed by " + _others([wallet_name(w) for w in self.followers], "")

    @property
    def label(self) -> str:
        level = self.level
        if level == "strong":
            return self.recommend_label
        if level == "weak":
            return self.followed_by_label
        if level == "following":
            return "Following"
        return ""

    def as_json(self) -> dict:
        return {
            "level": self.level,
            "label": self.label,
            "recommends": [{"address": w.stellar_address, "name": wallet_name(w)} for w in self.recommenders],
            "followed_by": [{"address": w.stellar_address, "name": wallet_name(w)} for w in self.followers],
            "following": self.following,
        }

    def __bool__(self) -> bool:
        return self.level != ""


def _name_key(wallet: WalletUser) -> tuple[str, str]:
    return (wallet_name(wallet).casefold(), wallet.stellar_address)


def _target_ids(targets: Iterable) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for t in targets:
        pk = int(t.pk if isinstance(t, WalletUser) else t)
        if pk not in seen:
            seen.add(pk)
            ids.append(pk)
    return ids


def signals(viewer: WalletUser | None, targets: Iterable) -> dict[int, NetworkSignal]:
    """{target_pk: NetworkSignal} for EVERY target (an empty signal when there is nothing to show).

    `targets` holds WalletUser rows or pks. Anonymous viewer → {}. T == viewer → empty signal.
    Constant number of queries whatever the number of targets: the viewer's follows (with names),
    then the recommendations and the follows those wallets have on the targets.
    """
    if viewer is None:
        return {}
    ids = _target_ids(targets)
    result = {pk: NetworkSignal() for pk in ids}
    if not ids:
        return result

    followed: dict[int, WalletUser] = {
        row.followed_id: row.followed
        for row in Follow.objects.filter(follower=viewer).select_related("followed")
    }
    if not followed:
        return result

    for pk in ids:
        if pk in followed and pk != viewer.pk:
            result[pk].following = True

    recs = Recommendation.objects.filter(author_id__in=followed, subject_id__in=ids).values_list(
        "author_id", "subject_id"
    )
    for author_id, subject_id in recs:
        if subject_id != viewer.pk:
            result[subject_id].recommenders.append(followed[author_id])

    hops = Follow.objects.filter(follower_id__in=followed, followed_id__in=ids).values_list(
        "follower_id", "followed_id"
    )
    for follower_id, followed_id in hops:
        if followed_id != viewer.pk:
            result[followed_id].followers.append(followed[follower_id])

    for sig in result.values():
        sig.recommenders.sort(key=_name_key)
        sig.followers.sort(key=_name_key)
    return result


# --- feed and profile --------------------------------------------------------------------

def _profile_url(wallet: WalletUser) -> str:
    return reverse("dashboard:profile", kwargs={"address": wallet.stellar_address})


def network_feed(viewer: WalletUser | None, limit: int = 12) -> list[dict]:
    """Recent activity of the wallets V follows (one hop), newest first.

    Items: {"kind": "recommendation"|"follow"|"project", "actor", "target", "project", "message", "when", "href"}.
    """
    if viewer is None or limit <= 0:
        return []
    followed_ids = list(Follow.objects.filter(follower=viewer).values_list("followed_id", flat=True))
    if not followed_ids:
        return []

    items: list[dict] = []
    recs = (
        Recommendation.objects.filter(author_id__in=followed_ids)
        .select_related("author", "subject")
        .order_by("-updated_at", "-pk")[:limit]
    )
    for rec in recs:
        items.append(
            {
                "kind": "recommendation",
                "actor": rec.author,
                "target": rec.subject,
                "project": None,
                "message": rec.message,
                "when": rec.updated_at,
                "href": _profile_url(rec.subject),
            }
        )
    follows = (
        Follow.objects.filter(follower_id__in=followed_ids)
        .select_related("follower", "followed")
        .order_by("-created_at", "-pk")[:limit]
    )
    for row in follows:
        items.append(
            {
                "kind": "follow",
                "actor": row.follower,
                "target": row.followed,
                "project": None,
                "message": "",
                "when": row.created_at,
                "href": _profile_url(row.followed),
            }
        )
    projects = (
        Project.objects.filter(company_id__in=followed_ids).select_related("company").order_by("-created_at", "-pk")[:limit]
    )
    for project in projects:
        items.append(
            {
                "kind": "project",
                "actor": project.company,
                "target": None,
                "project": project,
                "message": project.title,
                "when": project.created_at,
                "href": reverse("projects:project_detail", kwargs={"pk": project.pk}),
            }
        )

    def _when(item: dict) -> datetime:
        return item["when"]

    items.sort(key=_when, reverse=True)
    return items[:limit]


def profile_network(profile: WalletUser, viewer: WalletUser | None) -> dict:
    """Everything the profile page shows about a wallet's network, from the viewer's point of view."""
    recommendations = list(
        Recommendation.objects.filter(subject=profile).select_related("author").order_by("-created_at", "-pk")
    )
    can_act = viewer is not None and viewer.pk != profile.pk
    viewer_follows = False
    viewer_recommendation = None
    signal = None
    if can_act:
        viewer_follows = Follow.objects.filter(follower=viewer, followed=profile).exists()
        viewer_recommendation = next((r for r in recommendations if r.author_id == viewer.pk), None)
        signal = signals(viewer, [profile])[profile.pk]
    return {
        "followers_count": Follow.objects.filter(followed=profile).count(),
        "following_count": Follow.objects.filter(follower=profile).count(),
        "recommendations_count": len(recommendations),
        "recommendations": recommendations,
        "viewer_follows": viewer_follows,
        "viewer_recommendation": viewer_recommendation,
        "known_followers": list(signal.followers) if signal else [],
        "known_recommenders": list(signal.recommenders) if signal else [],
        "signal": signal,
        "can_act": can_act,
    }
