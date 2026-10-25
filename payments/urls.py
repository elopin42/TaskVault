from django.urls import include, path

from . import deposit_views, views

app_name = "payments"

# Mounted at the site root by lowbid/urls.py: every payment endpoint lives under /pay/, the public
# guarantee-fund page at /fonds/.
pay_urlpatterns = [
    path("prepare/<int:task_pk>/<slug:step>/", views.prepare, name="prepare"),
    path("send/<int:task_pk>/<slug:step>/", views.send, name="send"),
    path("trustline/prepare/", views.trustline_prepare, name="trustline_prepare"),
    path("trustline/send/", views.trustline_send, name="trustline_send"),
    path("project/<int:pk>/pending.json", views.project_pending, name="project_pending"),
    path("<int:task_pk>/", views.task_pay, name="task_pay"),
    # Publication deposit (payments/deposits.py)
    path("caution/<int:project_pk>/prepare/<slug:step>/", deposit_views.deposit_prepare, name="deposit_prepare"),
    path("caution/<int:project_pk>/send/<slug:step>/", deposit_views.deposit_send, name="deposit_send"),
    path("caution/<int:project_pk>/pending.json", deposit_views.deposit_pending, name="deposit_pending"),
    path("caution/<int:project_pk>/recuperer/", deposit_views.deposit_refund, name="deposit_refund"),
    path("caution/<int:project_pk>/signaler/", deposit_views.deposit_report, name="deposit_report"),
]

urlpatterns = [
    path("pay/", include(pay_urlpatterns)),
    path("fonds/", deposit_views.fund_page, name="fund_page"),
]
