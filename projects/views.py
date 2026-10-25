"""Task-board pages (server-rendered) + the JSON endpoints the pages call through `Lowbid.api`.
Rules live in services.py; this module only maps ProjectError codes to HTTP.
"""

import json
import logging
from collections import Counter
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import wallet_required
from accounts.identity import get_wallet
from network import services as network
from payments import services as payments
from payments import stellar
from payments.views import next_json

from . import services
from .forms import ProjectForm
from .models import Application, Dispute, Project, Task
from .scoring import company_history, is_validated, recommended_pk, score_parts
from .services import ProjectError, dec_str

logger = logging.getLogger(__name__)

LIST_TABS = (("active", "In progress"), ("closed", "Closed"), ("all", "All"))
# ?sort= on the list page → (label, ordering over with_totals() annotations).
LIST_SORTS = (
    ("newest", "Newest", ("-created_at",)),
    ("budget", "Highest budget", ("-total", "-created_at")),
    ("open", "Most open tasks", ("-open_total", "-created_at")),
)
LIST_PAGE_SIZE = 24
POPULAR_TAGS = 8
MY_TABS = (("active", "In progress"), ("done", "Closed"), ("all", "All"))
BOARD_COLUMNS = (
    ("open", "Open", "Every open task, available to take."),
    ("taken", "Taken", "Your tasks in progress: deliver a link."),
    ("delivered", "Delivered", "Waiting for the company to validate — or for the arbiter, once disputed."),
    ("paid", "Paid", "Validated and paid, or settled by the arbiter."),
)
# The kanban keeps its four columns (the mobile snap-scroll and the e2e contract rely on them): a disputed task
# still sits in "Delivered" (the money is locked, a decision is pending), a resolved one in "Paid" (settled).
# Each carries its own status badge (_board_card.html), so the column never hides the state.
BOARD_COLUMN_OF = {
    Task.Status.OPEN: "open",
    Task.Status.TAKEN: "taken",
    Task.Status.DELIVERED: "delivered",
    Task.Status.DISPUTED: "delivered",
    Task.Status.PAID: "paid",
    Task.Status.RESOLVED: "paid",
}
# HTTP status for a refused action, by error code (anything else → 400).
ERROR_STATUS = {
    "forbidden": 403,
    "own_task": 403,
    "not_assigned": 403,
    "wrong_state": 409,
    "duplicate": 409,
    "too_many_revisions": 409,
    "not_published": 409,
    "not_covered": 409,
    "invalid": 400,
    "bad_tags": 400,
}


# --- helpers ----------------------------------------------------------------------

def _json_body(request: HttpRequest) -> dict:
    """JSON body from Lowbid.api, or a classic form POST (both are accepted)."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST.dict()


def _error_response(err: ProjectError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=ERROR_STATUS.get(err.code, 400))


def _tasks_with_counts(project: Project):
    return (
        project.tasks.select_related("assigned_to")
        .annotate(
            app_count=Count("applications"),
            pending_count=Count("applications", filter=Q(applications__status=Application.Status.PENDING)),
        )
        .order_by("position", "pk")
    )


# Light highlight of a candidate row reached through the viewer's network (CSS in lowbid-components.css).
NETWORK_ROW_CLASS = {"strong": "is-network-strong", "weak": "is-network", "following": "is-network"}


def _company_signals(wallet, items, get_company_id) -> None:
    """Attach `company_signal` (NetworkSignal or None) to each item, with ONE signals() call for the page."""
    sigs = network.signals(wallet, {get_company_id(i) for i in items})
    for i in items:
        i.company_signal = sigs.get(get_company_id(i))


def _candidate_rows(task: Task, wallet) -> list[dict]:
    """Ranked rows (score desc, oldest first) with the badges precomputed so templates stay dumb."""
    apps = list(task.applications.select_related("freelancer").order_by("-score", "created_at", "pk"))
    rec_pk = recommended_pk(apps) if task.is_open else None
    company_id = task.project.company_id
    wanted = set(task.tags or [])
    net = network.signals(wallet, [app.freelancer_id for app in apps])  # one-hop badges only: never the order
    rows = []
    for rank, app in enumerate(apps, start=1):
        history = company_history(company_id, app.freelancer_id)
        sig = net.get(app.freelancer_id)
        parts = score_parts(task.tags, app.tags, history)
        rows.append(
            {
                "app": app,
                "rank": rank,
                "score": app.score,
                "fmt": {
                    "score": f"{app.score:.1f}",
                    "history": f"{parts['history_part']:.1f}",
                    "rating": f"{parts['rating_part']:.1f}",
                    "tags": f"{parts['tags_part']:.1f}",
                },
                "history": history,
                "validated": is_validated(history),
                "recommended": app.pk == rec_pk,
                "tags": [{"name": t, "match": t in wanted} for t in (app.tags or [])],
                "is_mine": wallet is not None and app.freelancer_id == wallet.pk,
                "is_chosen": app.status == Application.Status.CHOSEN,
                "is_rejected": app.status == Application.Status.REJECTED,
                "choose_url": reverse("projects:task_choose", kwargs={"pk": task.pk, "app_pk": app.pk}),
                "network": sig,
                "network_class": NETWORK_ROW_CLASS.get(sig.level if sig else "", ""),
            }
        )
    return rows


def _fingerprint(task: Task, rows: list[dict]) -> str:
    ids = ",".join(f"{r['app'].pk}:{r['fmt']['score']}:{r['network'].level if r['network'] else ''}" for r in rows)
    return f"{task.status}:{len(rows)}:{task.assigned_to_id or 0}:{ids}"


def _candidates_context(task: Task, wallet) -> dict:
    rows = _candidate_rows(task, wallet)
    is_company = task.is_company(wallet)
    return {
        "task": task,
        "rows": rows,
        "viewer_is_company": is_company,
        "task_open": task.is_open,
        "can_choose": is_company and task.is_open,
        "fingerprint": _fingerprint(task, rows),
    }


def _candidate_json(row: dict) -> dict:
    app: Application = row["app"]
    return {
        "id": app.pk,
        "rank": row["rank"],
        "freelancer": app.freelancer.stellar_address,
        "name": app.freelancer.display_name,
        "message": app.message,
        "tags": app.tags,
        "score": row["fmt"]["score"],
        "parts": {"history": row["fmt"]["history"], "rating": row["fmt"]["rating"], "tags": row["fmt"]["tags"]},
        "validated": row["validated"],
        "recommended": row["recommended"],
        "status": app.status,
        "created_at": app.created_at.isoformat(),
        "network": row["network"].as_json() if row["network"] else None,
    }


def _project_tags(project: Project) -> list[str]:
    seen: list[str] = []
    for task in project.tasks.all():
        for t in task.tags or []:
            if t not in seen:
                seen.append(t)
    return seen


# --- pages ------------------------------------------------------------------------

def project_list(request: HttpRequest) -> HttpResponse:
    tab = request.GET.get("tab", "active")
    if tab not in dict(LIST_TABS):
        tab = "active"
    tag = (request.GET.get("tag") or "").strip().lower()[:24]
    q = (request.GET.get("q") or "").strip()[:80]
    sort = request.GET.get("sort") or "newest"
    if sort not in {k for k, _, _ in LIST_SORTS}:
        sort = "newest"
    ordering = next(o for k, _, o in LIST_SORTS if k == sort)

    qs = Project.objects.published().with_totals().select_related("company").prefetch_related("tasks")
    if tab == "active":
        qs = qs.exclude(status__in=(Project.Status.CLOSED, Project.Status.CANCELLED))
    elif tab == "closed":
        qs = qs.filter(status__in=(Project.Status.CLOSED, Project.Status.CANCELLED))
    if q:
        # JSON containment is not portable to SQLite: tags are matched on their text repr.
        task_hits = Task.objects.filter(Q(title__icontains=q) | Q(tags__icontains=q)).values("project_id")
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(pk__in=task_hits))
    qs = qs.order_by(*ordering)
    projects = list(qs)
    for p in projects:
        p.tag_list = _project_tags(p)
    if tag:  # the demo volume makes a Python filter fine
        projects = [p for p in projects if tag in p.tag_list]

    page = Paginator(projects, LIST_PAGE_SIZE).get_page(request.GET.get("page"))
    _company_signals(get_wallet(request), list(page.object_list), lambda p: p.company_id)
    counter = Counter(
        t for tags in Task.objects.filter(status=Task.Status.OPEN).values_list("tags", flat=True) for t in (tags or [])
    )
    popular_tags = [t for t, _ in counter.most_common(POPULAR_TAGS)]
    if tag and tag not in popular_tags:
        popular_tags.insert(0, tag)

    return render(
        request,
        "projects/project_list.html",
        {
            "projects": page.object_list,
            "page": page,
            "total": page.paginator.count,
            "tab": tab,
            "tabs": LIST_TABS,
            "tag": tag,
            "q": q,
            "sort": sort,
            "sorts": [(k, label) for k, label, _ in LIST_SORTS],
            "popular_tags": popular_tags,
            "open_tasks": Task.objects.filter(status=Task.Status.OPEN).count(),
        },
    )


@wallet_required
def project_create(request: HttpRequest) -> HttpResponse:
    wallet = get_wallet(request)
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(company=wallet)
            logger.info("project created project=%s company=%s", project.pk, wallet.pk)
            messages.success(request, "Project created. Now add your fixed-price tasks.")
            return redirect("projects:project_detail", pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, "projects/project_form.html", {"form": form})


def project_detail(request: HttpRequest, pk: int) -> HttpResponse:
    project = get_object_or_404(Project.objects.with_totals().select_related("company"), pk=pk)
    wallet = get_wallet(request)
    is_company = project.is_company(wallet)
    _company_signals(wallet, [project], lambda p: p.company_id)
    tasks = list(_tasks_with_counts(project))
    my_apps = {}
    if wallet is not None and not is_company:
        my_apps = {a.task_id: a for a in Application.objects.filter(task__project=project, freelancer=wallet)}
    for task in tasks:
        task.project = project  # reuse the annotated instance (no extra query per row)
        task.can_delete = is_company and task.is_open
        task.my_application = my_apps.get(task.pk)
        task.is_mine = wallet is not None and task.assigned_to_id == wallet.pk
    candidate_blocks = []
    if is_company:
        for task in tasks:
            if task.is_open and task.app_count:
                candidate_blocks.append(_candidates_context(task, wallet))
    pending_total = sum(t.pending_count for t in tasks)
    to_validate = [t for t in tasks if t.status == Task.Status.DELIVERED]
    funding = payments.project_funding(project, wallet)
    for task in tasks:  # escrow status per row (project_funding already loaded every Escrow)
        row = next((r for r in funding["rows"] if r["task"].pk == task.pk), None)
        task.pay_status_label = row["status_label"] if row else ""
        task.pay_badge_class = row["badge_class"] if row else ""
    return render(
        request,
        "projects/project_detail.html",
        {
            "project": project,
            "tasks": tasks,
            "wallet": wallet,
            "viewer_is_company": is_company,
            "can_add_task": is_company and project.status not in (Project.Status.CLOSED, Project.Status.CANCELLED),
            "funding": funding,
            # The company sees "Fund the project" as soon as the project has a task; it is enabled
            # only when an assigned task still has to be deployed/funded (escrow mode).
            "show_fund": is_company and len(tasks) >= 1 and project.status not in (Project.Status.CLOSED, Project.Status.CANCELLED),
            "candidate_blocks": candidate_blocks,
            "pending_total": pending_total,
            "to_validate": to_validate,
            "tag_list": _project_tags(project),
        },
    )


def task_detail(request: HttpRequest, pk: int) -> HttpResponse:
    task = get_object_or_404(Task.objects.select_related("project__company", "assigned_to"), pk=pk)
    wallet = get_wallet(request)
    ctx = _candidates_context(task, wallet)
    _company_signals(wallet, [task.project], lambda p: p.company_id)
    is_company = ctx["viewer_is_company"]
    my_app = None if is_company else task.application_for(wallet)
    try:
        rating = task.rating
    except Task.rating.RelatedObjectDoesNotExist:
        rating = None
    source_visible = services.source_visible(task, wallet)
    history = services.delivery_history(task, source_visible=source_visible)
    for row in history:  # explorer link of each on-chain event (delivery declaration, dispute, resolution)
        row["explorer_url"] = stellar.explorer_tx_url(row["tx_hash"]) if row.get("tx_hash") else ""
    dispute = Dispute.objects.select_related("opened_by").filter(task=task).first()
    ctx.update(
        {
            "project": task.project,
            "wallet": wallet,
            "my_application": my_app,
            "can_apply": wallet is not None and not is_company and task.is_open and my_app is None,
            "is_assignee": task.is_assignee(wallet),
            "source_visible": source_visible,
            # Link rendering (projects.services.link_info decides trust; components/ext_link.html renders it).
            "delivery_link_info": services.link_info(task.delivery_link) if task.delivery_link else None,
            "source_link_info": services.link_info(task.source_link) if source_visible and task.source_link else None,
            "rating": rating,
            # Review window + revisions (projects.services decides; the template reads the values).
            "review_deadline": services.review_deadline(task),
            "review_overdue": services.is_review_overdue(task),
            "max_revisions": services.max_revisions(),
            "revisions_left": services.revisions_left(task),
            "latest_revision": task.revision_requests.first() if task.revision_count else None,
            "history": history,
            "dispute": dispute,
            "is_arbiter": payments.is_arbiter(wallet),
            "pay_action": payments.next_action(task, wallet),
            "pay_mode": payments.effective_mode(payments.get_escrow(task)),
            "candidates_url": reverse("projects:task_candidates_json", kwargs={"pk": task.pk}),
            "siblings": list(task.project.tasks.exclude(pk=task.pk).order_by("position", "pk")[:8]),
        }
    )
    return render(request, "projects/task_detail.html", ctx)


@wallet_required
def board(request: HttpRequest) -> HttpResponse:
    """The freelance kanban: open tasks of every company (not mine) + the tasks assigned to me."""
    wallet = get_wallet(request)
    applied = set(
        Application.objects.filter(freelancer=wallet, status=Application.Status.PENDING).values_list("task_id", flat=True)
    )
    open_tasks = list(
        Task.objects.filter(status=Task.Status.OPEN, project__published_at__isnull=False)
        .exclude(project__status=Project.Status.CANCELLED)
        .exclude(project__company=wallet)
        .select_related("project__company")
        .annotate(app_count=Count("applications"))
        .order_by("-created_at")
    )
    for t in open_tasks:
        t.applied = t.pk in applied
    open_tasks.sort(key=lambda t: (0 if t.applied else 1, -t.created_at.timestamp()))
    mine = list(
        Task.objects.filter(assigned_to=wallet)
        .select_related("project__company")
        .annotate(app_count=Count("applications"))
        .order_by("-updated_at")
    )
    _company_signals(wallet, open_tasks + mine, lambda t: t.project.company_id)
    by_status = {key: [] for key, _, _ in BOARD_COLUMNS}
    by_status["open"] = open_tasks
    for t in mine:
        column = BOARD_COLUMN_OF.get(t.status)
        if column and column != "open":
            by_status[column].append(t)
    columns = [{"key": key, "label": label, "hint": hint, "tasks": by_status[key]} for key, label, hint in BOARD_COLUMNS]
    earned = sum((t.price for t in by_status["paid"] if t.status == Task.Status.PAID), Decimal("0"))
    return render(
        request,
        "projects/board.html",
        {
            "columns": columns,
            "applied_count": len(applied),
            "earned_usdc": earned,
            "counts": {key: len(by_status[key]) for key in by_status},
        },
    )


@wallet_required
def my_projects(request: HttpRequest) -> HttpResponse:
    wallet = get_wallet(request)
    tab = request.GET.get("tab", "active")
    if tab not in dict(MY_TABS):
        tab = "active"
    all_projects = list(
        Project.objects.filter(company=wallet)
        .with_totals()
        .prefetch_related(
            Prefetch(
                "tasks",
                queryset=Task.objects.annotate(
                    pending_count=Count("applications", filter=Q(applications__status=Application.Status.PENDING))
                ),
            )
        )
    )
    kpis = {"draft": 0, "funded": 0, "closed": 0, "cancelled": 0, "to_choose": 0, "to_validate": 0}
    projects = []
    for project in all_projects:
        kpis[project.status] += 1
        tasks = list(project.tasks.all())
        project.to_choose = sum(1 for t in tasks if t.is_open and t.pending_count)
        project.to_validate = sum(1 for t in tasks if t.status == Task.Status.DELIVERED)
        project.disputed = sum(1 for t in tasks if t.status == Task.Status.DISPUTED)
        project.pending_apps = sum(t.pending_count for t in tasks)
        project.attention = bool(project.to_choose or project.to_validate)
        kpis["to_choose"] += project.to_choose
        kpis["to_validate"] += project.to_validate
        done = project.status in (Project.Status.CLOSED, Project.Status.CANCELLED)
        if (tab == "active" and done) or (tab == "done" and not done):
            continue
        projects.append(project)
    return render(request, "projects/my_projects.html", {"projects": projects, "tab": tab, "tabs": MY_TABS, "kpis": kpis})


@wallet_required
def disputes(request: HttpRequest) -> HttpResponse:
    """`/litiges/` — the arbiter's desk: every disputed task (newest first) with its resolution form, then the
    resolved ones. 403 for any other wallet (the rule is payments.services.is_arbiter; nothing here decides)."""
    wallet = get_wallet(request)
    if not payments.is_arbiter(wallet):
        logger.info("disputes page refused wallet=%s", wallet.stellar_address)
        return render(request, "403.html", {"reason": "Only the arbiter wallet can open the disputes desk."}, status=403)
    rows = []
    disputes_qs = (
        Dispute.objects.select_related("task__project__company", "task__assigned_to", "opened_by")
        .filter(task__status__in=(Task.Status.DISPUTED, Task.Status.RESOLVED))
        .order_by("-created_at", "-pk")
    )
    for dispute in disputes_qs:
        task = dispute.task
        escrow = payments.get_escrow(task)
        action = payments.next_action(task, wallet)
        rows.append(
            {
                "dispute": dispute,
                "task": task,
                "project": task.project,
                "escrow": escrow,
                "amount": escrow.amount if escrow is not None else task.price,
                "links": escrow.explorer_links() if escrow is not None else [],
                "delivery_link_info": services.link_info(task.delivery_link) if task.delivery_link else None,
                "history": services.delivery_history(task, source_visible=False),
                "by_company": dispute.opened_by_id == task.project.company_id,
                "open": task.status == Task.Status.DISPUTED,
                "action": action if action and action["mine"] and action["step"] == "resolve" else None,
                "last_error": escrow.last_error if escrow is not None else "",
            }
        )
    for row in rows:
        for h in row["history"]:
            h["explorer_url"] = stellar.explorer_tx_url(h["tx_hash"]) if h.get("tx_hash") else ""
    open_rows = [r for r in rows if r["open"]]
    closed_rows = [r for r in rows if not r["open"]]
    return render(
        request,
        "projects/disputes.html",
        {"open_rows": open_rows, "closed_rows": closed_rows, "wallet": wallet, "arbiter_address": payments.resolver_address()},
    )


# --- JSON -------------------------------------------------------------------------

@require_GET
def task_candidates_json(request: HttpRequest, pk: int) -> JsonResponse:
    """Polled every 5 s by the task page. Carries the ranked rows both as data and as the
    rendered `_candidates.html` fragment so the page swaps the list in place."""
    task = get_object_or_404(Task.objects.select_related("project__company", "assigned_to"), pk=pk)
    wallet = get_wallet(request)
    ctx = _candidates_context(task, wallet)
    return JsonResponse(
        {
            "ok": True,
            "task": task.pk,
            "status": task.status,
            "count": len(ctx["rows"]),
            "fingerprint": ctx["fingerprint"],
            "candidates": [_candidate_json(r) for r in ctx["rows"]],
            "html": render_to_string("projects/_candidates.html", ctx, request=request),
        }
    )


@require_POST
@wallet_required
def task_add(request: HttpRequest, pk: int) -> JsonResponse:
    project = get_object_or_404(Project, pk=pk)
    data = _json_body(request)
    try:
        task = services.add_task(
            project,
            get_wallet(request),
            title=data.get("title"),
            description=data.get("description"),
            price=data.get("price"),
            tags=data.get("tags"),
        )
    except ProjectError as e:
        return _error_response(e)
    return JsonResponse(
        {
            "ok": True,
            "task": {"id": task.pk, "title": task.title, "price": dec_str(task.price), "tags": task.tags, "status": task.status},
            "count": project.tasks.count(),
            "total": dec_str(project.total_amount),
            "message": f'Task "{task.title}" added.',
        },
        status=201,
    )


@require_POST
@wallet_required
def project_cancel(request: HttpRequest, pk: int) -> JsonResponse:
    """The company cancels its project before choosing anyone (services.cancel_project); payments then
    settles the deposit once the cancellation is committed."""
    project = get_object_or_404(Project, pk=pk)
    try:
        project = services.cancel_project(project, get_wallet(request))
    except ProjectError as e:
        return _error_response(e)
    return JsonResponse(
        {
            "ok": True,
            "status": project.status,
            "message": "Project cancelled.",
            "redirect": reverse("projects:project_detail", kwargs={"pk": project.pk}),
        }
    )


@require_POST
@wallet_required
def task_delete(request: HttpRequest, pk: int) -> JsonResponse:
    task = get_object_or_404(Task.objects.select_related("project"), pk=pk)
    project_pk = task.project_id
    try:
        services.delete_task(task, get_wallet(request))
    except ProjectError as e:
        return _error_response(e)
    return JsonResponse(
        {"ok": True, "message": "Task deleted.", "redirect": reverse("projects:project_detail", kwargs={"pk": project_pk})}
    )


@require_POST
@wallet_required
def apply_create(request: HttpRequest, pk: int) -> JsonResponse:
    task = get_object_or_404(Task.objects.select_related("project"), pk=pk)
    data = _json_body(request)
    try:
        app = services.apply(task, get_wallet(request), message=data.get("message"), tags=data.get("tags"))
    except ProjectError as e:
        return _error_response(e)
    return JsonResponse(
        {
            "ok": True,
            "application": {"id": app.pk, "score": f"{app.score:.1f}", "tags": app.tags},
            "message": "Application sent. The company chooses among the candidates.",
        },
        status=201,
    )


@require_POST
@wallet_required
def task_choose(request: HttpRequest, pk: int, app_pk: int) -> JsonResponse:
    task = get_object_or_404(Task.objects.select_related("project"), pk=pk)
    app = get_object_or_404(Application.objects.select_related("freelancer"), pk=app_pk, task=task)
    try:
        task = services.choose(task, app, get_wallet(request))
    except ProjectError as e:
        return _error_response(e)
    return JsonResponse(
        {
            "ok": True,
            "status": task.status,
            "assigned_to": app.freelancer.stellar_address,
            "message": f'{app.freelancer.display_name or app.freelancer.short_address} is chosen for "{task.title}".',
        }
    )


@require_POST
@wallet_required
def task_deliver(request: HttpRequest, pk: int) -> JsonResponse:
    task = get_object_or_404(Task.objects.select_related("project"), pk=pk)
    data = _json_body(request)
    try:
        task = services.deliver(
            task,
            get_wallet(request),
            delivery_link=data.get("delivery_link"),
            delivery_hash=data.get("delivery_hash") or "",
            source_link=data.get("source_link") or "",
        )
    except ProjectError as e:
        return _error_response(e)
    return JsonResponse({"ok": True, "status": task.status, "message": "Delivery submitted. The company validates and rates."})


@require_POST
@wallet_required
def task_request_changes(request: HttpRequest, pk: int) -> JsonResponse:
    """The company sends the delivery back for changes (projects.services.request_changes): the task
    returns to `taken`, the escrow row follows, the freelance delivers again."""
    task = get_object_or_404(Task.objects.select_related("project__company", "assigned_to"), pk=pk)
    data = _json_body(request)
    try:
        task = services.request_changes(task, get_wallet(request), message=data.get("message"))
    except ProjectError as e:
        return _error_response(e)
    left = services.revisions_left(task)
    return JsonResponse(
        {
            "ok": True,
            "status": task.status,
            "revision_count": task.revision_count,
            "revisions_left": left,
            "message": f"Changes requested: the freelancer delivers again ({left} request{'s' if left != 1 else ''} left).",
        }
    )


@require_POST
@wallet_required
def task_validate(request: HttpRequest, pk: int) -> JsonResponse:
    """Saves the Rating, then answers `next`: the payment step the company must sign right away
    (approve → release in escrow mode, direct_pay in direct mode) so lowbid-projects.js chains it."""
    task = get_object_or_404(Task.objects.select_related("project__company", "assigned_to"), pk=pk)
    wallet = get_wallet(request)
    data = _json_body(request)
    try:
        task = services.validate(task, wallet, note=data.get("note"), comment=str(data.get("comment") or ""))
    except ProjectError as e:
        return _error_response(e)
    nxt = payments.next_action(task, wallet)
    if task.status == Task.Status.PAID:
        message = "Task validated, rated and paid."
    elif nxt and nxt["mine"]:
        message = f'Rating saved. Now sign "{nxt["label"]}" in Freighter.'
    else:
        message = "Task validated and rated."
    return JsonResponse(
        {
            "ok": True,
            "status": task.status,
            "project_status": task.project.status,
            "next": next_json(nxt),
            "message": message,
        }
    )
