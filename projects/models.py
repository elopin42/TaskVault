"""Project → Task → Application (+ Rating, Delivery, RevisionRequest, Dispute): the task-board domain.

A company splits a Project into fixed-price Tasks; freelances apply to open tasks; the
company picks one freelance per task; the chosen one delivers; the company validates and
rates — or sends the delivery back for changes (at most LOWBID_MAX_REVISIONS times, before the
Rating) — or either party opens a dispute (escrow mode: the company while the delivery is
unrated, the freelance once the review window is over) that the arbiter wallet settles with a split
of the locked funds. Every (re)delivery is a Delivery row, every change request a RevisionRequest
row and the dispute a Dispute row (one per task), so the task's history is readable; Task itself
holds the LATEST delivery. The payments app attaches one Escrow row to each Task (one Trustless
Work escrow per task, or one direct payment) — nothing Stellar-related is stored here except the
tx hash a Delivery was declared with.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

ZERO = Decimal("0")

PROJECT_STATUS_LABELS = {"draft": "Draft", "funded": "Funded", "closed": "Closed", "cancelled": "Cancelled"}
PROJECT_STATUS_BADGES = {
    "draft": "ui-badge-neutral",
    "funded": "ui-badge-ok",
    "closed": "ui-badge-brand",
    "cancelled": "ui-badge-neutral",
}

STATUS_LABELS = {
    "open": "Open",
    "taken": "Taken",
    "delivered": "Delivered",
    "paid": "Paid",
    "disputed": "Disputed",
    "resolved": "Resolved",
}
STATUS_BADGES = {
    "open": "ui-badge-info",
    "taken": "ui-badge-brand",
    "delivered": "ui-badge-attn",
    "paid": "ui-badge-ok",
    "disputed": "ui-badge-danger",
    "resolved": "ui-badge-brand",
}
# A task is settled when its money has left the escrow for good: paid to the freelance, or split by the arbiter.
SETTLED_STATUSES = ("paid", "resolved")

APPLICATION_LABELS = {"pending": "Pending", "chosen": "Chosen", "rejected": "Not selected"}
APPLICATION_BADGES = {"pending": "ui-badge-neutral", "chosen": "ui-badge-ok", "rejected": "ui-badge-neutral"}


class ProjectQuerySet(models.QuerySet):
    def with_totals(self):
        """Annotate `total` (sum of task prices), `tasks_total`, `paid_total`, `open_total` in one query."""
        return self.annotate(
            total=Coalesce(Sum("tasks__price"), ZERO, output_field=models.DecimalField(max_digits=18, decimal_places=7)),
            tasks_total=Count("tasks"),
            paid_total=Count("tasks", filter=Q(tasks__status=Task.Status.PAID)),
            resolved_total=Count("tasks", filter=Q(tasks__status=Task.Status.RESOLVED)),
            open_total=Count("tasks", filter=Q(tasks__status=Task.Status.OPEN)),
        )

    def active(self):
        return self.exclude(status=Project.Status.CLOSED)

    def published(self):
        """Projects visible on the public list: `published_at` set (payments.deposits: the publication
        deposit is funded in escrow mode; set at creation when deposits are not active)."""
        return self.filter(published_at__isnull=False)


class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"  # no task funded / paid yet
        FUNDED = "funded", "Funded"  # every assigned task holds funds (escrow) / a first payment was made (direct)
        CLOSED = "closed", "Closed"  # every task paid or resolved by the arbiter
        CANCELLED = "cancelled", "Cancelled"  # the company cancelled it before choosing anyone (projects.services.cancel_project)

    company = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="projects")
    title = models.CharField(max_length=120)
    description = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    # When the project started taking applications: the publication deposit was funded (escrow mode with
    # deposits, payments.deposits.confirm_deposit), or at creation when deposits are not active. None = unpublished.
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"

    # --- computed figures (annotated by with_totals() when available) --------------

    @property
    def total_amount(self) -> Decimal:
        cached = getattr(self, "total", None)
        if cached is not None:
            return cached
        return self.tasks.aggregate(s=Sum("price"))["s"] or ZERO

    @property
    def tasks_count(self) -> int:
        cached = getattr(self, "tasks_total", None)
        if cached is not None:
            return cached
        return self.tasks.count()

    @property
    def paid_count(self) -> int:
        cached = getattr(self, "paid_total", None)
        if cached is not None:
            return cached
        return self.tasks.filter(status=Task.Status.PAID).count()

    @property
    def resolved_count(self) -> int:
        cached = getattr(self, "resolved_total", None)
        if cached is not None:
            return cached
        return self.tasks.filter(status=Task.Status.RESOLVED).count()

    @property
    def settled_count(self) -> int:
        """Tasks whose money left the escrow: paid + resolved by the arbiter (what closes a project)."""
        return self.paid_count + self.resolved_count

    @property
    def open_count(self) -> int:
        cached = getattr(self, "open_total", None)
        if cached is not None:
            return cached
        return self.tasks.filter(status=Task.Status.OPEN).count()

    @property
    def progress_pct(self) -> int:
        total = self.tasks_count
        return int(round(100 * self.settled_count / total)) if total else 0

    @property
    def status_label(self) -> str:
        return PROJECT_STATUS_LABELS[self.status]

    @property
    def badge_class(self) -> str:
        return PROJECT_STATUS_BADGES[self.status]

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    @property
    def is_published(self) -> bool:
        return self.published_at is not None

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.Status.CANCELLED

    def is_company(self, wallet) -> bool:
        return wallet is not None and wallet.pk == self.company_id


class Task(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        TAKEN = "taken", "Taken"
        DELIVERED = "delivered", "Delivered"
        PAID = "paid", "Paid"
        # Escrow mode only: a party opened a Trustless Work dispute (projects.services.mark_disputed, called by
        # payments once the dispute-escrow transaction is confirmed); the funds stay locked.
        DISPUTED = "disputed", "Disputed"
        # The arbiter split the locked funds (projects.services.mark_resolved, the ONLY gate): terminal, like `paid`.
        RESOLVED = "resolved", "Resolved"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=7)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    assigned_to = models.ForeignKey(
        "accounts.WalletUser", on_delete=models.PROTECT, null=True, blank=True, related_name="assigned_tasks"
    )
    # The demo / preview link (required at delivery); shown to everyone once delivered.
    delivery_link = models.CharField(max_length=500, blank=True)
    # Fingerprint of the deliverable: "" or lowercase hex, 40 chars (git commit) or 64 chars (SHA-256).
    # In escrow mode it goes on chain inside the milestone evidence (payments.services.build_evidence).
    delivery_hash = models.CharField(max_length=64, blank=True, default="")
    # The full deliverable (repository, archive…): the assignee always sees it, the company only once paid
    # (projects.services.source_visible).
    source_link = models.CharField(max_length=500, blank=True, default="")
    # Time of the LATEST delivery; None again when the company requests changes (the review window —
    # projects.services.review_deadline — only makes sense while the task is `delivered`).
    delivered_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Set by projects.services.mark_resolved once the arbiter's resolve-dispute transaction is confirmed.
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Change requests made by the company so far (projects.services.request_changes, max LOWBID_MAX_REVISIONS).
    revision_count = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project_id", "position", "pk"]

    def __str__(self) -> str:
        return f"Task #{self.pk} {self.title} ({self.price} USDC)"

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def badge_class(self) -> str:
        return STATUS_BADGES[self.status]

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN

    @property
    def is_settled(self) -> bool:
        return self.status in SETTLED_STATUSES

    @property
    def company_id(self) -> int:
        return self.project.company_id

    def is_company(self, wallet) -> bool:
        return self.project.is_company(wallet)

    def is_assignee(self, wallet) -> bool:
        return wallet is not None and self.assigned_to_id == wallet.pk

    def pending_applications(self):
        return self.applications.filter(status=Application.Status.PENDING).select_related("freelancer")

    @property
    def applications_count(self) -> int:
        cached = getattr(self, "app_count", None)
        if cached is not None:
            return cached
        return self.applications.count()

    def application_for(self, wallet):
        if wallet is None:
            return None
        return self.applications.filter(freelancer=wallet).first()


class Application(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CHOSEN = "chosen", "Chosen"
        REJECTED = "rejected", "Not selected"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="applications")
    freelancer = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="applications")
    message = models.CharField(max_length=280, blank=True)
    tags = models.JSONField(default=list, blank=True)
    # Deterministic server-side score (projects.scoring), stored at creation and refreshed by services.rescore().
    score = models.DecimalField(max_digits=5, decimal_places=1, default=ZERO)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-score", "created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["task", "freelancer"], name="projects_one_application_per_freelancer"),
        ]

    def __str__(self) -> str:
        return f"Application #{self.pk} by {self.freelancer_id} on task #{self.task_id}"

    @property
    def status_label(self) -> str:
        return APPLICATION_LABELS[self.status]

    @property
    def badge_class(self) -> str:
        return APPLICATION_BADGES[self.status]

    def matching_tags(self, task=None) -> list[str]:
        task = task or self.task
        wanted = set(task.tags or [])
        return [t for t in (self.tags or []) if t in wanted]


class Delivery(models.Model):
    """One row per (re)delivery of a task, written by projects.services.deliver — the history behind
    Task.delivery_link / delivery_hash / source_link, which hold the latest one. `tx_hash` is the
    Trustless Work milestone change that declared it (escrow mode), empty in direct mode."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="deliveries")
    freelancer = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="deliveries")
    delivery_link = models.CharField(max_length=500)
    delivery_hash = models.CharField(max_length=64, blank=True, default="")
    source_link = models.CharField(max_length=500, blank=True, default="")
    tx_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Delivery #{self.pk} of task #{self.task_id}"


class RevisionRequest(models.Model):
    """The company sent a delivery back for changes (projects.services.request_changes): the task
    went `delivered → taken`, the freelance delivers again."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="revision_requests")
    company = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="revision_requests")
    message = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Change request #{self.pk} on task #{self.task_id}"


class Dispute(models.Model):
    """One dispute per task (escrow mode). `opened_by` is the party whose Freighter signature sent the
    Trustless Work dispute-escrow transaction (payments.services.confirm_dispute → projects.services
    .mark_disputed); `reason` lives here only (v1 has no reason field on chain). `freelance_pct` and
    `resolved_at` are filled by projects.services.mark_resolved once the arbiter's resolve-dispute
    transaction is confirmed: the freelance received that percentage of the escrow balance, the company
    the rest. The transaction hashes are on the payments.Escrow row."""

    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="dispute")
    opened_by = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="disputes_opened")
    reason = models.CharField(max_length=280, blank=True)
    freelance_pct = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Dispute on task #{self.task_id}"

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def company_pct(self) -> int | None:
        return None if self.freelance_pct is None else 100 - self.freelance_pct


class Rating(models.Model):
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="rating")
    company = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="ratings_given")
    freelancer = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="ratings_received")
    note = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Rating {self.note}/5 on task #{self.task_id}"
