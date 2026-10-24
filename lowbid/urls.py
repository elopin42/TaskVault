"""Lowbid URL configuration.

    /            core (landing, healthz) + auctions (needs, bids)
    /auth/       accounts (wallet challenge / verify / logout)
    /pay/        payments (escrow)
    /django-admin/  Django admin (staff only, debugging aid)
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("pay/", include("payments.urls")),
    path("", include("core.urls")),
    path("", include("auctions.urls")),
]

handler400 = "core.views.error_400"
handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
