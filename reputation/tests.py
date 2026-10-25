"""Reputation: company ratings, the « Reliable payer » profile (confirmed on-chain payouts only),
badges, the « No history » signal and the GitHub proof. No network: `requests.get` is mocked."""

import base64
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from payments.models import Escrow, ProjectDeposit
from projects import services as projects
from projects.models import Application, Dispute, Task

from . import services
from .models import CompanyRating, GithubIdentity
from .services import ReputationError

JSON = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "fetch"}
GIST_ID = "0123456789abcdef0123456789abcdef"
HASH_A = "a" * 64
UTC = dt_timezone.utc


def make_wallet(name: str = "") -> tuple[WalletUser, Keypair]:
    kp = Keypair.random()
    return WalletUser.objects.create(stellar_address=kp.public_key, display_name=name), kp


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


_counter = {"n": 0}


def _tx_hash() -> str:
    _counter["n"] += 1
    return f"{_counter['n']:064x}"


def make_task(company, freelancer, *, price="100", status="paid", project=None) -> Task:
    """A task of `company` taken by `freelancer`, pushed to `status` (taken / delivered / paid)."""
    project = project or projects.create_project(company, "Reputation project", "A description.")
    task = projects.add_task(project, company, "A task", "", price, ["django"])
    projects.apply(task, freelancer, "", ["django"])
    projects.choose(task, Application.objects.get(task=task, freelancer=freelancer), company)
    if status in ("delivered", "paid"):
        projects.deliver(task, freelancer, "https://example.com/pr/1")
    if status == "paid":
        projects.validate(task, company, 5, "")
        projects.mark_paid(task)
    task.refresh_from_db()
    return task


def confirm(task: Task, *, mode: str = "direct", released_at=None, delivered_at=None) -> Escrow:
    """Store a confirmed on-chain payout on the task's escrow row (what payments.confirm_* does)."""
    fields = {"status": Escrow.Status.PAID, "payment_tx_hash": _tx_hash()} if mode == "direct" else {
        "status": Escrow.Status.RELEASED, "release_tx_hash": _tx_hash(), "mode": Escrow.Mode.ESCROW}
    escrow, _ = Escrow.objects.get_or_create(
        task=task,
        defaults={
            "mode": Escrow.Mode.DIRECT, "amount": task.price,
            "payer_address": task.project.company.stellar_address, "payee_address": task.assigned_to.stellar_address,
        },
    )
    fields["released_at"] = released_at or task.paid_at
    Escrow.objects.filter(pk=escrow.pk).update(**fields)
    if delivered_at is not None:
        Task.objects.filter(pk=task.pk).update(delivered_at=delivered_at)
    escrow.refresh_from_db()
    return escrow


def paid_task(company, freelancer, **kw) -> Task:
    task = make_task(company, freelancer, price=kw.pop("price", "100"))
    confirm(task, **kw)
    return task


# --- company ratings ------------------------------------------------------------------------


class RateCompanyTests(TestCase):
    def setUp(self):
        self.company, _ = make_wallet("Studio")
        self.freelance, _ = make_wallet("Yanis")
        self.other, _ = make_wallet("Nora")

    def test_only_the_assignee(self):
        task = make_task(self.company, self.freelance)
        for wallet in (self.other, self.company, None):
            with self.assertRaises(ReputationError) as ctx:
                services.rate_company(task, wallet, 5)
            self.assertEqual(ctx.exception.code, "forbidden")

    def test_wrong_state_until_settled(self):
        for status in ("taken", "delivered"):
            task = make_task(self.company, self.freelance, status=status)
            with self.assertRaises(ReputationError) as ctx:
                services.rate_company(task, self.freelance, 4)
            self.assertEqual(ctx.exception.code, "wrong_state", status)
        self.assertFalse(CompanyRating.objects.exists())

    def test_paid_then_duplicate(self):
        task = make_task(self.company, self.freelance)
        with self.assertLogs("reputation.services", "INFO") as logs:
            rating = services.rate_company(task, self.freelance, "4", "  Clear brief  " + "x" * 400)
        self.assertEqual((rating.note, rating.company, rating.freelancer), (4, self.company, self.freelance))
        self.assertEqual(len(rating.comment), 280)
        self.assertTrue(rating.comment.startswith("Clear brief"))
        self.assertIn(f"company rated task={task.pk} note=4 company={self.company.pk}", logs.output[0])
        with self.assertRaises(ReputationError) as ctx:
            services.rate_company(task, self.freelance, 5)
        self.assertEqual(ctx.exception.code, "duplicate")

    def test_note_bounds(self):
        task = make_task(self.company, self.freelance)
        for note in (0, 6, "x", None, "4.5"):
            with self.assertRaises(ReputationError) as ctx:
                services.rate_company(task, self.freelance, note)
            self.assertEqual(ctx.exception.code, "invalid", note)

    def test_resolved_status_string_is_settled(self):
        task = make_task(self.company, self.freelance, status="delivered")
        Task.objects.filter(pk=task.pk).update(status="resolved")  # arrives with a later merge
        task.refresh_from_db()
        self.assertEqual(services.rate_company(task, self.freelance, 3).note, 3)

    def test_summary(self):
        self.assertEqual(services.company_rating_summary(self.company), {"avg": None, "count": 0})
        services.rate_company(make_task(self.company, self.freelance), self.freelance, 5)
        services.rate_company(make_task(self.company, self.other), self.other, 4)
        services.rate_company(make_task(self.company, self.freelance), self.freelance, 4)
        summary = services.company_rating_summary(self.company)
        self.assertEqual(summary, {"avg": Decimal("4.3"), "count": 3})

    def test_does_not_touch_the_freelance_score_history(self):
        """Company ratings never feed projects.scoring (Validated / Recommended)."""
        task = make_task(self.company, self.freelance)
        before = projects.company_history(self.company.pk, self.freelance.pk)
        services.rate_company(task, self.freelance, 1)
        self.assertEqual(projects.company_history(self.company.pk, self.freelance.pk), before)


# --- payer profile, badges, history ----------------------------------------------------------


class PayerProfileTests(TestCase):
    def setUp(self):
        self.company, _ = make_wallet("Studio")
        self.f1, _ = make_wallet("A")
        self.f2, _ = make_wallet("B")
        self.f3, _ = make_wallet("C")

    def test_only_confirmed_escrows_count(self):
        paid_task(self.company, self.f1, price="120")
        paid_task(self.company, self.f2, price="80", mode="escrow")
        no_hash = make_task(self.company, self.f3)  # escrow row (created at validation) but no hash
        self.assertTrue(Escrow.objects.filter(task=no_hash, payment_tx_hash="", release_tx_hash="").exists())
        no_escrow = make_task(self.company, self.f3)
        Escrow.objects.filter(task=no_escrow).delete()
        pending = make_task(self.company, self.f3)  # a pending direct hash (Horizon timeout) is not confirmed
        Escrow.objects.filter(task=pending).update(payment_tx_hash=_tx_hash(), status=Escrow.Status.CREATED)

        profile = services.payer_profile(self.company)
        self.assertEqual(profile["paid_tasks"], 2)
        self.assertEqual(profile["partners"], 2)
        self.assertEqual(profile["paid_total"], Decimal("200"))
        self.assertEqual(profile["disputes_lost"], {"count": 0, "links": []})
        self.assertEqual(profile["deposits_forfeited"], {"count": 0, "links": []})

    def test_disputes_lost_from_resolved_escrows(self):
        lost = make_task(self.company, self.f1)
        Escrow.objects.filter(task=lost).update(resolve_tx_hash=_tx_hash(), status=Escrow.Status.RESOLVED)
        Dispute.objects.create(task=lost, opened_by=self.f1, reason="silence", freelance_pct=70, resolved_at=timezone.now())
        won = make_task(self.company, self.f2)
        Escrow.objects.filter(task=won).update(resolve_tx_hash=_tx_hash(), status=Escrow.Status.RESOLVED)
        Dispute.objects.create(task=won, opened_by=self.company, reason="late", freelance_pct=20, resolved_at=timezone.now())
        pending = make_task(self.company, self.f3)  # dispute open, nothing resolved on chain
        Dispute.objects.create(task=pending, opened_by=self.company, reason="late")
        for _ in range(3):
            paid_task(self.company, self.f3)
        profile = services.payer_profile(self.company)
        self.assertEqual(profile["disputes_lost"]["count"], 1)
        self.assertEqual(profile["disputes_lost"]["links"][0]["task_id"], lost.pk)
        self.assertIn("/tx/", profile["disputes_lost"]["links"][0]["url"])
        self.assertFalse(profile["reliable_payer"])

    def test_deposits_forfeited_from_resolved_deposits(self):
        lost = make_task(self.company, self.f1)
        common = dict(
            amount=Decimal("5"), covered_budget=Decimal("100"), payer_address=self.company.stellar_address,
            platform_address="G" + "A" * 55, resolver_address="G" + "B" * 55, fund_address="G" + "C" * 55,
        )
        ProjectDeposit.objects.create(
            project=lost.project, status=ProjectDeposit.Status.FORFEITED, resolve_tx_hash=_tx_hash(),
            dispute_tx_hash=_tx_hash(), settled_at=timezone.now(), **common,
        )
        other = make_task(self.company, self.f2)
        ProjectDeposit.objects.create(project=other.project, status=ProjectDeposit.Status.FUNDED, **common)
        for _ in range(3):
            paid_task(self.company, self.f3)
        profile = services.payer_profile(self.company)
        self.assertEqual(profile["deposits_forfeited"]["count"], 1)
        self.assertEqual(profile["deposits_forfeited"]["links"][0]["project_id"], lost.project_id)
        self.assertFalse(profile["reliable_payer"])

    def test_distinct_partners(self):
        paid_task(self.company, self.f1)
        paid_task(self.company, self.f1)
        profile = services.payer_profile(self.company)
        self.assertEqual((profile["paid_tasks"], profile["partners"]), (2, 1))
        self.assertEqual(len(profile["links"]["partners"]), 1)

    def test_reliable_payer_threshold(self):
        paid_task(self.company, self.f1)
        paid_task(self.company, self.f2)
        self.assertFalse(services.payer_profile(self.company)["reliable_payer"])
        with override_settings(LOWBID_RELIABLE_PAYER_MIN_PARTNERS=2):
            self.assertTrue(services.payer_profile(self.company)["reliable_payer"])
            self.assertIn("reliable-payer", [b["key"] for b in services.wallet_badges(self.company)])
        paid_task(self.company, self.f3)
        self.assertTrue(services.payer_profile(self.company)["reliable_payer"])

    def test_disputes_or_deposits_block_the_badge(self):
        for who in (self.f1, self.f2, self.f3):
            paid_task(self.company, who)
        with patch("reputation.services._disputes_lost", return_value={"count": 1, "links": []}):
            self.assertFalse(services.payer_profile(self.company)["reliable_payer"])
        with patch("reputation.services._deposits_forfeited", return_value={"count": 1, "links": []}):
            self.assertFalse(services.payer_profile(self.company)["reliable_payer"])

    def test_avg_delay_days(self):
        d0 = datetime(2026, 1, 1, tzinfo=UTC)
        paid_task(self.company, self.f1, delivered_at=d0, released_at=d0 + timedelta(days=2, hours=12))
        paid_task(self.company, self.f2, delivered_at=d0, released_at=d0 + timedelta(days=1))
        profile = services.payer_profile(self.company)
        self.assertEqual(profile["avg_delay_days"], Decimal("1.8"))  # (2.5 + 1) / 2 = 1.75
        self.assertEqual(len(profile["links"]["avg_delay_days"]), 2)

    def test_avg_delay_none_without_data(self):
        self.assertIsNone(services.payer_profile(self.company)["avg_delay_days"])

    def test_every_figure_has_verifiable_links(self):
        task = paid_task(self.company, self.f1)
        escrow = Escrow.objects.get(task=task)
        profile = services.payer_profile(self.company)
        for key in ("paid_tasks", "partners", "paid_total", "avg_delay_days", "disputes_lost", "deposits_forfeited"):
            self.assertIn(key, profile["links"])
        for key in ("paid_tasks", "partners", "paid_total", "avg_delay_days"):
            link = profile["links"][key][0]
            self.assertEqual(link["label"], f"task #{task.pk}")
            self.assertEqual(link["url"], f"https://stellar.expert/explorer/testnet/tx/{escrow.payment_tx_hash}")

    def test_new_account_badge_and_history(self):
        self.assertIn("new-account", [b["key"] for b in services.wallet_badges(self.company)])
        self.assertFalse(services.has_history(self.company))
        self.assertFalse(services.has_history(self.f1))
        make_task(self.company, self.f1)  # paid in DB, no confirmed hash: still no history
        self.assertFalse(services.has_history(self.f1))
        paid_task(self.company, self.f2)
        for wallet in (self.company, self.f2):  # payer and payee
            self.assertTrue(services.has_history(wallet))
            self.assertNotIn("new-account", [b["key"] for b in services.wallet_badges(wallet)])
        self.assertFalse(services.has_history(None))

    def test_github_badge(self):
        GithubIdentity.objects.create(
            wallet=self.f1, github_id=7, github_login="octo", gist_id=GIST_ID,
            account_created_at=datetime(2015, 1, 1, tzinfo=UTC), scheme="sep53",
        )
        badge = next(b for b in services.wallet_badges(self.f1) if b["key"] == "github-verified")
        self.assertEqual((badge["label"], badge["tone"], badge["href"]), ("Verified GitHub", "info", "https://github.com/octo"))


# --- GitHub proof ----------------------------------------------------------------------------


def _resp(status: int, payload=None, bad_json: bool = False):
    r = Mock()
    r.status_code = status
    r.json = Mock(side_effect=ValueError("no json")) if bad_json else Mock(return_value=payload)
    return r


class GithubTests(TestCase):
    def setUp(self):
        self.wallet, self.kp = make_wallet("Yanis")
        self.message = services.github_message(self.wallet)
        self.login = "octo"
        self.github_id = 4242
        self.created_at = "2018-03-04T05:06:07Z"
        self.public = True
        self.content = self.proof()

    def proof(self, message=None, signature=None) -> str:
        message = message or self.message
        sig = signature or base64.b64encode(self.kp.sign_message(message)).decode()
        return f"{message}\nsignature: {sig}\n"

    def fake_get(self, url, headers=None, timeout=None):
        if url.endswith(f"/gists/{GIST_ID}"):
            return _resp(200, {
                "public": self.public, "owner": {"login": self.login, "id": self.github_id},
                "files": {"readme.md": {"content": "TaskVault proof"}, "proof.txt": {"content": self.content}},
            })
        if url.endswith(f"/users/{self.login}"):
            return _resp(200, {"login": self.login, "id": self.github_id, "created_at": self.created_at})
        return _resp(404)

    def verify(self, ref=GIST_ID, wallet=None):
        with patch("reputation.services.requests.get", side_effect=self.fake_get) as get:
            identity = services.verify_github(wallet or self.wallet, ref)
        return identity, get

    def assertCode(self, code, ref=GIST_ID, wallet=None):
        with self.assertRaises(ReputationError) as ctx:
            self.verify(ref, wallet)
        self.assertEqual(ctx.exception.code, code)

    def test_message(self):
        self.assertEqual(self.message, f"lowbid:{self.wallet.stellar_address}")

    def test_happy_path_with_url(self):
        identity, get = self.verify(f"https://gist.github.com/octo/{GIST_ID}")
        self.assertEqual((identity.github_login, identity.github_id, identity.gist_id), ("octo", 4242, GIST_ID))
        self.assertEqual(identity.scheme, "sep53")
        self.assertEqual(identity.account_created_at, datetime(2018, 3, 4, 5, 6, 7, tzinfo=UTC))
        urls = [c.args[0] for c in get.call_args_list]
        self.assertEqual(urls, [f"https://api.github.com/gists/{GIST_ID}", "https://api.github.com/users/octo"])
        for c in get.call_args_list:
            self.assertEqual(c.kwargs["timeout"], 10)
            self.assertEqual(c.kwargs["headers"]["Accept"], "application/vnd.github+json")
            self.assertNotIn("Authorization", c.kwargs["headers"])

    def test_raw_scheme_accepted(self):
        self.content = self.proof(signature=base64.b64encode(self.kp.sign(self.message.encode())).decode())
        identity, _ = self.verify()
        self.assertEqual(identity.scheme, "raw")

    def test_bad_refs(self):
        for ref in ("", "nope", "https://gist.github.com/octo/xyz", "https://evil.example/octo/" + GIST_ID, GIST_ID + "0"):
            with self.assertRaises(ReputationError) as ctx:
                services.verify_github(self.wallet, ref)
            self.assertEqual(ctx.exception.code, "invalid", ref)

    def test_not_found(self):
        self.assertCode("not_found", "f" * 32)

    def test_not_public(self):
        self.public = False
        self.assertCode("not_public")

    def test_wrong_message(self):
        other, _ = make_wallet()
        self.content = self.proof(message=services.github_message(other))
        self.assertCode("bad_signature")
        self.content = "signature: abc"
        self.assertCode("bad_signature")

    def test_wrong_signature(self):
        stranger = Keypair.random()
        self.content = self.proof(signature=base64.b64encode(stranger.sign_message(self.message)).decode())
        self.assertCode("bad_signature")
        self.content = self.proof(signature="not-base64")
        self.assertCode("bad_signature")

    def test_too_recent(self):
        self.created_at = "2026-01-01T00:00:00Z"
        with patch("django.utils.timezone.now", return_value=datetime(2026, 6, 1, tzinfo=UTC)):
            self.assertCode("too_recent")
            with override_settings(LOWBID_GITHUB_MIN_AGE_DAYS=100):
                identity, _ = self.verify()
        self.assertEqual(identity.github_login, "octo")

    def test_already_used(self):
        self.verify()
        other, other_kp = make_wallet()
        self.kp, self.message = other_kp, services.github_message(other)
        self.content = self.proof()
        self.assertCode("already_used", wallet=other)

    def test_duplicate_for_the_wallet(self):
        self.verify()
        self.assertCode("duplicate")

    def test_provider_errors_are_logged(self):
        with patch("reputation.services.requests.get", side_effect=requests.ConnectionError("boom")):
            with self.assertLogs("reputation.services", "ERROR") as logs:
                with self.assertRaises(ReputationError) as ctx:
                    services.verify_github(self.wallet, GIST_ID)
        self.assertEqual(ctx.exception.code, "provider")
        self.assertIn("github request failed", logs.output[0])
        self.assertIn("ConnectionError", "\n".join(logs.output))
        with patch("reputation.services.requests.get", return_value=_resp(200, bad_json=True)):
            with self.assertLogs("reputation.services", "ERROR"):
                with self.assertRaises(ReputationError) as ctx:
                    services.verify_github(self.wallet, GIST_ID)
        self.assertEqual(ctx.exception.code, "provider")
        with patch("reputation.services.requests.get", return_value=_resp(403, {"message": "rate limited"})):
            with self.assertRaises(ReputationError) as ctx:
                services.verify_github(self.wallet, GIST_ID)
        self.assertEqual(ctx.exception.code, "provider")

    @override_settings(LOWBID_GITHUB_TOKEN="ghp_supersecret")
    def test_token_header_never_logged(self):
        with self.assertLogs("reputation.services", "DEBUG") as logs:
            identity, get = self.verify()
            with patch("reputation.services.requests.get", side_effect=requests.Timeout("slow")):
                with self.assertRaises(ReputationError):
                    services.verify_github(make_wallet()[0], GIST_ID)
        for c in get.call_args_list:
            self.assertEqual(c.kwargs["headers"]["Authorization"], "Bearer ghp_supersecret")
        self.assertNotIn("ghp_supersecret", "\n".join(logs.output))
        self.assertIsNotNone(identity.pk)

    def test_unlink(self):
        self.verify()
        services.unlink_github(self.wallet)
        self.assertFalse(GithubIdentity.objects.exists())
        with self.assertRaises(ReputationError) as ctx:
            services.unlink_github(self.wallet)
        self.assertEqual(ctx.exception.code, "not_found")


# --- views -----------------------------------------------------------------------------------


class ViewTests(TestCase):
    def setUp(self):
        self.company, _ = make_wallet("Studio")
        self.freelance, self.kp = make_wallet("Yanis")
        self.task = make_task(self.company, self.freelance)
        self.rate_url = reverse("reputation:rate_company", kwargs={"pk": self.task.pk})

    def post(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json", **JSON)

    def test_anonymous_gets_401_json(self):
        for url in (self.rate_url, reverse("reputation:github_verify"), reverse("reputation:github_unlink")):
            r = self.post(url, {})
            self.assertEqual(r.status_code, 401, url)
            self.assertEqual(r.json()["error"], "wallet_required")
        self.assertEqual(self.client.get(reverse("reputation:github_message"), **JSON).status_code, 401)

    def test_rate_company_ok(self):
        login(self.client, self.freelance)
        r = self.post(self.rate_url, {"note": 4, "comment": "Paid fast"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "note": 4, "avg": "4.0", "count": 1, "message": r.json()["message"]})
        self.assertEqual(self.post(self.rate_url, {"note": 4}).status_code, 409)

    def test_rate_company_codes(self):
        login(self.client, self.freelance)
        r = self.post(self.rate_url, {"note": 9})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        taken = make_task(self.company, self.freelance, status="taken")
        r = self.post(reverse("reputation:rate_company", kwargs={"pk": taken.pk}), {"note": 5})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "wrong_state"))
        self.assertEqual(self.post(reverse("reputation:rate_company", kwargs={"pk": 999999}), {"note": 5}).status_code, 404)
        self.assertEqual(self.client.get(self.rate_url, **JSON).status_code, 405)

    def test_acting_wallet_comes_from_the_session(self):
        login(self.client, self.company)
        body = {"note": 5, "freelancer": self.freelance.stellar_address, "address": self.freelance.stellar_address}
        r = self.post(self.rate_url, body)
        self.assertEqual((r.status_code, r.json()["error"]), (403, "forbidden"))
        self.assertFalse(CompanyRating.objects.exists())
        r = self.client.get(reverse("reputation:github_message") + f"?address={self.freelance.stellar_address}", **JSON)
        self.assertEqual(r.json()["message"], f"lowbid:{self.company.stellar_address}")

    def test_github_endpoints(self):
        login(self.client, self.freelance)
        url = reverse("reputation:github_verify")
        r = self.post(url, {"gist": "nope"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid"))
        with patch("reputation.services.requests.get", return_value=_resp(404)):
            r = self.post(url, {"gist": GIST_ID})
        self.assertEqual((r.status_code, r.json()["error"]), (404, "not_found"))
        with patch("reputation.services.requests.get", side_effect=requests.ConnectionError("down")):
            with self.assertLogs("reputation.services", "ERROR"):
                r = self.post(url, {"gist": GIST_ID})
        self.assertEqual((r.status_code, r.json()["error"]), (502, "provider"))

        message = f"lowbid:{self.freelance.stellar_address}"
        sig = base64.b64encode(self.kp.sign_message(message)).decode()

        def fake_get(u, headers=None, timeout=None):
            if "/gists/" in u:
                return _resp(200, {"public": True, "owner": {"login": "octo", "id": 9},
                                   "files": {"p": {"content": f"{message}\nsignature: {sig}"}}})
            return _resp(200, {"login": "octo", "created_at": "2015-01-01T00:00:00Z"})

        other, _ = make_wallet()
        with patch("reputation.services.requests.get", side_effect=fake_get):
            r = self.post(url, {"gist": GIST_ID, "address": other.stellar_address})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["login"], "octo")
        self.assertIn("verified_at", r.json())
        self.assertEqual(GithubIdentity.objects.get().wallet, self.freelance)
        r = self.post(url, {"gist": GIST_ID})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "duplicate"))
        r = self.post(reverse("reputation:github_unlink"), {})
        self.assertEqual(r.status_code, 200)
        r = self.post(reverse("reputation:github_unlink"), {})
        self.assertEqual((r.status_code, r.json()["error"]), (404, "not_found"))

    def test_task_page_panels(self):
        login(self.client, self.freelance)
        page = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.task.pk})).content.decode()
        self.assertIn('id="rate-company-panel"', page)
        self.assertIn("data-rate-company", page)
        self.assertEqual(page.count("data-company-rate="), 5)
        self.assertIn("js/lowbid-reputation.js", page)
        self.assertIn("data-no-history", page)  # the chosen freelance has no confirmed payout
        services.rate_company(self.task, self.freelance, 4)
        login(self.client, self.company)
        page = self.client.get(reverse("projects:task_detail", kwargs={"pk": self.task.pk})).content.decode()
        self.assertIn('data-company-rating="4"', page)
        self.assertNotIn("data-rate-company ", page)

    def test_profile_page(self):
        paid = make_task(self.company, self.freelance)
        confirm(paid)
        services.rate_company(paid, self.freelance, 5)
        page = self.client.get(reverse("dashboard:profile", args=[self.company.stellar_address])).content.decode()
        self.assertIn('id="payer-profile"', page)
        self.assertIn('data-company-avg="5.0"', page)
        self.assertNotIn('id="github-verify"', page)  # owner only
        login(self.client, self.company)
        page = self.client.get(reverse("dashboard:profile", args=[self.company.stellar_address])).content.decode()
        self.assertIn('id="github-verify"', page)
        self.assertIn("data-github-sign", page)
        self.assertIn("https://gist.github.com", page)
        page = self.client.get(reverse("dashboard:profile", args=[self.freelance.stellar_address])).content.decode()
        self.assertNotIn('id="payer-profile"', page)  # never posted a project
        self.assertNotIn('id="github-verify"', page)


# --- template tags ---------------------------------------------------------------------------


class TagTests(TestCase):
    def render(self, src: str, **ctx) -> str:
        return Template("{% load reputation_extras %}" + src).render(Context(ctx))

    def setUp(self):
        self.company, _ = make_wallet("Studio")
        self.freelance, _ = make_wallet("Yanis")

    def test_badges(self):
        html = self.render("{% reputation_badges w %}", w=self.freelance)
        self.assertIn('data-badge="new-account"', html)
        GithubIdentity.objects.create(
            wallet=self.freelance, github_id=1, github_login="octo", gist_id=GIST_ID,
            account_created_at=datetime(2015, 1, 1, tzinfo=UTC), scheme="sep53",
        )
        html = self.render("{% reputation_badges w %}", w=self.freelance)
        self.assertIn('data-badge="github-verified"', html)
        self.assertIn('href="https://github.com/octo"', html)
        self.assertIn('rel="noopener noreferrer nofollow"', html)
        with override_settings(LOWBID_RELIABLE_PAYER_MIN_PARTNERS=1):
            paid_task(self.company, self.freelance)
            html = self.render("{% reputation_badges w %}", w=self.company)
        self.assertIn('data-badge="reliable-payer"', html)
        self.assertNotIn('data-badge="new-account"', html)

    def test_payer_panel(self):
        self.assertEqual(self.render("{% payer_profile_panel w %}", w=self.company).strip(), "")
        projects.create_project(self.company, "Empty", "Nothing yet.")
        html = self.render("{% payer_profile_panel w %}", w=self.company)
        self.assertIn('id="payer-profile"', html)
        for key in ("paid_tasks", "partners", "paid_total", "avg_delay_days", "disputes_lost", "deposits_forfeited"):
            self.assertIn(f'data-payer-figure="{key}"', html)
        self.assertNotIn("data-payer-links", html)
        self.assertIn("Computed only from confirmed Stellar transactions.", html)
        paid_task(self.company, self.freelance)
        html = self.render("{% payer_profile_panel w %}", w=self.company)
        self.assertIn("data-payer-links", html)
        self.assertIn("https://stellar.expert/explorer/testnet/tx/", html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_rate_company_panel(self):
        task = make_task(self.company, self.freelance, status="delivered")
        self.assertEqual(self.render("{% rate_company_panel t w %}", t=task, w=self.freelance).strip(), "")
        projects.validate(task, self.company, 5)
        projects.mark_paid(task)
        task.refresh_from_db()
        self.assertIn('id="rate-company-panel"', self.render("{% rate_company_panel t w %}", t=task, w=self.freelance))
        self.assertEqual(self.render("{% rate_company_panel t w %}", t=task, w=self.company).strip(), "")
        services.rate_company(task, self.freelance, 2, "Slow")
        for viewer in (self.freelance, self.company, None):
            html = self.render("{% rate_company_panel t w %}", t=task, w=viewer)
            self.assertIn('data-company-rating="2"', html)
            self.assertNotIn("data-rate-company-submit", html)

    def test_history_signal(self):
        self.assertIn("data-no-history", self.render("{% history_signal w %}", w=self.freelance))
        paid_task(self.company, self.freelance)
        self.assertEqual(self.render("{% history_signal w %}", w=self.freelance).strip(), "")
