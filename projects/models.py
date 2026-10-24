"""Project → Task → Application (+ Rating): the task-board domain.

A company splits a Project into fixed-price Tasks; freelances apply to open tasks; the
company picks one freelance per task; the chosen one delivers; the company validates and
rates. Payments (Phase 2) attach an Escrow to the Project and a milestone to each Task —
nothing Stellar-related is stored here.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

ZERO = Decimal("0")

PROJECT_STATUS_LABELS = {"draft": "Brouillon", "funded": "Financé", "closed": "Terminé"}
PROJECT_STATUS_BADGES = {"draft": "ui-badge-neutral", "funded": "ui-badge-ok", "closed": "ui-badge-brand"}

STATUS_LABELS = {"open": "Ouvert", "taken": "Pris", "delivered": "Livré", "paid": "Payé"}
STATUS_BADGES = {"open": "ui-badge-info", "taken": "ui-badge-brand", "delivered": "ui-badge-attn", "paid": "ui-badge-ok"}

APPLICATION_LABELS = {"pending": "En attente", "chosen": "Choisi", "rejected": "Non retenu"}
APPLICATION_BADGES = {"pending": "ui-badge-neutral", "chosen": "ui-badge-ok", "rejected": "ui-badge-neutral"}


class ProjectQuerySet(models.QuerySet):
    def with_totals(self):
        """Annotate `total` (sum of task prices), `tasks_total`, `paid_total`, `open_total` in one query."""
        return self.annotate(
            total=Coalesce(Sum("tasks__price"), ZERO, output_field=models.DecimalField(max_digits=18, decimal_places=7)),
            tasks_total=Count("tasks"),
            paid_total=Count("tasks", filter=Q(tasks__status=Task.Status.PAID)),
            open_total=Count("tasks", filter=Q(tasks__status=Task.Status.OPEN)),
        )

    def active(self):
        return self.exclude(status=Project.Status.CLOSED)


class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"  # not funded yet, tasks editable
        FUNDED = "funded", "Financé"  # escrow holds the money (Phase 2) / direct mode armed
        CLOSED = "closed", "Terminé"  # every task paid

    company = models.ForeignKey("accounts.WalletUser", on_delete=models.PROTECT, related_name="projects")
    title = models.CharField(max_length=120)
    description = models.TextField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT, db_index=True)
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
    def open_count(self) -> int:
        cached = getattr(self, "open_total", None)
        if cached is not None:
            return cached
        return self.tasks.filter(status=Task.Status.OPEN).count()

    @property
    def progress_pct(self) -> int:
        total = self.tasks_count
        return int(round(100 * self.paid_count / total)) if total else 0

    @property
    def status_label(self) -> str:
        return PROJECT_STATUS_LABELS[self.status]

    @property
    def badge_class(self) -> str:
        return PROJECT_STATUS_BADGES[self.status]

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    def is_company(self, wallet) -> bool:
        return wallet is not None and wallet.pk == self.company_id


class Task(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        TAKEN = "taken", "Pris"
        DELIVERED = "delivered", "Livré"
        PAID = "paid", "Payé"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=7)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    assigned_to = models.ForeignKey(
        "accounts.WalletUser", on_delete=models.PROTECT, null=True, blank=True, related_name="assigned_tasks"
    )
    delivery_link = models.CharField(max_length=500, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
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
        PENDING = "pending", "En attente"
        CHOSEN = "chosen", "Choisi"
        REJECTED = "rejected", "Non retenu"

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
