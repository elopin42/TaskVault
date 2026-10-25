from django.urls import path

from . import views

app_name = "reputation"

urlpatterns = [
    path("taches/<int:pk>/noter-entreprise/", views.rate_company, name="rate_company"),
    path("profil/github/message/", views.github_message, name="github_message"),
    path("profil/github/verifier/", views.github_verify, name="github_verify"),
    path("profil/github/retirer/", views.github_unlink, name="github_unlink"),
]
