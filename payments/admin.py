from django.contrib import admin

from .models import Escrow, ProjectDeposit


@admin.register(Escrow)
class EscrowAdmin(admin.ModelAdmin):
    list_display = ("task", "mode", "status", "amount", "payer_address", "payee_address", "contract_id", "updated_at")
    list_filter = ("mode", "status")
    search_fields = ("task__title", "payer_address", "payee_address", "contract_id", "payment_tx_hash")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("task",)


@admin.register(ProjectDeposit)
class ProjectDepositAdmin(admin.ModelAdmin):
    list_display = ("project", "kind", "status", "amount", "covered_budget", "payer_address", "contract_id", "updated_at")
    list_filter = ("kind", "status")
    search_fields = ("project__title", "payer_address", "contract_id", "fund_tx_hash", "resolve_tx_hash")
    readonly_fields = ("created_at", "updated_at", "funded_at", "settled_at")
    raw_id_fields = ("project",)
