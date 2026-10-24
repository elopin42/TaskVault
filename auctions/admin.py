from django.contrib import admin

from .models import Bid, Need


class BidInline(admin.TabularInline):
    model = Bid
    extra = 0
    fields = ("freelancer", "price", "delay_days", "tags", "status", "created_at")
    readonly_fields = ("created_at",)
    raw_id_fields = ("freelancer",)


@admin.register(Need)
class NeedAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "client", "budget_max", "delay_max_days", "status", "bidding_ends_at", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "client__stellar_address")
    readonly_fields = ("created_at", "updated_at", "awarded_at")
    raw_id_fields = ("client", "winning_bid")
    inlines = [BidInline]


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "need", "freelancer", "price", "delay_days", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("need__title", "freelancer__stellar_address")
    readonly_fields = ("created_at",)
    raw_id_fields = ("need", "freelancer")
