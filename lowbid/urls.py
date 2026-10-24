"""Lowbid URL configuration.

    /            core (landing, healthz) + projects (projets, tâches, tableau)
    /auth/       accounts (wallet challenge / verify / logout)
    /pay/        payments (Trustless Work escrow per task, direct payment fallback, trustline)
    /tableau-de-bord/  /profil/<addr>/   dashboard (signed-in home, public wallet profile)
    /django-admin/  Django admin (staff only, debugging aid)
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("pay/", include("payments.urls")),
    path("", include("core.urls")),
    path("", include("projects.urls")),
    path("", include("dashboard.urls")),
]

handler400 = "core.views.error_400"
handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
