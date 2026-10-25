"""projects side of the publication deposit: published_at at creation, cancel_project, the public lists
hiding unpublished / cancelled projects, my_projects with a cancelled project. No network."""

import json

from django.test import TestCase, override_settings
from django.urls import reverse

from payments.tests_deposit import DEPOSIT_SETTINGS
from payments.tests_flow import JSON, login, make_wallet
from projects import services
from payments.models import ProjectDeposit
from projects.models import Application, Project, Task
from projects.services import ProjectError

DIRECT = {"LOWBID_PAYMENT_MODE": "direct", "TRUSTLESS_WORK_API_KEY": ""}


class PublicationTests(TestCase):
    def setUp(self):
        self.company, _ = make_wallet("company")
        self.freelance, _ = make_wallet("freelance")

    @override_settings(**DIRECT)
    def test_direct_mode_publishes_at_creation_and_apply_works(self):
        project = services.create_project(self.company, "Direct project", "Body.")
        self.assertIsNotNone(project.published_at)
        task = services.add_task(project, self.company, "Task", "", "100", [])
        services.apply(task, self.freelance, "hi", [])
        self.assertEqual(Application.objects.count(), 1)

    @override_settings(**DEPOSIT_SETTINGS)
    def test_escrow_mode_with_deposits_starts_unpublished(self):
        project = services.create_project(self.company, "Escrow project", "Body.")
        self.assertIsNone(project.published_at)

    @override_settings(**{**DEPOSIT_SETTINGS, "LOWBID_DEPOSIT_ENABLED": False})
    def test_escrow_mode_without_deposits_publishes_at_creation(self):
        self.assertIsNotNone(services.create_project(self.company, "Escrow project", "Body.").published_at)

    @override_settings(**DEPOSIT_SETTINGS)
    def test_create_form_follows_the_same_rule(self):
        login(self.client, self.company)
        r = self.client.post(reverse("projects:project_create"), {"title": "Form project", "description": "Body."})
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(Project.objects.get(title="Form project").published_at)
        with override_settings(**DIRECT):
            self.client.post(reverse("projects:project_create"), {"title": "Direct form", "description": "Body."})
        self.assertIsNotNone(Project.objects.get(title="Direct form").published_at)


@override_settings(**DIRECT)
class CancelProjectTests(TestCase):
    def setUp(self):
        self.company, _ = make_wallet("company")
        self.freelance, _ = make_wallet("freelance")
        self.project = services.create_project(self.company, "To cancel", "Body.")
        self.task = services.add_task(self.project, self.company, "Task", "", "100", [])

    def test_company_only(self):
        with self.assertRaises(ProjectError) as ctx:
            services.cancel_project(self.project, self.freelance)
        self.assertEqual(ctx.exception.code, "forbidden")

    def test_cancel_then_refused_twice_and_no_new_task_nor_choice(self):
        services.apply(self.task, self.freelance, "hi", [])
        project = services.cancel_project(self.project, self.company)
        self.assertEqual((project.status, project.status_label, project.badge_class), ("cancelled", "Cancelled", "ui-badge-neutral"))
        self.assertTrue(project.is_cancelled)
        for call in (
            lambda: services.cancel_project(self.project, self.company),
            lambda: services.add_task(self.project, self.company, "More", "", "10", []),
            lambda: services.choose(self.task, Application.objects.get(), self.company),
        ):
            with self.assertRaises(ProjectError) as ctx:
                call()
            self.assertEqual(ctx.exception.code, "wrong_state")

    def test_refused_once_a_freelance_is_chosen(self):
        services.apply(self.task, self.freelance, "hi", [])
        services.choose(self.task, Application.objects.get(), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.cancel_project(self.project, self.company)
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_refused_when_closed(self):
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CLOSED)
        with self.assertRaises(ProjectError) as ctx:
            services.cancel_project(self.project, self.company)
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_endpoint(self):
        url = reverse("projects:project_cancel", args=[self.project.pk])
        login(self.client, self.freelance)
        self.assertEqual(self.client.post(url, **JSON).status_code, 403)
        login(self.client, self.company)
        r = self.client.post(url, data=json.dumps({}), content_type="application/json", **JSON)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "cancelled"))
        self.assertEqual(self.client.post(url, **JSON).status_code, 409)


class ListingTests(TestCase):
    def setUp(self):
        self.company, _ = make_wallet("company")
        self.freelance, _ = make_wallet("freelance")
        with override_settings(**DEPOSIT_SETTINGS):
            self.hidden = services.create_project(self.company, "Hidden unpublished", "Body.")
            services.add_task(self.hidden, self.company, "Hidden task", "", "100", [])
        with override_settings(**DIRECT):
            self.public = services.create_project(self.company, "Public project", "Body.")
            services.add_task(self.public, self.company, "Public task", "", "100", [])
            self.cancelled = services.create_project(self.company, "Cancelled project", "Body.")
            services.add_task(self.cancelled, self.company, "Cancelled task", "", "100", [])
            services.cancel_project(self.cancelled, self.company)

    def test_project_list_hides_unpublished(self):
        html = self.client.get(reverse("projects:project_list")).content.decode()
        self.assertIn("Public project", html)
        self.assertNotIn("Hidden unpublished", html)
        self.assertNotIn("Cancelled project", html, "cancelled projects are not in progress")
        html = self.client.get(reverse("projects:project_list") + "?tab=closed").content.decode()
        self.assertIn("Cancelled project", html)

    def test_board_hides_unpublished_and_cancelled(self):
        login(self.client, self.freelance)
        html = self.client.get(reverse("projects:board")).content.decode()
        self.assertIn("Public task", html)
        self.assertNotIn("Hidden task", html)
        self.assertNotIn("Cancelled task", html)

    def test_my_projects_with_a_cancelled_project(self):
        login(self.client, self.company)
        r = self.client.get(reverse("projects:my_projects") + "?tab=all")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["kpis"]["cancelled"], 1)
        self.assertContains(r, "Cancelled project")
        self.assertContains(r, "Hidden unpublished", msg_prefix="the company still sees its unpublished project")
        r = self.client.get(reverse("projects:my_projects") + "?tab=done")
        self.assertContains(r, "Cancelled project")

    def test_landing_hides_unpublished(self):
        html = self.client.get(reverse("core:landing")).content.decode()
        self.assertNotIn("Hidden unpublished", html)

    def test_unpublished_badge_on_the_project_page(self):
        self.assertContains(self.client.get(reverse("projects:project_detail", args=[self.hidden.pk])), "data-unpublished")
        self.assertNotContains(self.client.get(reverse("projects:project_detail", args=[self.public.pk])), "data-unpublished")
        self.assertEqual(Task.objects.filter(project=self.hidden).count(), 1)


@override_settings(**DEPOSIT_SETTINGS)
class DeleteGuardTests(TestCase):
    """R72: while the deposit is locked, a task that received applications cannot be deleted."""

    def setUp(self):
        self.company, _ = make_wallet("company")
        self.freelance, _ = make_wallet("freelance")
        self.project = services.create_project(self.company, "Guarded project", "Body.")
        self.task = services.add_task(self.project, self.company, "Task", "", "100", [])
        self.empty = services.add_task(self.project, self.company, "Empty", "", "50", [])
        ProjectDeposit.objects.create(
            project=self.project, status=ProjectDeposit.Status.FUNDED, amount="5", covered_budget="1000",
            payer_address=self.company.stellar_address, platform_address="G" + "A" * 55,
            resolver_address="G" + "B" * 55, fund_address="G" + "C" * 55,
        )
        Project.objects.filter(pk=self.project.pk).update(published_at=self.project.created_at)
        services.apply(self.task, self.freelance, "hi", [])

    def test_task_with_applications_cannot_be_deleted_while_locked(self):
        with self.assertRaises(ProjectError) as ctx:
            services.delete_task(self.task, self.company)
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())
        self.assertEqual(Application.objects.count(), 1)

    def test_task_without_applications_can_be_deleted(self):
        services.delete_task(self.empty, self.company)
        self.assertFalse(Task.objects.filter(pk=self.empty.pk).exists())

    def test_guard_only_while_deposits_are_active(self):
        with override_settings(LOWBID_DEPOSIT_ENABLED=False):
            services.delete_task(self.task, self.company)
        self.assertFalse(Task.objects.filter(pk=self.task.pk).exists())
