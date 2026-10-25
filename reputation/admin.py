from django.contrib import admin

from .models import CompanyRating, GithubIdentity


@admin.register(CompanyRating)
class CompanyRatingAdmin(admin.ModelAdmin):
    list_display = ("task", "note", "company", "freelancer", "created_at")
    list_filter = ("note",)
    search_fields = ("company__stellar_address", "freelancer__stellar_address", "task__title")
    raw_id_fields = ("task", "company", "freelancer")


@admin.register(GithubIdentity)
class GithubIdentityAdmin(admin.ModelAdmin):
    list_display = ("github_login", "github_id", "wallet", "scheme", "account_created_at", "verified_at")
    search_fields = ("wallet__stellar_address", "github_login")
    raw_id_fields = ("wallet",)
