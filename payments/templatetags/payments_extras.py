"""`{% escrow_panel task wallet %}` — renders templates/payments/_escrow_panel.html with the
payment view-model (escrow row, mode, stepper, next action for this viewer, explorer links, the
delivery fingerprint, whether this viewer may see the full deliverable, the review window, the
change requests and the dispute: who may open one, the open / resolved dispute row). Keeps the
projects views free of payment logic."""

from django import template
from django.urls import reverse

from payments import services, stellar
from payments.models import STATUS_BADGES, STATUS_LABELS, Escrow
from projects import services as projects
from projects.models import Dispute
from projects.services import source_visible

register = template.Library()

HASH_KINDS = {40: "git commit", 64: "SHA-256"}


@register.inclusion_tag("payments/_escrow_panel.html", takes_context=True)
def escrow_panel(context, task, wallet=None):
    escrow = services.get_escrow(task)
    mode = services.effective_mode(escrow)
    status = services.display_status(task, escrow, mode)
    role = services.viewer_role(task, wallet)
    payee = task.assigned_to.stellar_address if task.assigned_to_id else ""
    amount = escrow.amount if escrow is not None else task.price
    action = services.next_action(task, wallet)
    rated = services.is_rated(task)
    is_done = task.status in (task.Status.PAID, task.Status.RESOLVED)
    visible = source_visible(task, wallet)
    can_dispute, dispute_why = services.can_dispute(task, wallet)
    dispute = Dispute.objects.select_related("opened_by").filter(task=task).first()
    return {
        "request": context.get("request"),
        "task": task,
        "project": task.project,
        "escrow": escrow,
        "mode": mode,
        "is_direct": mode == Escrow.Mode.DIRECT,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "badge_class": STATUS_BADGES.get(status, "ui-badge-neutral"),
        "is_done": is_done,
        "steps": services.stepper(mode, status),
        "action": action,
        "role": role,
        "is_party": role in ("company", "freelance"),
        "is_arbiter": role == "arbiter",
        "rated": rated,
        "platform_fallback": services.platform_fallback_in_use(task, escrow, mode),
        "amount": amount,
        "payee": payee,
        "payer": task.project.company.stellar_address,
        "payee_explorer_url": stellar.explorer_account_url(payee) if payee else "",
        "links": escrow.explorer_links() if escrow is not None else [],
        "last_error": escrow.last_error if escrow is not None else "",
        "pending_hash": bool(escrow and escrow.payment_tx_hash and escrow.status != Escrow.Status.PAID),
        "asset_code": stellar.asset_code(),
        "asset_native": stellar.is_native(),
        # Two-step delivery (projects.services.source_visible decides; the template only reads booleans).
        "delivery_hash": task.delivery_hash,
        "hash_kind": HASH_KINDS.get(len(task.delivery_hash), ""),
        "deliver_tx_hash": escrow.deliver_tx_hash if escrow is not None else "",
        "deliver_tx_url": stellar.explorer_tx_url(escrow.deliver_tx_hash) if escrow is not None and escrow.deliver_tx_hash else "",
        "delivered_at": escrow.delivered_at if escrow is not None else task.delivered_at,
        "source_visible": visible,
        "source_pending": role == "company" and bool(task.source_link) and not visible,
        "source_link_info": projects.link_info(task.source_link) if visible and task.source_link else None,
        "validate_url": reverse("projects:task_validate", kwargs={"pk": task.pk}),
        "trustline_url": reverse("payments:trustline_prepare"),
        # Review window + change requests (projects.services decides; the template reads booleans / numbers).
        "review_deadline": projects.review_deadline(task),
        "review_overdue": projects.is_review_overdue(task),
        "can_request_changes": projects.can_request_changes(task, wallet),
        "revision_count": task.revision_count,
        "max_revisions": projects.max_revisions(),
        "revisions_left": projects.revisions_left(task),
        "latest_revision": task.revision_requests.first() if task.revision_count else None,
        "request_changes_url": reverse("projects:task_request_changes", kwargs={"pk": task.pk}),
        # Dispute (payments.services.can_dispute decides: mode + projects.services.can_dispute; the template reads booleans).
        "can_dispute": can_dispute,
        "dispute_why": dispute_why,
        "dispute_for_no_response": can_dispute and role == "freelance",
        "dispute_prepare_url": reverse("payments:prepare", kwargs={"task_pk": task.pk, "step": "dispute"}),
        "dispute": dispute,
        "dispute_by_company": dispute is not None and dispute.opened_by_id == task.project.company_id,
        "dispute_tx_url": stellar.explorer_tx_url(escrow.dispute_tx_hash) if escrow is not None and escrow.dispute_tx_hash else "",
        "resolve_tx_url": stellar.explorer_tx_url(escrow.resolve_tx_hash) if escrow is not None and escrow.resolve_tx_hash else "",
        "disputes_url": reverse("projects:disputes"),
        # Direct mode = unprotected payment: shown on every non-open task in direct mode, to everyone.
        "direct_warning": mode == Escrow.Mode.DIRECT and task.status != task.Status.OPEN,
    }
