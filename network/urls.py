from django.urls import path

from . import views

app_name = "network"

urlpatterns = [
    path("profil/<str:address>/suivre/", views.follow_view, name="follow"),
    path("profil/<str:address>/ne-plus-suivre/", views.unfollow_view, name="unfollow"),
    path("profil/<str:address>/recommander/", views.recommend_view, name="recommend"),
    path("profil/<str:address>/retirer-recommandation/", views.unrecommend_view, name="unrecommend"),
]
