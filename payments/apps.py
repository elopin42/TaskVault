from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def ready(self) -> None:
        from django.db.models.signals import post_save

        from payments import checks  # noqa: F401  (registers the deposit key checks)
        from payments.deposits import on_project_saved

        # A project that becomes closed / cancelled settles its funded deposits once the commit is done.
        post_save.connect(on_project_saved, sender="projects.Project", dispatch_uid="payments.deposits.on_project_saved")
