from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.templatetags.lowbid_extras import plain, short_addr, usdc


class LandingTests(TestCase):
    def test_landing_renders(self):
        resp = self.client.get(reverse("core:landing"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Lowbid")
        self.assertContains(resp, "data-wallet-connect")
        self.assertContains(resp, "prix fixe")
        self.assertContains(resp, "Recommandé")
        self.assertContains(resp, "data-landing-stats")
        self.assertNotContains(resp, "enchère")

    def test_landing_stats_and_latest_projects(self):
        from decimal import Decimal

        from stellar_sdk import Keypair

        from accounts.models import WalletUser
        from projects import services

        company = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        project = services.create_project(company, "Projet vitrine", "Une description.")
        services.add_task(project, company, "Landing page", "", "300", ["django", "ui"])
        resp = self.client.get(reverse("core:landing"))
        self.assertEqual(resp.context["stats"], {"open_tasks": 1, "projects": 1, "paid_usdc": 0})
        self.assertEqual([p.pk for p in resp.context["latest_projects"]], [project.pk])
        self.assertEqual(resp.context["latest_projects"][0].tag_list, ["django", "ui"])
        self.assertContains(resp, "project-card")
        self.assertEqual(resp.context["latest_projects"][0].total_amount, Decimal("300"))

    def test_landing_ignores_offsite_next(self):
        resp = self.client.get(reverse("core:landing") + "?next=https://evil.example/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["next_url"], "")

    def test_landing_keeps_relative_next(self):
        resp = self.client.get(reverse("core:landing") + "?next=/projets/nouveau/")
        self.assertEqual(resp.context["next_url"], "/projets/nouveau/")


class HealthzTests(TestCase):
    def test_healthz(self):
        resp = self.client.get(reverse("core:healthz"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["db"])
        self.assertEqual(data["network"], "testnet")


class FilterTests(TestCase):
    def test_short_addr(self):
        addr = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
        self.assertEqual(short_addr(addr), "GBBD…FLA5")
        self.assertEqual(short_addr(""), "")
        self.assertEqual(short_addr("GABC"), "GABC")

    def test_usdc(self):
        self.assertEqual(usdc("1234.5"), "1,234.50 USDC")
        self.assertEqual(usdc(0), "0.00 USDC")
        self.assertEqual(usdc(None), "—")

    def test_underline_last(self):
        from core.templatetags.lowbid_extras import underline_last

        self.assertEqual(underline_last("Mes projets"), '<span class="ui-title">Mes <span class="ui-underline">projets</span></span>')
        self.assertEqual(underline_last("Projets"), '<span class="ui-title"><span class="ui-underline">Projets</span></span>')
        self.assertEqual(underline_last("a <b>"), '<span class="ui-title">a <span class="ui-underline">&lt;b&gt;</span></span>')
        self.assertEqual(underline_last(""), "")

    def test_plain(self):
        self.assertEqual(plain(Decimal("500.0000000")), "500")
        self.assertEqual(plain(Decimal("400.5000000")), "400.5")
        self.assertEqual(plain(None), "")


class NavLinksTests(TestCase):
    def _active(self, path):
        resp = self.client.get(path)
        return [link["label"] for link in resp.context["nav_links"] if link["active"]]

    def test_only_the_most_specific_link_is_active(self):
        self.assertEqual(self._active(reverse("projects:project_list")), ["Projets"])
        # /projets/nouveau/ redirects anonymous users to the landing: inspect the context processor directly.
        from django.test import RequestFactory

        from core.context_processors import nav_links

        links = nav_links(RequestFactory().get(reverse("projects:project_create")))["nav_links"]
        self.assertEqual([link["label"] for link in links if link["active"]], ["Nouveau projet"])
        links = nav_links(RequestFactory().get(reverse("projects:board")))["nav_links"]
        self.assertEqual([link["label"] for link in links if link["active"]], ["Tableau"])

    def test_nav_links_cover_the_task_board(self):
        resp = self.client.get(reverse("core:landing"))
        labels = [link["label"] for link in resp.context["nav_links"]]
        self.assertEqual(labels, ["Projets", "Tableau", "Nouveau projet", "Mes projets", "Tableau de bord"])
        hrefs = {link["label"]: link["href"] for link in resp.context["nav_links"]}
        self.assertEqual(hrefs["Tableau"], "/taches/")
        self.assertEqual(hrefs["Mes projets"], "/mes-projets/")
        public = [link["label"] for link in resp.context["nav_links"] if not link["wallet"]]
        self.assertEqual(public, ["Projets"])

    def test_landing_has_no_active_link(self):
        self.assertEqual(self._active(reverse("core:landing")), [])


class ErrorPageTests(TestCase):
    def test_custom_404_template(self):
        with self.settings(DEBUG=False):
            resp = self.client.get("/cette-page-n-existe-pas/")
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "404.html")
        self.assertContains(resp, "Page introuvable", status_code=404)
