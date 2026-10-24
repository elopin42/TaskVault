from django.contrib import admin

from .models import Escrow


@admin.register(Escrow)
class EscrowAdmin(admin.ModelAdmin):
    list_display = ("need", "mode", "status", "amount", "payer_address", "payee_address", "contract_id", "updated_at")
    list_filter = ("mode", "status")
    search_fields = ("need__title", "payer_address", "payee_address", "contract_id", "payment_tx_hash")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("need",)
