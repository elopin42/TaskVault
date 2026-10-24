from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("prepare/<int:need_pk>/<slug:step>/", views.prepare, name="prepare"),
    path("send/<int:need_pk>/<slug:step>/", views.send, name="send"),
    path("trustline/prepare/", views.trustline_prepare, name="trustline_prepare"),
    path("trustline/send/", views.trustline_send, name="trustline_send"),
    path("<int:need_pk>/", views.need_pay, name="need_pay"),
]
