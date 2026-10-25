"""Reputation inclusion tags (`{% load reputation_extras %}`), so the projects and dashboard views
stay unchanged: every figure is computed by reputation.services, templates only read it.

  {% reputation_badges wallet %}        Reliable payer · New account · Verified GitHub
  {% company_rating_badge wallet %}     "Rated by freelancers 4.5/5 · 3 ratings" (when any)
  {% payer_profile_panel wallet %}      #payer-profile: confirmed on-chain payouts + stellar.expert links
  {% rate_company_panel task wallet %}  the assignee rates the company once the task is settled
  {% history_signal wallet %}           "No history" badge for a wallet without a confirmed payout
  {% github_panel wallet %}             #github-verify: the owner's two-step GitHub proof
"""

from django import template
from django.conf import settings
from django.urls import reverse

from projects.models import Project
from reputation import services
from reputation.models import CompanyRating, GithubIdentity

register = template.Library()

PAYER_FIGURES = (
    ("paid_tasks", "Tasks paid on chain"),
    ("partners", "Distinct freelancers paid"),
    ("paid_total", "Total paid"),
    ("avg_delay_days", "Average delay delivery → payment"),
    ("disputes_lost", "Disputes lost"),
    ("deposits_forfeited", "Deposits forfeited"),
)


@register.inclusion_tag("reputation/_badges.html")
def reputation_badges(wallet):
    return {"badges": services.wallet_badges(wallet)}


@register.inclusion_tag("reputation/_company_rating.html")
def company_rating_badge(wallet):
    return {"summary": services.company_rating_summary(wallet) if wallet is not None else {"avg": None, "count": 0}}


@register.inclusion_tag("reputation/_payer_profile.html")
def payer_profile_panel(wallet):
    if wallet is None or not Project.objects.filter(company=wallet).exists():
        return {"show": False}
    profile = services.payer_profile(wallet)
    figures = []
    for key, label in PAYER_FIGURES:
        value = profile[key]
        if isinstance(value, dict):  # disputes_lost / deposits_forfeited: {count, links}
            value = value["count"]
        figures.append({"key": key, "label": label, "value": value, "links": profile["links"][key]})
    return {"show": True, "profile": profile, "figures": figures}


@register.inclusion_tag("reputation/_rate_company.html")
def rate_company_panel(task, wallet=None):
    settled = task.status in services.SETTLED_STATUSES
    rating = CompanyRating.objects.filter(task=task).first()
    is_assignee = wallet is not None and task.assigned_to_id == wallet.pk
    return {
        "task": task,
        "show": settled and (is_assignee or rating is not None),
        "can_rate": settled and is_assignee and rating is None,
        "is_assignee": is_assignee,
        "rating": rating,
        "rate_url": reverse("reputation:rate_company", kwargs={"pk": task.pk}),
    }


@register.inclusion_tag("reputation/_history_signal.html")
def history_signal(wallet):
    return {"show": wallet is not None and not services.has_history(wallet)}


@register.inclusion_tag("reputation/_github_panel.html")
def github_panel(wallet):
    identity = GithubIdentity.objects.filter(wallet=wallet).first() if wallet is not None else None
    return {
        "wallet": wallet,
        "identity": identity,
        "min_age_days": settings.LOWBID_GITHUB_MIN_AGE_DAYS,
        "message_url": reverse("reputation:github_message"),
        "verify_url": reverse("reputation:github_verify"),
        "unlink_url": reverse("reputation:github_unlink"),
    }
