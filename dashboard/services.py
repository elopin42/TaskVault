"""View-models for the dashboard and the public wallet profile.

Pure read helpers over projects (Project / Task / Application / Rating): no HTTP, no writes.
Every function takes a WalletUser and returns plain dicts / lists so the templates stay dumb
and the tests can assert on data rather than on markup.
"""

from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.urls import reverse

from projects.models import Application, Project, Rating, Task

ZERO = Decimal("0")


def _task_url(task: Task, anchor: str = "") -> str:
    return reverse("projects:task_detail", kwargs={"pk": task.pk}) + anchor


def _project_url(project: Project, anchor: str = "") -> str:
    return reverse("projects:project_detail", kwargs={"pk": project.pk}) + anchor


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
        if task.status == Task.Status.DELIVERED:
            who = task.assigned_to.display_name or task.assigned_to.short_address if task.assigned_to else "le freelance"
            items.append(
                {
                    "tone": "act",
                    "kicker": "Livraison déclarée",
                    "headline": f"Valider et noter « {task.title} »",
                    "body": f"{who} a livré : {task.delivery_link}" if task.delivery_link else f"{who} a livré.",
                    "href": _task_url(task, "#validate-panel"),
                    "cta": "Valider + noter",
                    "icon": "fa-star",
                    "when": task.delivered_at or task.updated_at,
                }
            )
        elif task.status == Task.Status.OPEN and task.pending_count:
            items.append(
                {
                    "tone": "act",
                    "kicker": "Candidatures",
                    "headline": f"Choisir un freelance pour « {task.title} »",
                    "body": f"{task.pending_count} candidat{'s' if task.pending_count > 1 else ''}, "
                    f"{task.price:,.2f} USDC — projet « {task.project.title} ».",
                    "href": _task_url(task, "#candidates-panel"),
                    "cta": "Choisir",
                    "icon": "fa-user-check",
                    "when": task.updated_at,
                }
            )
    for project in Project.objects.filter(company=wallet, status=Project.Status.DRAFT).annotate(n=Count("tasks")):
        if project.n == 0:
            items.append(
                {
                    "tone": "wait",
                    "kicker": "Projet vide",
                    "headline": f"Ajouter des tâches à « {project.title} »",
                    "body": "Un projet sans tâche ne reçoit aucune candidature.",
                    "href": _project_url(project, "#task-form-panel"),
                    "cta": "Ajouter",
                    "icon": "fa-plus",
                    "when": project.created_at,
                }
            )

    # Freelance side: tasks to deliver, deliveries awaiting validation, pending applications.
    for task in Task.objects.filter(assigned_to=wallet).select_related("project"):
        if task.status == Task.Status.TAKEN:
            items.append(
                {
                    "tone": "act",
                    "kicker": "Tâche prise",
                    "headline": f"Livrer « {task.title} »",
                    "body": f"{task.price:,.2f} USDC à la validation — projet « {task.project.title} ».",
                    "href": _task_url(task, "#deliver-panel"),
                    "cta": "Livrer",
                    "icon": "fa-truck-fast",
                    "when": task.updated_at,
                }
            )
        elif task.status == Task.Status.DELIVERED:
            items.append(
                {
                    "tone": "wait",
                    "kicker": "Livraison déclarée",
                    "headline": f"« {task.title} » : en attente de validation par l’entreprise",
                    "body": "",
                    "href": _task_url(task),
                    "cta": "Voir",
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
                "kicker": "Candidature envoyée",
                "headline": f"« {app.task.title} » : l’entreprise choisit",
                "body": f"Votre score : {app.score:.1f}/100.",
                "href": _task_url(app.task),
                "cta": "Voir",
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
                "text": f"Candidature sur « {app.task.title} » ({app.task.price:,.2f} USDC)",
                "href": _task_url(app.task),
            }
        )

    for project in Project.objects.filter(company=wallet).order_by("-created_at")[:limit]:
        events.append(
            {
                "when": project.created_at,
                "icon": "fa-diagram-project",
                "tone": "",
                "text": f"Projet créé : « {project.title} »",
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
                    "text": (f"{who} choisi pour « {task.title} »" if mine_as_company else f"Choisi pour « {task.title} »"),
                    "href": _task_url(task),
                }
            )
        if task.delivered_at:
            events.append(
                {
                    "when": task.delivered_at,
                    "icon": "fa-truck-fast",
                    "tone": "",
                    "text": f"Livraison déclarée — « {task.title} »",
                    "href": _task_url(task, "#delivery-panel"),
                }
            )
        if task.paid_at:
            events.append(
                {
                    "when": task.paid_at,
                    "icon": "fa-money-bill-transfer",
                    "tone": "ok",
                    "text": f"{'Paiement envoyé' if mine_as_company else 'Paiement reçu'} — « {task.title} » ({task.price:,.2f} USDC)",
                    "href": _task_url(task),
                }
            )

    for rating in Rating.objects.filter(freelancer=wallet).select_related("task"):
        events.append(
            {
                "when": rating.created_at,
                "icon": "fa-star",
                "tone": "ok",
                "text": f"Note reçue : {rating.note}/5 sur « {rating.task.title} »",
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
