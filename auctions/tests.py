from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser

from . import services
from .models import Bid, Need
from .scoring import normalise_weights, rank_bids, score_bid
from .services import BidError, NeedError

JSON = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "fetch"}


def make_wallet(name: str = "") -> WalletUser:
    return WalletUser.objects.create(stellar_address=Keypair.random().public_key, display_name=name)


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


def make_need(client_wallet: WalletUser, **kw) -> Need:
    fields = {
        "title": "Landing page Django + Stellar",
        "description": "Une landing page.",
        "budget_max": Decimal("500"),
        "delay_max_days": 10,
        "tags": ["django", "stellar", "ui"],
        "bidding_ends_at": timezone.now() + timedelta(hours=2),
    }
    fields.update(kw)
    return Need.objects.create(client=client_wallet, **fields)


class BaseAuctionTest(TestCase):
    def setUp(self):
        self.owner = make_wallet("client")
        self.f1 = make_wallet("f1")
        self.f2 = make_wallet("f2")
        self.need = make_need(self.owner)

    def bid(self, freelancer, price, delay=8, tags=("django", "ui"), message=""):
        return services.place_bid(self.need, freelancer, price, delay, list(tags), message)


# --- templates ---------------------------------------------------------------------

class DetailTemplateTests(BaseAuctionTest):
    def test_no_template_syntax_leaks_into_the_page(self):
        """`{# #}` comments are single-line in Django: a multi-line one renders as text (seen on _bids_list)."""
        self.bid(self.f1, "450")
        self.bid(self.f2, "419.5", delay=9, tags=("ui",))
        session = self.client.session
        session["wallet_user_id"] = self.f1.pk
        session["wallet_address"] = self.f1.stellar_address
        session.save()
        html = self.client.get(reverse("auctions:need_detail", args=[self.need.pk])).content.decode()
        for token in ("{#", "#}", "{%", "%}", "{{", "}}"):
            self.assertNotIn(token, html, token)
        fragment = self.client.get(reverse("auctions:need_bids_json", args=[self.need.pk])).json()["html"]
        self.assertNotIn("{#", fragment)
        # Numbers the JS parses must be plain decimals with a dot: neither the 7-place Decimal repr
        # nor the fr-localised "419,5000000" (LANGUAGE_CODE=fr localises bare {{ decimal }}).
        self.assertIn('max="419.5"', html)
        self.assertIn('placeholder="419.5"', html)
        self.assertIn('data-price="419.5"', html)
        self.assertIn('data-price="450"', html)
        self.assertNotIn("419,5", html)
        self.assertNotIn("0000000", html.split("LOWBID_NEED")[0])


# --- services.place_bid (R1–R7) --------------------------------------------------

class PlaceBidTests(BaseAuctionTest):
    def test_first_bid_is_active_and_sets_best_price(self):
        bid = self.bid(self.f1, "450")
        self.assertEqual(bid.status, Bid.Status.ACTIVE)
        self.assertEqual(bid.price, Decimal("450"))
        self.assertEqual(self.need.best_price, Decimal("450"))
        self.assertEqual(self.need.current_price, Decimal("450"))

    def test_current_price_falls_back_to_budget(self):
        self.assertIsNone(self.need.best_price)
        self.assertEqual(self.need.current_price, Decimal("500"))

    def test_r1_not_strictly_lower_is_refused(self):
        self.bid(self.f1, "450")
        for price in ("450", "460"):
            with self.assertRaises(BidError) as ctx:
                self.bid(self.f2, price)
            self.assertEqual(ctx.exception.code, "not_lower")
        self.assertIn("450", ctx.exception.message)

    def test_r2_over_budget(self):
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "500.01")
        self.assertEqual(ctx.exception.code, "over_budget")
        self.bid(self.f1, "500")  # price == budget is allowed (≤)

    def test_r3_over_delay(self):
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "400", delay=11)
        self.assertEqual(ctx.exception.code, "over_delay")

    def test_r4_closed_by_timer_and_by_status(self):
        self.need.bidding_ends_at = timezone.now() - timedelta(seconds=1)
        self.need.save()
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "400")
        self.assertEqual(ctx.exception.code, "closed")
        self.need.bidding_ends_at = timezone.now() + timedelta(hours=1)
        self.need.status = Need.Status.CANCELLED
        self.need.save()
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "400")
        self.assertEqual(ctx.exception.code, "closed")

    def test_r5_own_need(self):
        with self.assertRaises(BidError) as ctx:
            self.bid(self.owner, "400")
        self.assertEqual(ctx.exception.code, "own_need")

    def test_bad_tags_and_normalisation(self):
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "400", tags=("a", "b", "c", "d"))
        self.assertEqual(ctx.exception.code, "bad_tags")
        self.assertEqual(services.clean_tags("Django, STELLAR  ui, django"), ["django", "stellar", "ui"])
        self.assertEqual(services.clean_tags(["Soroban ", "  "]), ["soroban"])
        self.assertEqual(services.clean_tags(None), [])

    def test_r7_invalid_price_or_delay(self):
        for price in ("0", "-5", "abc", "1.12345678"):
            with self.assertRaises(BidError, msg=price) as ctx:
                self.bid(self.f1, price)
            self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "400", delay=0)
        self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(self.bid(self.f1, "400.1234567").price, Decimal("400.1234567"))

    def test_r6_rebid_replaces_own_active_bid(self):
        first = self.bid(self.f1, "450")
        second = self.bid(self.f1, "430")
        first.refresh_from_db()
        self.assertEqual(first.status, Bid.Status.OUTBID)
        self.assertEqual(second.status, Bid.Status.ACTIVE)
        self.assertEqual(self.need.bids.filter(freelancer=self.f1, status="active").count(), 1)
        self.assertEqual(self.need.bids_count, 1)  # outbid rows do not count
        # R6: not lower than my own active bid → refused, the old one stays active.
        with self.assertRaises(BidError) as ctx:
            self.bid(self.f1, "440")
        self.assertEqual(ctx.exception.code, "not_lower")
        second.refresh_from_db()
        self.assertEqual(second.status, Bid.Status.ACTIVE)

    def test_descending_sequence_keeps_lowest_consistent(self):
        self.bid(self.f1, "450")
        self.bid(self.f2, "400")
        with self.assertRaises(BidError):
            self.bid(self.f1, "420")  # lower than my own, not lower than the current lowest
        self.bid(self.f1, "390")
        self.assertEqual(self.need.best_price, Decimal("390"))
        self.assertEqual(self.need.bids_count, 2)
        self.assertEqual(self.need.bids.filter(status="outbid").count(), 1)

    def test_one_active_bid_per_freelancer_constraint(self):
        self.bid(self.f1, "450")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Bid.objects.create(need=self.need, freelancer=self.f1, price="100", delay_days=1)
        # A second non-active row is fine (history).
        Bid.objects.create(need=self.need, freelancer=self.f1, price="100", delay_days=1, status="lost")


# --- need lifecycle -------------------------------------------------------------------

class NeedLifecycleTests(BaseAuctionTest):
    def test_close_expired_flips_only_expired_open_needs(self):
        expired = make_need(self.owner, bidding_ends_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(expired.effective_status(), "closed")  # lazy, before any write
        self.assertEqual(expired.status, "open")
        self.assertEqual(Need.objects.close_expired(), 1)
        expired.refresh_from_db()
        self.need.refresh_from_db()
        self.assertEqual(expired.status, "closed")
        self.assertEqual(self.need.status, "open")
        self.assertTrue(self.need.is_bidding_open())
        self.assertFalse(expired.is_bidding_open())

    def test_close_now_client_only(self):
        with self.assertRaises(NeedError) as ctx:
            services.close_bidding_now(self.need, self.f1)
        self.assertEqual(ctx.exception.code, "forbidden")
        with self.assertRaises(NeedError):
            services.close_bidding_now(self.need, None)
        need = services.close_bidding_now(self.need, self.owner)
        self.assertEqual(need.status, "closed")
        self.assertLessEqual(need.bidding_ends_at, timezone.now())
        with self.assertRaises(NeedError) as ctx:
            services.close_bidding_now(need, self.owner)
        self.assertEqual(ctx.exception.code, "not_open")

    def test_award_only_when_closed(self):
        bid = self.bid(self.f1, "450")
        with self.assertRaises(NeedError) as ctx:
            services.award(self.need, bid, self.owner)
        self.assertEqual(ctx.exception.code, "not_closed")

    def test_award_only_by_client(self):
        bid = self.bid(self.f1, "450")
        services.close_bidding_now(self.need, self.owner)
        with self.assertRaises(NeedError) as ctx:
            services.award(self.need, bid, self.f1)
        self.assertEqual(ctx.exception.code, "forbidden")

    def test_award_sets_won_lost_and_keeps_outbid(self):
        old = self.bid(self.f1, "450")
        mine = self.bid(self.f1, "440")
        other = self.bid(self.f2, "400")
        # Timer ran out but close_expired() has not run: award must still work (lazy status).
        Need.objects.filter(pk=self.need.pk).update(bidding_ends_at=timezone.now() - timedelta(seconds=1))
        self.need.refresh_from_db()
        need = services.award(self.need, mine, self.owner)  # R9: not the cheapest, still allowed
        old.refresh_from_db()
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(need.status, "awarded")
        self.assertEqual(need.winning_bid_id, mine.pk)
        self.assertIsNotNone(need.awarded_at)
        self.assertEqual(mine.status, "won")
        self.assertEqual(other.status, "lost")
        self.assertEqual(old.status, "outbid")
        self.assertEqual(mine.won_need, need)

    def test_award_refuses_outbid_bid(self):
        old = self.bid(self.f1, "450")
        self.bid(self.f1, "440")
        services.close_bidding_now(self.need, self.owner)
        with self.assertRaises(NeedError) as ctx:
            services.award(self.need, old, self.owner)
        self.assertEqual(ctx.exception.code, "bad_bid")

    def test_cancel_before_funded_only(self):
        with self.assertRaises(NeedError):
            services.cancel(self.need, self.f1)
        need = services.cancel(self.need, self.owner)
        self.assertEqual(need.status, "cancelled")
        funded = make_need(self.owner, status=Need.Status.FUNDED)
        with self.assertRaises(NeedError) as ctx:
            services.cancel(funded, self.owner)
        self.assertEqual(ctx.exception.code, "too_late")


# --- scoring ---------------------------------------------------------------------------

class ScoringTests(TestCase):
    def setUp(self):
        self.owner = make_wallet()
        self.need = make_need(self.owner)  # 500 USDC, 10 days, [django, stellar, ui]
        self.a = Bid(need=self.need, freelancer=make_wallet(), price=Decimal("450"), delay_days=8, tags=["django", "ui"])
        self.b = Bid(need=self.need, freelancer=make_wallet(), price=Decimal("380"), delay_days=12, tags=["stellar"])

    def test_worked_example_default_weights(self):
        a = score_bid(self.a, self.need)
        b = score_bid(self.b, self.need)
        self.assertAlmostEqual(a["price_part"], 4.0, places=6)
        self.assertAlmostEqual(a["delay_part"], 6.0, places=6)
        self.assertAlmostEqual(a["skills_part"], 20.0, places=6)
        self.assertAlmostEqual(a["total"], 30.0, places=6)
        self.assertAlmostEqual(b["price_part"], 9.6, places=6)
        self.assertEqual(b["delay_part"], 0.0)  # clamped: 1 - 12/10 < 0
        self.assertAlmostEqual(b["skills_part"], 10.0, places=6)
        self.assertAlmostEqual(b["total"], 19.6, places=6)

    def test_worked_example_reweighted_70_10_20(self):
        w = normalise_weights(70, 10, 20)
        self.assertEqual(w, (70, 10, 20))
        self.assertAlmostEqual(score_bid(self.a, self.need, w)["total"], 22.3, places=1)
        self.assertAlmostEqual(score_bid(self.b, self.need, w)["total"], 23.5, places=1)

    def test_no_requested_tags_makes_skills_neutral(self):
        self.need.tags = []
        self.assertEqual(score_bid(self.b, self.need)["skills_part"], 30.0)

    def test_rank_order_and_tie_breaks(self):
        f1, f2, f3 = make_wallet(), make_wallet(), make_wallet()
        # Same score (same price, delay, tags): the earlier bid wins the tie.
        early = Bid.objects.create(need=self.need, freelancer=f1, price="400", delay_days=8, tags=["django"])
        late = Bid.objects.create(need=self.need, freelancer=f2, price="400", delay_days=8, tags=["django"], status="lost")
        # Different score but tie-break on price: cheaper + no tags vs pricier + full match.
        cheap = Bid.objects.create(need=self.need, freelancer=f3, price="250", delay_days=10, tags=[])
        outbid = Bid.objects.create(need=self.need, freelancer=f3, price="450", delay_days=5, tags=["django", "stellar", "ui"], status="outbid")
        ranked = rank_bids(self.need)
        ids = [b.pk for b, _ in ranked]
        self.assertNotIn(outbid.pk, ids)
        # cheap: 40*0.5 + 0 + 0 = 20 ; early/late: 40*0.2 + 30*0.2 + 10 = 24
        self.assertEqual(ids, [early.pk, late.pk, cheap.pk])
        # A pure tie between different prices: cheaper first.
        self.need.tags = []
        x = Bid.objects.create(need=self.need, freelancer=make_wallet(), price="300", delay_days=10)  # 40*0.4 + 0 + 30 = 46
        y = Bid.objects.create(need=self.need, freelancer=make_wallet(), price="350", delay_days=9)  # 40*0.3 + 30*0.1 + 30 = 45
        ranked = rank_bids(self.need, bids=[y, x])
        self.assertEqual([b.pk for b, _ in ranked][:2], [x.pk, y.pk])

    def test_normalise_weights(self):
        self.assertEqual(normalise_weights(40, 30, 30), (40, 30, 30))
        self.assertEqual(sum(normalise_weights(1, 1, 1)), 100)
        self.assertEqual(normalise_weights(1, 1, 1), (34, 33, 33))
        self.assertEqual(normalise_weights(200, 0, 0), (100, 0, 0))
        self.assertEqual(normalise_weights(2, 1, 1), (50, 25, 25))
        for bad in [("x", 1, 1), (None, None, None), (0, 0, 0), (-1, 50, 51)]:
            self.assertEqual(normalise_weights(*bad), (40, 30, 30), bad)


# --- pages & JSON ------------------------------------------------------------------------

class PageTests(BaseAuctionTest):
    def detail(self, **params):
        return self.client.get(reverse("auctions:need_detail", args=[self.need.pk]), params)

    def test_need_list_public_with_tabs_and_tag_filter(self):
        make_need(self.owner, title="Vieux besoin", bidding_ends_at=timezone.now() - timedelta(hours=1), tags=["rust"])
        resp = self.client.get(reverse("auctions:need_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.need.title)
        self.assertNotContains(resp, "Vieux besoin")
        self.assertContains(resp, 'data-ends-at="')
        resp = self.client.get(reverse("auctions:need_list") + "?tab=closed")
        self.assertContains(resp, "Vieux besoin")
        self.assertNotContains(resp, self.need.title)
        resp = self.client.get(reverse("auctions:need_list") + "?tab=all&tag=rust")
        self.assertContains(resp, "Vieux besoin")
        self.assertNotContains(resp, self.need.title)
        self.assertEqual(self.client.get(reverse("auctions:need_list") + "?tab=all").context["needs"].__len__(), 2)

    def test_need_create_requires_wallet(self):
        resp = self.client.get(reverse("auctions:need_create"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/?next=/besoins/nouveau/"))
        resp = self.client.post(reverse("auctions:need_create"), {}, **JSON)
        self.assertEqual(resp.status_code, 401)

    def test_need_create_flow(self):
        login(self.client, self.owner)
        resp = self.client.get(reverse("auctions:need_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'value="5"')
        self.assertContains(self.client.get(reverse("auctions:need_create") + "?demo=1"), 'value="5"')
        data = {
            "title": "Dashboard analytics",
            "description": "Un tableau de bord.",
            "budget_max": "300",
            "delay_max_days": "7",
            "tags": "React, API, react",
            "duration": "5",  # demo value accepted even without ?demo=1
        }
        before = timezone.now()
        resp = self.client.post(reverse("auctions:need_create"), data)
        need = Need.objects.get(title="Dashboard analytics")
        self.assertRedirects(resp, reverse("auctions:need_detail", args=[need.pk]))
        self.assertEqual(need.client, self.owner)
        self.assertEqual(need.tags, ["react", "api"])
        self.assertEqual(need.status, "open")
        delta = need.bidding_ends_at - before
        self.assertTrue(timedelta(minutes=4, seconds=50) < delta <= timedelta(minutes=5, seconds=10), delta)
        # Validation errors stay on the form.
        bad = dict(data, tags="a,b,c,d", budget_max="0", duration="999")
        resp = self.client.post(reverse("auctions:need_create"), bad)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Au plus 3 compétences")
        self.assertContains(resp, "strictement positif")
        self.assertEqual(Need.objects.filter(title="Dashboard analytics").count(), 1)

    def test_detail_anonymous_shows_connect_cta(self):
        resp = self.detail()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "data-wallet-connect")
        self.assertContains(resp, f'data-next="/besoins/{self.need.pk}/"')
        self.assertNotContains(resp, 'id="bid-form"')
        self.assertEqual(self.client.get(reverse("auctions:need_detail", args=[9999])).status_code, 404)

    def test_detail_freelancer_sees_form_and_best_price_badge(self):
        self.bid(self.f2, "450")
        login(self.client, self.f1)
        resp = self.detail()
        self.assertContains(resp, 'id="bid-form"')
        self.assertContains(resp, "Meilleur prix")
        self.assertNotContains(resp, "Recommandé")
        self.assertNotContains(resp, "data-need-close")
        self.assertContains(resp, "450.00 USDC")  # the cap hint

    def test_detail_client_open_closed_awarded(self):
        login(self.client, self.owner)
        resp = self.detail()
        self.assertContains(resp, "data-need-close")
        self.assertContains(resp, "data-need-cancel")
        self.assertNotContains(resp, 'id="bid-form"')
        self.assertNotContains(resp, 'id="weights-panel"')

        bid = self.bid(self.f1, "450")
        self.bid(self.f2, "400", delay=9, tags=["stellar"])
        services.close_bidding_now(self.need, self.owner)
        resp = self.detail()
        self.assertContains(resp, 'id="weights-panel"')
        self.assertContains(resp, "Recommandé")
        self.assertEqual(resp.content.decode().count('data-choose="'), 2)  # Choisir on EVERY row
        self.assertNotContains(resp, "data-need-close")
        # Weights from the query string drive the server-side ranking.
        resp = self.detail(wp=100, wd=0, ws=0)
        self.assertEqual(resp.context["weights"], (100, 0, 0))
        self.assertEqual(resp.context["rows"][0]["bid"].freelancer, self.f2)
        self.assertEqual(self.detail().context["rows"][0]["bid"], bid)

        services.award(self.need, bid, self.owner)
        resp = self.detail()
        self.assertContains(resp, 'id="escrow-panel"')
        self.assertContains(resp, 'id="paiement"')  # payments panel (title depends on LOWBID_PAYMENT_MODE)
        self.assertContains(resp, "Retenue")
        self.assertContains(resp, "Non retenue")
        self.assertNotContains(resp, 'data-choose="')
        self.assertEqual(resp.context["winning_bid"], bid)

    def test_bid_create_json(self):
        url = reverse("auctions:bid_create", args=[self.need.pk])
        resp = self.client.post(url, {"price": "450"}, content_type="application/json", **JSON)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"], "wallet_required")
        login(self.client, self.f1)
        self.assertEqual(self.client.get(url, **JSON).status_code, 405)
        body = {"price": "450", "delay_days": 8, "tags": ["django", "ui"], "message": "Bonjour"}
        resp = self.client.post(url, body, content_type="application/json", **JSON)
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["bid"]["price"], "450")
        self.assertEqual(data["best_price"], "450")
        login(self.client, self.f2)
        resp = self.client.post(url, dict(body, price="450"), content_type="application/json", **JSON)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "not_lower")
        self.assertIn("450", resp.json()["message"])
        # Classic form-encoded POST also works.
        resp = self.client.post(url, {"price": "440", "delay_days": "9", "tags": "stellar", "message": ""}, **JSON)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Bid.objects.get(freelancer=self.f2).tags, ["stellar"])
        login(self.client, self.owner)
        resp = self.client.post(url, body, content_type="application/json", **JSON)
        self.assertEqual(resp.json()["error"], "own_need")

    def test_close_award_cancel_json(self):
        bid = self.bid(self.f1, "450")
        close_url = reverse("auctions:need_close", args=[self.need.pk])
        award_url = reverse("auctions:need_award", args=[self.need.pk, bid.pk])
        cancel_url = reverse("auctions:need_cancel", args=[self.need.pk])

        login(self.client, self.f1)
        self.assertEqual(self.client.post(close_url, **JSON).status_code, 403)
        self.assertEqual(self.client.post(award_url, **JSON).status_code, 403)
        self.assertEqual(self.client.post(cancel_url, **JSON).status_code, 403)

        login(self.client, self.owner)
        resp = self.client.post(award_url, **JSON)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "not_closed")
        resp = self.client.post(close_url, **JSON)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "closed")
        resp = self.client.post(award_url, **JSON)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "awarded")
        self.assertEqual(data["payee"], self.f1.stellar_address)
        self.assertEqual(data["amount"], "450")
        self.assertEqual(self.client.post(reverse("auctions:need_award", args=[self.need.pk, 9999]), **JSON).status_code, 404)
        resp = self.client.post(cancel_url, **JSON)  # awarded → still cancellable (R14)
        self.assertEqual(resp.json()["status"], "cancelled")
        self.assertEqual(self.client.post(cancel_url, **JSON).status_code, 409)

    def test_bids_json_shape(self):
        a = self.bid(self.f1, "450")
        b = self.bid(self.f2, "400", delay=9, tags=["stellar"])
        url = reverse("auctions:need_bids_json", args=[self.need.pk])
        self.assertEqual(self.client.post(url).status_code, 405)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(
            set(data), {"ok", "need", "status", "bidding_ends_at", "budget_max", "best_price", "count", "weights", "fingerprint", "bids", "html"}
        )
        self.assertEqual(data["status"], "open")
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["best_price"], "400")
        self.assertEqual(data["weights"], [40, 30, 30])
        self.assertEqual([x["id"] for x in data["bids"]], [a.pk, b.pk])  # A (30.0) ahead of B (16.6)
        self.assertEqual(data["bids"][0]["rank"], 1)
        self.assertEqual(set(data["bids"][0]), {"id", "rank", "freelancer", "price", "delay_days", "tags", "message", "status", "created_at", "score", "is_best_price", "is_winner"})
        self.assertAlmostEqual(data["bids"][0]["score"]["total"], 30.0)
        self.assertTrue(data["bids"][1]["is_best_price"])
        self.assertIn("ui-rank", data["html"])
        self.assertIn('data-price-ratio="0.1000"', data["html"])
        self.assertIn("Meilleur prix", data["html"])
        # Fingerprint changes with a new bid, and the status flips once the timer ends.
        self.bid(self.f1, "390")
        data2 = self.client.get(url).json()
        self.assertNotEqual(data2["fingerprint"], data["fingerprint"])
        Need.objects.filter(pk=self.need.pk).update(bidding_ends_at=timezone.now() - timedelta(seconds=1))
        data3 = self.client.get(url).json()
        self.assertEqual(data3["status"], "closed")
        self.assertIn("Recommandé", data3["html"])
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, "closed")  # close_expired() ran

    def test_my_bids_statuses(self):
        self.assertEqual(self.client.get(reverse("auctions:my_bids")).status_code, 302)
        login(self.client, self.f1)
        resp = self.client.get(reverse("auctions:my_bids"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Aucune enchère")

        self.bid(self.f1, "450")  # will be replaced → "Remplacée"
        self.bid(self.f1, "440")  # leading → "En tête"
        rows = self.client.get(reverse("auctions:my_bids")).context["rows"]
        self.assertEqual([r["label"] for r in rows], ["En tête", "Remplacée"])
        self.bid(self.f2, "400")  # now behind → "Dépassée"
        rows = self.client.get(reverse("auctions:my_bids")).context["rows"]
        self.assertEqual(rows[0]["label"], "Dépassée")
        self.assertEqual(rows[0]["best_price"], Decimal("400"))

        other = make_need(self.owner, title="Autre")
        won = services.place_bid(other, self.f1, "100", 5, [], "")
        services.place_bid(other, self.f2, "90", 5, [], "")
        services.close_bidding_now(other, self.owner)
        services.award(other, won, self.owner)
        resp = self.client.get(reverse("auctions:my_bids"))
        labels = [r["label"] for r in resp.context["rows"]]
        self.assertIn("Gagnée", labels)
        self.assertContains(resp, "ui-badge-ok")
        login(self.client, self.f2)
        labels = [r["label"] for r in self.client.get(reverse("auctions:my_bids")).context["rows"]]
        self.assertIn("Non retenue", labels)
        self.assertContains(self.client.get(reverse("auctions:my_bids")), 'data-label="Mon prix"')

    def test_my_needs_and_nav(self):
        self.assertEqual(self.client.get(reverse("auctions:my_needs")).status_code, 302)
        login(self.client, self.owner)
        self.bid(self.f1, "450")
        resp = self.client.get(reverse("auctions:my_needs"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.need.title)
        self.assertContains(resp, "Mes besoins")
        self.assertEqual(resp.context["needs"][0].bids_count, 1)
        labels = [link["label"] for link in resp.context["nav_links"]]
        self.assertEqual(labels, ["Besoins", "Poster un besoin", "Mes enchères", "Mes besoins"])
        self.assertTrue([link for link in resp.context["nav_links"] if link["label"] == "Mes besoins"][0]["active"])
        login(self.client, self.f1)
        self.assertNotContains(self.client.get(reverse("auctions:my_needs")), self.need.title)

    def test_landing_lists_latest_open_needs(self):
        make_need(self.owner, title="Fermé", bidding_ends_at=timezone.now() - timedelta(minutes=1))
        resp = self.client.get(reverse("core:landing"))
        self.assertContains(resp, self.need.title)
        self.assertNotContains(resp, "Fermé")
