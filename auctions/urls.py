from django.urls import path

from . import views

app_name = "auctions"

urlpatterns = [
    # Pages
    path("besoins/", views.need_list, name="need_list"),
    path("besoins/nouveau/", views.need_create, name="need_create"),
    path("besoins/<int:pk>/", views.need_detail, name="need_detail"),
    path("mes-encheres/", views.my_bids, name="my_bids"),
    path("mes-besoins/", views.my_needs, name="my_needs"),
    # JSON (fetch via Lowbid.api)
    path("besoins/<int:pk>/encheres.json", views.need_bids_json, name="need_bids_json"),
    path("besoins/<int:pk>/encherir/", views.bid_create, name="bid_create"),
    path("besoins/<int:pk>/cloturer/", views.need_close, name="need_close"),
    path("besoins/<int:pk>/choisir/<int:bid_pk>/", views.need_award, name="need_award"),
    path("besoins/<int:pk>/annuler/", views.need_cancel, name="need_cancel"),
]
