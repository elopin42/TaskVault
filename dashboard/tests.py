from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from auctions import services as auctions
from auctions.models import Need
from payments.models import Escrow

from . import services


def make_wallet(name: str = "") -> WalletUser:
    return WalletUser.objects.create(stellar_address=Keypair.random().public_key, display_name=name)


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


def make_need(owner: WalletUser, title: str, **kw) -> Need:
    fields = {
        "description": "Une description.",
        "budget_max": Decimal("500"),
        "delay_max_days": 10,
        "tags": ["django", "stellar"],
        "bidding_ends_at": timezone.now() + timedelta(hours=2),
    }
    fields.update(kw)
    return Need.objects.create(client=owner, title=title, **fields)


class ScenarioTest(TestCase):
    """One client with needs in every state, two freelancers with active / outbid / won / lost bids."""

    def setUp(self):
        self.client_w = make_wallet("Claire")
        self.f1 = make_wallet("Yanis")
        self.f2 = make_wallet("Nora")

        # open need, f1 leads then f2 beats them → f1 is outbid-by-price (still `active`, but not best)
        self.open = make_need(self.client_w, "Besoin ouvert")
        auctions.place_bid(self.open, self.f1, "450", 8, ["django"], "")
        auctions.place_bid(self.open, self.f2, "400", 9, ["stellar"], "")

        # open need with no bid, ending in 30 minutes → "bientôt fermé" (wait)
        self.soon = make_need(self.client_w, "Besoin bientôt fermé", bidding_ends_at=timezone.now() + timedelta(minutes=30))

        # closed need with bids → the client must choose
        self.closed = make_need(self.client_w, "Besoin terminé")
        auctions.place_bid(self.closed, self.f1, "300", 5, [], "")
        auctions.close_bidding_now(self.closed, self.client_w)

        # awarded need (f2 won, f1 lost) with a direct-mode escrow still `created`
        self.awarded = make_need(self.client_w, "Besoin attribué")
        auctions.place_bid(self.awarded, self.f1, "200", 5, [], "")
        won_bid = auctions.place_bid(self.awarded, self.f2, "150", 4, ["django"], "")
        auctions.close_bidding_now(self.awarded, self.client_w)
        auctions.award(self.awarded, won_bid, self.client_w)
        self.escrow = Escrow.objects.create(
            need=self.awarded,
            mode=Escrow.Mode.DIRECT,
            amount=Decimal("150"),
            payer_address=self.client_w.stellar_address,
            payee_address=self.f2.stellar_address,
        )

        # paid need (released) for the totals
        self.paid = make_need(self.client_w, "Besoin payé")
        paid_bid = auctions.place_bid(self.paid, self.f2, "100", 3, [], "")
        auctions.close_bidding_now(self.paid, self.client_w)
        auctions.award(self.paid, paid_bid, self.client_w)
        Need.objects.filter(pk=self.paid.pk).update(status=Need.Status.RELEASED)
        Escrow.objects.create(
            need=self.paid,
            mode=Escrow.Mode.DIRECT,
            amount=Decimal("100"),
            payer_address=self.client_w.stellar_address,
            payee_address=self.f2.stellar_address,
            status=Escrow.Status.PAID,
            payment_tx_hash="a" * 64,
            released_at=timezone.now(),
        )


class TodoTests(ScenarioTest):
    def test_client_todo(self):
        items = services.todo_items(self.client_w)
        headlines = [it["headline"] for it in items]
        self.assertTrue(any("Choisir un freelance" in h and "Besoin terminé" in h for h in headlines))
        self.assertTrue(any("Payer le freelance" in h and "Besoin attribué" in h for h in headlines))
        self.assertTrue(any("Aucune offre" in h and "bientôt fermé" in h for h in headlines))
        tones = [it["tone"] for it in items]
        self.assertEqual(tones, sorted(tones, key=lambda t: 0 if t == "act" else 1), "act items come first")
        for it in items:
            self.assertEqual(set(it), {"tone", "kicker", "headline", "body", "href", "cta", "icon", "when"})
            self.assertTrue(it["href"].startswith("/besoins/"))

    def test_freelancer_todo(self):
        f1 = services.todo_items(self.f1)
        self.assertTrue(any(it["kicker"] == "Offre dépassée" and it["tone"] == "act" for it in f1), f1)
        self.assertFalse(any(it["kicker"] == "Enchère gagnée" for it in f1))
        f2 = services.todo_items(self.f2)
        won = [it for it in f2 if it["kicker"] == "Enchère gagnée"]
        self.assertEqual(len(won), 1)
        self.assertEqual(won[0]["tone"], "act")
        self.assertIn("Déclarer la livraison", won[0]["headline"])
        self.assertFalse(any(it["kicker"] == "Offre dépassée" for it in f2), "f2 leads on the open need")

    def test_todo_waits_when_the_other_party_must_act(self):
        self.escrow.status = Escrow.Status.DELIVERED
        self.escrow.save(update_fields=["status"])
        Need.objects.filter(pk=self.awarded.pk).update(status=Need.Status.DELIVERED)
        f2 = [it for it in services.todo_items(self.f2) if it["kicker"] == "Enchère gagnée"]
        self.assertEqual(f2[0]["tone"], "wait")
        client = [it for it in services.todo_items(self.client_w) if "Besoin attribué" in it["headline"]]
        self.assertEqual(client[0]["tone"], "act")
        self.assertIn("Valider et payer", client[0]["headline"])


class StatsTests(ScenarioTest):
    def test_client_stats(self):
        s = services.client_stats(self.client_w)
        self.assertEqual(s["total"], 5)
        self.assertEqual(s["open"], 2)
        self.assertEqual(s["to_choose"], 1)
        self.assertEqual(s["awarded"], 2)  # awarded + released
        self.assertEqual(s["paid"], 1)
        self.assertEqual(s["committed_usdc"], Decimal("250"))
        self.assertEqual(s["bids_received"], 6)

    def test_freelancer_stats(self):
        s2 = services.freelancer_stats(self.f2)
        self.assertEqual(s2["active"], 1)
        self.assertEqual(s2["leading"], 1)
        self.assertEqual(s2["won"], 2)
        self.assertEqual(s2["lost"], 0)
        self.assertEqual(s2["earned_usdc"], Decimal("100"))
        self.assertEqual(s2["win_rate"], 100)
        s1 = services.freelancer_stats(self.f1)
        self.assertEqual(s1["active"], 1)
        self.assertEqual(s1["leading"], 0)
        self.assertEqual(s1["won"], 0)
        self.assertEqual(s1["lost"], 1)
        self.assertEqual(s1["earned_usdc"], Decimal("0"))
        self.assertEqual(s1["win_rate"], 0)
        self.assertIsNone(services.freelancer_stats(self.client_w)["win_rate"])

    def test_recent_activity_is_newest_first_and_merged(self):
        events = services.recent_activity(self.client_w)
        self.assertTrue(events)
        whens = [e["when"] for e in events]
        self.assertEqual(whens, sorted(whens, reverse=True))
        texts = " | ".join(e["text"] for e in events)
        self.assertIn("Besoin publié", texts)
        self.assertIn("retenue", texts)
        self.assertIn("Paiement envoyé", texts)
        for e in events:
            self.assertEqual(set(e), {"when", "icon", "text", "href", "tone"})
        self.assertLessEqual(len(services.recent_activity(self.client_w, limit=3)), 3)

    def test_profile_stats(self):
        s = services.profile_stats(self.client_w)
        self.assertEqual(s["needs_posted"], 5)
        self.assertEqual(s["needs_completed"], 1)
        self.assertEqual(s["bids_placed"], 0)
        s2 = services.profile_stats(self.f2)
        self.assertEqual(s2["bids_placed"], 3)
        self.assertEqual(s2["bids_won"], 2)
        self.assertEqual(len(s2["won_bids"]), 2)


class HomeViewTests(ScenarioTest):
    def test_anonymous_is_redirected_to_landing(self):
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_home_renders_sections(self):
        login(self.client, self.client_w)
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for marker in ("À faire", "Activité récente", "Côté client", "Côté freelance", "Choisir un freelance", "ui-timeline", "Claire"):
            self.assertIn(marker, html)
        self.assertNotIn("{%", html)
        self.assertNotIn("{{", html)

    def test_home_without_anything_shows_done_card(self):
        fresh = make_wallet()
        login(self.client, fresh)
        r = self.client.get(reverse("dashboard:home"))
        self.assertContains(r, "Rien à faire pour l’instant")
        self.assertContains(r, "Aucune activité")

    def test_navbar_links_to_dashboard(self):
        login(self.client, self.client_w)
        r = self.client.get(reverse("auctions:need_list"))
        self.assertContains(r, reverse("dashboard:home"))
        self.assertContains(r, reverse("dashboard:profile", kwargs={"address": self.client_w.stellar_address}))

    def test_landing_connect_button_targets_dashboard(self):
        r = self.client.get(reverse("core:landing"))
        self.assertContains(r, f'data-next="{reverse("dashboard:home")}"')
        r = self.client.get(reverse("core:landing") + "?next=/mes-encheres/")
        self.assertContains(r, 'data-next="/mes-encheres/"')


class ProfileViewTests(ScenarioTest):
    def url(self, wallet):
        return reverse("dashboard:profile", kwargs={"address": wallet.stellar_address})

    def test_unknown_wallet_404(self):
        r = self.client.get(reverse("dashboard:profile", kwargs={"address": Keypair.random().public_key}))
        self.assertEqual(r.status_code, 404)

    def test_public_profile_renders_without_login(self):
        r = self.client.get(self.url(self.f2))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Nora", html)
        self.assertIn("Enchères gagnées", html)
        self.assertIn("Besoin attribué", html)
        self.assertNotIn("Éditer mon nom", html)
        r = self.client.get(self.url(self.client_w))
        self.assertContains(r, "Besoin ouvert")
        self.assertContains(r, "need-card")

    def test_owner_sees_and_uses_the_name_form(self):
        login(self.client, self.f1)
        r = self.client.get(self.url(self.f1))
        self.assertContains(r, "Éditer mon nom")
        r = self.client.post(self.url(self.f1), {"display_name": "  Yanis Dev  "}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.display_name, "Yanis Dev")
        self.assertContains(r, "Nom affiché mis à jour")

    def test_name_is_truncated_to_80_chars(self):
        login(self.client, self.f1)
        self.client.post(self.url(self.f1), {"display_name": "x" * 100})
        self.f1.refresh_from_db()
        self.assertEqual(len(self.f1.display_name), 80)

    def test_other_wallet_cannot_rename(self):
        login(self.client, self.f1)
        r = self.client.post(self.url(self.f2), {"display_name": "Pirate"})
        self.assertEqual(r.status_code, 403)
        r = self.client.logout() or self.client.post(self.url(self.f2), {"display_name": "Pirate"})
        self.assertEqual(r.status_code, 403)
        self.f2.refresh_from_db()
        self.assertEqual(self.f2.display_name, "Nora")
