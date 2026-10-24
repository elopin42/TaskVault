"""End-to-end tests of the payment flow through the HTTP endpoints (no network: `requests`
is mocked in both payments.trustless_work and payments.stellar). Complements payments/tests.py
(unit tests of the two clients), which is left untouched."""

import unittest

from django.apps import apps

if not apps.is_installed("payments"):  # Phase 1 of the task-board pivot: payments is rewired in Phase 2.
    raise unittest.SkipTest("payments app disabled until Phase 2 (escrow per project)")

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair, TransactionEnvelope

from accounts.models import WalletUser
from auctions import services as auction_services
from auctions.models import Need
from payments import stellar
from payments import trustless_work as tw
from payments.models import Escrow
from payments.services import PENDING_MESSAGE, PaymentError, next_action, stepper

JSON = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "fetch"}
USDC_ISSUER = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
PLATFORM = Keypair.random().public_key
CONTRACT = "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"
TESTNET = "Test SDF Network ; September 2015"


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


def make_awarded_need(owner: WalletUser, winner: WalletUser, price: str = "120") -> Need:
    need = Need.objects.create(
        client=owner,
        title="Refonte du logo",
        description="Logo vectoriel + mini charte.",
        budget_max=Decimal("150"),
        delay_max_days=5,
        tags=["design", "figma"],
        bidding_ends_at=timezone.now() + timedelta(hours=1),
    )
    bid = auction_services.place_bid(need, winner, price, 4, ["design"], "3 pistes")
    auction_services.close_bidding_now(need, owner)
    auction_services.award(need, bid, owner)
    need.refresh_from_db()
    return need


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


ESCROW_SETTINGS = dict(
    TRUSTLESS_WORK_API_KEY="tw-test-key",
    TRUSTLESS_WORK_API_URL="https://dev.api.trustlesswork.com",
    LOWBID_PAYMENT_MODE="escrow",
    LOWBID_PLATFORM_ADDRESS=PLATFORM,
    LOWBID_PLATFORM_FEE=Decimal("1"),
    STELLAR_USDC_ISSUER=USDC_ISSUER,
    STELLAR_USDC_CODE="USDC",
    STELLAR_HORIZON_URL="https://horizon-testnet.stellar.org",
)


class BasePayTest(TestCase):
    def setUp(self):
        self.owner, self.owner_kp = make_wallet("client")
        self.winner, self.winner_kp = make_wallet("winner")
        self.other, self.other_kp = make_wallet("other")
        self.need = make_awarded_need(self.owner, self.winner)
        self.unsigned = some_xdr(self.owner.stellar_address, self.winner.stellar_address)

    # HTTP helpers
    def prepare(self, step, body=None, need=None):
        url = reverse("payments:prepare", kwargs={"need_pk": (need or self.need).pk, "step": step})
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json", **JSON)

    def send(self, step, signed_xdr, body=None, need=None):
        url = reverse("payments:send", kwargs={"need_pk": (need or self.need).pk, "step": step})
        payload = {"signed_xdr": signed_xdr, **(body or {})}
        return self.client.post(url, data=json.dumps(payload), content_type="application/json", **JSON)

    def run_step(self, step, kp, body=None):
        """prepare → sign with `kp` → send. Returns (prepare json, send json)."""
        prep = self.prepare(step, body).json()
        self.assertTrue(prep["ok"], prep)
        self.assertIn("xdr", prep)
        sent = self.send(step, sign(prep["xdr"], kp), body).json()
        return prep, sent

    def escrow(self) -> Escrow:
        return Escrow.objects.get(need=self.need)

    def detail(self):
        return self.client.get(reverse("auctions:need_detail", args=[self.need.pk]))


# =============================== escrow mode ==================================


@override_settings(**ESCROW_SETTINGS)
class EscrowHappyPathTests(BasePayTest):
    def test_full_flow_client_winner_client(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            # 1. client deploys
            login(self.client, self.owner)
            prep, sent = self.run_step("deploy", self.owner_kp)
            self.assertEqual(prep["send_url"], reverse("payments:send", kwargs={"need_pk": self.need.pk, "step": "deploy"}))
            self.assertTrue(sent["ok"], sent)
            self.assertEqual(sent["contract_id"], CONTRACT)
            self.assertTrue(sent["redirect"].endswith("#paiement"))
            self.assertIn("stellar.expert", sent["explorer_url"])
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.DEPLOYED)
            self.assertEqual(esc.mode, Escrow.Mode.ESCROW)
            self.assertEqual(esc.contract_id, CONTRACT)
            self.assertEqual(esc.deploy_tx_hash, sent["tx_hash"])
            self.assertEqual(len(esc.deploy_tx_hash), 64)
            self.assertEqual(esc.engagement_id, f"lowbid-{self.need.pk}")
            self.assertEqual(esc.amount, Decimal("120"))
            self.assertEqual(esc.payer_address, self.owner.stellar_address)
            self.assertEqual(esc.payee_address, self.winner.stellar_address)
            self.assertEqual(esc.platform_address, PLATFORM)
            self.need.refresh_from_db()
            self.assertEqual(self.need.status, Need.Status.AWARDED)
            # deploy payload: every role pinned to session wallet / winner / platform
            body = router.last(tw.PATH_DEPLOY)
            self.assertEqual(body["signer"], self.owner.stellar_address)
            self.assertEqual(body["roles"]["approver"], self.owner.stellar_address)
            self.assertEqual(body["roles"]["releaseSigner"], self.owner.stellar_address)
            self.assertEqual(body["roles"]["serviceProvider"], self.winner.stellar_address)
            self.assertEqual(body["roles"]["receiver"], self.winner.stellar_address)
            self.assertEqual(body["roles"]["disputeResolver"], PLATFORM)
            self.assertEqual(body["roles"]["platformAddress"], PLATFORM)
            self.assertEqual(body["amount"], 120)
            self.assertEqual(body["platformFee"], 1)
            self.assertEqual(body["engagementId"], f"lowbid-{self.need.pk}")
            self.assertEqual(body["milestones"], [{"description": f"Livraison du besoin #{self.need.pk}"}])

            # 2. client funds
            _, sent = self.run_step("fund", self.owner_kp)
            self.assertTrue(sent["ok"], sent)
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.FUNDED)
            self.assertEqual(len(esc.fund_tx_hash), 64)
            self.assertIsNotNone(esc.funded_at)
            self.need.refresh_from_db()
            self.assertEqual(self.need.status, Need.Status.FUNDED)
            self.assertEqual(router.last(tw.PATH_FUND), {"contractId": CONTRACT, "signer": self.owner.stellar_address, "amount": 120})

            # 3. winner delivers with evidence
            login(self.client, self.winner)
            _, sent = self.run_step("deliver", self.winner_kp, {"evidence": "https://figma.com/file/abc"})
            self.assertTrue(sent["ok"], sent)
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.DELIVERED)
            self.assertEqual(esc.delivery_note, "https://figma.com/file/abc")
            self.assertIsNotNone(esc.delivered_at)
            self.need.refresh_from_db()
            self.assertEqual(self.need.status, Need.Status.DELIVERED)
            body = router.last(tw.PATH_CHANGE_MILESTONE)
            self.assertEqual(body["serviceProvider"], self.winner.stellar_address)
            self.assertEqual(body["newEvidence"], "https://figma.com/file/abc")
            self.assertEqual(body["milestoneIndex"], "0")

            # 4. client approves
            login(self.client, self.owner)
            _, sent = self.run_step("approve", self.owner_kp)
            self.assertTrue(sent["ok"], sent)
            self.assertEqual(self.escrow().status, Escrow.Status.APPROVED)
            self.assertEqual(router.last(tw.PATH_APPROVE_MILESTONE)["approver"], self.owner.stellar_address)
            self.need.refresh_from_db()
            self.assertEqual(self.need.status, Need.Status.DELIVERED)

            # 5. client releases
            _, sent = self.run_step("release", self.owner_kp)
            self.assertTrue(sent["ok"], sent)
            esc = self.escrow()
            self.assertEqual(esc.status, Escrow.Status.RELEASED)
            self.assertEqual(len(esc.release_tx_hash), 64)
            self.assertIsNotNone(esc.released_at)
            self.assertEqual(esc.last_error, "")
            self.need.refresh_from_db()
            self.assertEqual(self.need.status, Need.Status.RELEASED)
            self.assertEqual(router.last(tw.PATH_RELEASE), {"contractId": CONTRACT, "releaseSigner": self.owner.stellar_address})
            self.assertIsNone(next_action(self.need, self.owner))
            # every hash has an explorer link, plus the contract
            self.assertEqual([l["key"] for l in esc.explorer_links()], ["contract", "deploy_tx_hash", "fund_tx_hash", "deliver_tx_hash", "approve_tx_hash", "release_tx_hash"])

    def test_send_is_idempotent_for_the_same_signed_xdr(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            self.run_step("deploy", self.owner_kp)
            prep = self.prepare("fund").json()
            signed = sign(prep["xdr"], self.owner_kp)
            first = self.send("fund", signed).json()
            sends_before = sum(1 for p, _ in router.calls if p == tw.PATH_SEND)
            second = self.send("fund", signed).json()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"], second)
        self.assertIn("déjà", second["message"])
        self.assertEqual(sum(1 for p, _ in router.calls if p == tw.PATH_SEND), sends_before)  # no second submit
        self.assertEqual(self.escrow().status, Escrow.Status.FUNDED)

    def test_platform_address_falls_back_to_client_with_a_warning(self):
        router = TWRouter(self.unsigned)
        with override_settings(LOWBID_PLATFORM_ADDRESS=""), patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            with self.assertLogs("payments.services", level="WARNING") as logs:
                prep = self.prepare("deploy").json()
        self.assertTrue(prep["ok"])
        self.assertTrue(any("LOWBID_PLATFORM_ADDRESS is empty" in line for line in logs.output))
        roles = router.last(tw.PATH_DEPLOY)["roles"]
        self.assertEqual(roles["disputeResolver"], self.owner.stellar_address)
        self.assertEqual(roles["platformAddress"], self.owner.stellar_address)

    def test_deploy_without_contract_id_is_a_provider_error(self):
        router = TWRouter(self.unsigned, send_payload={"status": "SUCCESS", "message": "ok"})
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            prep = self.prepare("deploy").json()
            sent = self.send("deploy", sign(prep["xdr"], self.owner_kp)).json()
        self.assertFalse(sent["ok"])
        self.assertEqual(sent["error"], "provider")
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.CREATED)
        self.assertIn("contrat", esc.last_error)


@override_settings(**ESCROW_SETTINGS)
class EscrowGuardTests(BasePayTest):
    def test_anonymous_gets_401_json(self):
        resp = self.prepare("deploy")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {"ok": False, "error": "wallet_required"})
        resp = self.send("deploy", "AAAA")
        self.assertEqual(resp.status_code, 401)

    def test_winner_cannot_deploy_or_fund(self):
        login(self.client, self.winner)
        with patch("payments.trustless_work.requests.post") as post:
            for step in ("deploy", "fund"):
                resp = self.prepare(step)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["error"], "forbidden", step)
                self.assertIn("client", resp.json()["message"])
        post.assert_not_called()

    def test_non_winner_cannot_deliver(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            self.run_step("deploy", self.owner_kp)
            self.run_step("fund", self.owner_kp)
            for wallet in (self.other, self.owner):
                login(self.client, wallet)
                resp = self.prepare("deliver", {"evidence": "x"}).json()
                self.assertEqual(resp["error"], "forbidden")
                resp = self.send("deliver", sign(self.unsigned, self.other_kp)).json()
                self.assertEqual(resp["error"], "forbidden")
        self.assertEqual(self.escrow().status, Escrow.Status.FUNDED)

    def test_wrong_order_release_before_funded(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            resp = self.prepare("release").json()  # nothing deployed yet
            self.assertEqual(resp["error"], "wrong_state")
            self.run_step("deploy", self.owner_kp)
            resp = self.prepare("release").json()
            self.assertEqual(resp["error"], "wrong_state")
            self.assertIn("Escrow créé", resp["message"])
            resp = self.send("release", sign(self.unsigned, self.owner_kp)).json()
            self.assertEqual(resp["error"], "wrong_state")
        self.assertEqual(self.escrow().status, Escrow.Status.DEPLOYED)
        self.assertFalse(any(p == tw.PATH_RELEASE for p, _ in router.calls))

    def test_unknown_step_and_direct_only_step(self):
        login(self.client, self.owner)
        self.assertEqual(self.prepare("refund").json()["error"], "unknown_step")
        self.assertEqual(self.prepare("direct_pay").json()["error"], "wrong_mode")

    def test_not_awarded_need(self):
        need = Need.objects.create(
            client=self.owner, title="t", description="d", budget_max=Decimal("10"), delay_max_days=1,
            bidding_ends_at=timezone.now() + timedelta(hours=1),
        )
        login(self.client, self.owner)
        self.assertEqual(self.prepare("deploy", need=need).json()["error"], "not_awarded")
        self.assertFalse(Escrow.objects.filter(need=need).exists())

    def test_provider_failure_keeps_status_and_stores_last_error(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            self.run_step("deploy", self.owner_kp)
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
            sent = self.send("fund", sign(prep["xdr"], self.owner_kp)).json()
        self.assertEqual(sent["error"], "provider")
        self.assertIn("op_no_trust", sent["message"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DEPLOYED)
        self.assertEqual(esc.fund_tx_hash, "")
        self.assertIn("op_no_trust", esc.last_error)
        # retry works and clears the error
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            _, sent = self.run_step("fund", self.owner_kp)
        self.assertTrue(sent["ok"])
        self.assertEqual(self.escrow().last_error, "")

    def test_missing_api_key_is_a_provider_error_without_http(self):
        login(self.client, self.owner)
        with override_settings(TRUSTLESS_WORK_API_KEY=""), patch("payments.trustless_work.requests.post") as post:
            resp = self.prepare("deploy").json()
        post.assert_not_called()
        self.assertEqual(resp["error"], "provider")
        self.assertIn("clé API", resp["message"])

    def test_garbage_signed_xdr_is_tampered(self):
        router = TWRouter(self.unsigned)
        with patch("payments.trustless_work.requests.post", side_effect=router):
            login(self.client, self.owner)
            self.prepare("deploy")
            resp = self.send("deploy", "not-an-xdr").json()
            self.assertEqual(resp["error"], "tampered")
            resp = self.send("deploy", "").json()
            self.assertEqual(resp["error"], "tampered")
        self.assertFalse(any(p == tw.PATH_SEND for p, _ in router.calls))


# =============================== direct mode (Plan B) ==================================


DIRECT_SETTINGS = {**ESCROW_SETTINGS, "LOWBID_PAYMENT_MODE": "direct"}


@override_settings(**DIRECT_SETTINGS)
class DirectModeTests(BasePayTest):
    def setUp(self):
        super().setUp()
        self.horizon = HorizonGet(
            accounts={
                self.owner.stellar_address: horizon_account(self.owner.stellar_address, balance="500.0000000"),
                self.winner.stellar_address: horizon_account(self.winner.stellar_address, balance="0.0000000"),
            }
        )

    def submit_ok(self):
        def post(url, data=None, **kw):
            h = TransactionEnvelope.from_xdr(data["tx"], TESTNET).hash_hex()
            return _resp(200, {"hash": h, "ledger": 1234, "successful": True})

        return post

    def test_prepare_returns_a_payment_xdr_pinned_to_the_need(self):
        login(self.client, self.owner)
        with patch("payments.stellar.requests.get", side_effect=self.horizon):
            prep = self.prepare("direct_pay").json()
        self.assertTrue(prep["ok"], prep)
        info = stellar.parse_payment_xdr(prep["xdr"])
        self.assertEqual(info["op_type"], "payment")
        self.assertEqual(info["source"], self.owner.stellar_address)
        self.assertEqual(info["destination"], self.winner.stellar_address)
        self.assertEqual(info["amount"], Decimal("120"))
        self.assertEqual(info["asset_issuer"], USDC_ISSUER)
        self.assertEqual(info["memo"], f"lowbid:{self.need.pk}")
        esc = self.escrow()
        self.assertEqual(esc.mode, Escrow.Mode.DIRECT)
        self.assertEqual(esc.platform_address, "")
        self.assertEqual(esc.status, Escrow.Status.CREATED)

    def test_success_marks_paid_and_need_released(self):
        login(self.client, self.owner)
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch(
            "payments.stellar.requests.post", side_effect=self.submit_ok()
        ):
            prep, sent = self.run_step("direct_pay", self.owner_kp)
        self.assertTrue(sent["ok"], sent)
        self.assertFalse(sent["pending"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.PAID)
        self.assertEqual(esc.payment_tx_hash, sent["tx_hash"])
        self.assertEqual(esc.payment_tx_hash, stellar.parse_payment_xdr(prep["xdr"])["hash"])
        self.assertIsNotNone(esc.released_at)
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, Need.Status.RELEASED)
        self.assertEqual([l["key"] for l in esc.explorer_links()], ["payment_tx_hash"])
        self.assertIsNone(next_action(self.need, self.owner))

    def test_tampered_signed_xdr_is_refused(self):
        login(self.client, self.owner)
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch("payments.stellar.requests.post") as post:
            self.prepare("direct_pay")
            # different amount
            forged = stellar.build_payment_xdr(source=self.owner.stellar_address, destination=self.winner.stellar_address, amount=Decimal("1"), sequence=42)
            resp = self.send("direct_pay", sign(forged, self.owner_kp)).json()
            self.assertEqual(resp["error"], "tampered")
            # different destination
            forged = stellar.build_payment_xdr(source=self.owner.stellar_address, destination=self.other.stellar_address, amount=Decimal("120"), sequence=42)
            resp = self.send("direct_pay", sign(forged, self.owner_kp)).json()
            self.assertEqual(resp["error"], "tampered")
            # a trustline op instead of a payment
            forged = stellar.build_change_trust_xdr(source=self.owner.stellar_address, sequence=42)
            resp = self.send("direct_pay", sign(forged, self.owner_kp)).json()
            self.assertEqual(resp["error"], "tampered")
        post.assert_not_called()
        self.assertEqual(self.escrow().status, Escrow.Status.CREATED)
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, Need.Status.AWARDED)

    def test_winner_deliver_is_db_only_then_client_validates_and_pays(self):
        login(self.client, self.winner)
        with patch("payments.stellar.requests.get") as get, patch("payments.trustless_work.requests.post") as tw_post:
            resp = self.prepare("deliver", {"evidence": "Livré sur Figma"}).json()
        get.assert_not_called()
        tw_post.assert_not_called()
        self.assertTrue(resp["ok"])
        self.assertNotIn("xdr", resp)  # nothing to sign: the JS just follows `redirect`
        self.assertTrue(resp["redirect"].endswith("#paiement"))
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.DELIVERED)
        self.assertEqual(esc.delivery_note, "Livré sur Figma")
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, Need.Status.DELIVERED)
        self.assertEqual(next_action(self.need, self.owner)["label"], "Valider et payer")
        login(self.client, self.owner)
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch(
            "payments.stellar.requests.post", side_effect=self.submit_ok()
        ):
            _, sent = self.run_step("direct_pay", self.owner_kp)
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(self.escrow().status, Escrow.Status.PAID)
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, Need.Status.RELEASED)

    def test_escrow_only_steps_refused_in_direct_mode(self):
        login(self.client, self.owner)
        for step in ("deploy", "fund", "approve", "release"):
            self.assertEqual(self.prepare(step).json()["error"], "wrong_mode", step)

    def test_horizon_rejection_keeps_status(self):
        login(self.client, self.owner)
        rejected = _resp(400, {"extras": {"result_codes": {"transaction": "tx_failed", "operations": ["op_no_trust"]}}})
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch("payments.stellar.requests.post", return_value=rejected):
            prep = self.prepare("direct_pay").json()
            sent = self.send("direct_pay", sign(prep["xdr"], self.owner_kp)).json()
        self.assertEqual(sent["error"], "provider")
        self.assertIn("trustline", sent["message"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.CREATED)
        self.assertEqual(esc.payment_tx_hash, "")
        self.assertIn("trustline", esc.last_error)

    def test_horizon_timeout_stores_hash_then_reconciles_on_next_prepare(self):
        login(self.client, self.owner)
        with patch("payments.stellar.requests.get", side_effect=self.horizon), patch(
            "payments.stellar.requests.post", return_value=_resp(504, {"status": 504, "title": "Timeout"})
        ):
            prep = self.prepare("direct_pay").json()
            signed = sign(prep["xdr"], self.owner_kp)
            sent = self.send("direct_pay", signed).json()
        tx_hash = TransactionEnvelope.from_xdr(signed, TESTNET).hash_hex()
        self.assertTrue(sent["ok"])
        self.assertTrue(sent["pending"])
        self.assertEqual(sent["tx_hash"], tx_hash)
        self.assertEqual(sent["message"], PENDING_MESSAGE)
        self.assertIn(tx_hash, sent["explorer_url"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.CREATED)
        self.assertEqual(esc.payment_tx_hash, tx_hash)
        self.assertEqual(esc.last_error, PENDING_MESSAGE)
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, Need.Status.AWARDED)
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
        self.assertIn("confirmé", prep["message"])
        esc = self.escrow()
        self.assertEqual(esc.status, Escrow.Status.PAID)
        self.assertEqual(esc.last_error, "")
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, Need.Status.RELEASED)

    def test_mode_is_refrozen_while_nothing_is_on_chain(self):
        """Deploy failed in escrow mode → founder flips LOWBID_PAYMENT_MODE=direct → Plan B just works."""
        with override_settings(LOWBID_PAYMENT_MODE="escrow"), patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned, build_status=500)):
            login(self.client, self.owner)
            self.assertEqual(self.prepare("deploy").json()["error"], "provider")
        self.assertEqual(self.escrow().mode, Escrow.Mode.ESCROW)
        with patch("payments.stellar.requests.get", side_effect=self.horizon):
            prep = self.prepare("direct_pay").json()
        self.assertTrue(prep["ok"], prep)
        self.assertEqual(self.escrow().mode, Escrow.Mode.DIRECT)

    def test_unfunded_client_account_is_a_stellar_error(self):
        login(self.client, self.owner)
        with patch("payments.stellar.requests.get", side_effect=HorizonGet()):
            resp = self.prepare("direct_pay").json()
        self.assertEqual(resp["error"], "stellar")
        self.assertIn("friendbot", resp["message"])
        self.assertIn("friendbot", self.escrow().last_error)


# =============================== trustline ==================================


@override_settings(**ESCROW_SETTINGS)
class TrustlineTests(BasePayTest):
    def test_anonymous_401(self):
        self.assertEqual(self.client.post(reverse("payments:trustline_prepare"), **JSON).status_code, 401)

    def test_already_present_returns_message_without_xdr(self):
        login(self.client, self.winner)
        horizon = HorizonGet(accounts={self.winner.stellar_address: horizon_account(self.winner.stellar_address, with_usdc=True)})
        with patch("payments.stellar.requests.get", side_effect=horizon):
            resp = self.client.post(reverse("payments:trustline_prepare"), **JSON).json()
        self.assertEqual(resp, {"ok": True, "message": "Trustline USDC déjà présente."})

    def test_missing_trustline_builds_change_trust_then_submits(self):
        login(self.client, self.winner)
        horizon = HorizonGet(accounts={self.winner.stellar_address: horizon_account(self.winner.stellar_address, with_usdc=False)})
        with patch("payments.stellar.requests.get", side_effect=horizon):
            prep = self.client.post(reverse("payments:trustline_prepare"), **JSON).json()
        self.assertTrue(prep["ok"])
        self.assertEqual(prep["send_url"], reverse("payments:trustline_send"))
        info = stellar.parse_payment_xdr(prep["xdr"])
        self.assertEqual(info["op_type"], "change_trust")
        self.assertEqual(info["source"], self.winner.stellar_address)
        self.assertEqual(info["asset_issuer"], USDC_ISSUER)

        def post(url, data=None, **kw):
            return _resp(200, {"hash": TransactionEnvelope.from_xdr(data["tx"], TESTNET).hash_hex(), "successful": True})

        with patch("payments.stellar.requests.post", side_effect=post):
            sent = self.client.post(
                reverse("payments:trustline_send"),
                data=json.dumps({"signed_xdr": sign(prep["xdr"], self.winner_kp)}),
                content_type="application/json",
                **JSON,
            ).json()
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(sent["message"], "Trustline USDC ajoutée.")
        self.assertIn(sent["tx_hash"], sent["explorer_url"])

    def test_trustline_for_another_wallet_is_tampered(self):
        login(self.client, self.winner)
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


# =============================== panel / pages ==================================


@override_settings(**ESCROW_SETTINGS)
class PanelTests(BasePayTest):
    def prepare_url(self, step):
        return reverse("payments:prepare", kwargs={"need_pk": self.need.pk, "step": step})

    def test_anonymous_panel_is_read_only(self):
        html = self.detail().content.decode()
        self.assertIn('id="escrow-panel"', html)
        self.assertIn("Paiement en escrow", html)
        self.assertNotIn("data-prepare-url", html)
        self.assertNotIn("data-pay-trustline", html)
        self.assertIn(f'data-usdc-balance="{self.winner.stellar_address}" data-watch', html)
        self.assertIn("En attente de la création de l’escrow", html)
        self.assertIn(f'data-copy="{self.winner.stellar_address}"', html)

    def test_client_sees_deploy_button_winner_waits(self):
        login(self.client, self.owner)
        html = self.detail().content.decode()
        self.assertIn(f'data-pay-step="deploy" data-prepare-url="{self.prepare_url("deploy")}"', html)
        self.assertIn("Créer l’escrow", html)
        self.assertIn("data-pay-trustline", html)
        self.assertIn("data-pay-error", html)
        login(self.client, self.winner)
        html = self.detail().content.decode()
        self.assertNotIn("data-prepare-url=", html.replace('data-pay-trustline data-prepare-url', ""))
        self.assertIn("En attente de la création de l’escrow", html)
        self.assertIn("data-pay-trustline", html)

    def test_winner_sees_deliver_form_once_funded(self):
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            login(self.client, self.owner)
            self.run_step("deploy", self.owner_kp)
            self.run_step("fund", self.owner_kp)
        login(self.client, self.winner)
        html = self.detail().content.decode()
        self.assertIn(f'data-pay-step="deliver" data-prepare-url="{self.prepare_url("deliver")}"', html)
        self.assertIn('name="evidence"', html)
        self.assertIn("data-pay-form", html)
        self.assertIn(f"/contract/{CONTRACT}", html)  # explorer link for the contract id
        self.assertIn("Fonds bloqués", html)
        login(self.client, self.owner)
        html = self.detail().content.decode()
        self.assertIn("En attente de la livraison", html)
        self.assertNotIn('data-pay-step="deliver"', html)

    def test_platform_fallback_alert_only_for_the_client_when_address_missing(self):
        """Empty LOWBID_PLATFORM_ADDRESS merges the platform roles onto the client (escrow mode):
        the client gets a one-line warning in the panel, nobody else does, direct mode never does."""
        with override_settings(LOWBID_PLATFORM_ADDRESS=""):
            login(self.client, self.owner)
            html = self.detail().content.decode()
            self.assertIn("data-platform-fallback", html)
            self.assertIn("Adresse plateforme non configurée", html)
            login(self.client, self.winner)
            self.assertNotIn("data-platform-fallback", self.detail().content.decode())
        login(self.client, self.owner)
        self.assertNotIn("data-platform-fallback", self.detail().content.decode())  # PLATFORM configured
        with override_settings(LOWBID_PLATFORM_ADDRESS="", LOWBID_PAYMENT_MODE="direct"):
            self.assertNotIn("data-platform-fallback", self.detail().content.decode())

    def test_platform_fallback_follows_the_frozen_escrow_row(self):
        from payments.services import ensure_escrow, platform_fallback_in_use

        with override_settings(LOWBID_PLATFORM_ADDRESS=""):
            escrow = ensure_escrow(self.need)  # frozen with the client as platform address
        self.assertEqual(escrow.platform_address, self.owner.stellar_address)
        self.assertTrue(platform_fallback_in_use(self.need, escrow, Escrow.Mode.ESCROW))
        self.assertFalse(platform_fallback_in_use(self.need, None, Escrow.Mode.DIRECT))

    @override_settings(LOWBID_PAYMENT_MODE="direct")
    def test_direct_mode_panel(self):
        login(self.client, self.owner)
        html = self.detail().content.decode()
        self.assertIn("Paiement direct USDC", html)
        self.assertIn("Plan B", html)
        self.assertIn(f'data-pay-step="direct_pay" data-prepare-url="{self.prepare_url("direct_pay")}"', html)
        self.assertNotIn("Fonds bloqués", html)  # two-step stepper
        login(self.client, self.winner)
        html = self.detail().content.decode()
        self.assertIn(f'data-pay-step="deliver" data-prepare-url="{self.prepare_url("deliver")}"', html)
        self.assertIn('name="evidence"', html)

    def test_stepper_states(self):
        self.assertEqual([s["state"] for s in stepper("escrow", "created")], ["current", "todo", "todo", "todo"])
        self.assertEqual([s["state"] for s in stepper("escrow", "funded")], ["done", "done", "current", "todo"])
        self.assertEqual([s["state"] for s in stepper("escrow", "approved")], ["done", "done", "done", "current"])
        self.assertEqual([s["state"] for s in stepper("escrow", "released")], ["done"] * 4)
        self.assertEqual([s["state"] for s in stepper("direct", "created")], ["current", "todo"])
        self.assertEqual([s["state"] for s in stepper("direct", "paid")], ["done", "done"])

    def test_next_action_per_viewer(self):
        a = next_action(self.need, self.owner)
        self.assertEqual((a["step"], a["mine"], a["who"]), ("deploy", True, "client"))
        a = next_action(self.need, self.winner)
        self.assertEqual((a["step"], a["mine"]), ("deploy", False))
        self.assertEqual(next_action(self.need, None)["step"], "deploy")
        with override_settings(LOWBID_PAYMENT_MODE="direct"):
            self.assertEqual(next_action(self.need, self.owner)["step"], "direct_pay")
            self.assertEqual(next_action(self.need, self.winner)["step"], "deliver")
            self.assertEqual(next_action(self.need, None)["step"], "direct_pay")
        open_need = Need.objects.create(
            client=self.owner, title="t", description="d", budget_max=Decimal("10"), delay_max_days=1,
            bidding_ends_at=timezone.now() + timedelta(hours=1),
        )
        self.assertIsNone(next_action(open_need, self.owner))

    def test_pay_redirects_to_detail_anchor(self):
        resp = self.client.get(reverse("payments:need_pay", kwargs={"need_pk": self.need.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("auctions:need_detail", args=[self.need.pk]) + "#paiement")
        self.assertEqual(self.client.get(reverse("payments:need_pay", kwargs={"need_pk": 9999})).status_code, 404)

    def test_my_bids_and_my_needs_show_payment_status(self):
        with patch("payments.trustless_work.requests.post", side_effect=TWRouter(self.unsigned)):
            login(self.client, self.owner)
            self.run_step("deploy", self.owner_kp)
        login(self.client, self.winner)
        html = self.client.get(reverse("auctions:my_bids")).content.decode()
        self.assertIn("Voir le paiement", html)
        self.assertIn(f"/besoins/{self.need.pk}/#paiement", html)
        self.assertIn("Escrow créé", html)
        login(self.client, self.owner)
        html = self.client.get(reverse("auctions:my_needs")).content.decode()
        self.assertIn("Escrow créé", html)

    def test_payment_error_shape(self):
        err = PaymentError("forbidden", "Non.")
        self.assertEqual((err.code, err.message, str(err)), ("forbidden", "Non.", "Non."))
