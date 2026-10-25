"""`seed_demo --flush`: the pitch state, the draft, and the food-truck showcase (change request + dispute)."""

import os
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from stellar_sdk import Keypair

from accounts.models import WalletUser
from payments import services as payment_services
from payments.models import Escrow

from .models import Application, Delivery, Dispute, Project, Rating, RevisionRequest, Task

ARBITER = Keypair.random().public_key
DEMO_ENV = ("LOWBID_DEMO_CLIENT", "LOWBID_DEMO_FREELANCE1", "LOWBID_DEMO_FREELANCE2", "LOWBID_DEMO_ARBITER")


class CleanDemoEnvMixin:
    """The seed reads LOWBID_DEMO_* from the environment (.env): ignore a developer's values here."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in DEMO_ENV:
            os.environ.pop(name, None)


@override_settings(LOWBID_DISPUTE_RESOLVER=ARBITER, LOWBID_PLATFORM_ADDRESS="", LOWBID_MAX_REVISIONS=2)
class SeedDemoTests(CleanDemoEnvMixin, TestCase):
    def seed(self) -> str:
        out = StringIO()
        call_command("seed_demo", "--flush", stdout=out)
        return out.getvalue()

    def test_seed_demo_builds_the_pitch_state(self):
        text = self.seed()
        self.assertIn("Demo data ready.", text)
        self.assertIn("freelancer A", text)
        self.assertEqual(Project.objects.count(), 3)
        self.assertEqual(WalletUser.objects.count(), 5)
        pitch = Project.objects.get(title__startswith="Booking")
        t1, t2, t3 = list(pitch.tasks.order_by("position"))
        self.assertEqual((t1.status, t2.status, t3.status), ("paid", "open", "open"))
        self.assertEqual(Rating.objects.get(task=t1).note, 5)
        escrow = Escrow.objects.get(task=t1)
        self.assertEqual((escrow.mode, escrow.status, len(escrow.payment_tx_hash)), ("direct", "paid", 64))
        self.assertIn("payment mode", text)
        self.assertIn("stellar.expert", text)
        scores = sorted(t2.applications.values_list("score", flat=True), reverse=True)
        self.assertEqual(scores, [Decimal("90.0"), Decimal("20.0")])
        self.assertEqual(pitch.status, Project.Status.FUNDED)
        draft = Project.objects.get(title__startswith="Brand")
        self.assertEqual(draft.status, Project.Status.DRAFT)
        self.assertEqual(draft.tasks.count(), 3)
        self.assertEqual(Application.objects.filter(task__project=draft).count(), 0)

    def test_change_request_task_is_delivered_again(self):
        self.seed()
        task = Task.objects.get(title="Menu page")
        self.assertEqual(task.status, Task.Status.DELIVERED)
        self.assertEqual(task.revision_count, 1)
        self.assertIsNotNone(task.delivered_at)
        self.assertEqual(task.assigned_to.display_name, "Nora (freelancer B)")
        deliveries = list(Delivery.objects.filter(task=task).order_by("created_at"))
        self.assertEqual(len(deliveries), 2)
        self.assertNotEqual(deliveries[0].delivery_hash, deliveries[1].delivery_hash)
        self.assertTrue(all(len(d.delivery_hash) == 40 and d.source_link for d in deliveries))
        self.assertEqual(task.delivery_hash, deliveries[1].delivery_hash)
        revision = RevisionRequest.objects.get(task=task)
        self.assertEqual(revision.message, "Please fix the mobile layout on the menu page.")
        self.assertLess(deliveries[0].created_at, revision.created_at)
        escrow = Escrow.objects.get(task=task)
        self.assertEqual((escrow.mode, escrow.status), ("direct", "delivered"))
        self.assertTrue(escrow.delivery_note.startswith(f"git:{task.delivery_hash} "))
        self.assertEqual(Rating.objects.filter(task=task).count(), 0)

    def test_disputed_task_has_an_escrow_row_with_demo_hashes(self):
        text = self.seed()
        task = Task.objects.get(title="Order tracking")
        self.assertEqual(task.status, Task.Status.DISPUTED)
        dispute = Dispute.objects.get(task=task)
        self.assertEqual(dispute.reason, "The demo does not match the agreed scope.")
        self.assertEqual(dispute.opened_by, task.project.company)
        self.assertIsNone(dispute.resolved_at)
        escrow = Escrow.objects.get(task=task)
        self.assertEqual((escrow.mode, escrow.status), ("escrow", "disputed"))
        self.assertTrue(escrow.contract_id.startswith("C"))
        self.assertEqual(len(escrow.contract_id), 56)
        for field in ("deploy_tx_hash", "fund_tx_hash", "deliver_tx_hash", "dispute_tx_hash"):
            self.assertEqual(len(getattr(escrow, field)), 64, field)
        for field in ("funded_at", "delivered_at", "disputed_at"):
            self.assertIsNotNone(getattr(escrow, field), field)
        self.assertEqual(escrow.resolver_address, ARBITER)
        self.assertEqual(escrow.payer_address, task.project.company.stellar_address)
        self.assertEqual(escrow.payee_address, task.assigned_to.stellar_address)
        self.assertEqual(Delivery.objects.get(task=task).tx_hash, escrow.deliver_tx_hash)
        self.assertTrue(escrow.holds_funds)
        # The arbiter wallet IS the configured resolver, so /litiges/ opens for it.
        arbiter = WalletUser.objects.get(stellar_address=ARBITER)
        self.assertTrue(payment_services.is_arbiter(arbiter))
        self.assertIn("/litiges/ opens for the arbiter wallet", text)

    def test_food_truck_project_status(self):
        """The disputed escrow holds its funds, but the Menu page's direct row holds nothing until it is
        paid, so sync_project_status keeps the project in draft (Funded means every assigned task covered)."""
        self.seed()
        project = Project.objects.get(title="Mobile app for a food truck")
        self.assertEqual(project.status, Project.Status.DRAFT)
        self.assertEqual(payment_services.sync_project_status(project).status, Project.Status.DRAFT)
        holds = {e.task.title: e.holds_funds for e in Escrow.objects.filter(task__project=project).select_related("task")}
        self.assertEqual(holds, {"Menu page": False, "Order tracking": True})

    def test_seed_demo_is_repeatable_with_flush(self):
        self.seed()
        text = self.seed()
        self.assertIn("flushed projects=3 tasks=8 applications=7 ratings=1 deliveries=4 revisions=1 disputes=1 escrows=3", text)
        self.assertEqual(Project.objects.count(), 3)
        self.assertEqual(Task.objects.count(), 8)
        self.assertEqual(Delivery.objects.count(), 4)
        self.assertEqual(RevisionRequest.objects.count(), 1)
        self.assertEqual(Dispute.objects.count(), 1)
        self.assertEqual(Escrow.objects.count(), 3)
        self.assertEqual(sorted(Task.objects.values_list("status", flat=True)).count("paid"), 1)


@override_settings(LOWBID_DISPUTE_RESOLVER="", LOWBID_PLATFORM_ADDRESS="")
class SeedDemoWithoutArbiterTests(CleanDemoEnvMixin, TestCase):
    def test_hint_when_no_resolver_is_configured(self):
        out = StringIO()
        call_command("seed_demo", "--flush", stdout=out)
        self.assertIn("/litiges/ is visible only to the wallet equal to LOWBID_DISPUTE_RESOLVER", out.getvalue())
