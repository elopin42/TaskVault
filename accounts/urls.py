from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("challenge/", views.auth_challenge, name="challenge"),
    path("verify/", views.auth_verify, name="verify"),
    path("logout/", views.auth_logout, name="logout"),
]
