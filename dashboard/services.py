"""View-models for the dashboard and the public wallet profile.

Read helpers over projects (Project / Task / Application / Rating), no HTTP. The one write is
`set_display_name` (the profile owner renaming their wallet). Every read function takes a WalletUser and returns plain dicts / lists so the templates stay dumb
and the tests can assert on data rather than on markup.
"""

from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from payments import services as payments
from payments.stellar import asset_code
from projects import services as projects
from projects.models import Application, Project, Rating, Task

ZERO = Decimal("0")
MAX_DISPLAY_NAME = 80

# Payment steps → to-do copy for the wallet that must sign them (company side) and for the
# freelance waiting on them. Mirrors payments.services.FLOW; the "validate" step is projects'.
COMPANY_PAY_STEPS = {
    "deploy": ("Funding", 'Fund "{title}"', "Create the task's escrow, then lock {amount} {code} (two signatures).", "Fund", "fa-lock", "#funding-panel"),
    "fund": ("Funding", 'Lock the funds for "{title}"', "Escrow created: {amount} {code} still to lock in it.", "Lock", "fa-lock", "#funding-panel"),
    "approve": ("Payment", 'Release the funds for "{title}"', "Rating saved: sign the validation, then the release of the {amount} {code}.", "Release", "fa-money-bill-transfer", "#paiement"),
    "release": ("Payment", 'Release the funds for "{title}"', "Delivery validated on-chain: sign the release of the {amount} {code}.", "Release", "fa-money-bill-transfer", "#paiement"),
    "direct_pay": ("Payment", 'Pay "{title}"', "Rating saved: sign the payment of {amount} {code} in Freighter.", "Pay", "fa-money-bill-transfer", "#paiement"),
}
FREELANCE_WAIT_STEPS = {
    "deploy": ("Funding awaited", '"{title}": waiting for the company to fund it', "You can declare the delivery once the {amount} {code} are locked in escrow."),
    "fund": ("Funding awaited", '"{title}": waiting for the company to fund it', "Escrow created, funds not locked yet."),
    "validate": ("Delivery declared", '"{title}": waiting for the company to validate it', "{deadline}"),
    "approve": ("Payment in progress", '"{title}": validated, funds release pending', "The company is signing the release of your {amount} {code}."),
    "release": ("Payment in progress", '"{title}": validated, funds release pending', "The company is signing the release of your {amount} {code}."),
    "direct_pay": ("Payment in progress", '"{title}": validated, payment pending', "The company is signing the payment of your {amount} {code}."),
}


def _fmt(text: str, task: Task) -> str:
    return text.format(title=task.title, amount=f"{task.price:,.2f}", code=asset_code(), deadline=_deadline_note(task))


def _task_url(task: Task, anchor: str = "") -> str:
    return reverse("projects:task_detail", kwargs={"pk": task.pk}) + anchor


def _project_url(project: Project, anchor: str = "") -> str:
    return reverse("projects:project_detail", kwargs={"pk": project.pk}) + anchor


def _deadline_note(task: Task) -> str:
    """"Review until Oct 31, 14:05" (or "Review window over") for the company's validate to-do; "" when
    the task is not delivered. The deadline is projects.services.review_deadline, computed at read time."""
    deadline = projects.review_deadline(task)
    if deadline is None:
        return ""
    if projects.is_review_overdue(task):
        return "Review window over."
    return f"Review until {date_format(timezone.localtime(deadline), 'M j, H:i')}."


def _avg_note(wallet):
    agg = Rating.objects.filter(freelancer=wallet).aggregate(avg=Avg("note"), n=Count("pk"))
    return (round(agg["avg"], 1) if agg["n"] else None), agg["n"]


# --- to-do ------------------------------------------------------------------------

def todo_items(wallet) -> list[dict]:
    """What this wallet should look at, `act` items first (then by date desc).

    Each item: {tone: act|wait, kicker, headline, body, href, cta, icon, when}.
    """
    items: list[dict] = []

    # Company side: deliveries to validate, candidates to choose, empty drafts.
    company_tasks = (
        Task.objects.filter(project__company=wallet)
        .select_related("project", "assigned_to")
        .annotate(pending_count=Count("applications", filter=Q(applications__status=Application.Status.PENDING)))
    )
    for task in company_tasks:
        if task.status in (Task.Status.TAKEN, Task.Status.DELIVERED):
            action = payments.next_action(task, wallet)
            if action and action["mine"] and action["step"] == "validate":
                who = task.assigned_to.display_name or task.assigned_to.short_address if task.assigned_to else "the freelancer"
                delivered = f"{who} delivered: {task.delivery_link}" if task.delivery_link else f"{who} delivered."
                if task.revision_count:
                    delivered = f"{who} delivered again (revision {task.revision_count}): {task.delivery_link}"
                items.append(
                    {
                        "tone": "act",
                        "kicker": "Delivery declared",
                        "headline": f'Validate and rate "{task.title}"',
                        "body": " ".join(part for part in (delivered, _deadline_note(task)) if part),
                        "href": _task_url(task, "#validate-panel"),
                        "cta": "Validate + rate",
                        "icon": "fa-star",
                        "when": task.delivered_at or task.updated_at,
                    }
                )
            elif action and action["mine"] and action["step"] in COMPANY_PAY_STEPS:
                kicker, headline, body, cta, icon, anchor = COMPANY_PAY_STEPS[action["step"]]
                href = _project_url(task.project, anchor) if anchor == "#funding-panel" else _task_url(task, anchor)
                items.append(
                    {
                        "tone": "act",
                        "kicker": kicker,
                        "headline": _fmt(headline, task),
                        "body": _fmt(body, task),
                        "href": href,
                        "cta": cta,
                        "icon": icon,
                        "when": task.updated_at,
                    }
                )
        elif task.status == Task.Status.OPEN and task.pending_count:
            items.append(
                {
                    "tone": "act",
                    "kicker": "Applications",
                    "headline": f'Choose a freelancer for "{task.title}"',
                    "body": f"{task.pending_count} candidate{'s' if task.pending_count > 1 else ''}, "
                    f'{task.price:,.2f} {asset_code()} — project "{task.project.title}".',
                    "href": _task_url(task, "#candidates-panel"),
                    "cta": "Choose",
                    "icon": "fa-user-check",
                    "when": task.updated_at,
                }
            )
    for project in Project.objects.filter(company=wallet, status=Project.Status.DRAFT).annotate(n=Count("tasks")):
        if project.n == 0:
            items.append(
                {
                    "tone": "wait",
                    "kicker": "Empty project",
                    "headline": f'Add tasks to "{project.title}"',
                    "body": "A project without tasks gets no applications.",
                    "href": _project_url(project, "#task-form-panel"),
                    "cta": "Add",
                    "icon": "fa-plus",
                    "when": project.created_at,
                }
            )

    # Freelance side: tasks to deliver, funding / validation / payment awaited, pending applications.
    for task in Task.objects.filter(assigned_to=wallet).select_related("project__company"):
        if task.status not in (Task.Status.TAKEN, Task.Status.DELIVERED):
            continue
        action = payments.next_action(task, wallet)
        if action and action["mine"] and action["step"] == "deliver" and task.revision_count:
            latest = task.revision_requests.first()
            items.append(
                {
                    "tone": "act",
                    "kicker": "Changes requested",
                    "headline": f'Changes requested on "{task.title}" ({task.revision_count}/{projects.max_revisions()})',
                    "body": f'"{latest.message}"' if latest and latest.message else "The company sent the delivery back: deliver again.",
                    "href": _task_url(task, "#deliver-panel"),
                    "cta": "Deliver again",
                    "icon": "fa-rotate-left",
                    "when": latest.created_at if latest else task.updated_at,
                }
            )
        elif action and action["mine"] and action["step"] == "deliver":
            items.append(
                {
                    "tone": "act",
                    "kicker": "Task taken",
                    "headline": f'Deliver "{task.title}"',
                    "body": f'{task.price:,.2f} {asset_code()} on validation — project "{task.project.title}".',
                    "href": _task_url(task, "#deliver-panel"),
                    "cta": "Deliver",
                    "icon": "fa-truck-fast",
                    "when": task.updated_at,
                }
            )
        elif action and action["step"] in FREELANCE_WAIT_STEPS:
            kicker, headline, body = FREELANCE_WAIT_STEPS[action["step"]]
            items.append(
                {
                    "tone": "wait",
                    "kicker": kicker,
                    "headline": _fmt(headline, task),
                    "body": _fmt(body, task),
                    "href": _task_url(task, "#paiement"),
                    "cta": "View",
                    "icon": "fa-hourglass-half",
                    "when": task.delivered_at or task.updated_at,
                }
            )
    pending_apps = (
        Application.objects.filter(freelancer=wallet, status=Application.Status.PENDING, task__status=Task.Status.OPEN)
        .select_related("task", "task__project")
        .order_by("-created_at")
    )
    for app in pending_apps:
        items.append(
            {
                "tone": "wait",
                "kicker": "Application sent",
                "headline": f'"{app.task.title}": the company is choosing',
                "body": f"Your score: {app.score:.1f}/100.",
                "href": _task_url(app.task),
                "cta": "View",
                "icon": "fa-paper-plane",
                "when": app.created_at,
            }
        )

    items.sort(key=lambda it: (0 if it["tone"] == "act" else 1, -(it["when"].timestamp() if it["when"] else 0)))
    return items


# --- stats ------------------------------------------------------------------------

def company_stats(wallet) -> dict:
    projects = list(Project.objects.filter(company=wallet).with_totals())
    tasks = Task.objects.filter(project__company=wallet)
    agg = tasks.aggregate(
        total=Count("pk"),
        open=Count("pk", filter=Q(status=Task.Status.OPEN)),
        taken=Count("pk", filter=Q(status=Task.Status.TAKEN)),
        delivered=Count("pk", filter=Q(status=Task.Status.DELIVERED)),
        paid=Count("pk", filter=Q(status=Task.Status.PAID)),
        paid_usdc=Sum("price", filter=Q(status=Task.Status.PAID)),
    )
    to_choose = (
        tasks.filter(status=Task.Status.OPEN, applications__status=Application.Status.PENDING).distinct().count()
    )
    return {
        "projects": len(projects),
        "draft": sum(1 for p in projects if p.status == Project.Status.DRAFT),
        "funded": sum(1 for p in projects if p.status == Project.Status.FUNDED),
        "closed": sum(1 for p in projects if p.status == Project.Status.CLOSED),
        "tasks": agg["total"],
        "open": agg["open"],
        "to_choose": to_choose,
        "in_progress": agg["taken"],
        "to_validate": agg["delivered"],
        "paid": agg["paid"],
        "committed_usdc": sum((p.total_amount for p in projects), ZERO),
        "paid_usdc": agg["paid_usdc"] or ZERO,
        "applications_received": Application.objects.filter(task__project__company=wallet).count(),
    }


def freelancer_stats(wallet) -> dict:
    apps = Application.objects.filter(freelancer=wallet).aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=Application.Status.PENDING)),
        chosen=Count("pk", filter=Q(status=Application.Status.CHOSEN)),
        rejected=Count("pk", filter=Q(status=Application.Status.REJECTED)),
    )
    tasks = Task.objects.filter(assigned_to=wallet).aggregate(
        taken=Count("pk", filter=Q(status=Task.Status.TAKEN)),
        delivered=Count("pk", filter=Q(status=Task.Status.DELIVERED)),
        paid=Count("pk", filter=Q(status=Task.Status.PAID)),
        earned=Sum("price", filter=Q(status=Task.Status.PAID)),
    )
    avg_note, ratings = _avg_note(wallet)
    decided = apps["chosen"] + apps["rejected"]
    return {
        "total": apps["total"],
        "pending": apps["pending"],
        "chosen": apps["chosen"],
        "rejected": apps["rejected"],
        "in_progress": tasks["taken"],
        "delivered": tasks["delivered"],
        "paid": tasks["paid"],
        "earned_usdc": tasks["earned"] or ZERO,
        "avg_note": avg_note,
        "ratings": ratings,
        "success_rate": int(round(100 * apps["chosen"] / decided)) if decided else None,
    }


# --- activity ---------------------------------------------------------------------

def recent_activity(wallet, limit: int = 12) -> list[dict]:
    """Merged, newest-first timeline: my applications, my projects, my tasks (chosen / delivered / paid), ratings."""
    events: list[dict] = []

    for app in Application.objects.filter(freelancer=wallet).select_related("task").order_by("-created_at")[:limit]:
        events.append(
            {
                "when": app.created_at,
                "icon": "fa-paper-plane",
                "tone": "brand",
                "text": f'Application for "{app.task.title}" ({app.task.price:,.2f} {asset_code()})',
                "href": _task_url(app.task),
            }
        )

    for project in Project.objects.filter(company=wallet).order_by("-created_at")[:limit]:
        events.append(
            {
                "when": project.created_at,
                "icon": "fa-diagram-project",
                "tone": "",
                "text": f'Project created: "{project.title}"',
                "href": _project_url(project),
            }
        )

    tasks = Task.objects.filter(Q(project__company=wallet) | Q(assigned_to=wallet)).select_related("project", "assigned_to")
    for task in tasks:
        mine_as_company = task.project.company_id == wallet.pk
        if task.assigned_to_id and task.status != Task.Status.OPEN:
            who = task.assigned_to.display_name or task.assigned_to.short_address
            events.append(
                {
                    "when": task.updated_at if task.status == Task.Status.TAKEN else (task.delivered_at or task.updated_at),
                    "icon": "fa-user-check",
                    "tone": "brand",
                    "text": (f'{who} chosen for "{task.title}"' if mine_as_company else f'Chosen for "{task.title}"'),
                    "href": _task_url(task),
                }
            )
        if task.delivered_at:
            events.append(
                {
                    "when": task.delivered_at,
                    "icon": "fa-truck-fast",
                    "tone": "",
                    "text": f'Delivery declared — "{task.title}"',
                    "href": _task_url(task, "#delivery-panel"),
                }
            )
        if task.paid_at:
            events.append(
                {
                    "when": task.paid_at,
                    "icon": "fa-money-bill-transfer",
                    "tone": "ok",
                    "text": f"{'Payment sent' if mine_as_company else 'Payment received'} — \"{task.title}\" ({task.price:,.2f} {asset_code()})",
                    "href": _task_url(task),
                }
            )

    for rating in Rating.objects.filter(freelancer=wallet).select_related("task"):
        events.append(
            {
                "when": rating.created_at,
                "icon": "fa-star",
                "tone": "ok",
                "text": f'Rating received: {rating.note}/5 for "{rating.task.title}"',
                "href": _task_url(rating.task),
            }
        )

    events.sort(key=lambda e: e["when"], reverse=True)
    return events[:limit]


# --- public profile ---------------------------------------------------------------

def profile_stats(wallet) -> dict:
    projects = Project.objects.filter(company=wallet).with_totals().select_related("company").prefetch_related("tasks")
    assigned = Task.objects.filter(assigned_to=wallet)
    counts = assigned.aggregate(
        won=Count("pk"),
        paid=Count("pk", filter=Q(status=Task.Status.PAID)),
        earned=Sum("price", filter=Q(status=Task.Status.PAID)),
    )
    avg_note, ratings = _avg_note(wallet)
    latest_projects = list(projects.order_by("-created_at")[:6])
    for p in latest_projects:
        seen: list[str] = []
        for task in p.tasks.all():
            seen.extend(t for t in (task.tags or []) if t not in seen)
        p.tag_list = seen
    return {
        "projects_posted": projects.count(),
        "tasks_paid_as_company": Task.objects.filter(project__company=wallet, status=Task.Status.PAID).count(),
        "applications": Application.objects.filter(freelancer=wallet).count(),
        "tasks_won": counts["won"],
        "tasks_paid": counts["paid"],
        "earned_usdc": counts["earned"] or ZERO,
        "avg_note": avg_note,
        "ratings_count": ratings,
        "member_since": wallet.created_at,
        "last_login": wallet.last_login_at,
        "projects": latest_projects,
        "tasks": list(assigned.select_related("project", "project__company").order_by("-updated_at")[:10]),
        "ratings": list(
            Rating.objects.filter(freelancer=wallet).select_related("task", "company").order_by("-created_at")[:10]
        ),
    }


def set_display_name(wallet, viewer, raw_name) -> str | None:
    """The owner renames their wallet (trimmed, ≤ MAX_DISPLAY_NAME, empty clears it).
    Returns the stored name, or None when the viewer is not the owner."""
    if viewer is None or viewer.pk != wallet.pk:
        return None
    name = (raw_name or "").strip()[:MAX_DISPLAY_NAME]
    wallet.display_name = name
    wallet.save(update_fields=["display_name"])
    return name
