"""Trust network: rules, DB constraints, one-hop signals, labels, query budget, feed, profile, endpoints."""

import json

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from stellar_sdk import Keypair

from accounts.models import WalletUser
from projects import services as projects

from . import services
from .models import Follow, Recommendation
from .services import NetworkError, NetworkSignal


def make_wallet(name: str = "") -> WalletUser:
    return WalletUser.objects.create(stellar_address=Keypair.random().public_key, display_name=name)


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


class RulesTests(TestCase):
    def setUp(self):
        self.v = make_wallet("Viewer")
        self.t = make_wallet("Target")

    def test_follow_self_refused(self):
        with self.assertRaises(NetworkError) as ctx:
            services.follow(self.v, self.v)
        self.assertEqual(ctx.exception.code, "self")
        self.assertEqual(Follow.objects.count(), 0)

    def test_recommend_self_refused(self):
        with self.assertRaises(NetworkError) as ctx:
            services.recommend(self.v, self.v, "me")
        self.assertEqual(ctx.exception.code, "self")
        self.assertEqual(Recommendation.objects.count(), 0)

    def test_follow_is_idempotent(self):
        first = services.follow(self.v, self.t)
        second = services.follow(self.v, self.t)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Follow.objects.filter(follower=self.v, followed=self.t).count(), 1)

    def test_recommend_upserts_the_message(self):
        first = services.recommend(self.v, self.t, "  Great work  ")
        self.assertEqual(first.message, "Great work")
        second = services.recommend(self.v, self.t, "Even better")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Recommendation.objects.count(), 1)
        self.assertEqual(Recommendation.objects.get().message, "Even better")

    def test_message_length(self):
        with self.assertRaises(NetworkError) as ctx:
            services.recommend(self.v, self.t, "x" * 281)
        self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(Recommendation.objects.count(), 0)
        rec = services.recommend(self.v, self.t, "y" * 280)
        self.assertEqual(len(rec.message), 280)

    def test_message_must_be_text(self):
        with self.assertRaises(NetworkError) as ctx:
            services.recommend(self.v, self.t, 42)
        self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(services.recommend(self.v, self.t, None).message, "")

    def test_unfollow_and_unrecommend_return_false_when_nothing_to_delete(self):
        self.assertFalse(services.unfollow(self.v, self.t))
        self.assertFalse(services.unrecommend(self.v, self.t))
        services.follow(self.v, self.t)
        services.recommend(self.v, self.t)
        self.assertTrue(services.unfollow(self.v, self.t))
        self.assertTrue(services.unrecommend(self.v, self.t))
        self.assertFalse(services.unfollow(self.v, self.t))
        self.assertFalse(services.unrecommend(self.v, self.t))


class ConstraintTests(TestCase):
    def setUp(self):
        self.a = make_wallet("A")
        self.b = make_wallet("B")

    def test_follow_unique_pair(self):
        Follow.objects.create(follower=self.a, followed=self.b)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Follow.objects.create(follower=self.a, followed=self.b)
        # the reverse direction is a different pair
        Follow.objects.create(follower=self.b, followed=self.a)

    def test_follow_not_self(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Follow.objects.create(follower=self.a, followed=self.a)

    def test_recommendation_unique_pair(self):
        Recommendation.objects.create(author=self.a, subject=self.b)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Recommendation.objects.create(author=self.a, subject=self.b, message="again")

    def test_recommendation_not_self(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Recommendation.objects.create(author=self.a, subject=self.a)

    def test_str(self):
        self.assertEqual(str(Follow.objects.create(follower=self.a, followed=self.b)), "A follows B")
        self.assertEqual(str(Recommendation.objects.create(author=self.a, subject=self.b)), "A recommends B")


class SignalTests(TestCase):
    def setUp(self):
        self.v = make_wallet("Viewer")
        self.a = make_wallet("Yanis")
        self.b = make_wallet("Nora")
        self.t = make_wallet("Target")

    def test_one_hop_recommendation_is_strong(self):
        services.follow(self.v, self.a)
        services.recommend(self.a, self.t, "solid")
        sig = services.signals(self.v, [self.t])[self.t.pk]
        self.assertTrue(sig)
        self.assertEqual(sig.level, "strong")
        self.assertEqual([w.pk for w in sig.recommenders], [self.a.pk])
        self.assertEqual(sig.label, "Yanis recommends")
        self.assertFalse(sig.following)

    def test_two_hops_give_no_badge(self):
        services.follow(self.v, self.a)
        services.follow(self.a, self.b)
        services.recommend(self.b, self.t, "two hops away")
        sig = services.signals(self.v, [self.t])[self.t.pk]
        self.assertFalse(sig)
        self.assertEqual(sig.level, "")
        self.assertEqual(sig.label, "")
        # ... but B itself gets the weak badge: A (followed by V) follows B
        sig_b = services.signals(self.v, [self.b])[self.b.pk]
        self.assertEqual(sig_b.level, "weak")
        self.assertEqual(sig_b.label, "Followed by Yanis")

    def test_following_directly(self):
        services.follow(self.v, self.t)
        sig = services.signals(self.v, [self.t])[self.t.pk]
        self.assertTrue(sig.following)
        self.assertEqual(sig.level, "following")
        self.assertEqual(sig.label, "Following")
        self.assertEqual(sig.recommend_label, "")
        self.assertEqual(sig.followed_by_label, "")

    def test_strong_wins_but_every_badge_is_available(self):
        services.follow(self.v, self.a)
        services.follow(self.v, self.b)
        services.follow(self.v, self.t)
        services.recommend(self.a, self.t)
        services.follow(self.b, self.t)
        sig = services.signals(self.v, [self.t])[self.t.pk]
        self.assertEqual(sig.level, "strong")
        self.assertEqual(sig.label, "Yanis recommends")
        self.assertEqual(sig.recommend_label, "Yanis recommends")
        self.assertEqual(sig.followed_by_label, "Followed by Nora")
        self.assertTrue(sig.following)
        self.assertEqual(
            sig.as_json(),
            {
                "level": "strong",
                "label": "Yanis recommends",
                "recommends": [{"address": self.a.stellar_address, "name": "Yanis"}],
                "followed_by": [{"address": self.b.stellar_address, "name": "Nora"}],
                "following": True,
            },
        )

    def test_target_is_viewer_gives_empty_signal(self):
        services.follow(self.v, self.a)
        services.recommend(self.a, self.v, "we love the viewer")
        services.follow(self.a, self.v)
        sig = services.signals(self.v, [self.v])[self.v.pk]
        self.assertFalse(sig)
        self.assertEqual(sig.as_json()["level"], "")

    def test_anonymous_viewer(self):
        self.assertEqual(services.signals(None, [self.t]), {})

    def test_every_target_gets_a_signal_and_pks_are_accepted(self):
        services.follow(self.v, self.a)
        services.recommend(self.a, self.t)
        result = services.signals(self.v, [self.t.pk, self.b, self.b.pk])
        self.assertEqual(set(result), {self.t.pk, self.b.pk})
        self.assertEqual(result[self.t.pk].level, "strong")
        self.assertEqual(result[self.b.pk].level, "")
        self.assertEqual(services.signals(self.v, []), {})

    def test_viewer_following_nobody(self):
        result = services.signals(self.v, [self.t])
        self.assertEqual(result[self.t.pk].level, "")

    def test_recommenders_are_ordered_by_name(self):
        zoe = make_wallet("Zoé")
        anon = make_wallet("")  # named by its short address, "G…"
        for w in (zoe, anon, self.a, self.b):
            services.follow(self.v, w)
            services.recommend(w, self.t)
        sig = services.signals(self.v, [self.t])[self.t.pk]
        self.assertEqual([services.wallet_name(w) for w in sig.recommenders][:1], [anon.short_address])
        self.assertEqual([w.pk for w in sig.recommenders][1:], [self.b.pk, self.a.pk, zoe.pk])
        self.assertEqual(sig.label, f"{anon.short_address} and 3 others recommend")


class LabelTests(TestCase):
    def setUp(self):
        self.names = [make_wallet(n) for n in ("Yanis", "Nora", "Zoé")]

    def test_recommend_labels(self):
        self.assertEqual(NetworkSignal(recommenders=self.names[:1]).label, "Yanis recommends")
        self.assertEqual(NetworkSignal(recommenders=self.names[:2]).label, "Yanis and 1 other recommend")
        self.assertEqual(NetworkSignal(recommenders=self.names).label, "Yanis and 2 others recommend")

    def test_followed_by_labels(self):
        self.assertEqual(NetworkSignal(followers=self.names[:1]).label, "Followed by Yanis")
        self.assertEqual(NetworkSignal(followers=self.names[:2]).label, "Followed by Yanis and 1 other")
        self.assertEqual(NetworkSignal(followers=self.names).label, "Followed by Yanis and 2 others")

    def test_following_and_empty(self):
        self.assertEqual(NetworkSignal(following=True).label, "Following")
        self.assertEqual(NetworkSignal(following=True).level, "following")
        empty = NetworkSignal()
        self.assertEqual(empty.label, "")
        self.assertFalse(empty)
        self.assertEqual(
            empty.as_json(), {"level": "", "label": "", "recommends": [], "followed_by": [], "following": False}
        )

    def test_short_address_when_no_display_name(self):
        anon = make_wallet("")
        self.assertEqual(NetworkSignal(recommenders=[anon]).label, f"{anon.short_address} recommends")
        self.assertEqual(NetworkSignal(recommenders=[anon]).as_json()["recommends"][0]["name"], anon.short_address)


class QueryBudgetTests(TestCase):
    def test_signals_query_count_is_constant(self):
        viewer = make_wallet("Viewer")
        friends = [make_wallet(f"Friend {i}") for i in range(5)]
        targets = [make_wallet(f"Target {i}") for i in range(20)]
        for f in friends:
            services.follow(viewer, f)
        for i, t in enumerate(targets):
            services.recommend(friends[i % 5], t, "ok")
            services.follow(friends[(i + 1) % 5], t)
            if i % 3 == 0:
                services.follow(viewer, t)

        with CaptureQueriesContext(connection) as one:
            result = services.signals(viewer, targets[:1])
        self.assertEqual(result[targets[0].pk].level, "strong")
        self.assertEqual(len(one), 3, [q["sql"] for q in one])

        with self.assertNumQueries(len(one)):
            result = services.signals(viewer, targets)
        self.assertEqual(len(result), 20)
        self.assertTrue(all(sig.level == "strong" for sig in result.values()))
        self.assertTrue(all(sig.followed_by_label for sig in result.values()))
        self.assertEqual(sum(1 for sig in result.values() if sig.following), 7)


class FeedTests(TestCase):
    def setUp(self):
        self.v = make_wallet("Viewer")
        self.a = make_wallet("Yanis")
        self.b = make_wallet("Nora")
        self.c = make_wallet("Stranger")
        self.t = make_wallet("Target")

    def test_empty_for_anonymous_or_lonely_viewer(self):
        self.assertEqual(services.network_feed(None), [])
        self.assertEqual(services.network_feed(self.v), [])

    def test_feed_content_and_order(self):
        services.follow(self.v, self.a)
        services.follow(self.v, self.b)
        follow_row = services.follow(self.a, self.t)
        rec = services.recommend(self.a, self.t, "ship it")
        project = projects.create_project(self.b, "Booking platform", "A description.")
        # noise: not followed by V
        services.recommend(self.c, self.t, "unseen")
        projects.create_project(self.c, "Invisible", "Nope.")
        services.follow(self.c, self.a)

        feed = services.network_feed(self.v)
        self.assertEqual([it["kind"] for it in feed], ["project", "recommendation", "follow"])
        whens = [it["when"] for it in feed]
        self.assertEqual(whens, sorted(whens, reverse=True))
        for it in feed:
            self.assertEqual(set(it), {"kind", "actor", "target", "project", "message", "when", "href"})

        proj_item, rec_item, follow_item = feed
        self.assertEqual(proj_item["actor"], self.b)
        self.assertEqual(proj_item["project"], project)
        self.assertIsNone(proj_item["target"])
        self.assertEqual(proj_item["href"], reverse("projects:project_detail", kwargs={"pk": project.pk}))
        self.assertEqual(rec_item["actor"], self.a)
        self.assertEqual(rec_item["target"], self.t)
        self.assertEqual(rec_item["message"], "ship it")
        self.assertEqual(rec_item["when"], rec.updated_at)
        self.assertEqual(rec_item["href"], reverse("dashboard:profile", kwargs={"address": self.t.stellar_address}))
        self.assertEqual(follow_item["actor"], self.a)
        self.assertEqual(follow_item["target"], self.t)
        self.assertEqual(follow_item["when"], follow_row.created_at)
        self.assertEqual(follow_item["href"], reverse("dashboard:profile", kwargs={"address": self.t.stellar_address}))

    def test_limit(self):
        services.follow(self.v, self.a)
        for i in range(6):
            services.recommend(self.a, make_wallet(f"W{i}"), str(i))
            services.follow(self.a, make_wallet(f"F{i}"))
        self.assertEqual(len(services.network_feed(self.v, limit=4)), 4)
        self.assertEqual(len(services.network_feed(self.v)), 12)
        self.assertEqual(services.network_feed(self.v, limit=0), [])


class ProfileNetworkTests(TestCase):
    def setUp(self):
        self.v = make_wallet("Viewer")
        self.a = make_wallet("Yanis")
        self.p = make_wallet("Profile")

    def test_keys_for_anonymous(self):
        services.follow(self.a, self.p)
        services.recommend(self.a, self.p, "great")
        data = services.profile_network(self.p, None)
        self.assertEqual(
            set(data),
            {
                "followers_count",
                "following_count",
                "recommendations_count",
                "recommendations",
                "viewer_follows",
                "viewer_recommendation",
                "known_followers",
                "known_recommenders",
                "signal",
                "can_act",
            },
        )
        self.assertEqual(data["followers_count"], 1)
        self.assertEqual(data["following_count"], 0)
        self.assertEqual(data["recommendations_count"], 1)
        self.assertEqual([r.author for r in data["recommendations"]], [self.a])
        self.assertFalse(data["viewer_follows"])
        self.assertIsNone(data["viewer_recommendation"])
        self.assertEqual(data["known_followers"], [])
        self.assertEqual(data["known_recommenders"], [])
        self.assertIsNone(data["signal"])
        self.assertFalse(data["can_act"])

    def test_viewer_point_of_view(self):
        services.follow(self.v, self.a)
        services.follow(self.a, self.p)
        services.recommend(self.a, self.p, "great")
        services.follow(self.v, self.p)
        mine = services.recommend(self.v, self.p, "mine")
        services.follow(self.p, self.a)
        data = services.profile_network(self.p, self.v)
        self.assertTrue(data["can_act"])
        self.assertTrue(data["viewer_follows"])
        self.assertEqual(data["viewer_recommendation"], mine)
        self.assertEqual(data["followers_count"], 2)
        self.assertEqual(data["following_count"], 1)
        self.assertEqual(data["recommendations_count"], 2)
        self.assertEqual([r.pk for r in data["recommendations"]], [mine.pk, Recommendation.objects.get(author=self.a).pk])
        self.assertEqual(data["known_followers"], [self.a])
        self.assertEqual(data["known_recommenders"], [self.a])
        self.assertEqual(data["signal"].level, "strong")
        self.assertTrue(data["signal"].following)

    def test_own_profile(self):
        services.follow(self.a, self.v)
        data = services.profile_network(self.v, self.v)
        self.assertFalse(data["can_act"])
        self.assertIsNone(data["signal"])
        self.assertFalse(data["viewer_follows"])
        self.assertEqual(data["followers_count"], 1)


class EndpointTests(TestCase):
    HEADERS = {"HTTP_X_REQUESTED_WITH": "fetch"}

    def setUp(self):
        self.v = make_wallet("Viewer")
        self.t = make_wallet("Yanis")

    def post(self, name: str, address: str, body: dict | None = None):
        url = reverse(f"network:{name}", kwargs={"address": address})
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json", **self.HEADERS)

    def test_anonymous_gets_401_json(self):
        for name in ("follow", "unfollow", "recommend", "unrecommend"):
            res = self.post(name, self.t.stellar_address)
            self.assertEqual(res.status_code, 401, name)
            self.assertEqual(res.json(), {"ok": False, "error": "wallet_required"})
        self.assertEqual(Follow.objects.count(), 0)

    def test_unknown_address_is_404(self):
        login(self.client, self.v)
        res = self.post("follow", "GUNKNOWN")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.json()["ok"])
        self.assertEqual(res.json()["error"], "not_found")

    def test_self_is_400(self):
        login(self.client, self.v)
        for name in ("follow", "recommend"):
            res = self.post(name, self.v.stellar_address)
            self.assertEqual(res.status_code, 400, name)
            self.assertEqual(res.json()["error"], "self")
            self.assertIn("message", res.json())

    def test_too_long_message_is_400(self):
        login(self.client, self.v)
        res = self.post("recommend", self.t.stellar_address, {"message": "x" * 281})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "invalid")
        self.assertEqual(Recommendation.objects.count(), 0)

    def test_follow_then_unfollow(self):
        login(self.client, self.v)
        res = self.post("follow", self.t.stellar_address)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json(),
            {
                "ok": True,
                "following": True,
                "followers_count": 1,
                "recommendation": None,
                "recommendations_count": 0,
                "message": "Following Yanis.",
            },
        )
        # idempotent
        self.assertEqual(self.post("follow", self.t.stellar_address).json()["followers_count"], 1)
        res = self.post("unfollow", self.t.stellar_address)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertFalse(body["following"])
        self.assertEqual(body["followers_count"], 0)
        self.assertEqual(body["message"], "No longer following Yanis.")

    def test_recommend_then_withdraw(self):
        login(self.client, self.v)
        res = self.post("recommend", self.t.stellar_address, {"message": " Ships fast "})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["recommendation"], {"message": "Ships fast"})
        self.assertEqual(body["recommendations_count"], 1)
        self.assertEqual(body["message"], "Recommendation saved.")
        # upsert through the endpoint
        body = self.post("recommend", self.t.stellar_address, {"message": "Updated"}).json()
        self.assertEqual(body["recommendation"], {"message": "Updated"})
        self.assertEqual(body["recommendations_count"], 1)
        res = self.post("unrecommend", self.t.stellar_address)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIsNone(body["recommendation"])
        self.assertEqual(body["recommendations_count"], 0)
        self.assertEqual(body["message"], "Recommendation withdrawn.")

    def test_form_post_is_accepted(self):
        login(self.client, self.v)
        url = reverse("network:recommend", kwargs={"address": self.t.stellar_address})
        res = self.client.post(url, {"message": "form"}, **self.HEADERS)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["recommendation"], {"message": "form"})

    def test_get_is_405(self):
        login(self.client, self.v)
        for name in ("follow", "unfollow", "recommend", "unrecommend"):
            res = self.client.get(reverse(f"network:{name}", kwargs={"address": self.t.stellar_address}))
            self.assertEqual(res.status_code, 405, name)

    def test_urls(self):
        addr = self.t.stellar_address
        self.assertEqual(reverse("network:follow", kwargs={"address": addr}), f"/profil/{addr}/suivre/")
        self.assertEqual(reverse("network:unfollow", kwargs={"address": addr}), f"/profil/{addr}/ne-plus-suivre/")
        self.assertEqual(reverse("network:recommend", kwargs={"address": addr}), f"/profil/{addr}/recommander/")
        self.assertEqual(
            reverse("network:unrecommend", kwargs={"address": addr}), f"/profil/{addr}/retirer-recommandation/"
        )
