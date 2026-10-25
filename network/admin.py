from django.contrib import admin

from .models import Follow, Recommendation


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("id", "follower", "followed", "created_at")
    search_fields = ("follower__stellar_address", "followed__stellar_address")
    readonly_fields = ("created_at",)
    raw_id_fields = ("follower", "followed")


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "subject", "message", "created_at", "updated_at")
    search_fields = ("author__stellar_address", "subject__stellar_address", "message")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("author", "subject")
