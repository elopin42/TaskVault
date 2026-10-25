import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from payments.models import Escrow

from . import services
from .models import Application, Delivery, Project, Rating, RevisionRequest, Task
from .scoring import company_history, is_validated, recommended_pk, score_application, score_parts
from .services import ProjectError

JSON = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "fetch"}


GIT_SHA = "a" * 39 + "b"  # a 40-hex git commit id
SHA256 = "0123456789abcdef" * 4  # a 64-hex digest


def make_wallet(name: str = "") -> WalletUser:
    return WalletUser.objects.create(stellar_address=Keypair.random().public_key, display_name=name)


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


def app_of(task: Task, wallet: WalletUser) -> Application:
    return Application.objects.get(task=task, freelancer=wallet)


class BaseProjectTest(TestCase):
    """Company + two freelances (A, B) + the §8 project with its three tasks, nothing applied yet."""

    def setUp(self):
        self.company = make_wallet("Studio Nova")
        self.a = make_wallet("Yanis")
        self.b = make_wallet("Nora")
        self.project = services.create_project(self.company, "Plateforme de réservation", "Trois tâches à prix fixe.")
        self.t1 = services.add_task(self.project, self.company, "Landing page", "Page d’accueil.", "300", ["django", "ui"])
        self.t2 = services.add_task(self.project, self.company, "Intégration Freighter", "", "500", ["stellar", "js"])
        self.t3 = services.add_task(self.project, self.company, "Dashboard", "", "400", ["django", "charts"])

    def pay_t1_to_a(self, note: int = 5) -> Task:
        """Run the §8 first half: A and B apply to T1, A is chosen, delivers, gets validated with `note`,
        then the payment is confirmed (what payments.confirm_release / confirm_direct_pay do: mark_paid)."""
        services.apply(self.t1, self.a, "A", ["django", "ui"])
        services.apply(self.t1, self.b, "B", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://github.com/studio-nova/booking/pull/1")
        services.validate(self.t1, self.company, note, "Parfait")
        return services.mark_paid(self.t1)

    def post_json(self, client, url, body=None):
        return client.post(url, data=body or {}, content_type="application/json", **JSON)


# --- parsing helpers -------------------------------------------------------------------

class HelperTests(TestCase):
    def test_clean_tags(self):
        self.assertEqual(services.clean_tags("Django, STELLAR  ui, django"), ["django", "stellar", "ui"])
        self.assertEqual(services.clean_tags(["Soroban ", "  "]), ["soroban"])
        self.assertEqual(services.clean_tags(None), [])
        self.assertEqual(services.clean_tags("Éducation"), ["education"])
        with self.assertRaises(ProjectError) as ctx:
            services.clean_tags("a, b, c, d")
        self.assertEqual(ctx.exception.code, "bad_tags")
        with self.assertRaises(ProjectError):
            services.clean_tags("x" * 30)
        with self.assertRaises(ProjectError):
            services.clean_tags({"not": "a list"})

    def test_parse_price(self):
        self.assertEqual(services.parse_price("300"), Decimal("300"))
        self.assertEqual(services.parse_price("12,5"), Decimal("12.5"))
        self.assertEqual(services.parse_price("400.1234567"), Decimal("400.1234567"))
        for bad in ("0", "-5", "abc", "1.12345678", None, "1e12"):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.parse_price(bad)
            self.assertEqual(ctx.exception.code, "invalid")

    def test_parse_note(self):
        for n in (1, "3", " 5 "):
            self.assertIsInstance(services.parse_note(n), int)
        for bad in (0, 6, "x", None, "2.5"):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.parse_note(bad)
            self.assertEqual(ctx.exception.code, "invalid")

    def test_dec_str(self):
        self.assertEqual(services.dec_str(Decimal("500.0000000")), "500")
        self.assertEqual(services.dec_str(Decimal("400.5000000")), "400.5")
        self.assertEqual(services.dec_str("300"), "300")

    def test_clean_hash(self):
        """R30: "" allowed; else exactly 40 hex (git commit) or 64 hex (SHA-256), lowercased."""
        git = "a" * 39 + "b"
        sha = "0123456789abcdef" * 4
        self.assertEqual(services.clean_hash(git), git)
        self.assertEqual(services.clean_hash(sha), sha)
        self.assertEqual(services.clean_hash("  " + git.upper() + " "), git, "uppercase normalised, whitespace stripped")
        self.assertEqual(services.clean_hash(""), "")
        self.assertEqual(services.clean_hash(None), "")
        self.assertEqual(services.clean_hash("   "), "")
        for bad in (git[:-1], git + "a", sha[:-1], sha + "0", "g" * 40, "0x" + git[2:], "é" * 40, git[:-1] + " "):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.clean_hash(bad)
            self.assertEqual(ctx.exception.code, "invalid")

    def test_clean_source_link(self):
        self.assertEqual(services.clean_source_link(""), "")
        self.assertEqual(services.clean_source_link(None), "")
        self.assertEqual(services.clean_source_link(" https://github.com/x/y.git "), "https://github.com/x/y.git")
        for bad in ("github.com/x", "ftp://x.y", "https://" + "x" * 500):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.clean_source_link(bad)
            self.assertEqual(ctx.exception.code, "invalid")


# --- company: project + tasks ---------------------------------------------------------------

class CreateProjectTests(TestCase):
    def test_create_project_is_draft(self):
        company = make_wallet()
        project = services.create_project(company, "  Mon projet ", "Une description.")
        self.assertEqual(project.status, Project.Status.DRAFT)
        self.assertEqual(project.title, "Mon projet")
        self.assertEqual(project.status_label, "Draft")
        self.assertEqual(project.total_amount, Decimal("0"))
        self.assertEqual(project.tasks_count, 0)
        self.assertTrue(project.is_company(company))
        self.assertFalse(project.is_company(None))

    def test_create_project_validates(self):
        company = make_wallet()
        with self.assertRaises(ProjectError) as ctx:
            services.create_project(company, "ab", "desc")
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(ProjectError) as ctx:
            services.create_project(company, "Un titre", "   ")
        self.assertEqual(ctx.exception.code, "invalid")


class AddTaskTests(BaseProjectTest):
    def test_tasks_are_open_ordered_and_summed(self):
        self.assertEqual([t.status for t in (self.t1, self.t2, self.t3)], ["open"] * 3)
        self.assertEqual([t.position for t in (self.t1, self.t2, self.t3)], [1, 2, 3])
        self.assertEqual(self.t1.tags, ["django", "ui"])
        self.assertEqual(self.project.total_amount, Decimal("1200"))
        annotated = Project.objects.with_totals().get(pk=self.project.pk)
        self.assertEqual(annotated.total, Decimal("1200"))
        self.assertEqual(annotated.tasks_total, 3)
        self.assertEqual(annotated.open_total, 3)
        self.assertEqual(annotated.paid_total, 0)

    def test_only_the_company_adds_tasks(self):
        with self.assertRaises(ProjectError) as ctx:
            services.add_task(self.project, self.a, "Hack", "", "1", [])
        self.assertEqual(ctx.exception.code, "forbidden")
        with self.assertRaises(ProjectError) as ctx:
            services.add_task(self.project, None, "Hack", "", "1", [])
        self.assertEqual(ctx.exception.code, "forbidden")

    def test_until_closed(self):
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.FUNDED)
        task = services.add_task(self.project, self.company, "Encore une", "", "10", [])  # one escrow per task: funded ≠ frozen
        self.assertEqual(task.status, "open")
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CLOSED)
        with self.assertRaises(ProjectError) as ctx:
            services.add_task(self.project, self.company, "Trop tard", "", "10", [])
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_task_validation(self):
        with self.assertRaises(ProjectError) as ctx:
            services.add_task(self.project, self.company, "ab", "", "10", [])
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(ProjectError) as ctx:
            services.add_task(self.project, self.company, "Tâche", "", "0", [])
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(ProjectError) as ctx:
            services.add_task(self.project, self.company, "Tâche", "", "10", "a b c d")
        self.assertEqual(ctx.exception.code, "bad_tags")


class DeleteTaskTests(BaseProjectTest):
    def test_company_deletes_an_open_task_of_a_draft_project(self):
        services.apply(self.t3, self.a, "", [])
        services.delete_task(self.t3, self.company)
        self.assertFalse(Task.objects.filter(pk=self.t3.pk).exists())
        self.assertFalse(Application.objects.filter(task_id=self.t3.pk).exists(), "applications cascade")

    def test_delete_is_gated(self):
        with self.assertRaises(ProjectError) as ctx:
            services.delete_task(self.t3, self.a)
        self.assertEqual(ctx.exception.code, "forbidden")
        services.apply(self.t3, self.a, "", [])
        services.choose(self.t3, app_of(self.t3, self.a), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.delete_task(self.t3, self.company)
        self.assertEqual(ctx.exception.code, "wrong_state")
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.FUNDED)
        services.delete_task(self.t2, self.company)  # still open → deletable whatever the project status
        self.assertFalse(Task.objects.filter(pk=self.t2.pk).exists())


# --- freelance: apply ---------------------------------------------------------------------------

class ApplyTests(BaseProjectTest):
    def test_apply_creates_a_pending_scored_application(self):
        app = services.apply(self.t1, self.a, "  Je prends.  ", "Django, UI")
        self.assertEqual(app.status, Application.Status.PENDING)
        self.assertEqual(app.message, "Je prends.")
        self.assertEqual(app.tags, ["django", "ui"])
        self.assertEqual(app.score, Decimal("20.0"), "no history: only the tag ratio counts")
        self.assertEqual(app.status_label, "Pending")
        self.assertEqual(self.t1.applications_count, 1)
        self.assertEqual(self.t1.application_for(self.a), app)
        self.assertIsNone(self.t1.application_for(self.b))

    def test_anyone_may_apply_even_without_history(self):
        newcomer = make_wallet()
        app = services.apply(self.t2, newcomer, "", [])
        self.assertEqual(app.score, Decimal("0.0"))

    def test_company_cannot_apply_to_its_own_task(self):
        with self.assertRaises(ProjectError) as ctx:
            services.apply(self.t1, self.company, "", [])
        self.assertEqual(ctx.exception.code, "own_task")

    def test_one_application_per_freelancer(self):
        services.apply(self.t1, self.a, "", [])
        with self.assertRaises(ProjectError) as ctx:
            services.apply(self.t1, self.a, "again", [])
        self.assertEqual(ctx.exception.code, "duplicate")
        self.assertEqual(Application.objects.filter(task=self.t1).count(), 1)

    def test_apply_needs_an_open_task(self):
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.apply(self.t1, self.b, "", [])
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_apply_validates_message_and_tags(self):
        with self.assertRaises(ProjectError) as ctx:
            services.apply(self.t1, self.a, "x" * 281, [])
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(ProjectError) as ctx:
            services.apply(self.t1, self.a, "", ["a", "b", "c", "d"])
        self.assertEqual(ctx.exception.code, "bad_tags")
        self.assertEqual(Application.objects.count(), 0)

    def test_apply_with_a_price_up_to_the_budget(self):
        app = services.apply(self.t1, self.a, "", [], "249.50")
        self.assertEqual(app.price, Decimal("249.50"))
        self.assertEqual(services.apply(self.t1, self.b, "", [], "300").price, Decimal("300"))
        self.assertEqual(services.apply(self.t2, self.a, "", []).price, Decimal("500"), "no price = the budget")

    def test_apply_refuses_a_price_over_the_budget_or_not_positive(self):
        for raw, code in (("300.01", "over_budget"), ("0", "invalid"), ("-5", "invalid"), ("abc", "invalid")):
            with self.assertRaises(ProjectError) as ctx:
                services.apply(self.t1, self.a, "", [], raw)
            self.assertEqual(ctx.exception.code, code, raw)
        self.assertEqual(Application.objects.count(), 0)


# --- company: choose ----------------------------------------------------------------------------

class ChooseTests(BaseProjectTest):
    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "A", ["django", "ui"])
        services.apply(self.t1, self.b, "B", ["django"])

    def test_choose_assigns_and_rejects_the_others(self):
        task = services.choose(self.t1, app_of(self.t1, self.b), self.company)
        self.assertEqual(task.status, Task.Status.TAKEN)
        self.assertEqual(task.assigned_to, self.b)
        self.assertEqual(app_of(self.t1, self.b).status, Application.Status.CHOSEN)
        self.assertEqual(app_of(self.t1, self.a).status, Application.Status.REJECTED)
        self.assertEqual(task.status_label, "Taken")
        self.assertTrue(task.is_assignee(self.b))

    def test_the_chosen_price_becomes_the_task_price(self):
        services.apply(self.t2, self.a, "", [], "420")
        services.apply(self.t2, self.b, "", [], "380")
        task = services.choose(self.t2, app_of(self.t2, self.a), self.company)
        self.assertEqual(task.price, Decimal("420"))
        self.assertEqual(Task.objects.get(pk=self.t2.pk).price, Decimal("420"))

    def test_any_candidate_may_be_chosen_not_only_the_recommended(self):
        # B has the lower score (10 vs 20) and is still a valid choice.
        self.assertLess(app_of(self.t1, self.b).score, app_of(self.t1, self.a).score)
        self.assertEqual(services.choose(self.t1, app_of(self.t1, self.b), self.company).assigned_to, self.b)

    def test_only_the_company_chooses(self):
        with self.assertRaises(ProjectError) as ctx:
            services.choose(self.t1, app_of(self.t1, self.a), self.a)
        self.assertEqual(ctx.exception.code, "forbidden")

    def test_choose_twice_is_refused(self):
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.choose(self.t1, app_of(self.t1, self.b), self.company)
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_application_must_belong_to_the_task(self):
        other = services.apply(self.t2, self.a, "", [])
        with self.assertRaises(ProjectError) as ctx:
            services.choose(self.t1, other, self.company)
        self.assertEqual(ctx.exception.code, "invalid")

    def test_choosing_does_not_need_funding(self):
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.FUNDED)
        self.assertEqual(services.choose(self.t1, app_of(self.t1, self.a), self.company).status, Task.Status.TAKEN)


# --- freelance: deliver -------------------------------------------------------------------------

class DeliverTests(BaseProjectTest):
    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "", ["django"])
        services.apply(self.t1, self.b, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)

    def test_assignee_delivers_a_link(self):
        task = services.deliver(self.t1, self.a, " https://github.com/x/y/pull/1 ")
        self.assertEqual(task.status, Task.Status.DELIVERED)
        self.assertEqual(task.delivery_link, "https://github.com/x/y/pull/1")
        self.assertIsNotNone(task.delivered_at)

    def test_only_the_assignee_delivers(self):
        for who in (self.b, self.company, None):
            with self.assertRaises(ProjectError, msg=who) as ctx:
                services.deliver(self.t1, who, "https://x.y")
            self.assertEqual(ctx.exception.code, "not_assigned")

    def test_only_a_taken_task(self):
        with self.assertRaises(ProjectError) as ctx:
            services.deliver(self.t2, self.a, "https://x.y")
        self.assertEqual(ctx.exception.code, "not_assigned")
        services.deliver(self.t1, self.a, "https://x.y")
        with self.assertRaises(ProjectError) as ctx:
            services.deliver(self.t1, self.a, "https://x.y/again")
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_link_validation(self):
        for bad in ("", "   ", "github.com/x", "ftp://x.y", "https://" + "x" * 500):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.deliver(self.t1, self.a, bad)
            self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.TAKEN)

    def test_deliver_stores_the_fingerprint_and_the_source_link(self):
        task = services.deliver(
            self.t1, self.a, "https://demo.x.y", delivery_hash=GIT_SHA.upper(), source_link=" https://github.com/x/y "
        )
        self.assertEqual((task.status, task.delivery_hash, task.source_link), ("delivered", GIT_SHA, "https://github.com/x/y"))
        fresh = Task.objects.get(pk=self.t1.pk)
        self.assertEqual((fresh.delivery_hash, fresh.source_link), (GIT_SHA, "https://github.com/x/y"))

    def test_deliver_defaults_to_no_fingerprint_and_no_source(self):
        task = services.deliver(self.t1, self.a, "https://demo.x.y")
        self.assertEqual((task.delivery_hash, task.source_link), ("", ""))

    def test_bad_fingerprint_or_source_link_changes_nothing(self):
        with self.assertRaises(ProjectError) as ctx:
            services.deliver(self.t1, self.a, "https://demo.x.y", delivery_hash="abc")
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(ProjectError) as ctx:
            services.deliver(self.t1, self.a, "https://demo.x.y", source_link="not-a-link")
        self.assertEqual(ctx.exception.code, "invalid")
        fresh = Task.objects.get(pk=self.t1.pk)
        self.assertEqual((fresh.status, fresh.delivery_link, fresh.delivery_hash, fresh.source_link), ("taken", "", "", ""))


class SourceVisibilityTests(BaseProjectTest):
    """R31: the assignee always, the company only once paid, anyone else never."""

    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "", ["django"])
        services.apply(self.t1, self.b, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        self.t1.refresh_from_db()

    def test_before_delivery_and_after_delivery(self):
        for task in (self.t1, services.deliver(self.t1, self.a, "https://demo.x.y", source_link="https://src.x.y")):
            self.assertTrue(services.source_visible(task, self.a), "assignee")
            self.assertFalse(services.source_visible(task, self.company), "company before payment")
            self.assertFalse(services.source_visible(task, self.b), "another freelance")
            self.assertFalse(services.source_visible(task, None), "anonymous")

    def test_company_sees_it_once_paid(self):
        services.deliver(self.t1, self.a, "https://demo.x.y", source_link="https://src.x.y")
        services.validate(self.t1, self.company, 5)
        self.assertFalse(services.source_visible(Task.objects.get(pk=self.t1.pk), self.company), "rated but not paid")
        task = services.mark_paid(self.t1)
        self.assertTrue(services.source_visible(task, self.company))
        self.assertTrue(services.source_visible(task, self.a))
        self.assertFalse(services.source_visible(task, self.b))
        self.assertFalse(services.source_visible(task, None))

    def test_open_task_is_visible_to_nobody_but_has_no_assignee(self):
        self.assertFalse(services.source_visible(self.t2, self.company))
        self.assertFalse(services.source_visible(self.t2, self.a))


# --- company: validate + rate → payment hook → mark_paid --------------------------------------------

class ValidateTests(BaseProjectTest):
    def test_validate_stores_the_rating_and_hands_over_to_payments(self):
        """validate() saves the Rating and calls payments.on_task_validated: the task stays `delivered`
        (nothing is paid without a signature), the Escrow row exists, mark_paid is payments' job."""
        services.apply(self.t1, self.a, "A", ["django", "ui"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://github.com/studio-nova/booking/pull/1")
        task = services.validate(self.t1, self.company, 5, "Parfait")
        self.assertEqual(task.status, Task.Status.DELIVERED)
        self.assertIsNone(task.paid_at)
        rating = Rating.objects.get(task=task)
        self.assertEqual((rating.note, rating.comment, rating.company, rating.freelancer), (5, "Parfait", self.company, self.a))
        escrow = Escrow.objects.get(task=task)
        self.assertEqual((escrow.mode, escrow.status, escrow.amount), (Escrow.Mode.DIRECT, Escrow.Status.CREATED, Decimal("300")))
        self.assertEqual((escrow.payer_address, escrow.payee_address), (self.company.stellar_address, self.a.stellar_address))
        task = services.mark_paid(task)
        self.assertEqual(task.status, Task.Status.PAID)
        self.assertIsNotNone(task.paid_at)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.DRAFT, "two tasks remain")

    @override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k", LOWBID_DEPOSIT_ENABLED=False)
    def test_db_only_delivery_is_refused_in_escrow_mode(self):
        services.apply(self.t1, self.a, "A", ["django", "ui"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.deliver(self.t1, self.a, "https://x.y/pr")
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertIn("escrow", ctx.exception.message.lower())
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.TAKEN)
        # payments confirms the on-chain milestone change with on_chain=True
        task = services.deliver(self.t1, self.a, "https://x.y/pr", on_chain=True)
        self.assertEqual(task.status, Task.Status.DELIVERED)

    def test_project_closes_when_every_task_is_paid(self):
        services.delete_task(self.t2, self.company)
        services.delete_task(self.t3, self.company)
        self.pay_t1_to_a(4)
        project = Project.objects.get(pk=self.project.pk)
        self.assertEqual(project.status, Project.Status.CLOSED)
        self.assertEqual(project.progress_pct, 100)

    def test_validate_is_gated(self):
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.validate(self.t1, self.company, 5)
        self.assertEqual(ctx.exception.code, "wrong_state", "not delivered yet")
        services.deliver(self.t1, self.a, "https://x.y")
        with self.assertRaises(ProjectError) as ctx:
            services.validate(self.t1, self.a, 5)
        self.assertEqual(ctx.exception.code, "forbidden")
        for bad in (0, 6, "x"):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.validate(self.t1, self.company, bad)
            self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(Rating.objects.count(), 0)
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.DELIVERED)

    def test_one_rating_per_task(self):
        self.pay_t1_to_a()
        Task.objects.filter(pk=self.t1.pk).update(status=Task.Status.DELIVERED)
        with self.assertRaises(ProjectError) as ctx:
            services.validate(self.t1, self.company, 3)
        self.assertEqual(ctx.exception.code, "duplicate")

    def test_mark_paid_is_idempotent_and_is_the_only_way_to_paid(self):
        task = self.pay_t1_to_a()
        first = task.paid_at
        again = services.mark_paid(task)
        self.assertEqual(again.paid_at, first)
        self.assertTrue(callable(services._after_validate) and callable(services._before_deliver), "payment hooks")

    def test_comment_is_optional_and_truncated(self):
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://x.y")
        services.validate(self.t1, self.company, "4", "y" * 300)
        self.assertEqual(len(Rating.objects.get(task=self.t1).comment), 280)


# --- scoring (docs/PRODUCT.md) -------------------------------------------------------------------------

class ScoringTests(BaseProjectTest):
    def test_section_8_numbers_a_90_b_20(self):
        self.pay_t1_to_a(5)
        a = services.apply(self.t2, self.a, "", ["stellar"])
        b = services.apply(self.t2, self.b, "", ["stellar", "js"])
        self.assertEqual(a.score, Decimal("90.0"), "40 + 5*8 + 20*(1/2)")
        self.assertEqual(b.score, Decimal("20.0"), "0 + 0 + 20*(2/2)")
        self.assertEqual(recommended_pk([a, b]), a.pk)
        self.assertTrue(is_validated(company_history(self.company, self.a)))
        self.assertFalse(is_validated(company_history(self.company, self.b)))

    def test_score_parts(self):
        parts = score_parts(["stellar", "js"], ["stellar"], {"paid_count": 1, "avg_note": Decimal("5")})
        self.assertEqual(parts, {"history_part": Decimal("40"), "rating_part": Decimal("40.0"), "tags_part": Decimal("10.0"), "total": Decimal("90.0")})
        parts = score_parts(["stellar", "js"], ["stellar", "js"], {"paid_count": 0, "avg_note": None})
        self.assertEqual(parts["total"], Decimal("20.0"))
        self.assertEqual(score_parts(["a", "b", "c"], ["a"], {"paid_count": 0, "avg_note": None})["total"], Decimal("6.7"))

    def test_no_task_tags_means_zero_tag_points(self):
        bare = services.add_task(self.project, self.company, "Sans tags", "", "10", [])
        self.assertEqual(services.apply(bare, self.a, "", ["django"]).score, Decimal("0.0"))

    def test_max_is_100(self):
        self.pay_t1_to_a(5)
        self.assertEqual(score_application(self.t2, self.a, ["stellar", "js"]), Decimal("100.0"))

    def test_history_is_per_company(self):
        self.pay_t1_to_a(5)
        other = make_wallet("Autre entreprise")
        project = services.create_project(other, "Autre projet", "Desc.")
        task = services.add_task(project, other, "Tâche", "", "10", ["stellar"])
        self.assertEqual(services.apply(task, self.a, "", ["stellar"]).score, Decimal("20.0"), "no history with THIS company")
        self.assertEqual(company_history(other, self.a), {"paid_count": 0, "avg_note": None, "ratings_count": 0})

    def test_validated_needs_a_paid_task_and_an_average_of_3(self):
        self.pay_t1_to_a(2)
        history = company_history(self.company, self.a)
        self.assertEqual(history["paid_count"], 1)
        self.assertEqual(history["avg_note"], Decimal("2"))
        self.assertFalse(is_validated(history))
        self.assertEqual(services.apply(self.t2, self.a, "", []).score, Decimal("56.0"), "40 + 2*8")

    def test_recommended_tie_goes_to_the_earliest_pending(self):
        a = services.apply(self.t2, self.a, "", ["stellar", "js"])
        b = services.apply(self.t2, self.b, "", ["stellar", "js"])
        self.assertEqual(a.score, b.score)
        self.assertEqual(recommended_pk([b, a]), a.pk)
        Application.objects.filter(pk=a.pk).update(status=Application.Status.REJECTED)
        a.refresh_from_db()
        self.assertEqual(recommended_pk([a, b]), b.pk)
        self.assertIsNone(recommended_pk([]))

    def test_rescore_after_a_rating_updates_pending_applications(self):
        a = services.apply(self.t2, self.a, "", ["stellar"])
        b = services.apply(self.t2, self.b, "", ["stellar", "js"])
        self.assertEqual((a.score, b.score), (Decimal("10.0"), Decimal("20.0")))
        self.pay_t1_to_a(5)  # history + rating change → open tasks of the company are rescored
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.score, b.score), (Decimal("90.0"), Decimal("20.0")))
        self.assertEqual(services.rescore(self.t2), 2)


# --- pages ------------------------------------------------------------------------------------------

class ProjectListViewTests(BaseProjectTest):
    def test_public_list_with_tabs_search_tag_and_sort(self):
        r = self.client.get(reverse("projects:project_list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Plateforme de réservation")
        self.assertContains(r, "project-card")
        self.assertContains(r, "Connect to post")
        self.assertEqual(r.context["total"], 1)
        self.assertEqual(r.context["popular_tags"][:1], ["django"])
        self.assertContains(self.client.get(reverse("projects:project_list") + "?q=freighter&tab=all"), "project-card")
        self.assertContains(self.client.get(reverse("projects:project_list") + "?q=zzzz"), "No projects")
        self.assertEqual(self.client.get(reverse("projects:project_list") + "?tag=stellar").context["total"], 1)
        self.assertEqual(self.client.get(reverse("projects:project_list") + "?tag=rust").context["total"], 0)
        self.assertEqual(self.client.get(reverse("projects:project_list") + "?tab=closed").context["total"], 0)
        self.assertEqual(self.client.get(reverse("projects:project_list") + "?sort=budget&tab=nope").context["sort"], "budget")

    def test_signed_in_list_links_to_create_and_board(self):
        login(self.client, self.a)
        r = self.client.get(reverse("projects:project_list"))
        self.assertContains(r, reverse("projects:project_create"))
        self.assertContains(r, reverse("projects:board"))


class ProjectCreateViewTests(BaseProjectTest):
    def test_anonymous_is_redirected(self):
        r = self.client.get(reverse("projects:project_create"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=/projets/nouveau/", r["Location"])

    def test_form_renders_and_creates(self):
        login(self.client, self.company)
        r = self.client.get(reverse("projects:project_create"))
        self.assertContains(r, 'id="id_title"')
        self.assertContains(r, 'id="id_description"')
        r = self.client.post(reverse("projects:project_create"), {"title": "Nouveau", "description": "Desc."})
        project = Project.objects.get(title="Nouveau")
        self.assertRedirects(r, reverse("projects:project_detail", args=[project.pk]))
        self.assertEqual(project.company, self.company)

    def test_invalid_form_shows_errors(self):
        login(self.client, self.company)
        r = self.client.post(reverse("projects:project_create"), {"title": "ab", "description": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "The title is too short.")
        self.assertEqual(Project.objects.count(), 1)


class ProjectDetailViewTests(BaseProjectTest):
    def url(self):
        return reverse("projects:project_detail", args=[self.project.pk])

    def test_company_view_has_task_form_candidates_and_disabled_fund_button(self):
        services.apply(self.t1, self.a, "", ["django"])
        services.apply(self.t1, self.b, "", [])
        login(self.client, self.company)
        r = self.client.get(self.url())
        html = r.content.decode()
        self.assertIn('data-tasks data-count="3"', html)
        self.assertEqual(html.count('class="task-row'), 3)
        self.assertIn('id="task-form"', html)
        for field in ("task-title", "task-description", "task-price", "task-tags"):
            self.assertIn(f'id="{field}"', html)
        self.assertIn("data-task-add", html)
        self.assertEqual(html.count("data-task-delete="), 3)
        self.assertIn('id="candidates-%d"' % self.t1.pk, html)
        self.assertEqual(html.count("data-choose="), 2, "a Choose button on EVERY candidate")
        self.assertIn("data-recommended", html)
        self.assertIn("window.LOWBID_PROJECT", html)
        self.assertIn(reverse("projects:task_add", args=[self.project.pk]), html)
        # direct mode (no Trustless Work key): no funding button, an honest note instead
        self.assertNotIn("data-fund", html)
        self.assertIn("Direct payment", html)
        with override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k", LOWBID_DEPOSIT_ENABLED=False):
            html = self.client.get(self.url()).content.decode()
        self.assertIn("data-fund", html)
        self.assertIn("disabled", html.split("data-fund", 1)[1][:80], "no chosen freelance → the button is disabled")
        self.assertIn("Choose a freelancer first", html)
        self.assertIn("Trustless Work fixes the escrow recipient", html)

    @override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k", LOWBID_DEPOSIT_ENABLED=False)
    def test_fund_button_enabled_once_a_freelance_is_chosen(self):
        login(self.client, self.company)
        empty = services.create_project(self.company, "Vide", "Rien.")
        self.assertNotContains(self.client.get(reverse("projects:project_detail", args=[empty.pk])), "data-fund")
        services.apply(self.t1, self.a, "", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn(f'data-fund data-pending-url="{reverse("payments:project_pending", args=[self.project.pk])}"', html)
        self.assertIn("1 assigned task to fund", html)
        self.assertIn('id="funding-panel"', html)
        self.assertIn("Preparing", html, "T1's escrow status in the banner")
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CLOSED)
        r = self.client.get(self.url())
        self.assertNotContains(r, "data-fund")
        self.assertNotContains(r, 'id="task-form"')

    def test_freelance_and_anonymous_views(self):
        services.apply(self.t1, self.a, "", ["django"])
        login(self.client, self.a)
        r = self.client.get(self.url())
        html = r.content.decode()
        self.assertNotIn('id="task-form"', html)
        self.assertNotIn("data-task-delete", html)
        self.assertNotIn("data-choose", html)
        self.assertNotIn("data-fund", html)
        self.assertIn("Applied", html, "the viewer's pending application is flagged on the row")
        self.client.logout()
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-wallet-connect")
        self.assertEqual(self.client.get(reverse("projects:project_detail", args=[9999])).status_code, 404)

    def test_delivered_task_shows_validate_cta_to_the_company(self):
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://x.y/pr")
        login(self.client, self.company)
        r = self.client.get(self.url())
        self.assertContains(r, "Validate + rate")
        self.assertContains(r, "#validate-panel")


class TaskDetailViewTests(BaseProjectTest):
    def url(self, task=None):
        return reverse("projects:task_detail", args=[(task or self.t1).pk])

    def test_freelance_sees_the_apply_form_then_their_application(self):
        login(self.client, self.a)
        html = self.client.get(self.url()).content.decode()
        for marker in ('id="apply-form"', 'id="apply-price"', 'data-budget="300"', 'data-error-for="price"', 'id="apply-message"', 'id="apply-tags"', "data-apply-submit", 'data-error-for="message"', 'data-error-for="tags"', 'data-error-for="_"', "window.LOWBID_TASK", 'data-candidates data-count="0"'):
            self.assertIn(marker, html, marker)
        self.assertIn(reverse("projects:apply_create", args=[self.t1.pk]), html)
        services.apply(self.t1, self.a, "Moi", ["django"], "275")
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="apply-form"', html)
        self.assertIn('id="my-application"', html)
        self.assertIn('data-my-price="275"', html)
        self.assertIn('data-bid-price="275"', html)
        self.assertIn("Your application", html)
        self.assertIn('data-candidates data-count="1"', html)

    def test_company_sees_choose_on_every_candidate_and_no_apply_form(self):
        services.apply(self.t1, self.a, "", ["django", "ui"])
        services.apply(self.t1, self.b, "", ["django"])
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="apply-form"', html)
        self.assertEqual(html.count("data-choose="), 2)
        self.assertEqual(html.count("data-recommended"), 1)
        self.assertIn('data-score="20.0"', html)
        self.assertIn('data-score="10.0"', html)
        rows = html.split('class="ui-list-row cand-row')
        self.assertIn(self.a.stellar_address, rows[1], "A (score 20) ranks first")
        self.assertIn(self.b.stellar_address, rows[2])

    def test_assignee_sees_the_deliver_form(self):
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        login(self.client, self.a)
        html = self.client.get(self.url()).content.decode()
        self.assertIn('id="deliver-panel"', html)
        self.assertIn('id="deliver-link"', html)
        self.assertIn('id="deliver-hash" name="delivery_hash"', html)
        self.assertIn('id="deliver-source" name="source_link"', html)
        self.assertIn("data-deliver", html)
        self.assertIn("Chosen", html)
        login(self.client, self.b)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="deliver-panel"', html)
        self.assertIn("A freelancer has been chosen", html)

    def test_source_link_hidden_from_the_company_until_paid(self):
        """R31 on the page: the fingerprint is public, [data-source-link] follows source_visible()."""
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://demo.x.y", delivery_hash=GIT_SHA, source_link="https://github.com/x/y-src")
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn(f'data-delivery-hash="{GIT_SHA}"', html)
        self.assertIn(f'data-copy="{GIT_SHA}"', html, "copy button on the fingerprint")
        self.assertNotIn("data-source-link", html)
        self.assertNotIn("https://github.com/x/y-src", html, "the source link is not even in the markup")
        self.assertIn("data-source-pending", html)
        self.assertIn("revealed once the task is paid", html)
        login(self.client, self.b)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn("data-source-link", html)
        self.assertNotIn("data-source-pending", html, "no hint for a stranger")
        self.assertNotIn("https://github.com/x/y-src", html)
        self.client.logout()
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn("https://github.com/x/y-src", html, "anonymous")
        self.assertIn(f'data-delivery-hash="{GIT_SHA}"', html, "the fingerprint is public")
        login(self.client, self.a)
        html = self.client.get(self.url()).content.decode()
        self.assertRegex(html, r'<a href="https://github\.com/x/y-src"[^>]*data-source-link', "the assignee always sees it")
        services.validate(self.t1, self.company, 5)
        services.mark_paid(self.t1)
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn("data-source-link", html)
        self.assertIn("https://github.com/x/y-src", html)
        self.assertNotIn("data-source-pending", html)

    def test_company_sees_the_rating_form_when_delivered(self):
        services.apply(self.t1, self.a, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://x.y/pr")
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn('id="validate-panel"', html)
        self.assertIn('novalidate data-validate data-validate-url="%s"' % reverse("projects:task_validate", args=[self.t1.pk]), html)
        self.assertEqual(html.count("data-rate="), 5)
        self.assertIn("data-validate-submit", html)
        self.assertIn("Validate and pay 300.00 USDC", html)
        self.assertIn('id="escrow-panel"', html)
        self.assertIn("https://x.y/pr", html)
        login(self.client, self.a)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="validate-panel"', html)
        self.assertIn("Delivery declared", html)

    def test_paid_task_shows_the_rating_and_badges_on_the_next_task(self):
        self.pay_t1_to_a(5)
        services.apply(self.t2, self.a, "", ["stellar"])
        services.apply(self.t2, self.b, "", ["stellar", "js"])
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn("Task paid", html)
        self.assertIn('data-rating="5"', html)
        self.assertNotIn("data-choose", html)
        self.assertIn("Chosen", html)
        self.assertIn("Not selected", html)
        html = self.client.get(self.url(self.t2)).content.decode()
        rows = html.split('class="ui-list-row cand-row')
        self.assertIn(self.a.stellar_address, rows[1])
        self.assertIn('data-badge="valide"', rows[1])
        self.assertIn("data-recommended", rows[1])
        self.assertIn('data-score="90.0"', rows[1])
        self.assertNotIn('data-badge="valide"', rows[2])
        self.assertIn('data-score="20.0"', rows[2])

    def test_no_template_syntax_leaks_and_decimals_are_plain(self):
        services.apply(self.t1, self.a, "", ["django"])
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        for token in ("{#", "#}", "{%", "%}", "{{", "}}"):
            self.assertNotIn(token, html, token)
        self.assertNotIn("0000000", html.split("LOWBID_TASK")[0])
        fragment = self.client.get(reverse("projects:task_candidates_json", args=[self.t1.pk])).json()["html"]
        self.assertNotIn("{#", fragment)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(self.client.get(reverse("projects:task_detail", args=[9999])).status_code, 404)


class BoardViewTests(BaseProjectTest):
    def test_board_requires_a_wallet(self):
        r = self.client.get(reverse("projects:board"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=/taches/", r["Location"])

    def test_columns_open_taken_delivered_paid(self):
        self.pay_t1_to_a(5)
        services.apply(self.t2, self.a, "", ["stellar"])
        services.apply(self.t3, self.b, "", ["django"])
        services.choose(self.t3, app_of(self.t3, self.b), self.company)
        login(self.client, self.a)
        r = self.client.get(reverse("projects:board"))
        html = r.content.decode()
        for col in ("open", "taken", "delivered", "paid"):
            self.assertIn(f'data-col="{col}"', html)
        cols = {c["key"]: [t.pk for t in c["tasks"]] for c in r.context["columns"]}
        self.assertEqual(cols, {"open": [self.t2.pk], "taken": [], "delivered": [], "paid": [self.t1.pk]})
        self.assertIn("data-applied", html, "my pending application is flagged")
        self.assertEqual(r.context["applied_count"], 1)
        self.assertEqual(r.context["earned_usdc"], Decimal("300"))
        login(self.client, self.b)
        r = self.client.get(reverse("projects:board"))
        cols = {c["key"]: [t.pk for t in c["tasks"]] for c in r.context["columns"]}
        self.assertEqual(cols["taken"], [self.t3.pk])
        self.assertEqual(cols["open"], [self.t2.pk])
        self.assertContains(r, "Deliver")

    def test_company_does_not_see_its_own_open_tasks(self):
        login(self.client, self.company)
        r = self.client.get(reverse("projects:board"))
        self.assertEqual(r.context["counts"]["open"], 0)
        self.assertContains(r, "No open tasks")


class MyProjectsViewTests(BaseProjectTest):
    def test_my_projects_table_and_kpis(self):
        services.apply(self.t1, self.a, "", [])
        login(self.client, self.company)
        r = self.client.get(reverse("projects:my_projects"))
        self.assertContains(r, "Plateforme de réservation")
        self.assertContains(r, "rcard")
        self.assertEqual(r.context["kpis"], {"draft": 1, "funded": 0, "closed": 0, "cancelled": 0, "to_choose": 1, "to_validate": 0})
        self.assertEqual(r.context["projects"][0].pending_apps, 1)
        self.assertTrue(r.context["projects"][0].attention)
        self.assertEqual(len(self.client.get(reverse("projects:my_projects") + "?tab=done").context["projects"]), 0)
        self.assertContains(self.client.get(reverse("projects:my_projects") + "?tab=done"), "Nothing here")

    def test_other_wallets_see_an_empty_list(self):
        login(self.client, self.a)
        r = self.client.get(reverse("projects:my_projects"))
        self.assertContains(r, "No projects in progress")
        self.assertEqual(self.client.get(reverse("projects:my_projects") + "?tab=nope").context["tab"], "active")


# --- JSON endpoints -----------------------------------------------------------------------------------

class TaskAddDeleteEndpointTests(BaseProjectTest):
    def test_company_adds_a_task(self):
        login(self.client, self.company)
        url = reverse("projects:task_add", args=[self.project.pk])
        r = self.post_json(self.client, url, {"title": "Tests e2e", "description": "", "price": "150", "tags": ["playwright"]})
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["task"]["price"], "150")
        self.assertEqual(data["count"], 4)
        self.assertEqual(data["total"], "1350")
        self.assertEqual(Task.objects.get(pk=data["task"]["id"]).position, 4)
        # classic form POST is accepted too
        r = self.client.post(url, {"title": "Encore", "price": "10", "tags": "a, b"}, **JSON)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["task"]["tags"], ["a", "b"])

    def test_task_add_errors_map_to_http(self):
        url = reverse("projects:task_add", args=[self.project.pk])
        self.assertEqual(self.post_json(self.client, url, {"title": "x"}).status_code, 401)
        login(self.client, self.a)
        r = self.post_json(self.client, url, {"title": "Hack", "price": "1"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "forbidden"))
        login(self.client, self.company)
        r = self.post_json(self.client, url, {"title": "Tâche", "price": "0"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        r = self.post_json(self.client, url, {"title": "Tâche", "price": "5", "tags": "a b c d"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "bad_tags"))
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CLOSED)
        r = self.post_json(self.client, url, {"title": "Tâche", "price": "5"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "wrong_state"))
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_task_delete(self):
        url = reverse("projects:task_delete", args=[self.t3.pk])
        login(self.client, self.a)
        self.assertEqual(self.post_json(self.client, url).status_code, 403)
        login(self.client, self.company)
        r = self.post_json(self.client, url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["redirect"], reverse("projects:project_detail", args=[self.project.pk]))
        self.assertFalse(Task.objects.filter(pk=self.t3.pk).exists())
        self.assertEqual(self.post_json(self.client, url).status_code, 404)


class ApplyChooseEndpointTests(BaseProjectTest):
    def test_apply_endpoint(self):
        url = reverse("projects:apply_create", args=[self.t1.pk])
        r = self.post_json(self.client, url, {"message": "x", "tags": ["django"], "price": "250"})
        self.assertEqual((r.status_code, r.json()["error"]), (401, "wallet_required"))
        login(self.client, self.a)
        r = self.post_json(self.client, url, {"message": "Je prends.", "tags": ["Django", "ui"]})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"), "the price is required")
        r = self.post_json(self.client, url, {"message": "Je prends.", "tags": ["Django", "ui"], "price": "250"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["application"]["score"], "20.0")
        self.assertEqual(r.json()["application"]["tags"], ["django", "ui"])
        self.assertEqual(r.json()["application"]["price"], "250")
        r = self.post_json(self.client, url, {"message": "encore", "price": "200"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "duplicate"))
        login(self.client, self.company)
        r = self.post_json(self.client, url, {"message": "moi", "price": "200"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "own_task"))
        login(self.client, self.b)
        r = self.post_json(self.client, url, {"tags": ["a", "b", "c", "d"], "price": "200"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "bad_tags"))
        self.assertIn("At most 3", r.json()["message"])
        r = self.post_json(self.client, url, {"price": "300.01"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "over_budget"))

    def test_choose_endpoint(self):
        services.apply(self.t1, self.a, "", [])
        services.apply(self.t1, self.b, "", [])
        url = reverse("projects:task_choose", args=[self.t1.pk, app_of(self.t1, self.b).pk])
        login(self.client, self.a)
        r = self.post_json(self.client, url)
        self.assertEqual((r.status_code, r.json()["error"]), (403, "forbidden"))
        login(self.client, self.company)
        r = self.post_json(self.client, url)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "taken")
        self.assertEqual(r.json()["assigned_to"], self.b.stellar_address)
        self.assertIn("Nora", r.json()["message"])
        r = self.post_json(self.client, reverse("projects:task_choose", args=[self.t1.pk, app_of(self.t1, self.a).pk]))
        self.assertEqual((r.status_code, r.json()["error"]), (409, "wrong_state"))
        other = services.apply(self.t2, self.a, "", [])
        self.assertEqual(self.post_json(self.client, reverse("projects:task_choose", args=[self.t1.pk, other.pk])).status_code, 404)


class DeliverValidateEndpointTests(BaseProjectTest):
    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "", ["django"])
        services.apply(self.t1, self.b, "", [])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)

    def test_deliver_endpoint(self):
        url = reverse("projects:task_deliver", args=[self.t1.pk])
        login(self.client, self.b)
        r = self.post_json(self.client, url, {"delivery_link": "https://x.y"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "not_assigned"))
        login(self.client, self.a)
        r = self.post_json(self.client, url, {"delivery_link": "pas-un-lien"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        r = self.post_json(self.client, url, {"delivery_link": "https://github.com/x/y/pull/1"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "delivered")
        r = self.post_json(self.client, url, {"delivery_link": "https://github.com/x/y/pull/2"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "wrong_state"))

    def test_deliver_endpoint_fingerprint_and_source(self):
        url = reverse("projects:task_deliver", args=[self.t1.pk])
        login(self.client, self.a)
        r = self.post_json(self.client, url, {"delivery_link": "https://x.y", "delivery_hash": "not-a-hash"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        self.assertIn("40-character", r.json()["message"])
        r = self.post_json(self.client, url, {"delivery_link": "https://x.y", "source_link": "nope"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.TAKEN, "nothing written")
        r = self.post_json(
            self.client, url, {"delivery_link": "https://x.y", "delivery_hash": SHA256.upper(), "source_link": "https://src.x.y"}
        )
        self.assertEqual(r.status_code, 200, r.content)
        task = Task.objects.get(pk=self.t1.pk)
        self.assertEqual((task.status, task.delivery_hash, task.source_link), ("delivered", SHA256, "https://src.x.y"))

    def test_validate_endpoint_saves_the_rating_and_returns_the_payment_step(self):
        url = reverse("projects:task_validate", args=[self.t1.pk])
        login(self.client, self.company)
        r = self.post_json(self.client, url, {"note": 5})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "wrong_state"), "not delivered yet")
        services.deliver(self.t1, self.a, "https://x.y")
        login(self.client, self.a)
        r = self.post_json(self.client, url, {"note": 5})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "forbidden"))
        login(self.client, self.company)
        r = self.post_json(self.client, url, {"note": 7})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        r = self.post_json(self.client, url, {"note": "5", "comment": "Top"})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["status"], "delivered", "nothing is paid before the signature")
        self.assertEqual(data["project_status"], "draft")
        self.assertEqual(data["next"]["step"], "direct_pay")
        self.assertTrue(data["next"]["mine"])
        self.assertEqual(data["next"]["prepare_url"], reverse("payments:prepare", kwargs={"task_pk": self.t1.pk, "step": "direct_pay"}))
        self.assertIn("Pay the freelancer", data["message"])
        self.assertEqual(Rating.objects.get(task=self.t1).comment, "Top")
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.DELIVERED)
        # a second validation is refused (the task is still delivered but rated)
        r = self.post_json(self.client, url, {"note": 4})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "duplicate"))


class CandidatesJsonTests(BaseProjectTest):
    def test_payload_and_fingerprint(self):
        url = reverse("projects:task_candidates_json", args=[self.t1.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        empty = r.json()
        self.assertEqual((empty["ok"], empty["count"], empty["status"], empty["candidates"]), (True, 0, "open", []))
        self.assertIn("No candidates", empty["html"])
        services.apply(self.t1, self.a, "Moi", ["django", "ui"])
        services.apply(self.t1, self.b, "", ["django"])
        data = self.client.get(url).json()
        self.assertNotEqual(data["fingerprint"], empty["fingerprint"])
        self.assertEqual(data["count"], 2)
        self.assertEqual([c["freelancer"] for c in data["candidates"]], [self.a.stellar_address, self.b.stellar_address])
        first = data["candidates"][0]
        self.assertEqual(first["score"], "20.0")
        self.assertEqual(first["parts"], {"history": "0.0", "rating": "0.0", "tags": "20.0"})
        self.assertTrue(first["recommended"])
        self.assertFalse(first["validated"])
        self.assertEqual(first["rank"], 1)
        self.assertNotIn("data-choose", data["html"], "anonymous: no Choose button")
        login(self.client, self.company)
        html = self.client.get(url).json()["html"]
        self.assertEqual(html.count("data-choose="), 2)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.get(reverse("projects:task_candidates_json", args=[9999])).status_code, 404)

    def test_rescoring_changes_the_fingerprint(self):
        services.apply(self.t2, self.a, "", ["stellar"])
        url = reverse("projects:task_candidates_json", args=[self.t2.pk])
        before = self.client.get(url).json()
        self.pay_t1_to_a(5)
        after = self.client.get(url).json()
        self.assertEqual(before["candidates"][0]["score"], "10.0")
        self.assertEqual(after["candidates"][0]["score"], "90.0")
        self.assertTrue(after["candidates"][0]["validated"])
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        self.assertIn('data-badge="valide"', after["html"])


# --- seed_demo ----------------------------------------------------------------------------------------

# --- review window + change requests (docs/PRODUCT.md R33–R36) -------------------------------------

class ReviewWindowTests(BaseProjectTest):
    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)

    def test_deadline_is_delivered_at_plus_review_days_while_delivered(self):
        self.assertIsNone(services.review_deadline(self.t1), "taken: no window")
        self.assertFalse(services.is_review_overdue(self.t1))
        task = services.deliver(self.t1, self.a, "https://x.y/pr")
        self.assertEqual(services.review_deadline(task), task.delivered_at + timedelta(days=7))
        with override_settings(LOWBID_REVIEW_DAYS=3):
            self.assertEqual(services.review_deadline(task), task.delivered_at + timedelta(days=3))
        self.assertFalse(services.is_review_overdue(task), "just delivered")
        services.validate(task, self.company, 5)
        paid = services.mark_paid(task)
        self.assertIsNone(services.review_deadline(paid), "paid: no window")

    def test_overdue_when_the_window_is_over_and_nothing_is_rated(self):
        services.deliver(self.t1, self.a, "https://x.y/pr")
        Task.objects.filter(pk=self.t1.pk).update(delivered_at=timezone.now() - timedelta(days=8))
        task = Task.objects.get(pk=self.t1.pk)
        self.assertTrue(services.is_review_overdue(task))
        with override_settings(LOWBID_REVIEW_DAYS=30):
            self.assertFalse(services.is_review_overdue(task), "a longer window is not over yet")
        services.validate(task, self.company, 4)
        self.assertFalse(services.is_review_overdue(Task.objects.get(pk=self.t1.pk)), "rated: the window no longer matters")

    def test_revisions_left_and_can_request_changes(self):
        self.assertEqual(services.max_revisions(), 2)
        self.assertEqual(services.revisions_left(self.t1), 2)
        self.assertFalse(services.can_request_changes(self.t1, self.company), "not delivered")
        services.deliver(self.t1, self.a, "https://x.y/pr")
        task = Task.objects.get(pk=self.t1.pk)
        self.assertTrue(services.can_request_changes(task, self.company))
        for who in (self.a, self.b, None):
            self.assertFalse(services.can_request_changes(task, who), who)
        services.validate(task, self.company, 5)
        self.assertFalse(services.can_request_changes(Task.objects.get(pk=self.t1.pk), self.company), "rated")
        with override_settings(LOWBID_MAX_REVISIONS=1):
            self.assertEqual(services.revisions_left(task), 1)
            Task.objects.filter(pk=self.t1.pk).update(revision_count=3)
            self.assertEqual(services.revisions_left(Task.objects.get(pk=self.t1.pk)), 0, "never negative")


class RequestChangesTests(BaseProjectTest):
    LINK1 = "https://github.com/x/y/pull/1"
    LINK2 = "https://github.com/x/y/pull/2"

    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, self.LINK1, delivery_hash=GIT_SHA, source_link="https://github.com/x/y")

    def fresh(self) -> Task:
        return Task.objects.select_related("project").get(pk=self.t1.pk)

    def test_deliver_writes_a_delivery_row(self):
        rows = list(Delivery.objects.filter(task=self.t1))
        self.assertEqual(len(rows), 1)
        d = rows[0]
        self.assertEqual(
            (d.freelancer, d.delivery_link, d.delivery_hash, d.source_link, d.tx_hash),
            (self.a, self.LINK1, GIT_SHA, "https://github.com/x/y", ""),
        )

    def test_only_the_company(self):
        for who in (self.a, self.b, None):
            with self.assertRaises(ProjectError, msg=who) as ctx:
                services.request_changes(self.t1, who, "Please fix the header.")
            self.assertEqual(ctx.exception.code, "forbidden")
        self.assertEqual(self.fresh().status, Task.Status.DELIVERED)
        self.assertEqual(RevisionRequest.objects.count(), 0)

    def test_message_is_required_and_bounded(self):
        for bad in ("", "   ", None, "x" * 281):
            with self.assertRaises(ProjectError, msg=bad) as ctx:
                services.request_changes(self.t1, self.company, bad)
            self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(self.fresh().status, Task.Status.DELIVERED)
        services.request_changes(self.t1, self.company, " " + "y" * 280 + " ")
        self.assertEqual(len(RevisionRequest.objects.get(task=self.t1).message), 280, "stripped, 280 accepted")

    def test_only_a_delivered_unrated_task(self):
        for task in (self.t2, self.t3):  # open
            with self.assertRaises(ProjectError) as ctx:
                services.request_changes(task, self.company, "x")
            self.assertEqual(ctx.exception.code, "wrong_state")
        services.request_changes(self.t1, self.company, "Round one.")  # now taken
        with self.assertRaises(ProjectError) as ctx:
            services.request_changes(self.t1, self.company, "again")
        self.assertEqual(ctx.exception.code, "wrong_state")
        services.deliver(self.t1, self.a, self.LINK2)
        services.validate(self.t1, self.company, 5)
        with self.assertRaises(ProjectError) as ctx:
            services.request_changes(self.t1, self.company, "too late")
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertIn("already been validated", ctx.exception.message)
        services.mark_paid(self.t1)
        with self.assertRaises(ProjectError) as ctx:
            services.request_changes(self.t1, self.company, "paid")
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertEqual(self.fresh().revision_count, 1)

    def test_success_in_direct_mode_moves_the_escrow_back_to_created(self):
        """Direct mode: the Escrow row (frozen at the DB-only delivery through payments) goes delivered → created."""
        from payments.models import Escrow

        Escrow.objects.create(
            task=self.t1, mode=Escrow.Mode.DIRECT, status=Escrow.Status.DELIVERED, amount=self.t1.price,
            payer_address=self.company.stellar_address, payee_address=self.a.stellar_address,
            delivery_note=self.LINK1, delivered_at=timezone.now(), last_error="old error",
        )
        task = services.request_changes(self.t1, self.company, "The contact form accepts an empty email.")
        self.assertEqual((task.status, task.revision_count, task.delivered_at), (Task.Status.TAKEN, 1, None))
        self.assertEqual((task.delivery_link, task.delivery_hash), (self.LINK1, GIT_SHA), "the latest delivery stays readable")
        req = RevisionRequest.objects.get(task=self.t1)
        self.assertEqual((req.company, req.message), (self.company, "The contact form accepts an empty email."))
        esc = Escrow.objects.get(task=self.t1)
        self.assertEqual((esc.status, esc.last_error), (Escrow.Status.CREATED, ""))
        self.assertIsNone(services.review_deadline(task))
        # re-delivery: a second Delivery row, the task holds the latest one, the window restarts
        again = services.deliver(self.t1, self.a, self.LINK2)
        self.assertEqual(again.status, Task.Status.DELIVERED)
        self.assertEqual((again.delivery_link, again.delivery_hash, again.source_link), (self.LINK2, "", ""))
        self.assertEqual(Delivery.objects.filter(task=self.t1).count(), 2)
        self.assertEqual(Delivery.objects.filter(task=self.t1).first().delivery_link, self.LINK2, "newest first")
        self.assertEqual(services.review_deadline(again), again.delivered_at + timedelta(days=7))

    def test_without_an_escrow_row_the_hook_has_nothing_to_move(self):
        task = services.request_changes(self.t1, self.company, "No escrow row yet (DB-only delivery).")
        self.assertEqual(task.status, Task.Status.TAKEN)

    def test_escrow_at_another_stage_refuses_the_request(self):
        from payments.models import Escrow

        Escrow.objects.create(
            task=self.t1, mode=Escrow.Mode.ESCROW, status=Escrow.Status.APPROVED, amount=self.t1.price,
            payer_address=self.company.stellar_address, payee_address=self.a.stellar_address,
        )
        with self.assertRaises(ProjectError) as ctx:
            services.request_changes(self.t1, self.company, "x")
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertIn("Delivery validated", ctx.exception.message)
        self.assertEqual(self.fresh().status, Task.Status.DELIVERED, "nothing changed")
        self.assertEqual(RevisionRequest.objects.count(), 0)

    def test_too_many_revisions_at_the_max(self):
        services.request_changes(self.t1, self.company, "One.")
        services.deliver(self.t1, self.a, self.LINK2)
        services.request_changes(self.t1, self.company, "Two.")
        services.deliver(self.t1, self.a, self.LINK2 + "?v=3")
        with self.assertRaises(ProjectError) as ctx:
            services.request_changes(self.t1, self.company, "Three.")
        self.assertEqual(ctx.exception.code, "too_many_revisions")
        self.assertIn("At most 2 change requests", ctx.exception.message)
        self.assertEqual((self.fresh().status, self.fresh().revision_count), (Task.Status.DELIVERED, 2))
        self.assertEqual(RevisionRequest.objects.filter(task=self.t1).count(), 2)
        self.assertEqual(Delivery.objects.filter(task=self.t1).count(), 3)

    @override_settings(LOWBID_MAX_REVISIONS=1)
    def test_max_revisions_is_configurable(self):
        services.request_changes(self.t1, self.company, "One.")
        services.deliver(self.t1, self.a, self.LINK2)
        with self.assertRaises(ProjectError) as ctx:
            services.request_changes(self.t1, self.company, "Two.")
        self.assertEqual(ctx.exception.code, "too_many_revisions")
        self.assertIn("At most 1 change request per task", ctx.exception.message)
        self.assertEqual(services.revisions_left(self.fresh()), 0)

    def test_delivery_history_interleaves_newest_first_and_hides_the_source(self):
        services.request_changes(self.t1, self.company, "Fix the header.")
        services.deliver(self.t1, self.a, self.LINK2, delivery_hash=SHA256, source_link="https://github.com/x/y2")
        rows = services.delivery_history(self.t1)
        self.assertEqual([r["kind"] for r in rows], ["delivery", "revision", "delivery"])
        self.assertEqual(rows[0]["delivery_link"], self.LINK2)
        self.assertEqual(rows[0]["delivery_hash"], SHA256)
        self.assertEqual(rows[1]["message"], "Fix the header.")
        self.assertEqual(rows[2]["delivery_link"], self.LINK1)
        self.assertEqual([r["source_link"] for r in rows if r["kind"] == "delivery"], ["", ""], "hidden by default")
        visible = services.delivery_history(self.t1, source_visible=True)
        self.assertEqual([r["source_link"] for r in visible if r["kind"] == "delivery"], ["https://github.com/x/y2", "https://github.com/x/y"])


class RequestChangesEndpointTests(BaseProjectTest):
    def setUp(self):
        super().setUp()
        services.apply(self.t1, self.a, "", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        services.deliver(self.t1, self.a, "https://x.y/pr/1")
        self.url = reverse("projects:task_request_changes", args=[self.t1.pk])

    def test_role_state_and_input_codes(self):
        login(self.client, self.a)
        resp = self.post_json(self.client, self.url, {"message": "x"})
        self.assertEqual((resp.status_code, resp.json()["error"]), (403, "forbidden"))
        login(self.client, self.company)
        resp = self.post_json(self.client, self.url, {"message": ""})
        self.assertEqual((resp.status_code, resp.json()["error"]), (400, "invalid"))
        resp = self.post_json(self.client, reverse("projects:task_request_changes", args=[self.t2.pk]), {"message": "x"})
        self.assertEqual((resp.status_code, resp.json()["error"]), (409, "wrong_state"))
        self.client.logout()
        resp = self.post_json(self.client, self.url, {"message": "x"})
        self.assertEqual((resp.status_code, resp.json()["error"]), (401, "wallet_required"))
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.DELIVERED)

    def test_success_then_409_too_many_revisions(self):
        login(self.client, self.company)
        resp = self.post_json(self.client, self.url, {"message": "Round one."})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual((data["ok"], data["status"], data["revision_count"], data["revisions_left"]), (True, "taken", 1, 1))
        self.assertIn("1 request left", data["message"])
        services.deliver(self.t1, self.a, "https://x.y/pr/2")
        data = self.post_json(self.client, self.url, {"message": "Round two."}).json()
        self.assertEqual((data["revision_count"], data["revisions_left"]), (2, 0))
        self.assertIn("0 requests left", data["message"])
        services.deliver(self.t1, self.a, "https://x.y/pr/3")
        resp = self.post_json(self.client, self.url, {"message": "Round three."})
        self.assertEqual((resp.status_code, resp.json()["error"]), (409, "too_many_revisions"))
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status, Task.Status.DELIVERED)

    def test_task_page_review_controls_and_history(self):
        """[data-request-changes] for the company only, while delivered + unrated; [data-review-deadline] for everyone;
        [data-delivery-history] lists every delivery and request; the freelance gets the alert and "Deliver again"."""
        page = reverse("projects:task_detail", args=[self.t1.pk])
        login(self.client, self.company)
        html = self.client.get(page).content.decode()
        self.assertIn("data-request-changes", html)
        self.assertIn('id="request-changes-form"', html)
        self.assertIn('id="request-changes-message"', html)
        self.assertIn("data-request-changes-submit", html)
        self.assertIn("data-review-deadline", html)
        self.assertIn('data-deadline="', html)
        self.assertIn("Review until", html)
        self.assertIn('data-delivery-history data-count="1"', html)
        self.assertIn(self.url, html)
        for who in (self.a, self.b):
            login(self.client, who)
            html = self.client.get(page).content.decode()
            self.assertNotIn("data-request-changes", html, who)
            self.assertIn("data-review-deadline", html, "everyone sees the window")
        self.client.logout()
        self.assertIn("data-review-deadline", self.client.get(page).content.decode(), "anonymous too")
        # the company requests changes → freelance alert + "Deliver again"; no deadline while taken
        services.request_changes(self.t1, self.company, "Fix the mobile menu.")
        login(self.client, self.a)
        html = self.client.get(page).content.decode()
        self.assertIn('data-changes-requested="1"', html)
        self.assertIn("Changes requested (1/2)", html)
        self.assertIn("Fix the mobile menu.", html)
        self.assertIn("Deliver again", html)
        self.assertNotIn("data-review-deadline", html)
        self.assertNotIn('id="delivery-panel"', html, "the old delivery is in the history, not in the Delivery panel")
        self.assertIn('data-delivery-history data-count="2"', html)
        login(self.client, self.company)
        html = self.client.get(page).content.decode()
        self.assertIn("data-changes-pending", html)
        self.assertNotIn("data-request-changes", html, "taken: nothing to send back")
        # second delivery → 2 deliveries + 1 request in the history, the source only for the assignee
        services.deliver(self.t1, self.a, "https://x.y/pr/2", delivery_hash=SHA256, source_link="https://github.com/x/src")
        html = self.client.get(page).content.decode()
        self.assertIn('data-delivery-history data-count="3"', html)
        self.assertEqual(html.count('data-kind="delivery"'), 2)
        self.assertEqual(html.count('data-kind="revision"'), 1)
        self.assertIn(f'data-history-hash="{SHA256}"', html)
        self.assertNotIn("https://github.com/x/src", html, "the company does not see the source before payment")
        self.assertIn('data-revisions="1"', html)
        self.assertIn("1/2", html)
        self.assertIn("data-request-changes", html)
        login(self.client, self.a)
        html = self.client.get(page).content.decode()
        self.assertIn("https://github.com/x/src", html, "the assignee sees the source in the history")
        # rated → the control disappears for the company
        services.validate(self.t1, self.company, 5)
        login(self.client, self.company)
        html = self.client.get(page).content.decode()
        self.assertNotIn("data-request-changes", html)

    @override_settings(LOWBID_MAX_REVISIONS=1)
    def test_button_disabled_once_the_max_is_reached(self):
        services.request_changes(self.t1, self.company, "Round one.")
        services.deliver(self.t1, self.a, "https://x.y/pr/2")
        login(self.client, self.company)
        html = self.client.get(reverse("projects:task_detail", args=[self.t1.pk])).content.decode()
        self.assertIn("data-request-changes disabled", html)
        self.assertIn("data-revisions-exhausted", html)
        self.assertNotIn('id="request-changes-form"', html)
        self.assertIn("1/1", html)
# --- trust-network badges on the project pages ------------------------------------------

class NetworkBadgesPageTests(BaseProjectTest):
    """One-hop network badges: shown to the right viewer, never to anonymous, never touching order or score."""

    def setUp(self):
        super().setUp()
        from network import services as network

        self.network = network
        self.x = make_wallet("Ines")  # someone the company follows
        services.apply(self.t2, self.a, "A", ["stellar", "js"])  # full skills match: best score
        services.apply(self.t2, self.b, "B", ["stellar"])

    def candidates(self, client):
        return client.get(reverse("projects:task_candidates_json", kwargs={"pk": self.t2.pk})).json()

    def scores_in_order(self, client) -> list[tuple[str, str]]:
        return [(c["freelancer"], c["score"]) for c in self.candidates(client)["candidates"]]

    def test_strong_badge_on_company_task_page_and_json(self):
        login(self.client, self.company)
        before = self.candidates(self.client)["fingerprint"]
        self.network.follow(self.company, self.x)
        self.network.recommend(self.x, self.a, "Great Soroban work")

        html = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.t2.pk})).content.decode()
        self.assertIn('data-network-badge="recommends"', html)
        self.assertIn("Ines recommends", html)
        self.assertRegex(html, r'class="[^"]*cand-row[^"]*is-network-strong[^"]*"[^>]*data-freelancer="'
                         + self.a.stellar_address)

        data = self.candidates(self.client)
        row = next(c for c in data["candidates"] if c["freelancer"] == self.a.stellar_address)
        self.assertEqual(row["network"]["level"], "strong")
        other = next(c for c in data["candidates"] if c["freelancer"] == self.b.stellar_address)
        self.assertIsNone(other["network"])
        self.assertNotEqual(data["fingerprint"], before)
        self.assertIn('data-network-badge="recommends"', data["html"])

    def test_anonymous_task_page_has_no_network_badge(self):
        self.network.follow(self.company, self.x)
        self.network.recommend(self.x, self.a)
        html = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.t2.pk})).content.decode()
        self.assertNotIn("data-network-badge", html)
        self.assertNotIn("is-network", html)
        for c in self.candidates(self.client)["candidates"]:
            self.assertIsNone(c["network"])

    def test_order_and_scores_unchanged_by_badges(self):
        login(self.client, self.company)
        plain = self.scores_in_order(self.client)
        html = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.t2.pk})).content.decode()
        plain_html = re.findall(r'data-score="([^"]+)"', html)
        self.assertEqual([a for a, _ in plain], [self.a.stellar_address, self.b.stellar_address])

        # The network pushes the LOWER-scored candidate: nothing about the ranking may move.
        self.network.follow(self.company, self.x)
        self.network.follow(self.company, self.b)
        self.network.recommend(self.x, self.b, "Trust her")
        self.assertEqual(self.scores_in_order(self.client), plain)
        html = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.t2.pk})).content.decode()
        self.assertEqual(re.findall(r'data-score="([^"]+)"', html), plain_html)
        self.assertIn("data-recommended", html)  # the score badge still goes to the best score (A)
        rec_row = re.search(r'data-freelancer="([^"]+)"(?:(?!data-freelancer=).)*data-recommended', html, re.S)
        self.assertEqual(rec_row.group(1), self.a.stellar_address)

    def test_strong_badge_text_is_never_bare_recommended(self):
        login(self.client, self.company)
        self.network.follow(self.company, self.x)
        self.network.recommend(self.x, self.a)
        html = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.t2.pk})).content.decode()
        badges = re.findall(r'data-network-badge="recommends"[^>]*>(.*?)</span>', html, re.S)
        self.assertTrue(badges)
        for badge in badges:
            text = re.sub(r"<[^>]+>", "", badge).strip()
            self.assertNotEqual(text, "Recommended")
            self.assertIn(" recommends", text)

    def test_board_card_shows_followed_by_for_company(self):
        freelance = make_wallet("Lea")
        self.network.follow(freelance, self.x)
        self.network.follow(self.x, self.company)
        login(self.client, freelance)
        html = self.client.get(reverse("projects:board")).content.decode()
        self.assertIn('data-network-badge="followed-by"', html)
        self.assertIn("Followed by Ines", html)

    def test_project_list_following_badge_signed_in_only(self):
        self.network.follow(self.a, self.company)
        login(self.client, self.a)
        html = self.client.get(reverse("projects:project_list")).content.decode()
        self.assertIn('data-network-badge="following"', html)
        self.client.logout()
        html = self.client.get(reverse("projects:project_list")).content.decode()
        self.assertNotIn("data-network-badge", html)

    def test_company_chip_badge_on_project_and_task_pages(self):
        self.network.follow(self.a, self.company)
        login(self.client, self.a)
        for url in (
            reverse("projects:project_detail", kwargs={"pk": self.project.pk}),
            reverse("projects:task_detail", kwargs={"pk": self.t1.pk}),
        ):
            self.assertIn('data-network-badge="following"', self.client.get(url).content.decode())
