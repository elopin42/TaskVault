from django.contrib import admin

from .models import WalletUser


@admin.register(WalletUser)
class WalletUserAdmin(admin.ModelAdmin):
    list_display = ("stellar_address", "display_name", "created_at", "last_login_at")
    search_fields = ("stellar_address", "display_name")
    readonly_fields = ("created_at", "last_login_at")
