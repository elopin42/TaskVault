"""Publication deposit (payments/deposits.py): amounts, verdict table, company steps, server-signed refund
and forfeit chains, triggers, endpoints, /fonds/, the system check and secret hygiene. No network:
`requests` is mocked in payments.trustless_work, Horizon reads are patched in payments.stellar."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.checks import CheckMessage, Error
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair, TransactionEnvelope

from payments import deposits, stellar
from payments import trustless_work as tw
from payments.checks import check_deposit_keys
from payments.models import ProjectDeposit
from payments.services import PaymentError
from payments.tests_flow import CONTRACT, ESCROW_SETTINGS, JSON, TESTNET, _resp, login, make_wallet, sign
from projects import services as projects
from projects.models import Application, Project, Task

PLATFORM_KP = Keypair.random()
RESOLVER_KP = Keypair.random()
FUND = Keypair.random().public_key

DEPOSIT_SETTINGS = {
    **ESCROW_SETTINGS,
    "LOWBID_DEPOSIT_ENABLED": True,
    "LOWBID_PLATFORM_ADDRESS": PLATFORM_KP.public_key,
    "LOWBID_PLATFORM_SECRET": PLATFORM_KP.secret,
    "LOWBID_DEPOSIT_RESOLVER_SECRET": RESOLVER_KP.secret,
    "LOWBID_GUARANTEE_FUND_ADDRESS": FUND,
    "LOWBID_DEPOSIT_RATE": Decimal("0.01"),
    "LOWBID_DEPOSIT_MIN": Decimal("5"),
    "LOWBID_DEPOSIT_TOPUP_MIN": Decimal("1"),
    "LOWBID_CHOICE_DAYS": 14,
    "LOWBID_NO_APPLICATION_DAYS": 30,
}
SECRETS = (PLATFORM_KP.secret, RESOLVER_KP.secret)
ROLE_KEYS = ("signer", "serviceProvider", "approver", "releaseSigner", "disputeResolver")


class DepositTW:
    """requests.post / requests.get stand-in for Trustless Work. Each build answers an unsigned XDR whose
    source is the role address in the body (what TW does); sends are recorded with the step they submit."""

    def __init__(self, fail=(), balance="5"):
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[tuple[str, str]] = []  # (build path, signed xdr)
        self.fail = set(fail)
        self.fail_send = set()
        self.balance = balance
        self._by_hash: dict[str, str] = {}
        self._seq = 100

    def post(self, url, json=None, **kw):
        path = url.split("trustlesswork.com", 1)[-1]
        body = json or {}
        self.calls.append((path, body))
        if path == tw.PATH_SEND:
            signed = body["signedXdr"]
            h = TransactionEnvelope.from_xdr(signed, TESTNET).hash_hex()
            built = self._by_hash.get(h, "?")
            self.sent.append((built, signed))
            if built in self.fail_send:
                return _resp(400, {"message": f"send refused for {built}"})
            payload = {"status": "SUCCESS"}
            if built == tw.PATH_DEPLOY:
                payload["contractId"] = CONTRACT
            return _resp(200, payload)
        if path in self.fail:
            return _resp(400, {"message": f"vendor refused {path}"})
        source = next(body[k] for k in ROLE_KEYS if k in body)
        self._seq += 1
        xdr = stellar.build_payment_xdr(source=source, destination=FUND, amount=Decimal("1"), sequence=self._seq)
        self._by_hash[TransactionEnvelope.from_xdr(xdr, TESTNET).hash_hex()] = path
        return _resp(201, {"status": "SUCCESS", "unsignedTransaction": xdr})

    def get(self, url, params=None, **kw):
        self.calls.append((url.split("trustlesswork.com", 1)[-1], params or {}))
        return _resp(200, {"contractId": CONTRACT, "balance": json_number(self.balance)})

    def built(self) -> list[str]:
        return [p for p, _ in self.calls if p not in (tw.PATH_SEND, tw.PATH_GET_ESCROW)]

    def sent_paths(self) -> list[str]:
        return [p for p, _ in self.sent]

    def signed_for(self, path: str) -> str:
        return next(x for p, x in self.sent if p == path)


def json_number(value: str):
    d = Decimal(value)
    return int(d) if d == d.to_integral_value() else float(d)


def signed_by(signed_xdr: str, kp: Keypair) -> bool:
    env = TransactionEnvelope.from_xdr(signed_xdr, TESTNET)
    for sig in env.signatures:
        if sig.signature_hint == kp.signature_hint():
            try:
                kp.verify(env.hash(), sig.signature)
                return True
            except Exception:
                return False
    return False


@override_settings(**DEPOSIT_SETTINGS)
class DepositBase(TestCase):
    def setUp(self):
        self.company, self.company_kp = make_wallet("company")
        self.freelance, _ = make_wallet("freelance")
        self.other, _ = make_wallet("other")
        self.project = projects.create_project(self.company, "Booking site", "A booking site.")
        self.t1 = projects.add_task(self.project, self.company, "Landing", "", "300", ["django"])
        self.t2 = projects.add_task(self.project, self.company, "Dashboard", "", "200", ["django"])
        self.tw = DepositTW()

    def patched(self):
        return patch("payments.trustless_work.requests.post", side_effect=self.tw.post), patch(
            "payments.trustless_work.requests.get", side_effect=self.tw.get
        )

    def funded_row(self, *, covered="500", amount="5", project=None) -> ProjectDeposit:
        project = project or self.project
        now = timezone.now()
        row = ProjectDeposit.objects.create(
            project=project,
            amount=Decimal(amount),
            covered_budget=Decimal(covered),
            payer_address=self.company.stellar_address,
            platform_address=PLATFORM_KP.public_key,
            resolver_address=RESOLVER_KP.public_key,
            fund_address=FUND,
            contract_id=CONTRACT,
            engagement_id=f"taskvault-deposit-{project.pk}-1",
            deploy_tx_hash="d" * 64,
            fund_tx_hash="f" * 64,
            status=ProjectDeposit.Status.FUNDED,
            funded_at=now,
        )
        Project.objects.filter(pk=project.pk, published_at__isnull=True).update(published_at=now)
        project.refresh_from_db()
        return row

    def post(self, name, body=None, **kwargs):
        return self.client.post(
            reverse(f"payments:{name}", kwargs={"project_pk": self.project.pk, **kwargs}),
            data=json.dumps(body or {}),
            content_type="application/json",
            **JSON,
        )

    def age_applications(self, days: float):
        Application.objects.filter(task__project=self.project).update(created_at=timezone.now() - timedelta(days=days))


# --- amounts -------------------------------------------------------------------------------------


class AmountTests(DepositBase):
    def test_deposit_amount_rate_min_and_quantization(self):
        self.assertEqual(deposits.deposit_amount(Decimal("100")), Decimal("5.0000000"), "1 % of 100 < min 5")
        self.assertEqual(deposits.deposit_amount(Decimal("1200")), Decimal("12.0000000"))
        self.assertEqual(deposits.deposit_amount(Decimal("1234.56789")), Decimal("12.3456789"))
        self.assertEqual(deposits.deposit_amount(Decimal("1234.567891")), Decimal("12.3456790"), "7 dp, rounded up")
        self.assertEqual(deposits.deposit_amount(0), Decimal("5"))

    def test_topup_amount(self):
        self.assertEqual(deposits.topup_amount(Decimal("50")), Decimal("1.0000000"), "min 1")
        self.assertEqual(deposits.topup_amount(Decimal("700")), Decimal("7.0000000"))

    @override_settings(LOWBID_DEPOSIT_RATE=Decimal("0.05"), LOWBID_DEPOSIT_MIN=Decimal("2"))
    def test_settings_drive_the_formula(self):
        self.assertEqual(deposits.deposit_amount(Decimal("100")), Decimal("5"))
        self.assertEqual(deposits.deposit_amount(Decimal("10")), Decimal("2"))

    def test_deposit_due_publication_then_topup(self):
        self.assertEqual(deposits.deposit_due(self.project), Decimal("5"), "1 % of 500 → min 5")
        self.funded_row(covered="500")
        self.assertEqual(deposits.deposit_due(self.project), Decimal("0"))
        projects.add_task(self.project, self.company, "API", "", "700", ["api"])
        self.assertEqual(deposits.deposit_due(self.project), Decimal("7"), "top-up on the 700 gap")

    def test_inactive_means_nothing_due(self):
        with override_settings(LOWBID_DEPOSIT_ENABLED=False):
            self.assertFalse(deposits.deposits_active())
            self.assertEqual(deposits.deposit_due(self.project), Decimal("0"))
        with override_settings(LOWBID_PAYMENT_MODE="direct"):
            self.assertFalse(deposits.deposits_active())


# --- coverage + apply gates ----------------------------------------------------------------------------


class CoverageTests(DepositBase):
    def test_unpublished_project_refuses_applications(self):
        self.assertIsNone(self.project.published_at)
        with self.assertRaises(projects.ProjectError) as ctx:
            projects.apply(self.t1, self.freelance, "hi", ["django"])
        self.assertEqual(ctx.exception.code, "not_published")

    def test_task_added_after_funding_waits_for_the_topup(self):
        self.funded_row(covered="500")
        projects.apply(self.t1, self.freelance, "hi", ["django"])
        t3 = projects.add_task(self.project, self.company, "API", "", "100", ["api"])
        self.assertTrue(deposits.task_covered(self.t2))
        self.assertFalse(deposits.task_covered(t3))
        with self.assertRaises(projects.ProjectError) as ctx:
            projects.apply(t3, self.freelance, "hi", ["api"])
        self.assertEqual(ctx.exception.code, "not_covered")
        self.funded_row(covered="100", amount="1")  # the top-up
        self.assertTrue(deposits.task_covered(t3))
        projects.apply(t3, self.freelance, "hi", ["api"])

    def test_apply_endpoint_maps_codes_to_409(self):
        login(self.client, self.freelance)
        r = self.client.post(
            reverse("projects:apply_create", args=[self.t1.pk]), data=json.dumps({"message": "x"}),
            content_type="application/json", **JSON,
        )
        self.assertEqual((r.status_code, r.json()["error"]), (409, "not_published"))

    def test_cancelled_project_refuses_applications_in_any_mode(self):
        projects.cancel_project(self.project, self.company)
        with override_settings(LOWBID_PAYMENT_MODE="direct"):
            with self.assertRaises(projects.ProjectError) as ctx:
                projects.apply(self.t1, self.freelance, "hi", [])
        self.assertEqual(ctx.exception.code, "wrong_state")


# --- verdict table ---------------------------------------------------------------------------------------


class VerdictTests(DepositBase):
    def setUp(self):
        super().setUp()
        self.row = self.funded_row()
        self.published = self.project.published_at

    def verdict(self, days_after_publication: float):
        return deposits.deposit_verdict(self.project, self.published + timedelta(days=days_after_publication))

    def test_no_application_locked_then_refund_after_30_days(self):
        v = self.verdict(29.9)
        self.assertEqual(v["verdict"], "locked")
        self.assertEqual(v["deadline"], self.published + timedelta(days=30))
        v = self.verdict(30)
        self.assertEqual((v["verdict"], v["deadline"]), ("refund", None))

    def test_application_without_choice_forfeits_after_14_days(self):
        projects.apply(self.t1, self.freelance, "hi", [])
        first = Application.objects.get().created_at
        v = deposits.deposit_verdict(self.project, first + timedelta(days=13, hours=23))
        self.assertEqual((v["verdict"], v["deadline"]), ("locked", first + timedelta(days=14)))
        v = deposits.deposit_verdict(self.project, first + timedelta(days=14))
        self.assertEqual((v["verdict"], v["deadline"]), ("forfeit", None))
        self.assertIn("14 days", v["reason"])

    def test_a_choice_keeps_it_locked_until_closed(self):
        projects.apply(self.t1, self.freelance, "hi", [])
        projects.choose(self.t1, Application.objects.get(), self.company)
        first = Application.objects.get().created_at
        v = deposits.deposit_verdict(self.project, first + timedelta(days=400))
        self.assertEqual((v["verdict"], v["deadline"]), ("locked", None))

    def test_closed_refunds(self):
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CLOSED)
        self.project.refresh_from_db()
        self.assertEqual(self.verdict(0)["verdict"], "refund")

    def test_cancelled_without_application_refunds(self):
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CANCELLED)
        self.project.refresh_from_db()
        self.assertEqual(self.verdict(0)["verdict"], "refund")

    def test_cancelled_with_application_forfeits(self):
        projects.apply(self.t1, self.freelance, "hi", [])
        Project.objects.filter(pk=self.project.pk).update(status=Project.Status.CANCELLED)
        self.project.refresh_from_db()
        self.assertEqual(self.verdict(0)["verdict"], "forfeit")

    def test_verdict_writes_nothing(self):
        before = (ProjectDeposit.objects.get().updated_at, Project.objects.get(pk=self.project.pk).updated_at)
        self.verdict(100)
        after = (ProjectDeposit.objects.get().updated_at, Project.objects.get(pk=self.project.pk).updated_at)
        self.assertEqual(before, after)

    def test_cancel_outcome(self):
        self.assertEqual(deposits.cancel_outcome(self.project), "refund")
        projects.apply(self.t1, self.freelance, "hi", [])
        self.assertEqual(deposits.cancel_outcome(self.project), "forfeit")
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, Project.Status.DRAFT, "hypothetical only")


# --- company steps (Freighter) -------------------------------------------------------------------------


class CompanyStepTests(DepositBase):
    def run_step(self, step, kp=None, body=None):
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            prep = self.post("deposit_prepare", body, step=step).json()
            if not prep.get("ok"):
                return prep, None
            sent = self.post("deposit_send", {"signed_xdr": sign(prep["xdr"], kp or self.company_kp), **(body or {})}, step=step).json()
        return prep, sent

    def test_publish_happy_path(self):
        login(self.client, self.company)
        pending = self.client.get(reverse("payments:deposit_pending", args=[self.project.pk]), **JSON).json()
        self.assertEqual((pending["next"]["step"], pending["amount"]), ("deploy", "5"))
        prep, sent = self.run_step("deploy")
        self.assertTrue(sent["ok"], sent)
        deploy = self.tw.calls[0][1]
        self.assertEqual(deploy["signer"], self.company.stellar_address)
        self.assertEqual(
            deploy["roles"],
            {
                "approver": PLATFORM_KP.public_key,
                "serviceProvider": PLATFORM_KP.public_key,
                "receiver": self.company.stellar_address,
                "releaseSigner": PLATFORM_KP.public_key,
                "disputeResolver": RESOLVER_KP.public_key,
                "platformAddress": PLATFORM_KP.public_key,
            },
        )
        self.assertEqual((deploy["amount"], deploy["platformFee"]), (5, 0))
        self.assertEqual(deploy["title"], "Publication deposit — Booking site")
        self.assertEqual(deploy["milestones"], [{"description": f"Deposit for project #{self.project.pk}"}])
        self.assertEqual(sent["next"]["step"], "fund")
        row = ProjectDeposit.objects.get()
        self.assertEqual((row.status, row.contract_id, row.kind), ("deployed", CONTRACT, "publication"))
        self.assertEqual(row.engagement_id, f"taskvault-deposit-{self.project.pk}-1")
        prep, sent = self.run_step("fund")
        self.assertTrue(sent["ok"], sent)
        self.assertIsNone(sent["next"])
        self.assertTrue(sent["published"])
        row.refresh_from_db()
        self.assertEqual((row.status, row.covered_budget), ("funded", Decimal("500")))
        self.assertIsNotNone(row.funded_at)
        self.assertIsNotNone(Project.objects.get(pk=self.project.pk).published_at)
        projects.apply(Task.objects.get(pk=self.t1.pk), self.freelance, "now I can", [])

    def test_role_gate_both_halves(self):
        login(self.client, self.other)
        r = self.post("deposit_prepare", step="deploy").json()
        self.assertEqual(r["error"], "forbidden")
        r = self.post("deposit_send", {"signed_xdr": "AAAA"}, step="deploy").json()
        self.assertEqual(r["error"], "forbidden")
        r = self.client.get(reverse("payments:deposit_pending", args=[self.project.pk]), **JSON).json()
        self.assertEqual(r["error"], "forbidden")
        self.assertFalse(ProjectDeposit.objects.exists())

    def test_state_gates(self):
        login(self.client, self.company)
        r = self.post("deposit_prepare", step="fund").json()
        self.assertEqual(r["error"], "wrong_state")
        r = self.post("deposit_prepare", step="refund").json()
        self.assertEqual(r["error"], "unknown_step")
        projects.cancel_project(self.project, self.company)
        r = self.post("deposit_prepare", step="deploy").json()
        self.assertEqual(r["error"], "wrong_state")
        with override_settings(LOWBID_PAYMENT_MODE="direct"):
            r = self.post("deposit_prepare", step="deploy").json()
        self.assertEqual(r["error"], "wrong_mode")

    def test_replayed_send_is_idempotent(self):
        login(self.client, self.company)
        self.run_step("deploy")
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            prep = self.post("deposit_prepare", step="fund").json()
            signed = sign(prep["xdr"], self.company_kp)
            first = self.post("deposit_send", {"signed_xdr": signed}, step="fund").json()
            sends = self.tw.sent_paths().count(tw.PATH_FUND)
            again = self.post("deposit_send", {"signed_xdr": signed}, step="fund").json()
        self.assertTrue(first["ok"] and again["ok"], (first, again))
        self.assertEqual(again["message"], "Step already confirmed.")
        self.assertEqual(self.tw.sent_paths().count(tw.PATH_FUND), sends, "nothing sent twice")

    def test_body_addresses_are_ignored(self):
        login(self.client, self.company)
        evil = {"signer": self.other.stellar_address, "payer_address": self.other.stellar_address, "receiver": self.other.stellar_address}
        prep, sent = self.run_step("deploy", body=evil)
        deploy = self.tw.calls[0][1]
        self.assertEqual(deploy["signer"], self.company.stellar_address)
        self.assertEqual(deploy["roles"]["receiver"], self.company.stellar_address)
        self.assertEqual(ProjectDeposit.objects.get().payer_address, self.company.stellar_address)

    def test_xdr_signed_by_someone_else_is_tampered(self):
        login(self.client, self.company)
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            self.post("deposit_prepare", step="deploy")
            foreign = stellar.build_payment_xdr(source=self.other.stellar_address, destination=FUND, amount=Decimal("1"), sequence=3)
            r = self.post("deposit_send", {"signed_xdr": foreign}, step="deploy").json()
        self.assertEqual(r["error"], "tampered")
        self.assertEqual(ProjectDeposit.objects.get().status, "created")

    def test_provider_failure_keeps_status(self):
        login(self.client, self.company)
        self.tw.fail_send.add(tw.PATH_DEPLOY)
        prep, sent = self.run_step("deploy")
        self.assertEqual(sent["error"], "provider")
        row = ProjectDeposit.objects.get()
        self.assertEqual(row.status, "created")
        self.assertIn("send refused", row.last_error)

    def test_topup_row(self):
        self.funded_row()
        projects.add_task(self.project, self.company, "API", "", "700", [])
        login(self.client, self.company)
        self.run_step("deploy")
        row = ProjectDeposit.objects.order_by("-pk").first()
        self.assertEqual((row.kind, row.amount, row.covered_budget), ("topup", Decimal("7"), Decimal("700")))
        self.assertEqual(row.engagement_id, f"taskvault-deposit-{self.project.pk}-2")


# --- server chains -------------------------------------------------------------------------------------


class RefundChainTests(DepositBase):
    def setUp(self):
        super().setUp()
        self.row = self.funded_row()

    def test_refund_happy_path(self):
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            row = deposits.refund(self.row)
        self.assertEqual(self.tw.built(), [tw.PATH_CHANGE_MILESTONE, tw.PATH_APPROVE_MILESTONE, tw.PATH_RELEASE])
        self.assertEqual(self.tw.sent_paths(), [tw.PATH_CHANGE_MILESTONE, tw.PATH_APPROVE_MILESTONE, tw.PATH_RELEASE])
        for _, signed in self.tw.sent:
            self.assertTrue(signed_by(signed, PLATFORM_KP))
        milestone = self.tw.calls[0][1]
        self.assertEqual((milestone["serviceProvider"], milestone["newEvidence"]), (PLATFORM_KP.public_key, "deposit refund"))
        self.assertEqual(row.status, "refunded")
        self.assertTrue(row.milestone_tx_hash and row.approve_tx_hash and row.release_tx_hash)
        self.assertIsNotNone(row.settled_at)
        self.assertEqual(row.last_error, "")

    def test_partial_failure_then_rerun_sends_only_missing_steps(self):
        self.tw.fail.add(tw.PATH_APPROVE_MILESTONE)
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            row = deposits.refund(self.row)
        self.assertEqual(row.status, "funded")
        self.assertIn("vendor refused", row.last_error)
        self.assertTrue(row.milestone_tx_hash)
        self.assertFalse(row.approve_tx_hash)
        self.tw.fail.clear()
        self.tw.calls.clear()
        self.tw.sent.clear()
        with post_patch, get_patch:
            row = deposits.refund(row)
        self.assertEqual(self.tw.built(), [tw.PATH_APPROVE_MILESTONE, tw.PATH_RELEASE])
        self.assertEqual(row.status, "refunded")
        self.assertEqual(row.last_error, "")

    def test_refund_is_idempotent_once_done(self):
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            deposits.refund(self.row)
            n = len(self.tw.calls)
            row = deposits.refund(self.row)
        self.assertEqual(len(self.tw.calls), n)
        self.assertEqual(row.status, "refunded")

    @override_settings(LOWBID_PLATFORM_SECRET="")
    def test_missing_key_records_error_without_calls(self):
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            row = deposits.refund(self.row)
        self.assertEqual(self.tw.calls, [])
        self.assertEqual((row.status, row.last_error), ("funded", "Server signing key is not configured."))

    def test_settle_refuses_while_locked(self):
        with self.assertRaises(PaymentError) as ctx:
            deposits.settle(self.row)
        self.assertEqual(ctx.exception.code, "wrong_state")


class ForfeitChainTests(DepositBase):
    def setUp(self):
        super().setUp()
        self.row = self.funded_row()
        self.tw.balance = "4.985"

    def test_missing_trustline_blocks_without_any_call(self):
        post_patch, get_patch = self.patched()
        with post_patch, get_patch, patch("payments.stellar.has_trustline", return_value=False):
            row = deposits.forfeit(self.row)
        self.assertEqual(self.tw.calls, [])
        self.assertEqual((row.status, row.last_error), ("funded", "The guarantee fund has no USDC trustline."))

    def test_forfeit_happy_path(self):
        post_patch, get_patch = self.patched()
        with post_patch, get_patch, patch("payments.stellar.has_trustline", return_value=True):
            row = deposits.forfeit(self.row)
        self.assertEqual(self.tw.built(), [tw.PATH_DISPUTE, tw.PATH_RESOLVE])
        dispute = self.tw.calls[0][1]
        self.assertEqual(dispute, {"contractId": CONTRACT, "signer": PLATFORM_KP.public_key})
        balance_read = next(params for p, params in self.tw.calls if p == tw.PATH_GET_ESCROW)
        self.assertEqual(balance_read.get("validateOnChain"), "true")
        resolve = next(body for p, body in self.tw.calls if p == tw.PATH_RESOLVE)
        self.assertEqual(resolve["disputeResolver"], RESOLVER_KP.public_key)
        self.assertEqual(resolve["distributions"], [{"address": FUND, "amount": 4.985}])
        self.assertTrue(signed_by(self.tw.signed_for(tw.PATH_DISPUTE), PLATFORM_KP))
        self.assertFalse(signed_by(self.tw.signed_for(tw.PATH_DISPUTE), RESOLVER_KP))
        self.assertTrue(signed_by(self.tw.signed_for(tw.PATH_RESOLVE), RESOLVER_KP))
        self.assertFalse(signed_by(self.tw.signed_for(tw.PATH_RESOLVE), PLATFORM_KP))
        self.assertEqual(row.status, "forfeited")
        self.assertTrue(row.dispute_tx_hash and row.resolve_tx_hash)

    def test_resolve_failure_keeps_the_dispute_hash(self):
        self.tw.fail.add(tw.PATH_RESOLVE)
        post_patch, get_patch = self.patched()
        with post_patch, get_patch, patch("payments.stellar.has_trustline", return_value=True):
            row = deposits.forfeit(self.row)
            self.assertEqual(row.status, "funded")
            self.assertTrue(row.dispute_tx_hash)
            self.tw.fail.clear()
            self.tw.calls.clear()
            row = deposits.forfeit(row)
        self.assertNotIn(tw.PATH_DISPUTE, self.tw.built())
        self.assertEqual(row.status, "forfeited")


# --- triggers + endpoints --------------------------------------------------------------------------------


class TriggerTests(DepositBase):
    def test_closing_the_project_refunds_on_commit(self):
        self.funded_row()
        projects.delete_task(self.t2, self.company)
        projects.apply(self.t1, self.freelance, "hi", [])
        projects.choose(self.t1, Application.objects.get(), self.company)
        post_patch, get_patch = self.patched()
        with post_patch, get_patch, self.captureOnCommitCallbacks(execute=True) as callbacks:
            projects.mark_paid(Task.objects.get(pk=self.t1.pk))
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, "closed")
        self.assertEqual(ProjectDeposit.objects.get().status, "refunded")

    def test_cancel_with_applications_forfeits_on_commit(self):
        self.funded_row()
        projects.apply(self.t1, self.freelance, "hi", [])
        post_patch, get_patch = self.patched()
        with post_patch, get_patch, patch("payments.stellar.has_trustline", return_value=True), self.captureOnCommitCallbacks(execute=True):
            projects.cancel_project(self.project, self.company)
        self.assertEqual(ProjectDeposit.objects.get().status, "forfeited")

    def test_auto_settle_failure_is_logged_not_raised(self):
        self.funded_row()
        with patch("payments.deposits.settle_project", side_effect=RuntimeError("boom")), self.assertLogs("payments.deposits", level="ERROR"):
            with self.captureOnCommitCallbacks(execute=True):
                projects.cancel_project(self.project, self.company)
        self.assertEqual(Project.objects.get(pk=self.project.pk).status, "cancelled")

    def test_no_funded_deposit_no_callback(self):
        with self.captureOnCommitCallbacks() as callbacks:
            projects.cancel_project(self.project, self.company)
        self.assertEqual(callbacks, [])


class EndpointTests(DepositBase):
    def setUp(self):
        super().setUp()
        self.row = self.funded_row()

    def test_report_only_when_forfeit_and_by_any_wallet(self):
        login(self.client, self.other)
        r = self.post("deposit_report").json()
        self.assertEqual(r["error"], "wrong_state")
        projects.apply(self.t1, self.freelance, "hi", [])
        self.age_applications(15)
        post_patch, get_patch = self.patched()
        with post_patch, get_patch, patch("payments.stellar.has_trustline", return_value=True):
            r = self.post("deposit_report").json()
        self.assertTrue(r["ok"], r)
        self.assertTrue(any("stellar.expert" in u for u in r["explorer_urls"]))
        self.assertEqual(ProjectDeposit.objects.get().status, "forfeited")

    def test_report_failure_answers_provider_and_retry_works(self):
        projects.apply(self.t1, self.freelance, "hi", [])
        self.age_applications(15)
        login(self.client, self.other)
        with patch("payments.stellar.has_trustline", return_value=False):
            r = self.post("deposit_report").json()
        self.assertEqual((r["ok"], r["error"]), (False, "provider"))
        self.assertIn("trustline", r["message"])

    def test_reclaim_only_for_the_company(self):
        Project.objects.filter(pk=self.project.pk).update(published_at=timezone.now() - timedelta(days=31))
        login(self.client, self.other)
        self.assertEqual(self.post("deposit_refund").json()["error"], "forbidden")
        login(self.client, self.company)
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            r = self.post("deposit_refund").json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(ProjectDeposit.objects.get().status, "refunded")

    def test_reclaim_refused_while_locked(self):
        login(self.client, self.company)
        r = self.post("deposit_refund").json()
        self.assertEqual(r["error"], "wrong_state")
        self.assertIn("cannot be reclaimed", r["message"])

    def test_anonymous_gets_401(self):
        r = self.post("deposit_report")
        self.assertEqual(r.status_code, 401)


# --- panel, /fonds/, dashboard ---------------------------------------------------------------------------


class PageTests(DepositBase):
    def page(self):
        return self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()

    def test_panel_due_for_the_company(self):
        login(self.client, self.company)
        html = self.page()
        self.assertIn('data-deposit-status="due"', html)
        self.assertIn("Publish the project (deposit 5.00 USDC)", html)
        self.assertIn("data-publish", html)
        self.assertIn("data-unpublished", html)
        self.assertIn("lowbid-deposit.js", html)
        self.assertIn("data-project-cancel", html)

    def test_panel_funded_shows_deadline_and_badge(self):
        self.funded_row()
        html = self.page()
        self.assertIn('data-deposit-status="funded"', html)
        self.assertIn("data-deposit-deadline", html)
        self.assertIn("Refundable if no application by", html)
        self.assertIn("data-deposit-badge", html)
        projects.apply(self.t1, self.freelance, "hi", [])
        self.assertIn("Choose a freelancer before", self.page())

    def test_report_button_for_any_wallet_when_forfeit(self):
        self.funded_row()
        projects.apply(self.t1, self.freelance, "hi", [])
        self.age_applications(15)
        login(self.client, self.other)
        html = self.page()
        self.assertIn("data-deposit-report", html)
        self.assertNotIn("data-deposit-refund", html)

    def test_cancel_confirm_states_the_outcome(self):
        self.funded_row()
        login(self.client, self.company)
        self.assertIn("is refunded to your wallet", self.page())
        projects.apply(self.t1, self.freelance, "hi", [])
        self.assertIn("goes to the guarantee fund", self.page())

    def test_direct_mode_single_line(self):
        with override_settings(LOWBID_PAYMENT_MODE="direct"):
            html = self.page()
        self.assertIn('data-deposit-status="direct"', html)
        self.assertIn("Direct mode: payment not protected.", html)
        self.assertNotIn("data-publish", html)

    def test_last_error_and_retry(self):
        row = self.funded_row()
        Project.objects.filter(pk=self.project.pk).update(published_at=timezone.now() - timedelta(days=31))
        ProjectDeposit.objects.filter(pk=row.pk).update(last_error="vendor said no")
        login(self.client, self.company)
        html = self.page()
        self.assertIn("vendor said no", html)
        self.assertIn("data-no-confirm", html)

    def test_fund_page(self):
        row = self.funded_row()
        ProjectDeposit.objects.filter(pk=row.pk).update(status="forfeited", resolve_tx_hash="e" * 64, settled_at=timezone.now())
        with patch("payments.stellar.asset_balance", return_value=Decimal("42.5")):
            html = self.client.get(reverse("payments:fund_page")).content.decode()
        self.assertEqual(reverse("payments:fund_page"), "/fonds/")
        self.assertIn("Money from ghost listings protects scammed freelancers.", html)
        self.assertIn("data-fund-balance", html)
        self.assertIn('data-fund-balance>42<span class="ui-dec">.50</span>', html)
        self.assertIn("Booking site", html)
        self.assertIn(stellar.explorer_tx_url("e" * 64), html)
        self.assertIn(stellar.explorer_account_url(FUND), html)

    def test_fund_page_with_horizon_down(self):
        with patch("payments.stellar.asset_balance", return_value=None):
            r = self.client.get(reverse("payments:fund_page"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Balance unavailable right now")

    def test_dashboard_todo_publish_and_reclaim(self):
        from dashboard.services import todo_items

        heads = [i["headline"] for i in todo_items(self.company)]
        self.assertIn('Publish "Booking site" (deposit 5.00 USDC)', heads)
        self.funded_row()
        Project.objects.filter(pk=self.project.pk).update(published_at=timezone.now() - timedelta(days=31))
        heads = [i["headline"] for i in todo_items(self.company)]
        self.assertIn('Reclaim my deposit for "Booking site"', heads)
        self.assertFalse(any(h.startswith("Publish") for h in heads))


# --- secrets never leak -----------------------------------------------------------------------------------


class SecretHygieneTests(DepositBase):
    def assertNoSecret(self, text: str):
        for secret in SECRETS:
            self.assertNotIn(secret, text)

    def test_logs_of_full_chains(self):
        row = self.funded_row()
        post_patch, get_patch = self.patched()
        with self.assertLogs("payments", level="DEBUG") as logs, post_patch, get_patch:
            deposits.refund(row)
            other = Project.objects.create(company=self.company, title="Other", description="x")
            row2 = self.funded_row(project=other)
            with patch("payments.stellar.has_trustline", return_value=True):
                deposits.forfeit(row2)  # verdict not consulted: the chain itself is under test
        self.assertNoSecret("\n".join(logs.output))
        for _, signed in self.tw.sent:  # nor a signed XDR body
            self.assertNotIn(signed, "\n".join(logs.output))

    def test_pages_and_json(self):
        self.funded_row()
        login(self.client, self.company)
        html = self.client.get(reverse("projects:project_detail", args=[self.project.pk])).content.decode()
        self.assertIn("window.LOWBID", html)
        self.assertNoSecret(html)
        with patch("payments.stellar.asset_balance", return_value=Decimal("1")):
            self.assertNoSecret(self.client.get(reverse("payments:fund_page")).content.decode())
        self.assertNoSecret(self.client.get(reverse("payments:deposit_pending", args=[self.project.pk]), **JSON).content.decode())
        self.assertNoSecret(self.post("deposit_refund").content.decode())
        projects.add_task(self.project, self.company, "API", "", "700", [])
        post_patch, get_patch = self.patched()
        with post_patch, get_patch:
            prep = self.post("deposit_prepare", step="deploy")
            sent = self.post("deposit_send", {"signed_xdr": sign(prep.json()["xdr"], self.company_kp)}, step="deploy")
        self.assertNoSecret(prep.content.decode() + sent.content.decode())

    def test_signer_errors_do_not_echo_the_value(self):
        from payments import signer

        with override_settings(LOWBID_PLATFORM_SECRET="SNOTAVALIDSECRETVALUE"), self.assertLogs("payments", level="DEBUG") as logs:
            with self.assertRaises(PaymentError) as ctx:
                signer.platform_keypair()
        self.assertNotIn("SNOTAVALIDSECRETVALUE", "\n".join(logs.output) + ctx.exception.message)


# --- system check -------------------------------------------------------------------------------------------


class SystemCheckTests(TestCase):
    def ids(self, **overrides):
        with override_settings(**{**DEPOSIT_SETTINGS, **overrides}):
            errors = check_deposit_keys()
        for e in errors:
            self.assertIsInstance(e, CheckMessage)
            for secret in SECRETS:
                self.assertNotIn(secret, e.msg)
        return [e.id for e in errors]

    def test_valid_configuration(self):
        self.assertEqual(self.ids(), [])

    def test_inactive_means_no_errors(self):
        self.assertEqual(self.ids(LOWBID_DEPOSIT_ENABLED=False, LOWBID_PLATFORM_SECRET=""), [])
        self.assertEqual(self.ids(LOWBID_PAYMENT_MODE="direct", LOWBID_PLATFORM_SECRET=""), [])

    def test_platform_secret_errors(self):
        self.assertEqual(self.ids(LOWBID_PLATFORM_SECRET=""), ["payments.W001"])
        self.assertEqual(self.ids(LOWBID_PLATFORM_SECRET="Sbogus"), ["payments.E002"])
        self.assertEqual(self.ids(LOWBID_PLATFORM_ADDRESS=Keypair.random().public_key), ["payments.E003"])

    def test_resolver_secret_errors(self):
        self.assertEqual(self.ids(LOWBID_DEPOSIT_RESOLVER_SECRET=""), ["payments.W004"])
        self.assertEqual(self.ids(LOWBID_DEPOSIT_RESOLVER_SECRET="Sbogus"), ["payments.E005"])
        self.assertEqual(self.ids(LOWBID_DEPOSIT_RESOLVER_SECRET=PLATFORM_KP.secret), ["payments.E006"])

    def test_fund_address_errors(self):
        self.assertEqual(self.ids(LOWBID_GUARANTEE_FUND_ADDRESS=""), ["payments.W007"])
        self.assertEqual(self.ids(LOWBID_GUARANTEE_FUND_ADDRESS="GBOGUS"), ["payments.E008"])
        self.assertEqual(self.ids(LOWBID_GUARANTEE_FUND_ADDRESS=PLATFORM_KP.public_key), ["payments.E009"])
