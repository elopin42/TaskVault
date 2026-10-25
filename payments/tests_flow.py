"""End-to-end tests of the payment flow through the HTTP endpoints (no network: `requests`
is mocked in both payments.trustless_work and payments.stellar). Complements payments/tests.py
(unit tests of the two clients). One Trustless Work escrow PER TASK; direct payment fallback."""

import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from stellar_sdk import Keypair, TransactionEnvelope

from accounts.models import WalletUser
from payments import stellar
from payments import trustless_work as tw
from payments.models import Escrow
from payments.services import PENDING_MESSAGE, PaymentError, next_action, project_funding, stepper
from projects import services as projects
from projects.models import Application, Project, Rating, Task

JSON = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "fetch"}
USDC_ISSUER = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
PLATFORM = Keypair.random().public_key
CONTRACT = "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"
TESTNET = "Test SDF Network ; September 2015"
LINK = "https://github.com/studio-nova/booking/pull/1"


# --- fixtures ----------------------------------------------------------------------------


def _resp(status: int, payload=None):
    r = Mock()
    r.status_code = status
    r.content = b"x" if payload is not None else b""
    r.text = json.dumps(payload) if payload is not None else ""
    r.json = Mock(return_value=payload) if payload is not None else Mock(side_effect=ValueError("no json"))
    return r


def make_wallet(name: str = "") -> tuple[WalletUser, Keypair]:
    kp = Keypair.random()
    return WalletUser.objects.create(stellar_address=kp.public_key, display_name=name), kp


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


def make_project(company: WalletUser, freelance: WalletUser) -> tuple[Project, Task, Task]:
    """A draft project with T1 (120 USDC) TAKEN by `freelance` and T2 (80 USDC) still open."""
    project = projects.create_project(company, "Refonte du logo", "Logo vectoriel + mini charte.")
    t1 = projects.add_task(project, company, "Logo vectoriel", "3 pistes, 2 itérations.", "120", ["design", "figma"])
    t2 = projects.add_task(project, company, "Mini charte", "", "80", ["design"])
    projects.apply(t1, freelance, "3 pistes", ["design"])
    projects.choose(t1, Application.objects.get(task=t1, freelancer=freelance), company)
    t1.refresh_from_db()
    return project, t1, t2


def sign(xdr: str, kp: Keypair) -> str:
    env = TransactionEnvelope.from_xdr(xdr, TESTNET)
    env.sign(kp)
    return env.to_xdr()


def some_xdr(source: str, destination: str, amount: str = "1") -> str:
    """Any valid unsigned XDR (offline build) — what Trustless Work would hand back."""
    return stellar.build_payment_xdr(source=source, destination=destination, amount=Decimal(amount), sequence=7)


class TWRouter:
    """requests.post stand-in for Trustless Work: records every call, answers builds and sends."""

    def __init__(self, xdr: str, send_payload=None, build_status=201, send_status=200):
        self.xdr = xdr
        self.calls: list[tuple[str, dict]] = []
        self.send_payload = send_payload or {"status": "SUCCESS", "message": "ok", "contractId": CONTRACT}
        self.build_status = build_status
        self.send_status = send_status
        self.build_payload = {"status": "SUCCESS", "unsignedTransaction": xdr}

    def __call__(self, url, json=None, **kw):
        path = url.split("trustlesswork.com", 1)[-1]
        self.calls.append((path, json or {}))
        if path == tw.PATH_SEND:
            return _resp(self.send_status, self.send_payload)
        return _resp(self.build_status, self.build_payload)

    def last(self, path: str) -> dict:
        return next(body for p, body in reversed(self.calls) if p == path)

    def count(self, path: str) -> int:
        return sum(1 for p, _ in self.calls if p == path)


def horizon_account(address: str, with_usdc: bool = True, balance: str = "10.0000000", sequence: str = "42"):
    balances = [{"asset_type": "native", "balance": "9999.0000000"}]
    if with_usdc:
        balances.insert(0, {"asset_type": "credit_alphanum4", "asset_code": "USDC", "asset_issuer": USDC_ISSUER, "balance": balance})
    return {"id": address, "account_id": address, "sequence": sequence, "balances": balances}


class HorizonGet:
    """requests.get stand-in for Horizon: /accounts/{addr}, /fee_stats, /transactions/{hash}."""

    def __init__(self, accounts: dict | None = None, transactions: dict | None = None):
        self.accounts = accounts or {}
        self.transactions = transactions or {}

    def __call__(self, url, **kw):
        if url.endswith("/fee_stats"):
            return _resp(200, {"last_ledger_base_fee": "100"})
        if "/accounts/" in url:
            addr = url.rsplit("/accounts/", 1)[-1]
            payload = self.accounts.get(addr)
            return _resp(200, payload) if payload else _resp(404, {"status": 404})
        if "/transactions/" in url:
            h = url.rsplit("/transactions/", 1)[-1]
            payload = self.transactions.get(h)
            return _resp(200, payload) if payload else _resp(404, {"status": 404})
        return _resp(404, {})


def submit_ok(url, data=None, **kw):
    h = TransactionEnvelope.from_xdr(data["tx"], TESTNET).hash_hex()
    return _resp(200, {"hash": h, "ledger": 1234, "successful": True})


ESCROW_SETTINGS = dict(
    TRUSTLESS_WORK_API_KEY="tw-test-key",
    TRUSTLESS_WORK_API_URL="https://dev.api.trustlesswork.com",
    LOWBID_PAYMENT_MODE="escrow",
    LOWBID_PLATFORM_ADDRESS=PLATFORM,
    LOWBID_PLATFORM_FEE=Decimal("1"),
    STELLAR_ASSET_ISSUER=USDC_ISSUER,
    STELLAR_ASSET_CODE="USDC",
    STELLAR_HORIZON_URL="https://horizon-testnet.stellar.org",
)
DIRECT_SETTINGS = {**ESCROW_SETTINGS, "LOWBID_PAYMENT_MODE": "direct"}


class BasePayTest(TestCase):
    def setUp(self):
        self.company, self.company_kp = make_wallet("company")
        self.freelance, self.freelance_kp = make_wallet("freelance")
        self.other, self.other_kp = make_wallet("other")
        self.project, self.task, self.open_task = make_project(self.company, self.freelance)
        self.unsigned = some_xdr(self.company.stellar_address, self.freelance.stellar_address)

    # HTTP helpers
    def prepare(self, step, body=None, task=None):
        url = reverse("payments:prepare", kwargs={"task_pk": (task or self.task).pk, "step": step})
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json", **JSON)

    def send(self, step, signed_xdr, body=None, task=None):
        url = reverse("payments:send", kwargs={"task_pk": (task or self.task).pk, "step": step})
        payload = {"signed_xdr": signed_xdr, **(body or {})}
        return self.client.post(url, data=json.dumps(payload), content_type="application/json", **JSON)

    def run_step(self, step, kp, body=None):
        """prepare → sign with `kp` → send. Returns (prepare json, send json)."""
        prep = self.prepare(step, body).json()
        self.assertTrue(prep["ok"], prep)
        self.assertIn("xdr", prep)
        sent = self.send(step, sign(prep["xdr"], kp), body).json()
        return prep, sent

    def validate(self, note=5, comment="Top"):
        url = reverse("projects:task_validate", kwargs={"pk": self.task.pk})
        return self.client.post(url, data=json.dumps({"note": note, "comment": comment}), content_type="application/json", **JSON)

    def escrow(self) -> Escrow:
        return Escrow.objects.get(task=self.task)

    def task_status(self) -> str:
        return Task.objects.get(pk=self.task.pk).status

    def fresh(self) -> Task:
        return Task.objects.select_related("project__company", "assigned_to").get(pk=self.task.pk)

    def detail(self, task=None):
        return self.client.get(reverse("projects:task_detail", args=[(task or self.task).pk]))

    def prepare_url(self, step, task=None):
        return reverse("payments:prepare", kwargs={"task_pk": (task or self.task).pk, "step": step})


# =============================== escrow mode ==================================


@override_settings(**ESCROW_SETTINGS)
class EscrowHappyPathTests(BasePayTest):
    def test_full_flow_company_freelance_company(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            # 1. company deploys the escrow of THIS task
            login(self.client, self.company)
            prep, sent = self.run_step("deploy", self.company_kp)
            self.assertEqual(prep["send_url"], reverse("payments:send", kwargs={"task_pk": self.task.pk, "step": "deploy"}))
            self.assertTrue(sent["ok"], sent)
            self.assertEqual(sent["contract_id"], CONTRACT)
            self.assertTrue(sent["redirect"].endswith(f"/taches/{self.task.pk}/#paiement"))
            self.assertIn("stellar.expert", sent["explorer_url"])
            self.assertEqual(sent["task_status"], "taken")
            self.assertEqual((sent["next"]["step"], sent["next"]["mine"]), ("fund", True), "the page chains fund right away")
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.DEPLOYED)
            self.assertEqual(esc.mode, Escrow.Mode.ESCROW)
            self.assertEqual(esc.contract_id, CONTRACT)
            self.assertEqual(esc.deploy_tx_hash, sent["tx_hash"])
            self.assertEqual(len(esc.deploy_tx_hash), 64)
            self.assertEqual(esc.engagement_id, f"taskvault-task-{self.task.pk}")
            self.assertEqual(esc.amount, Decimal("120"))
            self.assertEqual(esc.payer_address, self.company.stellar_address)
            self.assertEqual(esc.payee_address, self.freelance.stellar_address)
            self.assertEqual(esc.platform_address, PLATFORM)
            self.assertEqual(self.task_status(), "taken")
            # deploy payload: every role pinned to session wallet / chosen freelance / platform
            body = router.last(tw.PATH_DEPLOY)
            self.assertEqual(body["signer"], self.company.stellar_address)
            self.assertEqual(body["roles"]["approver"], self.company.stellar_address)
            self.assertEqual(body["roles"]["releaseSigner"], self.company.stellar_address)
            self.assertEqual(body["roles"]["serviceProvider"], self.freelance.stellar_address)
            self.assertEqual(body["roles"]["receiver"], self.freelance.stellar_address)
            self.assertEqual(body["roles"]["disputeResolver"], PLATFORM)
            self.assertEqual(body["roles"]["platformAddress"], PLATFORM)
            self.assertEqual(body["amount"], 120)
            self.assertEqual(body["platformFee"], 1)
            self.assertEqual(body["title"], "Logo vectoriel")
            self.assertEqual(body["engagementId"], f"taskvault-task-{self.task.pk}")
            self.assertEqual(body["milestones"], [{"description": f"Delivery of task #{self.task.pk} — Logo vectoriel"}])
            self.assertEqual(body["trustline"], {"address": USDC_ISSUER, "symbol": "USDC"})

            # 2. company funds → the task holds its money; the project is NOT funded yet (T2 is open… but
            #    only assigned tasks count, so it IS funded: every non-open task holds funds)
            _, sent = self.run_step("fund", self.company_kp)
            self.assertTrue(sent["ok"], sent)
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.FUNDED)
            self.assertEqual(len(esc.fund_tx_hash), 64)
            self.assertIsNotNone(esc.funded_at)
            self.assertTrue(esc.holds_funds)
            self.assertEqual(router.last(tw.PATH_FUND), {"contractId": CONTRACT, "signer": self.company.stellar_address, "amount": 120})
            self.assertEqual((sent["next"]["step"], sent["next"]["mine"]), ("deliver", False), "the freelance acts next")
            self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.FUNDED)
            # One escrow per task: funding T1 locks T1's price only, the company can still add a task.
            extra = projects.add_task(self.project, self.company, "Extra", "", "1", [])
            self.assertEqual(extra.status, "open")
            with self.assertRaises(projects.ProjectError):  # … but a chosen task can no longer be deleted
                projects.delete_task(self.task, self.company)

            # 3. freelance delivers: TW milestone change + projects.services.deliver(link)
            login(self.client, self.freelance)
            _, sent = self.run_step("deliver", self.freelance_kp, {"delivery_link": LINK})
            self.assertTrue(sent["ok"], sent)
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.DELIVERED)
            self.assertEqual(esc.delivery_note, LINK)
            self.assertIsNotNone(esc.delivered_at)
            task = Task.objects.get(pk=self.task.pk)
            self.assertEqual((task.status, task.delivery_link), ("delivered", LINK))
            self.assertIsNotNone(task.delivered_at)
            body = router.last(tw.PATH_CHANGE_MILESTONE)
            self.assertEqual(body["serviceProvider"], self.freelance.stellar_address)
            self.assertEqual(body["newEvidence"], LINK)
            self.assertEqual(body["milestoneIndex"], "0")
            self.assertEqual(sent["next"]["step"], "validate")
            self.assertFalse(sent["next"]["mine"])

            # 4. approve is refused until the company has rated; validate saves the Rating and answers next=approve
            login(self.client, self.company)
            self.assertEqual(self.prepare("approve").json()["error"], "wrong_state")
            data = self.validate(5, "Impeccable").json()
            self.assertTrue(data["ok"], data)
            self.assertEqual(data["status"], "delivered", "nothing is paid before the signatures")
            self.assertEqual(data["next"]["step"], "approve")
            self.assertTrue(data["next"]["mine"])
            self.assertEqual(data["next"]["prepare_url"], self.prepare_url("approve"))
            self.assertEqual(Rating.objects.get(task=self.task).note, 5)
            self.assertEqual(self.task_status(), "delivered")

            # 5. company approves → next = release (chained by the page)
            _, sent = self.run_step("approve", self.company_kp)
            self.assertTrue(sent["ok"], sent)
            self.assertEqual(self.escrow().status, Escrow.Status.APPROVED)
            self.assertEqual(router.last(tw.PATH_APPROVE_MILESTONE)["approver"], self.company.stellar_address)
            self.assertEqual((sent["next"]["step"], sent["next"]["mine"]), ("release", True))
            self.assertEqual(self.task_status(), "delivered", "approve alone pays nothing")

            # 6. company releases → mark_paid
            _, sent = self.run_step("release", self.company_kp)
            self.assertTrue(sent["ok"], sent)
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.RELEASED)
            self.assertEqual(len(esc.release_tx_hash), 64)
            self.assertIsNotNone(esc.released_at)
            self.assertEqual(esc.last_error, "")
            task = Task.objects.get(pk=self.task.pk)
            self.assertEqual(task.status, "paid")
            self.assertIsNotNone(task.paid_at)
            self.assertEqual(sent["task_status"], "paid")
            self.assertIsNone(sent["next"])
            self.assertEqual(router.last(tw.PATH_RELEASE), {"contractId": CONTRACT, "releaseSigner": self.company.stellar_address})
            self.assertIsNone(next_action(self.task, self.company))
            # every hash has an explorer link, plus the contract
            self.assertEqual(
                [l["key"] for l in esc.explorer_links()],
                ["contract", "deploy_tx_hash", "fund_tx_hash", "deliver_tx_hash", "approve_tx_hash", "release_tx_hash"],
            )
            self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.FUNDED, "T2 is still open")

    def test_send_is_idempotent_for_the_same_signed_xdr(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            prep = self.prepare("fund").json()
            signed = sign(prep["xdr"], self.company_kp)
            first = self.send("fund", signed).json()
            sends_before = router.count(tw.PATH_SEND)
            second = self.send("fund", signed).json()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"], second)
        self.assertIn("already", second["message"])
        self.assertEqual(router.count(tw.PATH_SEND), sends_before)  # no second submit
        self.assertEqual(self.escrow().status, Escrow.Status.FUNDED)

    def test_release_replay_after_paid_does_not_pay_twice(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            login(self.client, self.freelance)
            self.run_step("deliver", self.freelance_kp, {"delivery_link": LINK})
            login(self.client, self.company)
            self.validate()
            self.run_step("approve", self.company_kp)
            prep = self.prepare("release").json()
            signed = sign(prep["xdr"], self.company_kp)
            self.assertTrue(self.send("release", signed).json()["ok"])
            paid_at = Task.objects.get(pk=self.task.pk).paid_at
            again = self.send("release", signed).json()
        self.assertTrue(again["ok"], again)
        self.assertIn("already", again["message"])
        self.assertEqual(Task.objects.get(pk=self.task.pk).paid_at, paid_at)

    def test_platform_address_falls_back_to_company_with_a_warning(self):
        router = TWRouter(self.unsigned)
        with override_settings(LOWBID_PLATFORM_ADDRESS=""), patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            with self.assertLogs("payments.services", level="WARNING") as logs:
                prep = self.prepare("deploy").json()
        self.assertTrue(prep["ok"])
        self.assertTrue(any("LOWBID_PLATFORM_ADDRESS is empty" in line for line in logs.output))
        roles = router.last(tw.PATH_DEPLOY)["roles"]
        self.assertEqual(roles["disputeResolver"], self.company.stellar_address)
        self.assertEqual(roles["platformAddress"], self.company.stellar_address)

    def test_deploy_without_contract_id_is_a_provider_error(self):
        router = TWRouter(self.unsigned, send_payload={"status": "SUCCESS", "message": "ok"})
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            prep = self.prepare("deploy").json()
            sent = self.send("deploy", sign(prep["xdr"], self.company_kp)).json()
        self.assertFalse(sent["ok"])
        self.assertEqual(sent["error"], "provider")
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.CREATED)
        self.assertIn("contract", esc.last_error)

    def test_confirm_logs_task_step_and_hash(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            with self.assertLogs("payments.services", level="INFO") as logs:
                _, sent = self.run_step("deploy", self.company_kp)
        line = next(l for l in logs.output if "payments: confirm task=" in l)
        self.assertIn(f"task={self.task.pk} step=deploy", line)
        self.assertIn(f"hash={sent['tx_hash']}", line)
        self.assertIn(f"contract={CONTRACT}", line)


@override_settings(**ESCROW_SETTINGS)
class EscrowGuardTests(BasePayTest):
    def test_anonymous_gets_401_json(self):
        resp = self.prepare("deploy")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {"ok": False, "error": "wallet_required"})
        resp = self.send("deploy", "AAAA")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.client.get(reverse("payments:project_pending", args=[self.project.pk]), **JSON).status_code, 401)

    def test_freelance_and_stranger_cannot_deploy_or_fund(self):
        for wallet in (self.freelance, self.other):
            login(self.client, wallet)
            with patch("payments.trustless_work.requests.post") as post:
                for step in ("deploy", "fund"):
                    resp = self.prepare(step)
                    self.assertEqual(resp.status_code, 200)
                    self.assertEqual(resp.json()["error"], "forbidden", step)
                    self.assertIn("company", resp.json()["message"])
            post.assert_not_called()

    def test_choosing_a_new_task_sends_a_funded_project_back_to_draft(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.FUNDED)
        projects.apply(self.open_task, self.other, "Je prends", ["design"])
        projects.choose(self.open_task, Application.objects.get(task=self.open_task), self.company)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.DRAFT, "T2 holds nothing yet")
        self.assertTrue(project_funding(self.project)["can_fund"])

    def test_non_assignee_cannot_deliver(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            for wallet, kp in ((self.other, self.other_kp), (self.company, self.company_kp)):
                login(self.client, wallet)
                resp = self.prepare("deliver", {"delivery_link": LINK}).json()
                self.assertEqual(resp["error"], "not_assigned")
                resp = self.send("deliver", sign(self.unsigned, kp), {"delivery_link": LINK}).json()
                self.assertEqual(resp["error"], "not_assigned")
        self.assertEqual(self.escrow().status, Escrow.Status.FUNDED)
        self.assertEqual(self.task_status(), "taken")

    def test_deliver_needs_a_funded_escrow_and_a_valid_link(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.freelance)
            resp = self.prepare("deliver", {"delivery_link": LINK}).json()
            self.assertEqual(resp["error"], "wrong_state", "nothing deployed: the freelance must wait for the funding")
            self.assertEqual(next_action(self.task, self.freelance)["waiting"], "Waiting for the company to create the escrow.")
            # the DB-only endpoint is refused too in escrow mode
            r = self.client.post(reverse("projects:task_deliver", args=[self.task.pk]), data=json.dumps({"delivery_link": LINK}), content_type="application/json", **JSON)
            self.assertEqual((r.status_code, r.json()["error"]), (409, "wrong_state"))
            self.assertIn("Escrow task", r.json()["message"])
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            login(self.client, self.freelance)
            resp = self.prepare("deliver", {"delivery_link": "pas-un-lien"}).json()
            self.assertEqual(resp["error"], "invalid")
            self.assertIn("http", resp["message"])
            resp = self.prepare("deliver", {}).json()
            self.assertEqual(resp["error"], "invalid")
        self.assertEqual(router.count(tw.PATH_CHANGE_MILESTONE), 0)
        self.assertEqual(self.task_status(), "taken")

    def test_wrong_order_release_before_funded(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            resp = self.prepare("release").json()  # nothing deployed yet
            self.assertEqual(resp["error"], "wrong_state")
            self.run_step("deploy", self.company_kp)
            resp = self.prepare("release").json()
            self.assertEqual(resp["error"], "wrong_state")
            self.assertIn("Escrow created", resp["message"])
            resp = self.send("release", sign(self.unsigned, self.company_kp)).json()
            self.assertEqual(resp["error"], "wrong_state")
        self.assertEqual(self.escrow().status, Escrow.Status.DEPLOYED)
        self.assertEqual(router.count(tw.PATH_RELEASE), 0)

    def test_unknown_step_and_direct_only_step(self):
        login(self.client, self.company)
        self.assertEqual(self.prepare("refund").json()["error"], "unknown_step")
        self.assertEqual(self.prepare("direct_pay").json()["error"], "wrong_mode")

    def test_open_task_has_no_payment(self):
        login(self.client, self.company)
        self.assertEqual(self.prepare("deploy", task=self.open_task).json()["error"], "not_chosen")
        self.assertFalse(Escrow.objects.filter(task=self.open_task).exists())
        self.assertIsNone(next_action(self.open_task, self.company))

    def test_provider_failure_keeps_status_and_stores_last_error(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
        # build refused (400 with a vendor message)
        bad = TWRouter(self.unsigned, build_status=400)
        bad.build_payload = {"status": "FAILED", "message": "Insufficient USDC balance"}
        with patch("payments.trustless_work.requests.post", side_effect=bad):
            resp = self.prepare("fund").json()
        self.assertEqual(resp, {"ok": False, "error": "provider", "message": "Insufficient USDC balance"})
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DEPLOYED)
        self.assertEqual(esc.last_error, "Insufficient USDC balance")
        # send refused
        bad_send = TWRouter(self.unsigned, send_payload={"status": "FAILED", "message": "tx_failed op_no_trust"})
        with patch("payments.trustless_work.requests.post", side_effect=bad_send):
            prep = self.prepare("fund").json()
            sent = self.send("fund", sign(prep["xdr"], self.company_kp)).json()
        self.assertEqual(sent["error"], "provider")
        self.assertIn("op_no_trust", sent["message"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DEPLOYED)
        self.assertEqual(esc.fund_tx_hash, "")
        self.assertIn("op_no_trust", esc.last_error)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.DRAFT)
        # the panel shows the vendor message; retry works and clears it
        html = self.detail().content.decode()
        self.assertIn("op_no_trust", html)
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            _, sent = self.run_step("fund", self.company_kp)
        self.assertTrue(sent["ok"])
        self.assertEqual(self.escrow().last_error, "")

    def test_missing_api_key_is_a_provider_error_without_http(self):
        login(self.client, self.company)
        with override_settings(TRUSTLESS_WORK_API_KEY=""), patch("payments.trustless_work.requests.post") as post:
            resp = self.prepare("deploy").json()
        post.assert_not_called()
        self.assertEqual(resp["error"], "provider")
        self.assertIn("API key", resp["message"])

    def test_garbage_signed_xdr_is_tampered(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.prepare("deploy")
            resp = self.send("deploy", "not-an-xdr").json()
            self.assertEqual(resp["error"], "tampered")
            resp = self.send("deploy", "").json()
            self.assertEqual(resp["error"], "tampered")
        self.assertEqual(router.count(tw.PATH_SEND), 0)

    def test_release_failure_leaves_the_task_delivered(self):
        """A refused release must not mark the task paid: mark_paid only follows a confirmed send."""
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            login(self.client, self.freelance)
            self.run_step("deliver", self.freelance_kp, {"delivery_link": LINK})
            login(self.client, self.company)
            self.validate()
            self.run_step("approve", self.company_kp)
        bad_send = TWRouter(self.unsigned, send_payload={"status": "FAILED", "message": "EscrowBalanceNotEnoughToSendEarnings"})
        with patch("payments.trustless_work.requests.post", side_effect=bad_send):
            prep = self.prepare("release").json()
            sent = self.send("release", sign(prep["xdr"], self.company_kp)).json()
        self.assertEqual(sent["error"], "provider")
        self.assertEqual(self.escrow().status, Escrow.Status.APPROVED)
        self.assertEqual(self.task_status(), "delivered")
        self.assertEqual(next_action(self.fresh(), self.company)["label"], "Release the funds", "the panel offers to resume")


# =============================== project funding ==================================


@override_settings(**ESCROW_SETTINGS)
class ProjectFundingTests(BasePayTest):
    def pending_url(self):
        return reverse("payments:project_pending", args=[self.project.pk])

    def test_pending_list_is_the_company_deploy_fund_chain(self):
        login(self.client, self.company)
        data = self.client.get(self.pending_url(), **JSON).json()
        self.assertTrue(data["ok"])
        self.assertEqual((data["mode"], data["total"], data["funded"], data["can_fund"]), ("escrow", "200", "0", True))
        self.assertEqual(len(data["tasks"]), 1, "only T1 (taken) — the open T2 has no receiver yet")
        row = data["tasks"][0]
        self.assertEqual((row["task"], row["title"], row["amount"]), (self.task.pk, "Logo vectoriel", "120"))
        self.assertEqual((row["next"]["step"], row["next"]["mine"], row["next"]["prepare_url"]), ("deploy", True, self.prepare_url("deploy")))
        # after deploy the pending step is fund; after fund the task is gone from the list
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            self.run_step("deploy", self.company_kp)
            self.assertEqual(self.client.get(self.pending_url(), **JSON).json()["tasks"][0]["next"]["step"], "fund")
            self.run_step("fund", self.company_kp)
        data = self.client.get(self.pending_url(), **JSON).json()
        self.assertEqual(data["tasks"], [])
        self.assertEqual((data["funded"], data["can_fund"]), ("120", False))
        self.assertIn("is funded", data["hint"])

    def test_pending_list_is_company_only(self):
        for wallet in (self.freelance, self.other):
            login(self.client, wallet)
            resp = self.client.get(self.pending_url(), **JSON)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["error"], "forbidden")
        self.assertEqual(self.client.get(reverse("payments:project_pending", args=[9999]), **JSON).status_code, 404)

    def test_project_funding_view_model_and_banner(self):
        funding = project_funding(self.project)
        self.assertEqual((funding["total"], funding["funded"], funding["paid"]), (Decimal("200"), Decimal("0"), Decimal("0")))
        self.assertTrue(funding["can_fund"])
        self.assertEqual([p["task"].pk for p in funding["pending"]], [self.task.pk])
        self.assertEqual([r["status_label"] for r in funding["rows"]], ["Preparing", ""])
        login(self.client, self.company)
        html = self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()
        self.assertIn('data-fund data-pending-url="%s"' % self.pending_url(), html)
        self.assertIn('id="funding-panel"', html)
        self.assertIn("Escrow funding", html)
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
        html = self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()
        self.assertIn(f"/contract/{CONTRACT}", html, "explorer link of the contract in the banner")
        self.assertIn(f"/tx/{self.escrow().fund_tx_hash}", html)
        self.assertIn("Funds locked", html)
        self.assertIn("Funded", html, "project badge")
        funding = project_funding(self.project)
        self.assertEqual(funding["funded"], Decimal("120"))
        self.assertFalse(funding["can_fund"])
        self.assertIn("Every assigned task is funded", funding["fund_hint"])

    def test_no_chosen_freelance_explains_why(self):
        empty = projects.create_project(self.company, "Nouveau", "Rien d’attribué.")
        projects.add_task(empty, self.company, "Tâche", "", "10", [])
        funding = project_funding(empty)
        self.assertFalse(funding["can_fund"])
        self.assertIn("Choose a freelancer first", funding["fund_hint"])
        self.assertIn("recipient", funding["fund_hint"])

    def test_project_funded_only_when_every_assigned_task_holds_funds(self):
        """Two assigned tasks: funding one of them is not enough."""
        self.other_free, _ = make_wallet("second")
        projects.apply(self.open_task, self.other_free, "", ["design"])
        projects.choose(self.open_task, Application.objects.get(task=self.open_task, freelancer=self.other_free), self.company)
        login(self.client, self.company)
        self.assertEqual(len(self.client.get(self.pending_url(), **JSON).json()["tasks"]), 2)
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.DRAFT)
            prep = self.prepare("deploy", task=self.open_task).json()
            self.send("deploy", sign(prep["xdr"], self.company_kp), task=self.open_task)
            prep = self.prepare("fund", task=self.open_task).json()
            sent = self.send("fund", sign(prep["xdr"], self.company_kp), task=self.open_task).json()
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.FUNDED)
        self.assertEqual(project_funding(self.project)["funded"], Decimal("200"))


# =============================== direct mode (fallback) ==================================


@override_settings(**DIRECT_SETTINGS)
class DirectModeTests(BasePayTest):
    def setUp(self):
        super().setUp()
        self.horizon = HorizonGet(
            accounts={
                self.company.stellar_address: horizon_account(self.company.stellar_address, balance="500.0000000"),
                self.freelance.stellar_address: horizon_account(self.freelance.stellar_address, balance="0.0000000"),
            }
        )

    def deliver_db(self, link=LINK):
        """The freelance's direct-mode delivery (prepare deliver = no transaction)."""
        login(self.client, self.freelance)
        resp = self.prepare("deliver", {"delivery_link": link}).json()
        login(self.client, self.company)
        return resp

    def test_freelance_delivers_without_a_transaction(self):
        login(self.client, self.freelance)
        with patch("payments.stellar.requests.get") as get, patch("payments.trustless_work.requests.post") as tw_post:
            resp = self.prepare("deliver", {"delivery_link": LINK}).json()
        get.assert_not_called()
        tw_post.assert_not_called()
        self.assertTrue(resp["ok"])
        self.assertNotIn("xdr", resp)  # nothing to sign: the JS just follows `redirect`
        self.assertTrue(resp["redirect"].endswith("#paiement"))
        self.assertEqual(resp["next"]["step"], "validate")
        self.assertFalse(resp["next"]["mine"])
        esc = self.escrow()
        self.assertEqual((esc.mode, esc.status, esc.delivery_note), (Escrow.Mode.DIRECT, Escrow.Status.DELIVERED, LINK))
        task = Task.objects.get(pk=self.task.pk)
        self.assertEqual((task.status, task.delivery_link), ("delivered", LINK))
        # the DB-only projects endpoint stays available in direct mode (same rule, same result)
        self.assertEqual(self.prepare("deliver", {"delivery_link": LINK}).json()["error"], "wrong_state")

    def test_bad_link_is_invalid_and_changes_nothing(self):
        login(self.client, self.freelance)
        resp = self.prepare("deliver", {"delivery_link": "ftp://nope"}).json()
        self.assertEqual(resp["error"], "invalid")
        self.assertEqual(self.task_status(), "taken")
        self.assertFalse(Escrow.objects.filter(task=self.task, status=Escrow.Status.DELIVERED).exists())

    def test_direct_pay_needs_delivery_and_rating(self):
        login(self.client, self.company)
        with patch("payments.stellar.requests.get", side_effect=self.horizon) as get:
            self.assertEqual(self.prepare("direct_pay").json()["error"], "wrong_state", "not delivered")
            self.deliver_db()
            resp = self.prepare("direct_pay").json()
            self.assertEqual(resp["error"], "wrong_state", "delivered but not rated")
            self.assertIn("rate", resp["message"])
        get.assert_not_called()
        self.assertEqual(next_action(self.fresh(), self.company)["step"], "validate")

    def test_validate_then_pay(self):
        self.deliver_db()
        login(self.client, self.company)
        data = self.validate(4, "Bien").json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["status"], "delivered")
        self.assertEqual((data["next"]["step"], data["next"]["mine"], data["next"]["prepare_url"]), ("direct_pay", True, self.prepare_url("direct_pay")))
        self.assertIn("Pay the freelancer", data["message"])
        self.assertEqual(self.task_status(), "delivered", "rated, not paid")
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch("payments.stellar.requests.post", side_effect=submit_ok):
            prep, sent = self.run_step("direct_pay", self.company_kp)
        info = stellar.parse_payment_xdr(prep["xdr"])
        self.assertEqual(info["op_type"], "payment")
        self.assertEqual(info["source"], self.company.stellar_address)
        self.assertEqual(info["destination"], self.freelance.stellar_address)
        self.assertEqual(info["amount"], Decimal("120"))
        self.assertEqual(info["asset_issuer"], USDC_ISSUER)
        self.assertEqual(info["memo"], f"taskvault:task:{self.task.pk}")
        self.assertTrue(sent["ok"], sent)
        self.assertFalse(sent["pending"])
        self.assertIsNone(sent["next"])
        self.assertEqual(sent["task_status"], "paid")
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.PAID)
        self.assertEqual(esc.platform_address, "")
        self.assertEqual(esc.payment_tx_hash, sent["tx_hash"])
        self.assertEqual(esc.payment_tx_hash, info["hash"])
        self.assertIsNotNone(esc.released_at)
        self.assertEqual([l["key"] for l in esc.explorer_links()], ["payment_tx_hash"])
        task = Task.objects.get(pk=self.task.pk)
        self.assertEqual(task.status, "paid")
        self.assertIsNotNone(task.paid_at)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.FUNDED, "direct mode: funded on the first payment")
        self.assertIsNone(next_action(self.task, self.company))

    def test_tampered_signed_xdr_is_refused(self):
        self.deliver_db()
        login(self.client, self.company)
        self.validate()
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch("payments.stellar.requests.post") as post:
            self.prepare("direct_pay")
            # different amount
            forged = stellar.build_payment_xdr(source=self.company.stellar_address, destination=self.freelance.stellar_address, amount=Decimal("1"), sequence=42)
            self.assertEqual(self.send("direct_pay", sign(forged, self.company_kp)).json()["error"], "tampered")
            # different destination
            forged = stellar.build_payment_xdr(source=self.company.stellar_address, destination=self.other.stellar_address, amount=Decimal("120"), sequence=42)
            self.assertEqual(self.send("direct_pay", sign(forged, self.company_kp)).json()["error"], "tampered")
            # a trustline op instead of a payment
            forged = stellar.build_change_trust_xdr(source=self.company.stellar_address, sequence=42)
            self.assertEqual(self.send("direct_pay", sign(forged, self.company_kp)).json()["error"], "tampered")
        post.assert_not_called()
        self.assertEqual(self.escrow().status, Escrow.Status.DELIVERED)
        self.assertEqual(self.task_status(), "delivered")

    def test_escrow_only_steps_refused_in_direct_mode(self):
        login(self.client, self.company)
        for step in ("deploy", "fund", "approve", "release"):
            self.assertEqual(self.prepare(step).json()["error"], "wrong_mode", step)

    def test_horizon_rejection_keeps_status(self):
        self.deliver_db()
        login(self.client, self.company)
        self.validate()
        rejected = _resp(400, {"extras": {"result_codes": {"transaction": "tx_failed", "operations": ["op_no_trust"]}}})
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch("payments.stellar.requests.post", return_value=rejected):
            prep = self.prepare("direct_pay").json()
            sent = self.send("direct_pay", sign(prep["xdr"], self.company_kp)).json()
        self.assertEqual(sent["error"], "provider")
        self.assertEqual(sent["message"], "The recipient has no USDC trustline.")
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DELIVERED)
        self.assertEqual(esc.payment_tx_hash, "")
        self.assertIn("trustline", esc.last_error)
        self.assertEqual(self.task_status(), "delivered")
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.DRAFT)

    def test_horizon_timeout_stores_hash_then_reconciles_on_next_prepare(self):
        self.deliver_db()
        login(self.client, self.company)
        self.validate()
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch(
            "payments.stellar.requests.post", return_value=_resp(504, {"status": 504, "title": "Timeout"})
        ):
            prep = self.prepare("direct_pay").json()
            signed = sign(prep["xdr"], self.company_kp)
            sent = self.send("direct_pay", signed).json()
        tx_hash = TransactionEnvelope.from_xdr(signed, TESTNET).hash_hex()
        self.assertTrue(sent["ok"])
        self.assertTrue(sent["pending"])
        self.assertEqual(sent["tx_hash"], tx_hash)
        self.assertEqual(sent["message"], PENDING_MESSAGE)
        self.assertIn(tx_hash, sent["explorer_url"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DELIVERED)
        self.assertEqual(esc.payment_tx_hash, tx_hash)
        self.assertEqual(esc.last_error, PENDING_MESSAGE)
        self.assertEqual(self.task_status(), "delivered")
        # the panel shows the pending hash + explorer link
        html = self.detail().content.decode()
        self.assertIn(PENDING_MESSAGE, html)
        self.assertIn(f"/tx/{tx_hash}", html)
        # next prepare: Horizon says the tx went through → finalised without a new signature
        self.horizon.transactions[tx_hash] = {"hash": tx_hash, "successful": True}
        with patch("payments.stellar.requests.get", side_effect=self.horizon):
            prep = self.prepare("direct_pay").json()
        self.assertTrue(prep["ok"])
        self.assertNotIn("xdr", prep)
        self.assertIn("confirmed", prep["message"])
        self.assertIsNone(prep["next"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.PAID)
        self.assertEqual(esc.last_error, "")
        self.assertEqual(self.task_status(), "paid")

    def test_mode_is_refrozen_while_nothing_is_on_chain(self):
        """Deploy failed in escrow mode → founder flips LOWBID_PAYMENT_MODE=direct → the fallback just works."""
        with override_settings(LOWBID_PAYMENT_MODE="escrow"), patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned, build_status=500)):
            login(self.client, self.company)
            self.assertEqual(self.prepare("deploy").json()["error"], "provider")
        self.assertEqual(self.escrow().mode, Escrow.Mode.ESCROW)
        self.deliver_db()  # direct mode now: the row is re-frozen at this prepare
        self.assertEqual(self.escrow().mode, Escrow.Mode.DIRECT)
        self.assertEqual(self.escrow().status, Escrow.Status.DELIVERED)

    def test_unfunded_company_account_is_a_stellar_error(self):
        self.deliver_db()
        login(self.client, self.company)
        self.validate()
        with patch("payments.stellar.requests.get", side_effect=HorizonGet()):
            resp = self.prepare("direct_pay").json()
        self.assertEqual(resp["error"], "stellar")
        self.assertIn("friendbot", resp["message"])
        self.assertIn("friendbot", self.escrow().last_error)
        self.assertEqual(self.task_status(), "delivered")

    def test_validate_marks_nothing_paid_and_db_delivery_endpoint_works(self):
        """The projects endpoint (no escrow row yet) + validate: the task stays delivered, next = direct_pay."""
        login(self.client, self.freelance)
        r = self.client.post(reverse("projects:task_deliver", args=[self.task.pk]), data=json.dumps({"delivery_link": LINK}), content_type="application/json", **JSON)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Escrow.objects.filter(task=self.task).exists())
        self.assertEqual(next_action(self.fresh(), self.company)["step"], "validate")
        login(self.client, self.company)
        html = self.detail().content.decode()
        self.assertIn('id="validate-panel"', html)
        self.assertIn("Delivered", html)  # display_status: delivered without a row
        data = self.validate().json()
        self.assertEqual((data["status"], data["next"]["step"]), ("delivered", "direct_pay"))
        esc = self.escrow()  # created by on_task_validated
        self.assertEqual((esc.mode, esc.status), (Escrow.Mode.DIRECT, Escrow.Status.CREATED))
        self.assertEqual(self.task_status(), "delivered")


@override_settings(**{**DIRECT_SETTINGS, "STELLAR_ASSET_CODE": "XLM", "STELLAR_ASSET_ISSUER": ""})
class NativeAssetTests(BasePayTest):
    def test_native_payment_and_no_trustline(self):
        login(self.client, self.freelance)
        self.prepare("deliver", {"delivery_link": LINK})
        login(self.client, self.company)
        self.validate()
        horizon = HorizonGet(accounts={self.company.stellar_address: horizon_account(self.company.stellar_address, with_usdc=False)})
        with patch("payments.stellar.requests.get", side_effect=horizon), patch("payments.stellar.requests.post", side_effect=submit_ok):
            prep, sent = self.run_step("direct_pay", self.company_kp)
        self.assertTrue(sent["ok"], sent)
        op = TransactionEnvelope.from_xdr(prep["xdr"], TESTNET).transaction.operations[0]
        self.assertTrue(op.asset.is_native())
        self.assertEqual(self.task_status(), "paid")
        self.assertIn("XLM payment confirmed", sent["message"])
        # trustline helper: nothing to do
        resp = self.client.post(reverse("payments:trustline_prepare"), **JSON).json()
        self.assertEqual(resp["ok"], True)
        self.assertNotIn("xdr", resp)
        self.assertIn("native", resp["message"])
        html = self.detail().content.decode()
        self.assertNotIn("data-pay-trustline", html)
        self.assertIn("XLM", html)

    def test_escrow_mode_falls_back_to_direct_for_the_native_asset(self):
        with override_settings(LOWBID_PAYMENT_MODE="escrow"):
            login(self.client, self.company)
            with self.assertLogs("payments.stellar", level="WARNING"):
                self.assertEqual(self.prepare("deploy").json()["error"], "wrong_mode")
            self.assertEqual(self.escrow().mode, Escrow.Mode.DIRECT)
            self.assertEqual(next_action(self.task, self.freelance)["step"], "deliver")


# =============================== trustline ==================================


@override_settings(**ESCROW_SETTINGS)
class TrustlineTests(BasePayTest):
    def test_anonymous_401(self):
        self.assertEqual(self.client.post(reverse("payments:trustline_prepare"), **JSON).status_code, 401)

    def test_already_present_returns_message_without_xdr(self):
        login(self.client, self.freelance)
        horizon = HorizonGet(accounts={self.freelance.stellar_address: horizon_account(self.freelance.stellar_address, with_usdc=True)})
        with patch("payments.stellar.requests.get", side_effect=horizon):
            resp = self.client.post(reverse("payments:trustline_prepare"), **JSON).json()
        self.assertEqual(resp, {"ok": True, "message": "USDC trustline already present."})

    def test_missing_trustline_builds_change_trust_then_submits(self):
        login(self.client, self.freelance)
        horizon = HorizonGet(accounts={self.freelance.stellar_address: horizon_account(self.freelance.stellar_address, with_usdc=False)})
        with patch("payments.stellar.requests.get", side_effect=horizon):
            prep = self.client.post(reverse("payments:trustline_prepare"), **JSON).json()
        self.assertTrue(prep["ok"])
        self.assertEqual(prep["send_url"], reverse("payments:trustline_send"))
        info = stellar.parse_payment_xdr(prep["xdr"])
        self.assertEqual(info["op_type"], "change_trust")
        self.assertEqual(info["source"], self.freelance.stellar_address)
        self.assertEqual(info["asset_issuer"], USDC_ISSUER)

        with patch("payments.stellar.requests.post", side_effect=submit_ok):
            sent = self.client.post(
                reverse("payments:trustline_send"),
                data=json.dumps({"signed_xdr": sign(prep["xdr"], self.freelance_kp)}),
                content_type="application/json",
                **JSON,
            ).json()
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(sent["message"], "USDC trustline added.")
        self.assertIn(sent["tx_hash"], sent["explorer_url"])

    def test_trustline_for_another_asset_code_is_tampered(self):
        login(self.client, self.freelance)
        with self.settings(STELLAR_ASSET_CODE="EURC"):
            forged = stellar.build_change_trust_xdr(source=self.freelance.stellar_address, sequence=1)
        with patch("payments.stellar.requests.post") as post:
            sent = self.client.post(
                reverse("payments:trustline_send"),
                data=json.dumps({"signed_xdr": sign(forged, self.freelance_kp)}),
                content_type="application/json",
                **JSON,
            ).json()
        post.assert_not_called()
        self.assertEqual(sent["error"], "tampered")

    def test_trustline_for_another_wallet_is_tampered(self):
        login(self.client, self.freelance)
        forged = stellar.build_change_trust_xdr(source=self.other.stellar_address, sequence=1)
        with patch("payments.stellar.requests.post") as post:
            sent = self.client.post(
                reverse("payments:trustline_send"),
                data=json.dumps({"signed_xdr": sign(forged, self.other_kp)}),
                content_type="application/json",
                **JSON,
            ).json()
        post.assert_not_called()
        self.assertEqual(sent["error"], "tampered")


# =============================== panel / pages / dashboard ==================================


@override_settings(**ESCROW_SETTINGS)
class PanelTests(BasePayTest):
    def test_anonymous_panel_is_read_only(self):
        html = self.detail().content.decode()
        self.assertIn('id="escrow-panel"', html)
        self.assertIn("Escrow payment", html)
        self.assertNotIn("data-prepare-url", html)
        self.assertNotIn("data-pay-trustline", html)
        self.assertIn(f'data-usdc-balance="{self.freelance.stellar_address}" data-watch', html)
        self.assertIn("Waiting for the company to create the escrow", html)
        self.assertIn(f'data-copy="{self.freelance.stellar_address}"', html)
        self.assertNotIn('id="escrow-panel"', self.detail(self.open_task).content.decode(), "no panel on an open task")

    def test_company_sees_deploy_button_freelance_waits(self):
        login(self.client, self.company)
        html = self.detail().content.decode()
        self.assertIn(f'data-pay-step="deploy" data-prepare-url="{self.prepare_url("deploy")}"', html)
        self.assertIn("Create the escrow", html)
        self.assertIn("data-pay-trustline", html)
        self.assertIn("data-pay-error", html)
        login(self.client, self.freelance)
        html = self.detail().content.decode()
        self.assertNotIn("data-prepare-url=", html.replace("data-pay-trustline data-prepare-url", ""))
        self.assertIn("Waiting for the company to create the escrow", html)
        self.assertIn("data-pay-trustline", html)

    def test_freelance_sees_deliver_form_once_funded(self):
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
        login(self.client, self.freelance)
        html = self.detail().content.decode()
        self.assertIn('id="deliver-panel"', html)
        self.assertIn('id="deliver-link"', html)
        self.assertIn(f'data-pay-step="deliver" data-prepare-url="{self.prepare_url("deliver")}" data-deliver', html)
        self.assertIn("data-pay-form", html)
        self.assertNotIn("data-confirm-message", html, "escrow mode: Freighter is the confirmation")
        self.assertIn(f"/contract/{CONTRACT}", html)  # explorer link for the contract id
        self.assertIn("Funds locked", html)
        login(self.client, self.company)
        html = self.detail().content.decode()
        self.assertIn("Waiting for the freelancer", html)
        self.assertNotIn('data-pay-step="deliver"', html)

    def test_company_sees_the_rating_form_then_the_resume_button(self):
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            login(self.client, self.freelance)
            self.run_step("deliver", self.freelance_kp, {"delivery_link": LINK})
            login(self.client, self.company)
            html = self.detail().content.decode()
            self.assertIn('id="validate-panel"', html)
            self.assertIn("form[data-validate]".replace("form[", "<form id=\"validate-form\" class=\"ui-form-grid\" novalidate ").split("]")[0], html)
            self.assertIn("Validate and release 120.00 USDC", html)
            self.assertNotIn('data-pay-step="approve"', html)
            self.validate()
            html = self.detail().content.decode()
            self.assertNotIn('id="validate-panel"', html)
            self.assertIn(f'data-pay-step="approve" data-prepare-url="{self.prepare_url("approve")}"', html)
            self.assertIn("The release of the funds follows", html)
            self.run_step("approve", self.company_kp)
            html = self.detail().content.decode()
            self.assertIn(f'data-pay-step="release" data-prepare-url="{self.prepare_url("release")}"', html)
            self.assertIn("Release the funds", html)
            self.run_step("release", self.company_kp)
        html = self.detail().content.decode()
        self.assertIn("Task paid", html)
        self.assertIn("Funds released to the freelancer", html)
        self.assertNotIn("data-pay-step=", html)
        self.assertEqual(html.count("stellar.expert/explorer/testnet/tx/"), 5, "every hash has its explorer link")

    def test_platform_fallback_alert_only_for_the_company_when_address_missing(self):
        with override_settings(LOWBID_PLATFORM_ADDRESS=""):
            login(self.client, self.company)
            html = self.detail().content.decode()
            self.assertIn("data-platform-fallback", html)
            self.assertIn("Platform address not configured", html)
            login(self.client, self.freelance)
            self.assertNotIn("data-platform-fallback", self.detail().content.decode())
        login(self.client, self.company)
        self.assertNotIn("data-platform-fallback", self.detail().content.decode())  # PLATFORM configured
        with override_settings(LOWBID_PLATFORM_ADDRESS="", LOWBID_PAYMENT_MODE="direct"):
            self.assertNotIn("data-platform-fallback", self.detail().content.decode())

    @override_settings(LOWBID_PAYMENT_MODE="direct")
    def test_direct_mode_panel(self):
        login(self.client, self.company)
        html = self.detail().content.decode()
        self.assertIn("Direct payment USDC", html)
        self.assertIn("no escrow", html)
        self.assertNotIn("Funds locked", html)  # two-step stepper
        self.assertIn("Waiting for the freelancer", html)
        login(self.client, self.freelance)
        html = self.detail().content.decode()
        self.assertIn(f'data-pay-step="deliver" data-prepare-url="{self.prepare_url("deliver")}" data-deliver', html)
        self.assertIn("data-confirm-message", html, "no Freighter prompt in direct mode: Lowbid.confirm instead")
        self.assertIn('id="deliver-link"', html)

    def test_stepper_states(self):
        self.assertEqual([s["state"] for s in stepper("escrow", "created")], ["current", "todo", "todo", "todo"])
        self.assertEqual([s["state"] for s in stepper("escrow", "funded")], ["done", "done", "current", "todo"])
        self.assertEqual([s["state"] for s in stepper("escrow", "approved")], ["done", "done", "done", "current"])
        self.assertEqual([s["state"] for s in stepper("escrow", "released")], ["done"] * 4)
        self.assertEqual([s["state"] for s in stepper("direct", "created")], ["current", "todo"])
        self.assertEqual([s["state"] for s in stepper("direct", "paid")], ["done", "done"])

    def test_next_action_per_viewer(self):
        a = next_action(self.task, self.company)
        self.assertEqual((a["step"], a["mine"], a["who"]), ("deploy", True, "company"))
        a = next_action(self.task, self.freelance)
        self.assertEqual((a["step"], a["mine"]), ("deploy", False))
        self.assertEqual(next_action(self.task, None)["step"], "deploy")
        self.assertEqual(next_action(self.task, self.other)["mine"], False)
        with override_settings(LOWBID_PAYMENT_MODE="direct"):
            self.assertEqual(next_action(self.task, self.company)["step"], "deliver")
            self.assertEqual(next_action(self.task, self.freelance)["step"], "deliver")
            self.assertTrue(next_action(self.task, self.freelance)["mine"])
            self.assertEqual(next_action(self.task, None)["step"], "deliver")
        self.assertIsNone(next_action(self.open_task, self.company))

    def test_pay_redirects_to_detail_anchor(self):
        resp = self.client.get(reverse("payments:task_pay", kwargs={"task_pk": self.task.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("projects:task_detail", args=[self.task.pk]) + "#paiement")
        self.assertEqual(self.client.get(reverse("payments:task_pay", kwargs={"task_pk": 9999})).status_code, 404)

    def test_project_rows_carry_the_escrow_badge(self):
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
        html = self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()
        self.assertIn("data-pay-badge", html)
        self.assertIn("Escrow created", html)

    def test_dashboard_todo_follows_the_payment_step(self):
        from dashboard.services import todo_items

        company = todo_items(self.company)
        fund = next(it for it in company if it["kicker"] == "Funding")
        self.assertEqual(fund["tone"], "act")
        self.assertIn('Fund "Logo vectoriel"', fund["headline"])
        self.assertTrue(fund["href"].endswith("#funding-panel"))
        wait = next(it for it in todo_items(self.freelance) if it["kicker"] == "Funding awaited")
        self.assertEqual(wait["tone"], "wait")
        self.assertIn("120.00 USDC", wait["body"])
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            login(self.client, self.company)
            self.run_step("deploy", self.company_kp)
            self.run_step("fund", self.company_kp)
            self.assertTrue(any(it["kicker"] == "Task taken" and it["tone"] == "act" for it in todo_items(self.freelance)))
            self.assertFalse(any(it["kicker"] == "Funding" for it in todo_items(self.company)))
            login(self.client, self.freelance)
            self.run_step("deliver", self.freelance_kp, {"delivery_link": LINK})
            self.assertTrue(any("Validate and rate" in it["headline"] for it in todo_items(self.company)))
            login(self.client, self.company)
            self.validate()
            release = next(it for it in todo_items(self.company) if it["kicker"] == "Payment")
            self.assertIn("Release the funds", release["headline"])
            self.assertTrue(release["href"].endswith("#paiement"))
            self.assertTrue(any(it["kicker"] == "Payment in progress" for it in todo_items(self.freelance)))
            self.run_step("approve", self.company_kp)
            self.run_step("release", self.company_kp)
        self.assertFalse(any("Logo vectoriel" in it["headline"] for it in todo_items(self.company)), "paid: nothing to do")

    def test_payment_error_shape(self):
        err = PaymentError("forbidden", "Non.")
        self.assertEqual((err.code, err.message, str(err)), ("forbidden", "Non.", "Non."))
