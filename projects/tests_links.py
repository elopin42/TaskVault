"""User-supplied links (docs/PRODUCT.md R43–R44): `link_info` and how every delivery / full-deliverable
link renders (components/ext_link.html) on the task page, the payment panel and the disputes desk."""

import os
import re
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from stellar_sdk import Keypair

from accounts.models import WalletUser

from . import services
from .models import Task
from .services import ProjectError
from .tests import BaseProjectTest, app_of, login

REL = 'rel="noopener noreferrer nofollow ugc"'
ARBITER = Keypair.random().public_key


class LinkInfoTests(TestCase):
    def test_trusted_host(self):
        info = services.link_info("https://github.com/studio-nova/booking/pull/1")
        self.assertEqual(info["host"], "github.com")
        self.assertTrue(info["trusted"])
        self.assertEqual(info["href"], "https://github.com/studio-nova/booking/pull/1")
        self.assertEqual(info["display"], "https://github.com/studio-nova/booking/pull/1")

    def test_subdomain_of_a_trusted_host(self):
        info = services.link_info("https://my-app.vercel.app/")
        self.assertEqual(info["host"], "my-app.vercel.app")
        self.assertTrue(info["trusted"])
        self.assertTrue(services.link_info("https://a.b.netlify.app/x")["trusted"])

    def test_untrusted_and_look_alike_hosts(self):
        for url in (
            "https://evil.example/x",
            "https://github.com.evil.example/a",  # a trusted name as a prefix is not the host
            "https://evilgithub.com/a",  # nor as a suffix without the dot
            "https://github.com@evil.example/a",  # userinfo trick: the host is evil.example
            "http://vercel.app.evil.example",
        ):
            info = services.link_info(url)
            self.assertFalse(info["trusted"], url)
            self.assertTrue(info["href"], url)
        self.assertEqual(services.link_info("https://github.com@evil.example/a")["host"], "evil.example")

    def test_uppercase_and_trailing_dot_hosts(self):
        info = services.link_info("HTTPS://GitHub.COM./Studio/Repo")
        self.assertEqual(info["host"], "github.com")
        self.assertTrue(info["trusted"])

    def test_idn_host_is_shown_as_punycode_and_untrusted(self):
        info = services.link_info("https://gïthub.com/a/b")  # a look-alike of github.com
        self.assertTrue(info["host"].startswith("xn--"), info["host"])
        self.assertFalse(info["trusted"])
        with override_settings(LOWBID_TRUSTED_LINK_HOSTS=["bücher.example"]):
            self.assertFalse(services.link_info("https://bücher.example/")["trusted"], "entries are compared as ASCII")

    def test_malformed_and_non_http_values_never_crash(self):
        for raw in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,hi", "https://[::1", "https://", "", None, "not a url", "ftp://github.com/x"):
            info = services.link_info(raw)
            self.assertEqual(info["href"], "", raw)
            self.assertFalse(info["trusted"], raw)
            self.assertEqual(info["host"], "", raw)

    def test_javascript_links_are_refused_upstream(self):
        for raw in ("javascript:alert(1)", " javascript://github.com/%0aalert(1)", "data:text/html,x"):
            with self.assertRaises(ProjectError) as ctx:
                services.clean_link(raw)
            self.assertEqual(ctx.exception.code, "invalid")
            with self.assertRaises(ProjectError):
                services.clean_source_link(raw)

    def test_long_url_display_is_cut(self):
        url = "https://github.com/" + "a" * 300
        info = services.link_info(url)
        self.assertEqual(info["href"], url)
        self.assertEqual(len(info["display"]), services.LINK_DISPLAY_MAX)
        self.assertTrue(info["display"].endswith("…"))

    @override_settings(LOWBID_TRUSTED_LINK_HOSTS=["example.org"])
    def test_override_settings(self):
        self.assertTrue(services.link_info("https://docs.example.org/x")["trusted"])
        self.assertFalse(services.link_info("https://github.com/a/b")["trusted"])

    @override_settings(LOWBID_TRUSTED_LINK_HOSTS=[])
    def test_no_trusted_host_means_every_link_warns(self):
        self.assertFalse(services.link_info("https://github.com/a/b")["trusted"])


class TaskPageLinkTests(BaseProjectTest):
    def deliver_t1(self, link: str, source: str = "") -> Task:
        services.apply(self.t1, self.a, "A", ["django"])
        services.choose(self.t1, app_of(self.t1, self.a), self.company)
        return services.deliver(self.t1, self.a, link, source_link=source)

    def page(self, wallet=None) -> str:
        if wallet is not None:
            login(self.client, wallet)
        return self.client.get(reverse("projects:task_detail", args=[self.t1.pk])).content.decode()

    def test_unknown_domain_shows_the_warning(self):
        self.deliver_t1("https://evil.example/x")
        html = self.page()
        self.assertIn("data-untrusted-host", html)
        self.assertIn("Unknown domain — open with care", html)
        self.assertIn('<span class="ui-link-host">', html)
        self.assertIn("evil.example", html)
        self.assertRegex(html, r'<a href="https://evil\.example/x"[^>]*data-delivery-link')

    def test_trusted_domain_shows_no_warning(self):
        self.deliver_t1("https://github.com/a/b")
        html = self.page()
        self.assertNotIn("data-untrusted-host", html)
        self.assertIn('<span class="ui-link-host">', html)
        self.assertRegex(html, r'<a href="https://github\.com/a/b"[^>]*data-delivery-link')

    @override_settings(LOWBID_TRUSTED_LINK_HOSTS=["evil.example"])
    def test_override_settings_reaches_the_page(self):
        self.deliver_t1("https://evil.example/x")
        self.assertNotIn("data-untrusted-host", self.page())

    def test_untrusted_source_link_warns_the_assignee(self):
        self.deliver_t1("https://github.com/a/b", source="https://files.example/archive.zip")
        html = self.page(self.a)
        self.assertIn("data-untrusted-host", html)
        self.assertRegex(html, r'<a href="https://files\.example/archive\.zip"[^>]*data-source-link')
        # The company does not get the source link (nor its warning) before payment.
        html = self.page(self.company)
        self.assertNotIn("files.example", html)
        self.assertNotIn("data-untrusted-host", html)


def _user_anchors(html: str, urls: set[str]) -> list[str]:
    """Every <a> whose href is one of the user-supplied URLs, plus every ext_link anchor."""
    anchors = re.findall(r"<a\s[^>]*>", html)
    return [a for a in anchors if "ui-ext-anchor" in a or any(f'href="{u}"' in a for u in urls)]


@override_settings(LOWBID_DISPUTE_RESOLVER=ARBITER, LOWBID_PLATFORM_ADDRESS="")
class RelAttributeTests(TestCase):
    """On the seeded data: every delivery / full-deliverable link (task page, payment panel, history,
    disputes desk) carries exactly rel="noopener noreferrer nofollow ugc" and opens in a new tab."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("LOWBID_DEMO_CLIENT", "LOWBID_DEMO_FREELANCE1", "LOWBID_DEMO_FREELANCE2", "LOWBID_DEMO_ARBITER"):
            os.environ.pop(name, None)
        call_command("seed_demo", "--flush", stdout=StringIO())

    def check(self, html: str, task: Task, minimum: int) -> None:
        urls = set()
        for d in task.deliveries.all():
            urls.update(u for u in (d.delivery_link, d.source_link) if u)
        anchors = _user_anchors(html, urls)
        self.assertGreaterEqual(len(anchors), minimum, anchors)
        for anchor in anchors:
            rels = re.findall(r'rel="[^"]*"', anchor)
            self.assertEqual(rels, [REL], anchor)
            self.assertIn('target="_blank"', anchor)

    def test_task_page_panel_and_history(self):
        task = Task.objects.get(title="Menu page")
        login(self.client, task.assigned_to)  # the assignee sees the source links too
        html = self.client.get(reverse("projects:task_detail", args=[task.pk])).content.decode()
        self.assertIn('id="escrow-panel"', html)
        # delivery panel link + its source, panel source, history: 2 deliveries + 2 sources
        self.check(html, task, minimum=6)
        self.assertEqual(html.count("data-source-link"), 4)

    def test_disputes_desk(self):
        task = Task.objects.get(title="Order tracking")
        login(self.client, WalletUser.objects.get(stellar_address=ARBITER))
        response = self.client.get(reverse("projects:disputes"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.check(html, task, minimum=2)  # the card's delivery link + the history row
        self.assertIn("data-untrusted-host", html, "the seeded dispute link is on an unknown domain")

    def test_disputed_task_page_warns(self):
        task = Task.objects.get(title="Order tracking")
        html = self.client.get(reverse("projects:task_detail", args=[task.pk])).content.decode()
        self.check(html, task, minimum=2)
        self.assertIn("data-untrusted-host", html)
