"""Sponsorship on candidate rows: the sponsor's quote (one hop), « New account » on every row without on-chain
history, the Sponsor button (signed-in viewer who is not the candidate), `sponsoring` in candidats.json and the
poll fingerprint. None of it changes the score or the order."""

import re

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from stellar_sdk import Keypair

from accounts.models import WalletUser
from network import services as network
from reputation.tests import paid_task

from . import services

QUOTE = "Worked with her twice. Clean, fast, reliable."


def make_wallet(name: str = "") -> WalletUser:
    return WalletUser.objects.create(stellar_address=Keypair.random().public_key, display_name=name)


def login(client, wallet: WalletUser) -> None:
    session = client.session
    session["wallet_user_id"] = wallet.pk
    session["wallet_address"] = wallet.stellar_address
    session.save()


def _row(html: str, address: str) -> str:
    """The markup of one candidate row (from its opening div to the next row / end of list)."""
    start = html.index(f'data-freelancer="{address}"')
    nxt = html.find('class="ui-list-row cand-row', start)
    return html[start: nxt if nxt != -1 else len(html)]


class SponsorRowTests(TestCase):
    def setUp(self):
        self.company = make_wallet("Studio")
        self.yanis = make_wallet("Yanis")
        self.newbie = make_wallet("Lea")
        self.veteran = make_wallet("Omar")
        self.stranger = make_wallet("Stranger")
        paid_task(self.company, self.veteran)  # a confirmed on-chain payout: Omar has history
        project = services.create_project(self.company, "Sponsor project", "A description.")
        self.task = services.add_task(project, self.company, "Landing page", "", "300", ["django"])
        services.apply(self.task, self.newbie, "Hi", ["django"])
        services.apply(self.task, self.veteran, "Hello", ["django"])
        self.page = reverse("projects:task_detail", kwargs={"pk": self.task.pk})
        self.json_url = reverse("projects:task_candidates_json", kwargs={"pk": self.task.pk})

    def html_for(self, wallet=None) -> str:
        if wallet is not None:
            login(self.client, wallet)
        else:
            self.client.logout()
        return self.client.get(self.page).content.decode()

    # --- quote -----------------------------------------------------------------------------

    def test_quote_shown_to_a_viewer_who_follows_the_sponsor(self):
        network.follow(self.company, self.yanis)
        network.recommend(self.yanis, self.newbie, QUOTE)
        row = _row(self.html_for(self.company), self.newbie.stellar_address)
        self.assertIn("data-network-quote", row)
        self.assertIn(f"“{QUOTE}”", row)
        self.assertIn("— Yanis", row)
        self.assertIn("Yanis recommends", row)
        self.assertNotIn("data-network-quote", _row(self.html_for(self.company), self.veteran.stellar_address))

    def test_no_quote_for_a_stranger_or_anonymous(self):
        network.follow(self.company, self.yanis)
        network.recommend(self.yanis, self.newbie, QUOTE)
        for viewer in (self.stranger, None):
            html = self.html_for(viewer)
            self.assertNotIn("data-network-quote", html)
            self.assertNotIn(QUOTE, html)

    # --- New account ------------------------------------------------------------------------

    def test_new_account_badge_only_without_history(self):
        for viewer in (None, self.company):
            html = self.html_for(viewer)
            new_row = _row(html, self.newbie.stellar_address)
            self.assertIn('data-badge="new-account"', new_row)
            self.assertIn("New account", new_row)
            self.assertNotIn('data-badge="new-account"', _row(html, self.veteran.stellar_address))
        data = self.client.get(self.json_url).json()
        flags = {c["freelancer"]: c["new_account"] for c in data["candidates"]}
        self.assertEqual(flags, {self.newbie.stellar_address: True, self.veteran.stellar_address: False})

    def test_chosen_row_keeps_no_history_without_the_new_account_badge(self):
        app = self.task.applications.get(freelancer=self.newbie)
        services.choose(self.task, app, self.company)
        row = _row(self.html_for(self.company), self.newbie.stellar_address)
        self.assertIn("data-no-history", row)
        self.assertNotIn('data-badge="new-account"', row)

    def test_score_note_in_the_legend(self):
        self.assertIn("data-score-note", self.html_for(None))
        self.assertIn("Price never enters the score", self.html_for(None))

    # --- Sponsor button ---------------------------------------------------------------------

    def test_sponsor_button_for_the_company_and_another_freelancer(self):
        for viewer in (self.company, self.veteran):
            row = _row(self.html_for(viewer), self.newbie.stellar_address)
            self.assertIn("data-sponsor ", row)
            self.assertIn('data-sponsoring="0"', row)
            self.assertIn(f'data-recommend-url="{reverse("network:recommend", args=[self.newbie.stellar_address])}"', row)
            self.assertIn(
                f'data-unrecommend-url="{reverse("network:unrecommend", args=[self.newbie.stellar_address])}"', row
            )
            self.assertIn('data-name="Lea"', row)
            self.assertIn("data-sponsor-form", row)
            self.assertIn('maxlength="280"', row)
            self.assertRegex(row, r"</i> Sponsor\s*</button>")

    def test_no_sponsor_button_on_your_own_row_nor_for_anonymous(self):
        html = self.html_for(self.newbie)
        self.assertNotIn("data-sponsor ", _row(html, self.newbie.stellar_address))
        self.assertIn("data-sponsor ", _row(html, self.veteran.stellar_address))
        anon = self.html_for(None)
        self.assertNotIn("data-sponsor", anon)

    def test_sponsoring_state_after_recommending(self):
        network.recommend(self.company, self.newbie, "")
        html = self.html_for(self.company)
        row = _row(html, self.newbie.stellar_address)
        self.assertIn('data-sponsoring="1"', row)
        self.assertIn('aria-pressed="true"', row)
        self.assertIn("Sponsoring ✓", row)
        self.assertIn('data-sponsoring="0"', _row(html, self.veteran.stellar_address))

    def test_json_carries_sponsoring_and_the_fingerprint_moves(self):
        login(self.client, self.company)
        before = self.client.get(self.json_url).json()
        self.assertEqual({c["sponsoring"] for c in before["candidates"]}, {False})
        network.recommend(self.company, self.newbie, "Solid")
        after = self.client.get(self.json_url).json()
        sponsoring = {c["freelancer"]: c["sponsoring"] for c in after["candidates"]}
        self.assertEqual(sponsoring, {self.newbie.stellar_address: True, self.veteran.stellar_address: False})
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        self.assertIn('data-sponsoring="1"', after["html"])
        # the order and the scores never read the network
        self.assertEqual(
            [(c["freelancer"], c["score"]) for c in before["candidates"]],
            [(c["freelancer"], c["score"]) for c in after["candidates"]],
        )

    def test_sponsor_through_the_endpoint_then_withdraw(self):
        login(self.client, self.company)
        headers = {"HTTP_X_REQUESTED_WITH": "fetch", "HTTP_ACCEPT": "application/json"}
        url = reverse("network:recommend", args=[self.newbie.stellar_address])
        res = self.client.post(url, data='{"message": "Clean work"}', content_type="application/json", **headers)
        self.assertEqual(res.json()["message"], "You now sponsor Lea.")
        self.assertIn('data-sponsoring="1"', _row(self.html_for(self.company), self.newbie.stellar_address))
        res = self.client.post(reverse("network:unrecommend", args=[self.newbie.stellar_address]), **headers)
        self.assertEqual(res.json()["message"], "Sponsorship withdrawn.")
        self.assertIn('data-sponsoring="0"', _row(self.html_for(self.company), self.newbie.stellar_address))

    def test_project_page_rows_carry_the_sponsor_button(self):
        login(self.client, self.company)
        html = self.client.get(reverse("projects:project_detail", kwargs={"pk": self.task.project_id})).content.decode()
        self.assertEqual(len(re.findall(r"data-sponsor ", html)), 2)
        self.assertIn("lowbid-network.js", html)

    def test_extra_queries_are_constant(self):
        """The new reads (history + sponsoring) cost two queries whatever the number of rows."""
        login(self.client, self.company)

        for i in range(3):
            services.apply(self.task, make_wallet(f"Extra {i}"), "", ["django"])
        with CaptureQueriesContext(connection) as five_rows:
            self.client.get(self.json_url)
        history = [q for q in five_rows if "payments_escrow" in q["sql"] and "assigned_to_id" in q["sql"]]
        sponsoring = [q for q in five_rows if "network_recommendation" in q["sql"] and "author_id\" = " in q["sql"]]
        self.assertEqual(len(history), 1, [q["sql"] for q in history])
        self.assertEqual(len(sponsoring), 1, [q["sql"] for q in sponsoring])
