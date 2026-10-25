from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    # Pages
    path("projets/", views.project_list, name="project_list"),
    path("projets/nouveau/", views.project_create, name="project_create"),
    path("projets/<int:pk>/", views.project_detail, name="project_detail"),
    path("taches/", views.board, name="board"),
    path("taches/<int:pk>/", views.task_detail, name="task_detail"),
    path("mes-projets/", views.my_projects, name="my_projects"),
    # JSON (fetch via Lowbid.api)
    path("projets/<int:pk>/taches/ajouter/", views.task_add, name="task_add"),
    path("taches/<int:pk>/supprimer/", views.task_delete, name="task_delete"),
    path("taches/<int:pk>/postuler/", views.apply_create, name="apply_create"),
    path("taches/<int:pk>/choisir/<int:app_pk>/", views.task_choose, name="task_choose"),
    path("taches/<int:pk>/livrer/", views.task_deliver, name="task_deliver"),
    path("taches/<int:pk>/valider/", views.task_validate, name="task_validate"),
    path("taches/<int:pk>/modifications/", views.task_request_changes, name="task_request_changes"),
    path("taches/<int:pk>/candidats.json", views.task_candidates_json, name="task_candidates_json"),
]
