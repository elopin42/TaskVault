"""seed_demo: freelancer C and the trust-network graph (company → A, A recommends C, A → B)."""

import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from stellar_sdk import Keypair

from accounts.models import WalletUser
from network import services as network
from network.models import Follow, Recommendation
from projects.models import Application, Project, Task


def _seed() -> str:
    out = StringIO()
    call_command("seed_demo", "--flush", stdout=out)
    return out.getvalue()


class SeedNetworkTests(TestCase):
    def setUp(self):
        self.text = _seed()
        self.company = WalletUser.objects.get(display_name="Studio Nova (company)")
        self.a = WalletUser.objects.get(display_name="Yanis (freelancer A)")
        self.b = WalletUser.objects.get(display_name="Nora (freelancer B)")
        self.c = WalletUser.objects.get(display_name="Chloé (freelancer C)")
        pitch = Project.objects.get(title__startswith="Booking")
        self.t1, self.t2, self.t3 = list(pitch.tasks.order_by("position"))

    def test_five_wallets_and_the_graph(self):
        self.assertEqual(WalletUser.objects.count(), 5)
        self.assertTrue(Follow.objects.filter(follower=self.company, followed=self.a).exists())
        self.assertTrue(Follow.objects.filter(follower=self.a, followed=self.b).exists())
        self.assertEqual(Follow.objects.count(), 2)
        rec = Recommendation.objects.get()
        self.assertEqual((rec.author, rec.subject), (self.a, self.c))
        self.assertEqual(rec.message, "Chloé shipped our analytics dashboard in a week, clean Django and sharp charts.")

    def test_c_applies_to_t3(self):
        self.assertEqual(self.t3.title, "Dashboard")
        app = Application.objects.get(task=self.t3)
        self.assertEqual(app.freelancer, self.c)
        self.assertEqual(app.tags, ["django", "charts"])
        self.assertTrue(app.message)

    def test_t2_scores_unchanged(self):
        scores = {app.freelancer_id: f"{app.score:.1f}" for app in self.t2.applications.all()}
        self.assertEqual(scores, {self.a.pk: "90.0", self.b.pk: "20.0"})

    def test_stdout_mentions_c_and_the_network(self):
        self.assertIn("freelancer C", self.text)
        self.assertIn("company follows A, A recommends C, A follows B", self.text)
        self.assertIn("T2 scores", self.text)

    def test_flush_twice_is_idempotent(self):
        env = {
            name: Keypair.random().public_key
            for name in ("LOWBID_DEMO_CLIENT", "LOWBID_DEMO_FREELANCE1", "LOWBID_DEMO_FREELANCE2", "LOWBID_DEMO_FREELANCE3", "LOWBID_DEMO_ARBITER")
        }
        with mock.patch.dict(os.environ, env):
            _seed()
            wallets = WalletUser.objects.count()
            text = _seed()
        self.assertIn("follows=2", text)
        self.assertIn("recommendations=1", text)
        self.assertEqual(WalletUser.objects.count(), wallets)  # the pinned wallets are reused
        self.assertEqual(Project.objects.count(), 3)
        self.assertEqual(Task.objects.count(), 8)
        self.assertEqual(Application.objects.count(), 7)
        self.assertEqual(Follow.objects.count(), 2)
        self.assertEqual(Recommendation.objects.count(), 1)

    def test_signals_seen_by_the_company(self):
        sigs = network.signals(self.company, [self.a, self.b, self.c])
        self.assertEqual(sigs[self.c.pk].level, "strong")
        self.assertEqual(sigs[self.c.pk].label, "Yanis (freelancer A) recommends")
        self.assertEqual(sigs[self.b.pk].level, "weak")
        self.assertEqual(sigs[self.b.pk].label, "Followed by Yanis (freelancer A)")
        self.assertEqual(sigs[self.a.pk].level, "following")
