from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("tableau-de-bord/", views.home, name="home"),
    path("profil/<str:address>/", views.profile, name="profile"),
]
