"""Phase 3 — on-chain dispute (a party) and arbiter resolution (escrow mode only). No network: Trustless
Work POSTs go through `FreshTWRouter` (a new unsigned XDR per build, so every step has its own hash) and
get-escrow through `TWGet`. Covers the gates per role, the distributions sent to resolve-dispute, the
closing rule, the `/litiges/` desk, the panel markup, next_action / stepper and the dashboard items."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from dashboard import services as dashboard
from payments import services as payments
from payments import trustless_work as tw
from payments.models import Escrow
from projects import services as projects
from projects.models import Dispute, Project, Rating, Task

from .tests_flow import (
    DIRECT_SETTINGS,
    ESCROW_SETTINGS,
    LINK,
    BasePayTest,
    HorizonGet,
    TWRouter,
    _resp,
    horizon_account,
    login,
    sign,
    some_xdr,
)

ARBITER_KP = Keypair.random()
ARBITER = ARBITER_KP.public_key
DISPUTE_SETTINGS = {**ESCROW_SETTINGS, "LOWBID_DISPUTE_RESOLVER": ARBITER}
REASON = "The booking form is missing and the mockup was not followed."


class FreshTWRouter(TWRouter):
    """TWRouter whose every build answers a NEW unsigned XDR (different amount → different hash), like
    Trustless Work does in real life — so the dispute / resolve hashes never collide with the deploy's."""

    def __init__(self, source: str, destination: str):
        self.source, self.destination, self.n = source, destination, 1
        super().__init__(some_xdr(source, destination, "1"))

    def __call__(self, url, json=None, **kw):
        path = url.split("trustlesswork.com", 1)[-1]
        if path != tw.PATH_SEND:
            self.n += 1
            self.build_payload = {"status": "SUCCESS", "unsignedTransaction": some_xdr(self.source, self.destination, str(self.n))}
        return super().__call__(url, json=json, **kw)


class TWGet:
    """requests.get stand-in for get-escrow: answers `balance`, or fails (`fail` = "timeout" | "http")."""

    def __init__(self, balance="120", fail: str | None = None):
        self.balance, self.fail = balance, fail
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        if self.fail == "timeout":
            raise requests.Timeout("slow indexer")
        if self.fail == "http":
            return _resp(500, {"message": "indexer down"})
        return _resp(200, {"balance": self.balance, "flags": {"disputed": True, "released": False, "resolved": False}})


class BaseDisputeTest(BasePayTest):
    def setUp(self):
        super().setUp()
        self.arbiter = WalletUser.objects.create(stellar_address=ARBITER, display_name="arbiter")
        self.router = FreshTWRouter(self.company.stellar_address, self.freelance.stellar_address)
        patcher = patch("payments.trustless_work.requests.post", side_effect=self.router)
        patcher.start()
        self.addCleanup(patcher.stop)

    def deliver(self):
        login(self.client, self.company)
        self.run_step("deploy", self.company_kp)
        self.run_step("fund", self.company_kp)
        login(self.client, self.freelance)
        _, sent = self.run_step("deliver", self.freelance_kp, {"delivery_link": LINK})
        self.assertTrue(sent["ok"], sent)

    def dispute(self, who="company", reason=REASON):
        login(self.client, getattr(self, who))
        prep = self.prepare("dispute", {"reason": reason}).json()
        self.assertTrue(prep["ok"], prep)
        sent = self.send("dispute", sign(prep["xdr"], getattr(self, f"{who}_kp")), prep["extra"]).json()
        self.assertTrue(sent["ok"], sent)
        return prep, sent

    def resolve(self, pct, balance="120", body=None, fail=None):
        getter = TWGet(balance, fail)
        login(self.client, self.arbiter)
        with patch("payments.trustless_work.requests.get", side_effect=getter):
            prep = self.prepare("resolve", {"freelance_pct": pct, **(body or {})}).json()
        self.assertTrue(prep["ok"], prep)
        sent = self.send("resolve", sign(prep["xdr"], ARBITER_KP), prep["extra"]).json()
        return getter, prep, sent

    def overdue(self):
        Task.objects.filter(pk=self.task.pk).update(delivered_at=timezone.now() - timedelta(days=8))

    def error(self, resp):
        data = resp.json()
        self.assertFalse(data["ok"], data)
        return data["error"]


# =============================== dispute =====================================


@override_settings(**DISPUTE_SETTINGS)
class DisputeOpenTests(BaseDisputeTest):
    def test_deploy_pins_the_arbiter_as_dispute_resolver(self):
        login(self.client, self.company)
        self.run_step("deploy", self.company_kp)
        self.assertEqual(self.escrow().resolver_address, ARBITER)
        self.assertEqual(self.router.last(tw.PATH_DEPLOY)["roles"]["disputeResolver"], ARBITER)

    def test_company_dispute_happy_path_then_everything_else_is_wrong_state(self):
        self.deliver()
        prep, sent = self.dispute("company")
        self.assertEqual(prep["extra"], {"reason": REASON})
        self.assertEqual(self.router.last(tw.PATH_DISPUTE), {"contractId": self.escrow().contract_id, "signer": self.company.stellar_address})
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DISPUTED)
        self.assertEqual(esc.dispute_tx_hash, sent["tx_hash"])
        self.assertIsNotNone(esc.disputed_at)
        self.assertTrue(esc.holds_funds)
        self.assertIn("Dispute opened", [link["label"] for link in esc.explorer_links()])
        self.assertEqual(self.task_status(), "disputed")
        dispute = Dispute.objects.get(task=self.task)
        self.assertEqual((dispute.opened_by, dispute.reason, dispute.freelance_pct), (self.company, REASON, None))
        # nothing else moves: approve / release / dispute again / validate / request changes
        for step in ("approve", "release", "dispute"):
            self.assertEqual(self.error(self.prepare(step, {"reason": "again"})), "wrong_state", step)
        resp = self.validate(5)
        self.assertEqual(resp.json()["error"], "wrong_state")
        self.assertFalse(Rating.objects.filter(task=self.task).exists())
        with self.assertRaises(projects.ProjectError) as ctx:
            projects.request_changes(self.fresh(), self.company, "fix it")
        self.assertEqual(ctx.exception.code, "wrong_state")
        self.assertFalse(projects.can_request_changes(self.fresh(), self.company))
        # the same signed XDR sent twice is the idempotent "already confirmed"
        again = self.send("dispute", sign(prep["xdr"], self.company_kp), prep["extra"]).json()
        self.assertTrue(again["ok"], again)
        self.assertEqual(Dispute.objects.count(), 1)

    def test_company_refused_once_rated(self):
        self.deliver()
        login(self.client, self.company)
        self.assertTrue(self.validate(4).json()["ok"])
        self.assertEqual(self.error(self.prepare("dispute", {"reason": REASON})), "wrong_state")
        self.assertEqual(payments.can_dispute(self.fresh(), self.company)[0], False)

    def test_freelance_refused_before_the_deadline_allowed_after(self):
        self.deliver()
        login(self.client, self.freelance)
        resp = self.prepare("dispute", {"reason": REASON}).json()
        self.assertEqual(resp["error"], "wrong_state")
        self.assertIn("review window", resp["message"])
        self.overdue()
        self.dispute("freelance", "No answer from the company within the review window.")
        self.assertEqual(self.router.last(tw.PATH_DISPUTE)["signer"], self.freelance.stellar_address)
        self.assertEqual(Dispute.objects.get(task=self.task).opened_by, self.freelance)
        self.assertEqual(self.task_status(), "disputed")

    def test_stranger_and_arbiter_cannot_dispute(self):
        self.deliver()
        for wallet in (self.other, self.arbiter):
            login(self.client, wallet)
            self.assertEqual(self.error(self.prepare("dispute", {"reason": REASON})), "forbidden")
        self.assertEqual(self.router.count(tw.PATH_DISPUTE), 0)

    def test_reason_is_required_and_capped(self):
        self.deliver()
        login(self.client, self.company)
        for reason in ("", "   ", "x" * 281):
            self.assertEqual(self.error(self.prepare("dispute", {"reason": reason})), "invalid", len(reason))
        self.assertEqual(self.router.count(tw.PATH_DISPUTE), 0)
        prep = self.prepare("dispute", {"reason": "x" * 280}).json()
        self.assertTrue(prep["ok"], prep)
        # an empty reason in the send body is refused before anything reaches Trustless Work
        sends = self.router.count(tw.PATH_SEND)
        self.assertEqual(self.error(self.send("dispute", sign(prep["xdr"], self.company_kp), {"reason": ""})), "invalid")
        self.assertEqual(self.router.count(tw.PATH_SEND), sends)

    def test_not_before_delivery(self):
        login(self.client, self.company)
        self.run_step("deploy", self.company_kp)
        self.run_step("fund", self.company_kp)
        self.assertEqual(self.error(self.prepare("dispute", {"reason": REASON})), "wrong_state")


@override_settings(**{**DIRECT_SETTINGS, "LOWBID_DISPUTE_RESOLVER": ARBITER})
class DisputeDirectModeTests(BasePayTest):
    def test_direct_mode_has_no_dispute_and_shows_the_warning(self):
        horizon = HorizonGet(accounts={self.company.stellar_address: horizon_account(self.company.stellar_address)})
        with patch("payments.stellar.requests.get", side_effect=horizon):
            login(self.client, self.freelance)
            self.assertTrue(self.prepare("deliver", {"delivery_link": LINK}).json()["ok"])
            login(self.client, self.company)
            resp = self.prepare("dispute", {"reason": REASON}).json()
            self.assertEqual((resp["error"], resp["message"]), ("wrong_mode", payments.DIRECT_NO_DISPUTE))
            self.assertEqual(payments.can_dispute(self.fresh(), self.company), (False, payments.DIRECT_NO_DISPUTE))
            html = self.detail().content.decode()
        self.assertIn("data-direct-warning", html)
        self.assertIn("Direct mode: unprotected payment", html)
        self.assertNotIn("data-open-dispute", html)
        # an open task never shows the warning
        self.assertNotIn("data-direct-warning", self.detail(self.open_task).content.decode())


# =============================== resolve =====================================


@override_settings(**DISPUTE_SETTINGS)
class DisputeResolveTests(BaseDisputeTest):
    def setUp(self):
        super().setUp()
        self.deliver()
        self.dispute_prep, self.dispute_sent = self.dispute("company")

    def test_only_the_arbiter_resolves(self):
        for wallet in (self.company, self.freelance, self.other):
            login(self.client, wallet)
            self.assertEqual(self.error(self.prepare("resolve", {"freelance_pct": 50})), "forbidden")
        self.assertEqual(self.router.count(tw.PATH_RESOLVE), 0)

    def test_arbiter_must_be_the_resolver_fixed_at_deploy(self):
        Escrow.objects.filter(task=self.task).update(resolver_address=Keypair.random().public_key)
        login(self.client, self.arbiter)
        with patch("payments.trustless_work.requests.get", side_effect=TWGet()):
            self.assertEqual(self.error(self.prepare("resolve", {"freelance_pct": 50})), "forbidden")

    def test_pct_must_be_an_integer_between_0_and_100(self):
        login(self.client, self.arbiter)
        with patch("payments.trustless_work.requests.get", side_effect=TWGet()):
            for pct in (-1, 101, "abc", None, "50.5"):
                self.assertEqual(self.error(self.prepare("resolve", {"freelance_pct": pct})), "invalid", pct)

    def test_half_split_on_the_on_chain_balance_with_row_addresses(self):
        intruder = Keypair.random().public_key
        getter, prep, sent = self.resolve(50, balance="100.0000001", body={"address": intruder, "payee_address": intruder, "distributions": [{"address": intruder, "amount": 100}]})
        self.assertTrue(sent["ok"], sent)
        url, params = getter.calls[0]
        self.assertTrue(url.endswith(tw.PATH_GET_ESCROW))
        self.assertEqual(params, {"contractId": self.escrow().contract_id, "signer": ARBITER, "validateOnChain": "true"})
        body = self.router.last(tw.PATH_RESOLVE)
        self.assertEqual(body["contractId"], self.escrow().contract_id)
        self.assertEqual(body["disputeResolver"], ARBITER)
        self.assertEqual(
            body["distributions"],
            [{"address": self.freelance.stellar_address, "amount": 50}, {"address": self.company.stellar_address, "amount": 50.0000001}],
        )
        self.assertNotIn(intruder, json.dumps(body))
        self.assertEqual(sum(Decimal(str(d["amount"])) for d in body["distributions"]), Decimal("100.0000001"))
        self.assertEqual(prep["extra"], {"freelance_pct": 50, "balance": "100.0000001"})
        esc = self.escrow()
        self.assertEqual((esc.status, esc.resolve_tx_hash), (Escrow.Status.RESOLVED, sent["tx_hash"]))
        self.assertIsNotNone(esc.resolved_at)
        self.assertIn("Dispute resolved", [link["label"] for link in esc.explorer_links()])
        task = self.fresh()
        self.assertEqual(task.status, "resolved")
        self.assertIsNotNone(task.resolved_at)
        dispute = Dispute.objects.get(task=self.task)
        self.assertEqual((dispute.freelance_pct, dispute.company_pct), (50, 50))
        self.assertIsNotNone(dispute.resolved_at)
        # the other task is still open: the project stays open
        self.assertNotEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.CLOSED)
        # the company now sees the full deliverable (settled)
        self.assertTrue(projects.source_visible(task, self.company))
        self.assertIsNone(payments.next_action(task, self.company))

    def test_zero_and_hundred_percent_drop_the_empty_entry(self):
        _, _, sent = self.resolve(0)
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(self.router.last(tw.PATH_RESOLVE)["distributions"], [{"address": self.company.stellar_address, "amount": 120}])

    def test_hundred_percent_goes_to_the_freelance(self):
        _, _, sent = self.resolve(100, balance="119.64")
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(self.router.last(tw.PATH_RESOLVE)["distributions"], [{"address": self.freelance.stellar_address, "amount": 119.64}])

    def test_balance_read_failure_falls_back_to_the_stored_amount(self):
        for fail in ("timeout", "http"):
            with self.subTest(fail=fail), self.assertLogs("payments.services", level="WARNING") as logs:
                login(self.client, self.arbiter)
                with patch("payments.trustless_work.requests.get", side_effect=TWGet(fail=fail)):
                    prep = self.prepare("resolve", {"freelance_pct": 25}).json()
                self.assertTrue(prep["ok"], prep)
                self.assertEqual(prep["extra"]["balance"], "120")
                self.assertEqual(
                    self.router.last(tw.PATH_RESOLVE)["distributions"],
                    [{"address": self.freelance.stellar_address, "amount": 30}, {"address": self.company.stellar_address, "amount": 90}],
                )
                self.assertIn("balance unavailable", "\n".join(logs.output))

    def test_project_closes_when_every_other_task_is_paid(self):
        Task.objects.filter(pk=self.open_task.pk).update(status=Task.Status.PAID)
        _, _, sent = self.resolve(70)
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.CLOSED)

    def test_replayed_xdr_is_refused_and_a_resolved_task_is_terminal(self):
        login(self.client, self.arbiter)
        replay = self.send("resolve", sign(self.dispute_prep["xdr"], ARBITER_KP), {"freelance_pct": 50}).json()
        self.assertEqual((replay["ok"], replay["error"]), (False, "tampered"), replay)
        self.assertEqual(self.task_status(), "disputed")
        _, prep, sent = self.resolve(60)
        self.assertTrue(sent["ok"], sent)
        sends = self.router.count(tw.PATH_SEND)
        again = self.send("resolve", sign(prep["xdr"], ARBITER_KP), {"freelance_pct": 10}).json()
        self.assertTrue(again["ok"], again)
        self.assertIn("already", again["message"])
        self.assertEqual(self.router.count(tw.PATH_SEND), sends, "no second submission")
        self.assertEqual(Dispute.objects.get(task=self.task).freelance_pct, 60)
        with patch("payments.trustless_work.requests.get", side_effect=TWGet()):
            self.assertEqual(self.error(self.prepare("resolve", {"freelance_pct": 10})), "wrong_state")

    def test_next_action_and_stepper_while_disputed(self):
        task = self.fresh()
        arbiter = payments.next_action(task, self.arbiter)
        self.assertEqual((arbiter["step"], arbiter["mine"]), ("resolve", True))
        for wallet in (self.company, self.freelance, self.other):
            action = payments.next_action(task, wallet)
            self.assertEqual((action["step"], action["mine"], action["waiting"]), ("resolve", False, "Waiting for the arbiter's decision."))
        self.assertEqual(payments.viewer_role(task, self.arbiter), "arbiter")
        steps = payments.stepper(Escrow.Mode.ESCROW, Escrow.Status.DISPUTED)
        self.assertEqual([(s["label"], s["state"]) for s in steps], [
            ("Escrow created", "done"), ("Funds locked", "done"), ("Delivered", "done"), ("In dispute", "current"), ("Resolved", "todo"),
        ])
        self.assertTrue(all(s["state"] == "done" for s in payments.stepper(Escrow.Mode.ESCROW, Escrow.Status.RESOLVED)))
        # the normal path is unchanged
        self.assertEqual([s["label"] for s in payments.stepper(Escrow.Mode.ESCROW, Escrow.Status.DELIVERED)],
                         ["Escrow created", "Funds locked", "Delivered", "Funds released"])

    def test_dashboard_items_per_role(self):
        for wallet in (self.company, self.freelance):
            items = dashboard.todo_items(wallet)
            item = next(it for it in items if it["headline"].startswith("Dispute open on"))
            self.assertEqual(item["tone"], "wait")
        arbiter = dashboard.todo_items(self.arbiter)
        item = next(it for it in arbiter if it["headline"].startswith("Resolve the dispute on"))
        self.assertEqual(item["tone"], "act")
        self.assertIn(f"#resolve-form-{self.task.pk}", item["href"])
        self.assertEqual(dashboard.company_stats(self.company)["disputed"], 1)
        self.resolve(50)
        self.assertFalse(any("dispute" in it["headline"].lower() for it in dashboard.todo_items(self.arbiter)))
        stats = dashboard.freelancer_stats(self.freelance)
        self.assertEqual((stats["resolved"], stats["paid"], stats["settled"]), (1, 0, 1), "resolved counts as settled, not paid")

    def test_panel_markup_disputed_then_resolved(self):
        login(self.client, self.freelance)
        html = self.detail().content.decode()
        self.assertIn("data-disputed", html)
        self.assertIn(REASON, html)
        self.assertIn("Waiting for the arbiter", html)
        self.assertIn(f"/tx/{self.dispute_sent['tx_hash']}", html)
        self.assertNotIn("data-open-dispute", html)
        self.assertNotIn("data-validate-submit", html)
        self.resolve(40)
        login(self.client, self.company)
        html = self.detail().content.decode()
        self.assertIn('data-resolved data-freelance-pct="40"', html)
        self.assertIn("40% to the freelancer / 60% to the company", html)
        self.assertNotIn("data-disputed", html)

    def test_disputes_desk_is_arbiter_only(self):
        url = reverse("projects:disputes")
        for wallet in (self.company, self.freelance, self.other):
            login(self.client, wallet)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertNotIn('href="/litiges/"', self.client.get(reverse("dashboard:home")).content.decode())
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        login(self.client, self.arbiter)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn(f'id="resolve-form-{self.task.pk}"', html)
        self.assertIn("data-freelance-pct", html)
        self.assertIn('data-pay-step="resolve"', html)
        self.assertIn(reverse("payments:prepare", kwargs={"task_pk": self.task.pk, "step": "resolve"}), html)
        self.assertIn(REASON, html)
        self.assertIn("lowbid-disputes.js", html)
        self.assertIn('href="/litiges/"', html, "the arbiter gets the Disputes nav link")
        self.resolve(50)
        html = self.client.get(url).content.decode()
        self.assertNotIn(f'id="resolve-form-{self.task.pk}"', html)
        self.assertIn('data-split="50"', html)


@override_settings(**DISPUTE_SETTINGS)
class DisputePanelTests(BaseDisputeTest):
    def test_open_dispute_control_per_role(self):
        self.deliver()
        login(self.client, self.company)
        html = self.detail().content.decode()
        for marker in ("data-open-dispute", 'id="dispute-form"', 'id="dispute-reason"', "data-dispute-submit", 'data-pay-step="dispute"'):
            self.assertIn(marker, html)
        self.assertNotIn("data-direct-warning", html)
        login(self.client, self.freelance)
        self.assertNotIn("data-open-dispute", self.detail().content.decode(), "not before the review window is over")
        self.overdue()
        html = self.detail().content.decode()
        self.assertIn("data-open-dispute", html)
        self.assertIn("Dispute for no response", html)
        login(self.client, self.other)
        self.assertNotIn("data-open-dispute", self.detail().content.decode())

    def test_freelance_overdue_dashboard_item(self):
        self.deliver()
        self.overdue()
        item = next(it for it in dashboard.todo_items(self.freelance) if it["kicker"] == "No response")
        self.assertEqual(item["tone"], "act")


class MarkResolvedTests(TestCase):
    """projects.services.mark_resolved: the ONLY gate to `resolved` (idempotent, disputed tasks only)."""

    def setUp(self):
        from projects.models import Application

        self.company = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        self.freelance = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        self.project = projects.create_project(self.company, "Project", "Description.")
        self.task = projects.add_task(self.project, self.company, "Task", "", "100", ["x"])
        projects.apply(self.task, self.freelance, "", ["x"])
        projects.choose(self.task, Application.objects.get(task=self.task), self.company)
        self.task.refresh_from_db()

    def test_refused_on_a_non_disputed_task(self):
        with self.assertRaises(projects.ProjectError) as ctx:
            projects.mark_resolved(self.task, 50)
        self.assertEqual(ctx.exception.code, "wrong_state")

    def test_idempotent_and_closes_the_project(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.Status.DELIVERED, delivered_at=timezone.now())
        projects.mark_disputed(Task.objects.get(pk=self.task.pk), self.company, REASON)
        task = projects.mark_resolved(Task.objects.get(pk=self.task.pk), 30)
        self.assertEqual(task.status, "resolved")
        first = Dispute.objects.get(task=self.task).resolved_at
        again = projects.mark_resolved(Task.objects.get(pk=self.task.pk), 90)
        self.assertEqual(again.status, "resolved")
        dispute = Dispute.objects.get(task=self.task)
        self.assertEqual((dispute.freelance_pct, dispute.resolved_at), (30, first), "the second call changes nothing")
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.CLOSED)

    def test_invalid_share(self):
        with self.assertRaises(projects.ProjectError) as ctx:
            projects.mark_resolved(self.task, 101)
        self.assertEqual(ctx.exception.code, "invalid")
