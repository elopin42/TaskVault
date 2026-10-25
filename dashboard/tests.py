import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from network import services as network
from projects import services as projects
from projects.models import Application, Project, Task

from . import services


def make_wallet(name: str = "") -> WalletUser:
    return WalletUser.objects.create(stellar_address=Keypair.random().public_key, display_name=name)


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


class ScenarioTest(TestCase):
    """One company with a project in every task state, two freelances (A chosen / paid, B pending / rejected)."""

    def setUp(self):
        self.company = make_wallet("Studio Nova")
        self.a = make_wallet("Yanis")
        self.b = make_wallet("Nora")

        self.project = projects.create_project(self.company, "Plateforme de réservation", "Une description.")
        self.t1 = projects.add_task(self.project, self.company, "Landing page", "", "300", ["django", "ui"])
        self.t2 = projects.add_task(self.project, self.company, "Intégration Freighter", "", "500", ["stellar", "js"])
        self.t3 = projects.add_task(self.project, self.company, "Dashboard", "", "400", ["django", "charts"])
        self.t4 = projects.add_task(self.project, self.company, "Retouche photos", "", "120", ["photo"])
        # T1: paid to A (note 5); B rejected
        projects.apply(self.t1, self.a, "A", ["django", "ui"])
        projects.apply(self.t1, self.b, "B", ["django"])
        projects.choose(self.t1, Application.objects.get(task=self.t1, freelancer=self.a), self.company)
        projects.deliver(self.t1, self.a, "https://example.com/pr/1")
        projects.validate(self.t1, self.company, 5, "Parfait")
        projects.mark_paid(self.t1)  # what payments does once the payment is confirmed on chain
        # T2: open with A + B pending → company must choose
        projects.apply(self.t2, self.a, "", ["stellar"])
        projects.apply(self.t2, self.b, "", ["stellar", "js"])
        # T3: taken by A → A must deliver
        projects.apply(self.t3, self.a, "", ["django"])
        projects.choose(self.t3, Application.objects.get(task=self.t3, freelancer=self.a), self.company)
        # T4: delivered by B → company must validate
        projects.apply(self.t4, self.b, "", ["photo"])
        projects.choose(self.t4, Application.objects.get(task=self.t4, freelancer=self.b), self.company)
        projects.deliver(self.t4, self.b, "https://example.com/photos")
        # an empty draft project
        self.empty = projects.create_project(self.company, "Projet vide", "Rien dedans.")


class TodoTests(ScenarioTest):
    def test_company_todo(self):
        items = services.todo_items(self.company)
        headlines = [it["headline"] for it in items]
        self.assertTrue(any("Validate and rate" in h and "Retouche photos" in h for h in headlines), headlines)
        self.assertTrue(any("Choose a freelancer" in h and "Intégration Freighter" in h for h in headlines), headlines)
        self.assertTrue(any("Add tasks to" in h and "Projet vide" in h for h in headlines), headlines)
        self.assertFalse(any("Landing page" in h for h in headlines), "a paid task needs nothing")
        tones = [it["tone"] for it in items]
        self.assertEqual(tones, sorted(tones, key=lambda t: 0 if t == "act" else 1), "act items come first")
        for it in items:
            self.assertEqual(set(it), {"tone", "kicker", "headline", "body", "href", "cta", "icon", "when"})
            self.assertTrue(it["href"].startswith("/taches/") or it["href"].startswith("/projets/"), it["href"])
        validate = next(it for it in items if "Validate and rate" in it["headline"])
        self.assertEqual(validate["tone"], "act")
        self.assertTrue(validate["href"].endswith("#validate-panel"))
        self.assertIn("https://example.com/photos", validate["body"])

    def test_freelance_todo(self):
        a = services.todo_items(self.a)
        deliver = [it for it in a if it["kicker"] == "Task taken"]
        self.assertEqual(len(deliver), 1)
        self.assertEqual(deliver[0]["tone"], "act")
        self.assertIn('Deliver "Dashboard"', deliver[0]["headline"])
        self.assertTrue(deliver[0]["href"].endswith("#deliver-panel"))
        pending = [it for it in a if it["kicker"] == "Application sent"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["tone"], "wait")
        self.assertIn("90.0/100", pending[0]["body"])

        b = services.todo_items(self.b)
        self.assertTrue(any(it["kicker"] == "Delivery declared" and it["tone"] == "wait" for it in b), b)
        self.assertFalse(any(it["kicker"] == "Task taken" for it in b))
        self.assertEqual(sum(1 for it in b if it["kicker"] == "Application sent"), 1, "the rejected T1 application is gone")

    def test_company_validate_item_mentions_the_review_deadline(self):
        items = services.todo_items(self.company)
        validate = next(it for it in items if "Validate and rate" in it["headline"])
        self.assertIn("Review until", validate["body"])
        b = services.todo_items(self.b)
        wait = next(it for it in b if it["kicker"] == "Delivery declared")
        self.assertIn("Review until", wait["body"], "the freelance sees the same window")
        Task.objects.filter(pk=self.t4.pk).update(delivered_at=timezone.now() - timedelta(days=9))
        validate = next(it for it in services.todo_items(self.company) if "Validate and rate" in it["headline"])
        self.assertIn("Review window over", validate["body"])

    def test_freelance_changes_requested_item(self):
        projects.request_changes(self.t4, self.company, "The clipping is rough on three photos.")
        b = services.todo_items(self.b)
        item = next(it for it in b if it["kicker"] == "Changes requested")
        self.assertEqual(item["tone"], "act")
        self.assertIn('Changes requested on "Retouche photos" (1/2)', item["headline"])
        self.assertIn("clipping is rough", item["body"])
        self.assertEqual(item["cta"], "Deliver again")
        self.assertTrue(item["href"].endswith("#deliver-panel"))
        self.assertFalse(any(it["kicker"] == "Task taken" and "Retouche" in it["headline"] for it in b))
        company = services.todo_items(self.company)
        self.assertFalse(any("Validate and rate" in it["headline"] and "Retouche" in it["headline"] for it in company), "nothing to validate while taken")
        projects.deliver(self.t4, self.b, "https://example.com/photos-v2")
        validate = next(it for it in services.todo_items(self.company) if "Validate and rate" in it["headline"] and "Retouche" in it["headline"])
        self.assertIn("delivered again (revision 1)", validate["body"])
        self.assertIn("Review until", validate["body"])

    def test_fresh_wallet_has_nothing_to_do(self):
        self.assertEqual(services.todo_items(make_wallet()), [])


class StatsTests(ScenarioTest):
    def test_company_stats(self):
        s = services.company_stats(self.company)
        self.assertEqual(s["projects"], 2)
        self.assertEqual(s["draft"], 2)
        self.assertEqual(s["tasks"], 4)
        self.assertEqual(s["open"], 1)
        self.assertEqual(s["to_choose"], 1)
        self.assertEqual(s["in_progress"], 1)
        self.assertEqual(s["to_validate"], 1)
        self.assertEqual(s["paid"], 1)
        self.assertEqual(s["committed_usdc"], Decimal("1320"))
        self.assertEqual(s["paid_usdc"], Decimal("300"))
        self.assertEqual(s["applications_received"], 6)

    def test_freelancer_stats(self):
        a = services.freelancer_stats(self.a)
        self.assertEqual(a["total"], 3)
        self.assertEqual(a["pending"], 1)
        self.assertEqual(a["chosen"], 2)
        self.assertEqual(a["rejected"], 0)
        self.assertEqual(a["in_progress"], 1)
        self.assertEqual(a["paid"], 1)
        self.assertEqual(a["earned_usdc"], Decimal("300"))
        self.assertEqual(a["avg_note"], 5.0)
        self.assertEqual(a["ratings"], 1)
        self.assertEqual(a["success_rate"], 100)
        b = services.freelancer_stats(self.b)
        self.assertEqual(b["total"], 3)
        self.assertEqual(b["chosen"], 1)
        self.assertEqual(b["rejected"], 1)
        self.assertEqual(b["delivered"], 1)
        self.assertEqual(b["earned_usdc"], Decimal("0"))
        self.assertIsNone(b["avg_note"])
        self.assertEqual(b["success_rate"], 50)
        self.assertIsNone(services.freelancer_stats(self.company)["success_rate"])

    def test_recent_activity_is_newest_first_and_merged(self):
        events = services.recent_activity(self.company)
        self.assertTrue(events)
        whens = [e["when"] for e in events]
        self.assertEqual(whens, sorted(whens, reverse=True))
        texts = " | ".join(e["text"] for e in events)
        self.assertIn("Project created", texts)
        self.assertIn("chosen for", texts)
        self.assertIn("Payment sent", texts)
        for e in events:
            self.assertEqual(set(e), {"when", "icon", "text", "href", "tone"})
        self.assertLessEqual(len(services.recent_activity(self.company, limit=3)), 3)
        a_texts = " | ".join(e["text"] for e in services.recent_activity(self.a))
        self.assertIn("Application for", a_texts)
        self.assertIn("Payment received", a_texts)
        self.assertIn("Rating received: 5/5", a_texts)

    def test_profile_stats(self):
        s = services.profile_stats(self.company)
        self.assertEqual(s["projects_posted"], 2)
        self.assertEqual(s["tasks_paid_as_company"], 1)
        self.assertEqual(s["applications"], 0)
        self.assertIsNone(s["avg_note"])
        self.assertEqual(s["projects"][0].tag_list[:2], [])  # the empty draft comes first (newest)
        a = services.profile_stats(self.a)
        self.assertEqual(a["applications"], 3)
        self.assertEqual(a["tasks_won"], 2)
        self.assertEqual(a["tasks_paid"], 1)
        self.assertEqual(a["earned_usdc"], Decimal("300"))
        self.assertEqual(a["avg_note"], 5.0)
        self.assertEqual(a["ratings_count"], 1)
        self.assertEqual(len(a["ratings"]), 1)
        self.assertEqual(len(a["tasks"]), 2)


class HomeViewTests(ScenarioTest):
    def test_anonymous_is_redirected_to_landing(self):
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_home_renders_sections(self):
        login(self.client, self.company)
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for marker in ("To do", "Recent activity", "As a company", "As a freelancer", "Validate and rate", "ui-timeline", "Studio Nova"):
            self.assertIn(marker, html)
        self.assertNotIn("{%", html)
        self.assertNotIn("{{", html)

    def test_home_shows_the_freelance_average_note(self):
        login(self.client, self.a)
        r = self.client.get(reverse("dashboard:home"))
        self.assertContains(r, "data-avg-note")
        self.assertContains(r, "5.0/5")
        self.assertContains(r, "Deliver &quot;Dashboard&quot;")  # autoescaped quotes

    def test_home_without_anything_shows_done_card(self):
        fresh = make_wallet()
        login(self.client, fresh)
        r = self.client.get(reverse("dashboard:home"))
        self.assertContains(r, "Nothing to do for now")
        self.assertContains(r, "No activity")

    def test_navbar_links_to_dashboard(self):
        login(self.client, self.company)
        r = self.client.get(reverse("projects:project_list"))
        self.assertContains(r, reverse("dashboard:home"))
        self.assertContains(r, reverse("dashboard:profile", kwargs={"address": self.company.stellar_address}))

    def test_landing_connect_button_targets_dashboard(self):
        r = self.client.get(reverse("core:landing"))
        self.assertContains(r, f'data-next="{reverse("dashboard:home")}"')
        r = self.client.get(reverse("core:landing") + "?next=/taches/")
        self.assertContains(r, 'data-next="/taches/"')


class ProfileViewTests(ScenarioTest):
    def url(self, wallet):
        return reverse("dashboard:profile", kwargs={"address": wallet.stellar_address})

    def test_unknown_wallet_404(self):
        r = self.client.get(reverse("dashboard:profile", kwargs={"address": Keypair.random().public_key}))
        self.assertEqual(r.status_code, 404)

    def test_public_profile_renders_without_login(self):
        r = self.client.get(self.url(self.a))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Yanis", html)
        self.assertIn("Tasks completed", html)
        self.assertIn("Ratings received", html)
        self.assertIn('data-avg-note="5.0"', html)
        self.assertIn("Landing page", html)
        self.assertNotIn("Edit my name", html)
        r = self.client.get(self.url(self.company))
        self.assertContains(r, "Plateforme de réservation")
        self.assertContains(r, "project-card")
        self.assertContains(r, "no ratings received")

    def test_owner_sees_and_uses_the_name_form(self):
        login(self.client, self.a)
        r = self.client.get(self.url(self.a))
        self.assertContains(r, "Edit my name")
        r = self.client.post(self.url(self.a), {"display_name": "  Yanis Dev  "}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual(self.a.display_name, "Yanis Dev")
        self.assertContains(r, "Display name updated")

    def test_name_is_truncated_to_80_chars(self):
        login(self.client, self.a)
        self.client.post(self.url(self.a), {"display_name": "x" * 100})
        self.a.refresh_from_db()
        self.assertEqual(len(self.a.display_name), 80)

    def test_other_wallet_cannot_rename(self):
        login(self.client, self.a)
        r = self.client.post(self.url(self.b), {"display_name": "Pirate"})
        self.assertEqual(r.status_code, 403)
        r = self.client.logout() or self.client.post(self.url(self.b), {"display_name": "Pirate"})
        self.assertEqual(r.status_code, 403)
        self.b.refresh_from_db()
        self.assertEqual(self.b.display_name, "Nora")


class ModelHelpersTests(ScenarioTest):
    def test_project_progress_and_totals(self):
        p = Project.objects.with_totals().get(pk=self.project.pk)
        self.assertEqual(p.total_amount, Decimal("1320"))
        self.assertEqual(p.tasks_count, 4)
        self.assertEqual(p.paid_count, 1)
        self.assertEqual(p.open_count, 1)
        self.assertEqual(p.progress_pct, 25)
        self.assertEqual(Project.objects.get(pk=self.empty.pk).progress_pct, 0)
        self.assertEqual(Task.objects.get(pk=self.t1.pk).status_label, "Paid")


def _tag(html: str, marker: str) -> str:
    """The opening tag that carries `marker` (e.g. 'data-unrecommend '), or ''."""
    m = re.search(r"<[^<>]*" + re.escape(marker) + r"[^<>]*>", html)
    return m.group(0) if m else ""


class ProfileNetworkTests(TestCase):
    """The #network-panel and #recommendations blocks of the public profile, per viewer."""

    def setUp(self):
        self.me = make_wallet("Claire")
        self.target = make_wallet("Yanis")
        self.friend = make_wallet("Nora")
        self.friend2 = make_wallet("Omar")

    def url(self, wallet):
        return reverse("dashboard:profile", kwargs={"address": wallet.stellar_address})

    def test_signed_in_other_wallet_sees_counters_and_follow_button(self):
        network.follow(self.friend, self.target)
        network.follow(self.target, self.friend)
        network.recommend(self.friend, self.target, "Great work")
        login(self.client, self.me)
        r = self.client.get(self.url(self.target))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="network-panel"', html)
        self.assertRegex(html, r"data-followers-count>1<")
        self.assertRegex(html, r"data-following-count>1<")
        self.assertRegex(html, r"data-recommendations-count>1<")
        for label in ("Sponsorship", "Followers", "Following", "Sponsors"):
            self.assertIn(label, html)
        follow = _tag(html, "data-follow-url")
        self.assertIn(f'data-follow-url="{reverse("network:follow", args=[self.target.stellar_address])}"', follow)
        self.assertIn(f'data-unfollow-url="{reverse("network:unfollow", args=[self.target.stellar_address])}"', follow)
        self.assertIn('data-following="0"', follow)
        self.assertIn('data-name="Yanis"', follow)
        self.assertIn(f'data-recommend-url="{reverse("network:recommend", args=[self.target.stellar_address])}"', html)
        self.assertIn('id="recommend-form"', html)
        self.assertIn("data-recommend-counter", html)
        self.assertIn("lowbid-network.js", html)
        self.assertNotIn("{{", html)

    def test_follow_button_reflects_current_follow(self):
        network.follow(self.me, self.target)
        login(self.client, self.me)
        html = self.client.get(self.url(self.target)).content.decode()
        self.assertIn('data-following="1"', _tag(html, "data-follow-url"))
        self.assertIn('data-network-badge="following"', html)

    def test_own_profile_has_counters_only(self):
        login(self.client, self.me)
        html = self.client.get(self.url(self.me)).content.decode()
        self.assertIn('id="network-panel"', html)
        self.assertIn("data-followers-count", html)
        self.assertNotIn("data-follow-url", html)
        self.assertNotIn("data-recommend ", html)
        self.assertNotIn('id="recommend-form"', html)
        self.assertNotIn("Connect your wallet to follow", html)
        self.assertNotIn("ui-netbadges", html)

    def test_anonymous_gets_connect_prompt_and_no_actions(self):
        html = self.client.get(self.url(self.target)).content.decode()
        self.assertIn('id="network-panel"', html)
        self.assertNotIn("data-follow-url", html)
        self.assertNotIn('id="recommend-form"', html)
        self.assertIn("Connect your wallet to follow or sponsor this wallet.", html)
        panel = html[html.index('id="network-panel"'):html.index('id="recommendations"')]
        self.assertIn(f'data-next="{self.url(self.target)}"', _tag(panel, "data-wallet-connect"))

    def test_unrecommend_hidden_without_recommendation(self):
        login(self.client, self.me)
        html = self.client.get(self.url(self.target)).content.decode()
        self.assertIn(" hidden", _tag(html, "data-unrecommend "))
        self.assertIn('data-recommended="0"', _tag(html, "data-recommend "))

    def test_unrecommend_visible_and_message_prefilled_with_recommendation(self):
        network.recommend(self.me, self.target, "Ships fast")
        login(self.client, self.me)
        html = self.client.get(self.url(self.target)).content.decode()
        self.assertNotIn(" hidden", _tag(html, "data-unrecommend "))
        self.assertIn('data-recommended="1"', _tag(html, "data-recommend "))
        self.assertIn("Edit sponsorship", html)
        self.assertRegex(html, r'id="recommend-message"[^>]*>Ships fast</textarea>')

    def test_known_followers_singular_and_plural(self):
        network.follow(self.me, self.friend)
        network.follow(self.friend, self.target)
        login(self.client, self.me)
        r = self.client.get(self.url(self.target))
        self.assertContains(r, "Followed by 1 person you follow")
        self.assertContains(r, "data-known-followers")
        self.assertContains(r, "<strong>Nora</strong>", html=False)
        network.follow(self.me, self.friend2)
        network.follow(self.friend2, self.target)
        r = self.client.get(self.url(self.target))
        self.assertContains(r, "Followed by 2 people you follow")
        self.assertContains(r, "Nora, Omar")

    def test_no_known_followers_line_for_anonymous(self):
        network.follow(self.friend, self.target)
        r = self.client.get(self.url(self.target))
        self.assertNotContains(r, "data-known-followers")

    def test_recommendations_list_with_author_and_message(self):
        network.recommend(self.friend, self.target, "Delivered the landing in two days")
        network.recommend(self.friend2, self.target, "")
        r = self.client.get(self.url(self.target))
        html = r.content.decode()
        section = html[html.index('id="recommendations"'):]
        self.assertIn("Sponsored by", html)
        self.assertEqual(section.count("ui-timeline-item"), 2)
        self.assertIn("Nora", section)
        self.assertIn("Omar", section)
        self.assertIn('<p class="ui-network-quote">Delivered the landing in two days</p>', section)
        self.assertEqual(section.count("ui-network-quote"), 1)

    def test_recommendations_empty_state(self):
        r = self.client.get(self.url(self.target))
        self.assertContains(r, "No sponsors yet")

    def test_recommends_badge_in_header_when_followed_wallet_recommends(self):
        network.follow(self.me, self.friend)
        network.recommend(self.friend, self.target, "")
        login(self.client, self.me)
        html = self.client.get(self.url(self.target)).content.decode()
        header = html[html.index("ui-page-header"):html.index('id="network-panel"')]
        self.assertIn('data-network-badge="recommends"', header)
        self.assertIn("Nora recommends", header)
        # anonymous: no badge
        self.client.logout()
        self.assertNotContains(self.client.get(self.url(self.target)), "ui-netbadges")


class HomeNetworkFeedTests(TestCase):
    def setUp(self):
        self.me = make_wallet("Claire")
        self.friend = make_wallet("Nora")
        self.target = make_wallet("Yanis")

    def test_feed_lists_a_recommendation_by_someone_i_follow(self):
        network.follow(self.me, self.friend)
        network.recommend(self.friend, self.target, "Top freelancer")
        login(self.client, self.me)
        r = self.client.get(reverse("dashboard:home"))
        html = r.content.decode()
        self.assertIn('id="network-feed"', html)
        self.assertIn("In your network", html)
        feed = html[html.index('id="network-feed"'):]
        self.assertIn("ui-network-feed-item is-recommendation", feed)
        self.assertIn("sponsors", feed)
        self.assertIn("Yanis", feed)
        self.assertIn("Top freelancer", feed)
        self.assertNotIn("Your network is quiet", html)
        # the existing panels keep their ids, #network-feed comes after #activity
        self.assertLess(html.index('id="todo"'), html.index('id="activity"'))
        self.assertLess(html.index('id="activity"'), html.index('id="network-feed"'))

    def test_feed_empty_state_when_following_nobody(self):
        network.recommend(self.friend, self.target, "Not in my network")
        login(self.client, self.me)
        r = self.client.get(reverse("dashboard:home"))
        self.assertContains(r, 'id="network-feed"')
        self.assertContains(r, "Your network is quiet")
        self.assertContains(r, "Follow wallets from their profile to see them here.")
        self.assertNotContains(r, "Not in my network")
