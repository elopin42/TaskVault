from django.contrib import admin

from .models import Application, Project, Rating, Task


class TaskInline(admin.TabularInline):
    model = Task
    extra = 0
    fields = ("position", "title", "price", "tags", "status", "assigned_to", "delivered_at", "paid_at")
    readonly_fields = ("delivered_at", "paid_at")
    raw_id_fields = ("assigned_to",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "company", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "company__stellar_address")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("company",)
    inlines = [TaskInline]


class ApplicationInline(admin.TabularInline):
    model = Application
    extra = 0
    fields = ("freelancer", "score", "tags", "status", "created_at")
    readonly_fields = ("created_at",)
    raw_id_fields = ("freelancer",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "project", "price", "status", "assigned_to", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "project__title")
    readonly_fields = ("created_at", "updated_at", "delivered_at", "paid_at")
    raw_id_fields = ("project", "assigned_to")
    inlines = [ApplicationInline]


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "freelancer", "score", "status", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("task", "freelancer")
    readonly_fields = ("created_at",)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "company", "freelancer", "note", "created_at")
    raw_id_fields = ("task", "company", "freelancer")
    readonly_fields = ("created_at",)
