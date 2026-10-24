from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from stellar_sdk import Keypair

from accounts.models import WalletUser
from payments.models import Escrow

from . import services
from .models import Application, Project, Rating, Task
from .scoring import company_history, is_validated, recommended_pk, score_application, score_parts
from .services import ProjectError

JSON = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "fetch"}


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


# --- company: project + tasks ---------------------------------------------------------------

class CreateProjectTests(TestCase):
    def test_create_project_is_draft(self):
        company = make_wallet()
        project = services.create_project(company, "  Mon projet ", "Une description.")
        self.assertEqual(project.status, Project.Status.DRAFT)
        self.assertEqual(project.title, "Mon projet")
        self.assertEqual(project.status_label, "Brouillon")
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
        self.assertEqual(app.status_label, "En attente")
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
        self.assertEqual(task.status_label, "Pris")
        self.assertTrue(task.is_assignee(self.b))

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

    @override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k")
    def test_db_only_delivery_is_refused_in_escrow_mode(self):
        services.apply(self.t1, self.a, "A", ["django", "ui"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        with self.assertRaises(ProjectError) as ctx:
            services.deliver(self.t1, self.a, "https://x.y/pr")
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertIn("escrow", ctx.exception.message)
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


# --- scoring (SPEC §4 / §8) -------------------------------------------------------------------------

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
        self.assertContains(r, "Connecter pour publier")
        self.assertEqual(r.context["total"], 1)
        self.assertEqual(r.context["popular_tags"][:1], ["django"])
        self.assertContains(self.client.get(reverse("projects:project_list") + "?q=freighter&tab=all"), "project-card")
        self.assertContains(self.client.get(reverse("projects:project_list") + "?q=zzzz"), "Aucun projet")
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
        self.assertContains(r, "Le titre est trop court.")
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
        self.assertEqual(html.count("data-choose="), 2, "a Choisir button on EVERY candidate")
        self.assertIn("data-recommended", html)
        self.assertIn("window.LOWBID_PROJECT", html)
        self.assertIn(reverse("projects:task_add", args=[self.project.pk]), html)
        # direct mode (no Trustless Work key): no funding button, an honest note instead
        self.assertNotIn("data-fund", html)
        self.assertIn("Mode paiement direct", html)
        with override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k"):
            html = self.client.get(self.url()).content.decode()
        self.assertIn("data-fund", html)
        self.assertIn("disabled", html.split("data-fund", 1)[1][:80], "no chosen freelance → the button is disabled")
        self.assertIn("Choisissez d’abord un freelance", html)
        self.assertIn("Trustless Work fixe le destinataire", html)

    @override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k")
    def test_fund_button_enabled_once_a_freelance_is_chosen(self):
        login(self.client, self.company)
        empty = services.create_project(self.company, "Vide", "Rien.")
        self.assertNotContains(self.client.get(reverse("projects:project_detail", args=[empty.pk])), "data-fund")
        services.apply(self.t1, self.a, "", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn(f'data-fund data-pending-url="{reverse("payments:project_pending", args=[self.project.pk])}"', html)
        self.assertIn("1 tâche attribuée à financer", html)
        self.assertIn('id="funding-panel"', html)
        self.assertIn("En préparation", html, "T1's escrow status in the banner")
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
        self.assertIn("Postulé", html, "the viewer's pending application is flagged on the row")
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
        self.assertContains(r, "Valider + noter")
        self.assertContains(r, "#validate-panel")


class TaskDetailViewTests(BaseProjectTest):
    def url(self, task=None):
        return reverse("projects:task_detail", args=[(task or self.t1).pk])

    def test_freelance_sees_the_apply_form_then_their_application(self):
        login(self.client, self.a)
        html = self.client.get(self.url()).content.decode()
        for marker in ('id="apply-form"', 'id="apply-message"', 'id="apply-tags"', "data-apply-submit", 'data-error-for="message"', 'data-error-for="tags"', 'data-error-for="_"', "window.LOWBID_TASK", 'data-candidates data-count="0"'):
            self.assertIn(marker, html, marker)
        self.assertIn(reverse("projects:apply_create", args=[self.t1.pk]), html)
        services.apply(self.t1, self.a, "Moi", ["django"])
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="apply-form"', html)
        self.assertIn('id="my-application"', html)
        self.assertIn("Votre candidature", html)
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
        self.assertIn("data-deliver", html)
        self.assertIn("Choisi", html)
        login(self.client, self.b)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="deliver-panel"', html)
        self.assertIn("Un freelance a été choisi", html)

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
        self.assertIn("Valider et payer 300.00 USDC", html)
        self.assertIn('id="escrow-panel"', html)
        self.assertIn("https://x.y/pr", html)
        login(self.client, self.a)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('id="validate-panel"', html)
        self.assertIn("Livraison déclarée", html)

    def test_paid_task_shows_the_rating_and_badges_on_the_next_task(self):
        self.pay_t1_to_a(5)
        services.apply(self.t2, self.a, "", ["stellar"])
        services.apply(self.t2, self.b, "", ["stellar", "js"])
        login(self.client, self.company)
        html = self.client.get(self.url()).content.decode()
        self.assertIn("Tâche payée", html)
        self.assertIn('data-rating="5"', html)
        self.assertNotIn("data-choose", html)
        self.assertIn("Choisi", html)
        self.assertIn("Non retenu", html)
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
        self.assertContains(r, "Livrer")

    def test_company_does_not_see_its_own_open_tasks(self):
        login(self.client, self.company)
        r = self.client.get(reverse("projects:board"))
        self.assertEqual(r.context["counts"]["open"], 0)
        self.assertContains(r, "Aucune tâche ouverte")


class MyProjectsViewTests(BaseProjectTest):
    def test_my_projects_table_and_kpis(self):
        services.apply(self.t1, self.a, "", [])
        login(self.client, self.company)
        r = self.client.get(reverse("projects:my_projects"))
        self.assertContains(r, "Plateforme de réservation")
        self.assertContains(r, "rcard")
        self.assertEqual(r.context["kpis"], {"draft": 1, "funded": 0, "closed": 0, "to_choose": 1, "to_validate": 0})
        self.assertEqual(r.context["projects"][0].pending_apps, 1)
        self.assertTrue(r.context["projects"][0].attention)
        self.assertEqual(len(self.client.get(reverse("projects:my_projects") + "?tab=done").context["projects"]), 0)
        self.assertContains(self.client.get(reverse("projects:my_projects") + "?tab=done"), "Rien ici")

    def test_other_wallets_see_an_empty_list(self):
        login(self.client, self.a)
        r = self.client.get(reverse("projects:my_projects"))
        self.assertContains(r, "Aucun projet en cours")
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
        r = self.post_json(self.client, url, {"message": "x", "tags": ["django"]})
        self.assertEqual((r.status_code, r.json()["error"]), (401, "wallet_required"))
        login(self.client, self.a)
        r = self.post_json(self.client, url, {"message": "Je prends.", "tags": ["Django", "ui"]})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["application"]["score"], "20.0")
        self.assertEqual(r.json()["application"]["tags"], ["django", "ui"])
        r = self.post_json(self.client, url, {"message": "encore"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "duplicate"))
        login(self.client, self.company)
        r = self.post_json(self.client, url, {"message": "moi"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "own_task"))
        login(self.client, self.b)
        r = self.post_json(self.client, url, {"tags": ["a", "b", "c", "d"]})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "bad_tags"))
        self.assertIn("Au plus 3", r.json()["message"])

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
        self.assertIn("Payer le freelance", data["message"])
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
        self.assertIn("Aucun candidat", empty["html"])
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
        self.assertNotIn("data-choose", data["html"], "anonymous: no Choisir button")
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

class SeedDemoTests(TestCase):
    def test_seed_demo_builds_the_pitch_state(self):
        out = StringIO()
        call_command("seed_demo", "--flush", stdout=out)
        text = out.getvalue()
        self.assertIn("Demo data ready.", text)
        self.assertIn("freelance A", text)
        self.assertEqual(Project.objects.count(), 2)
        self.assertEqual(WalletUser.objects.count(), 3)
        pitch = Project.objects.get(title__startswith="Plateforme")
        t1, t2, t3 = list(pitch.tasks.order_by("position"))
        self.assertEqual((t1.status, t2.status, t3.status), ("paid", "open", "open"))
        self.assertEqual(Rating.objects.get(task=t1).note, 5)
        escrow = Escrow.objects.get(task=t1)
        self.assertEqual((escrow.mode, escrow.status, len(escrow.payment_tx_hash)), ("direct", "paid", 64))
        self.assertIn("payment mode", text)
        self.assertIn("stellar.expert", text)
        scores = sorted(t2.applications.values_list("score", flat=True), reverse=True)
        self.assertEqual(scores, [Decimal("90.0"), Decimal("20.0")])
        draft = Project.objects.exclude(pk=pitch.pk).get()
        self.assertEqual(draft.status, Project.Status.DRAFT)
        self.assertEqual(draft.tasks.count(), 3)
        self.assertEqual(Application.objects.filter(task__project=draft).count(), 0)

    def test_seed_demo_is_repeatable_with_flush(self):
        call_command("seed_demo", "--flush", stdout=StringIO())
        call_command("seed_demo", "--flush", stdout=StringIO())
        self.assertEqual(Project.objects.count(), 2)
        self.assertEqual(Task.objects.count(), 6)
