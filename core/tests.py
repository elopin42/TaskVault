from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.templatetags.lowbid_extras import plain, short_addr, usdc, usdc_parts


class LandingTests(TestCase):
    def test_landing_renders(self):
        resp = self.client.get(reverse("core:landing"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Lowbid")
        self.assertContains(resp, "data-wallet-connect")
        self.assertRegex(resp.content.decode(), r"(?i)fixed[- ]price")
        self.assertContains(resp, "data-landing-stats")
        self.assertNotRegex(resp.content.decode(), r"(?i)auction|enchère")

    def test_landing_stats_and_latest_projects(self):
        from decimal import Decimal

        from stellar_sdk import Keypair

        from accounts.models import WalletUser
        from projects import services

        company = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        project = services.create_project(company, "Showcase project", "Une description.")
        services.add_task(project, company, "Landing page", "", "300", ["django", "ui"])
        resp = self.client.get(reverse("core:landing"))
        self.assertEqual(resp.context["stats"], {"open_tasks": 1, "projects": 1, "paid_usdc": 0})
        self.assertEqual([p.pk for p in resp.context["latest_projects"]], [project.pk])
        self.assertEqual(resp.context["latest_projects"][0].tag_list, ["django", "ui"])
        self.assertContains(resp, "project-card")
        self.assertEqual(resp.context["latest_projects"][0].total_amount, Decimal("300"))

    def test_landing_ledger_tape_comes_from_real_escrows(self):
        from stellar_sdk import Keypair

        from accounts.models import WalletUser
        from payments.models import Escrow
        from projects import services

        company = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        freelance = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        project = services.create_project(company, "Showcase project", "Une description.")
        task = services.add_task(project, company, "Landing page", "", "300", ["django"])
        # Open task only: no on-chain event, no tape.
        resp = self.client.get(reverse("core:landing"))
        self.assertEqual(resp.context["tape"], [])
        self.assertContains(resp, "data-story")
        self.assertNotContains(resp, "lb-tape-item")

        Escrow.objects.create(
            task=task, mode=Escrow.Mode.ESCROW, amount=Decimal("300"), payer_address=company.stellar_address,
            payee_address=freelance.stellar_address, status=Escrow.Status.FUNDED,
            deploy_tx_hash="a" * 64, fund_tx_hash="b" * 64,
        )
        resp = self.client.get(reverse("core:landing"))
        labels = {e["label"] for e in resp.context["tape"]}
        self.assertEqual(labels, {"ESCROW CREATED", "FUNDS LOCKED"})
        self.assertGreaterEqual(len(resp.context["tape"]), 8)  # looped so one copy fills the viewport
        self.assertContains(resp, "FUNDS LOCKED")

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

    def test_usdc_parts(self):
        self.assertEqual(usdc_parts("1234.5"), '1,234<span class="ui-dec">.50</span>')
        self.assertEqual(usdc_parts(None), "—")

    def test_underline_last(self):
        from core.templatetags.lowbid_extras import underline_last

        self.assertEqual(underline_last("My projects"), '<span class="ui-title">My <span class="ui-underline">projects</span></span>')
        self.assertEqual(underline_last("Projects"), '<span class="ui-title"><span class="ui-underline">Projects</span></span>')
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
        self.assertEqual(self._active(reverse("projects:project_list")), ["Projects"])
        # /projets/nouveau/ redirects anonymous users to the landing: inspect the context processor directly.
        from django.test import RequestFactory

        from core.context_processors import nav_links

        links = nav_links(RequestFactory().get(reverse("projects:project_create")))["nav_links"]
        self.assertEqual([link["label"] for link in links if link["active"]], ["New project"])
        links = nav_links(RequestFactory().get(reverse("projects:board")))["nav_links"]
        self.assertEqual([link["label"] for link in links if link["active"]], ["Board"])

    def test_nav_links_cover_the_task_board(self):
        resp = self.client.get(reverse("core:landing"))
        labels = [link["label"] for link in resp.context["nav_links"]]
        self.assertEqual(labels, ["Projects", "Board", "New project", "My projects", "Dashboard"])
        hrefs = {link["label"]: link["href"] for link in resp.context["nav_links"]}
        self.assertEqual(hrefs["Board"], "/taches/")
        self.assertEqual(hrefs["My projects"], "/mes-projets/")
        public = [link["label"] for link in resp.context["nav_links"] if not link["wallet"]]
        self.assertEqual(public, ["Projects"])

    def test_landing_has_no_active_link(self):
        self.assertEqual(self._active(reverse("core:landing")), [])

    def test_signed_in_links_are_hidden_from_anonymous_visitors(self):
        from stellar_sdk import Keypair

        from accounts.models import WalletUser

        # Desktop nav + mobile nav: only "Projects" for an anonymous visitor, all five once signed in.
        html = self.client.get(reverse("core:landing")).content.decode()
        self.assertEqual(html.count('class="lb-nav-link"') + html.count('class="lb-nav-link is-active"'), 2)
        wallet = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        session = self.client.session
        session["wallet_user_id"] = wallet.pk
        session["wallet_address"] = wallet.stellar_address
        session.save()
        html = self.client.get(reverse("core:landing")).content.decode()
        self.assertEqual(html.count('class="lb-nav-link"') + html.count('class="lb-nav-link is-active"'), 10)


class ErrorPageTests(TestCase):
    def test_custom_404_template(self):
        with self.settings(DEBUG=False):
            resp = self.client.get("/cette-page-n-existe-pas/")
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "404.html")
        self.assertContains(resp, "Page not found", status_code=404)
