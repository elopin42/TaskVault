from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("prepare/<int:task_pk>/<slug:step>/", views.prepare, name="prepare"),
    path("send/<int:task_pk>/<slug:step>/", views.send, name="send"),
    path("trustline/prepare/", views.trustline_prepare, name="trustline_prepare"),
    path("trustline/send/", views.trustline_send, name="trustline_send"),
    path("project/<int:pk>/pending.json", views.project_pending, name="project_pending"),
    path("<int:task_pk>/", views.task_pay, name="task_pay"),
]
