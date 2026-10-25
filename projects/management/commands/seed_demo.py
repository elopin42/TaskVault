"""Seed the demo dataset: 4 wallets, 3 projects.

  1. "Booking platform" at the pitch state — T1 "Landing page" paid to freelance A
     (note 5, with its Escrow row: a direct payment and a demo tx hash so the explorer links render),
     T2 "Freighter integration" open with A + B applying (A is Validated + Recommended:
     40 + 5·8 + 20·(1/2) = 90 vs B 0 + 0 + 20·(2/2) = 20), T3 "Dashboard" open, no candidate.
  2. A draft project with open tasks and no application.
  3. "Mobile app for a food truck", the anti-scam showcase:
     - "Menu page" chosen freelance B, delivered with a fingerprint and a full-deliverable link, sent back
       with a change request ("Please fix the mobile layout on the menu page."), then delivered again:
       `delivered`, revision 1/N, two Delivery rows + one RevisionRequest, review window running. A
       direct-mode Escrow row (like T1), so the company can still validate and pay it live.
     - "Order tracking" chosen freelance A, an ESCROW-mode row with demo contract id + deploy / fund /
       deliver / dispute hashes, delivered on chain (demo) then disputed by the company ("The demo does
       not match the agreed scope."): Task + Escrow `disputed`, a Dispute row, the funds locked. Its
       delivery link is on an unknown domain, so the "Unknown domain" warning shows on the page.
     Nothing in this project is on chain: the hashes are deterministic demo values (explorer links
     render, stellar.expert has nothing behind them) and the disputed escrow cannot be resolved live.

Addresses come from LOWBID_DEMO_CLIENT / LOWBID_DEMO_FREELANCE1 / LOWBID_DEMO_FREELANCE2 /
LOWBID_DEMO_ARBITER (so the Freighter accounts you own are the actors), else random — except the arbiter,
which falls back to LOWBID_DISPUTE_RESOLVER (else LOWBID_PLATFORM_ADDRESS) before a random key: `/litiges/`
opens only for the wallet equal to that setting. The dev DB is throwaway: `rm data/db.sqlite3` then
`make dev` after a models change.

With publication deposits active (escrow mode, payments.deposits.deposits_active) the pitch project gets a
funded deposit row (demo hashes) before taking applications, the draft stays unpublished (no deposit row),
and a fourth, cancelled project shows a deposit forfeited to the guarantee fund (/fonds/). Direct mode seeds
exactly the three projects above.

    python manage.py seed_demo [--flush]
"""

import base64
import hashlib
import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from payments import deposits
from payments import services as payment_services
from payments import stellar
from payments.models import Escrow, ProjectDeposit
from projects import services
from projects.models import Application, Delivery, Dispute, Project, Rating, RevisionRequest, Task


def _wallet(env_name: str, display: str, fallback: str = "") -> WalletUser:
    address = (os.environ.get(env_name) or "").strip() or fallback or Keypair.random().public_key
    wallet, _ = WalletUser.objects.get_or_create(stellar_address=address, defaults={"display_name": display})
    if not wallet.display_name:
        wallet.display_name = display
        wallet.save(update_fields=["display_name"])
    return wallet


def _demo_hash(label: str) -> str:
    """A deterministic 64-hex "tx hash" for the seeded payment (explorer links render, nothing on chain)."""
    return hashlib.sha256(f"taskvault-demo:{label}".encode()).hexdigest()


def _demo_contract(label: str) -> str:
    """A deterministic Soroban-looking contract id: "C" + 55 base32 characters (nothing deployed)."""
    digest = hashlib.sha512(f"taskvault-demo-contract:{label}".encode()).digest()
    return "C" + base64.b32encode(digest).decode()[:55]


class Command(BaseCommand):
    help = (
        "Create the TaskVault demo data: 4 wallets (company, freelancers A and B, arbiter), the pitch project "
        "(one paid task with its escrow row, one open task with two candidates, one open task), a draft project, "
        "and a food-truck project with a delivered task after a change request and a disputed escrow task."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush", action="store_true",
            help="Delete every Project first (tasks, applications, ratings, deliveries, change requests, disputes, escrows).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            deposit_rows, _ = ProjectDeposit.objects.all().delete()
            escrows, _ = Escrow.objects.all().delete()
            disputes, _ = Dispute.objects.all().delete()
            revisions, _ = RevisionRequest.objects.all().delete()
            deliveries, _ = Delivery.objects.all().delete()
            ratings, _ = Rating.objects.all().delete()
            apps, _ = Application.objects.all().delete()
            tasks, _ = Task.objects.all().delete()
            projects, _ = Project.objects.all().delete()
            self.stdout.write(
                f"flushed projects={projects} tasks={tasks} applications={apps} ratings={ratings} "
                f"deliveries={deliveries} revisions={revisions} disputes={disputes} escrows={escrows} deposits={deposit_rows}"
            )

        company = _wallet("LOWBID_DEMO_CLIENT", "Studio Nova (company)")
        a = _wallet("LOWBID_DEMO_FREELANCE1", "Yanis (freelancer A)")
        b = _wallet("LOWBID_DEMO_FREELANCE2", "Nora (freelancer B)")
        resolver = payment_services.resolver_address()  # LOWBID_DISPUTE_RESOLVER, else LOWBID_PLATFORM_ADDRESS
        arbiter = _wallet("LOWBID_DEMO_ARBITER", "TaskVault arbiter", fallback=resolver)
        mode = stellar.payment_mode()
        with_deposits = deposits.deposits_active()

        # 1. The pitch project: T1 paid to A, T2 open with A + B, T3 open.
        p1 = services.create_project(
            company,
            "Booking platform for a yoga studio",
            "Class booking website (schedule, memberships, USDC payment via Freighter) for a studio "
            "with 3 rooms. Figma mockups provided, deployment on our VPS. Split into three fixed-price tasks.",
        )
        t1 = services.add_task(
            p1, company, "Landing page", "Responsive home page (Django + Tailwind) from the mockup, contact form.",
            "300", ["django", "ui"],
        )
        t2 = services.add_task(
            p1, company, "Freighter integration",
            "Wallet connection, SEP-53 signature and USDC payment of a membership from the browser.",
            "500", ["stellar", "js"],
        )
        t3 = services.add_task(
            p1, company, "Dashboard", "Studio dashboard: occupancy rate, USDC revenue, CSV export.",
            "400", ["django", "charts"],
        )
        if with_deposits:
            _demo_deposit(p1, company, ProjectDeposit.Status.FUNDED)
        services.apply(t1, a, "Django + Tailwind every day, I deliver in 5 days including deployment.", ["django", "ui"])
        services.apply(t1, b, "Clean build from Figma, 2 iterations included.", ["django"])
        app_a = Application.objects.get(task=t1, freelancer=a)
        services.choose(t1, app_a, company)
        # T1 is settled as a DIRECT payment whatever the configured mode: the seed cannot sign anything
        # on chain, and a direct row is the only honest terminal state without a contract id. The row is
        # frozen in direct mode (status past `created`) BEFORE the DB-only delivery, which escrow mode refuses.
        link = "https://github.com/studio-nova/booking/pull/1"
        now = timezone.now()
        escrow = Escrow.objects.create(
            task=t1, mode=Escrow.Mode.DIRECT, status=Escrow.Status.DELIVERED, amount=t1.price,
            payer_address=company.stellar_address, payee_address=a.stellar_address, engagement_id=f"taskvault-task-{t1.pk}",
            delivery_note=link, delivered_at=now,
        )
        services.deliver(t1, a, link)
        services.validate(t1, company, 5, "Flawless, pixel-perfect and ahead of schedule.")  # Rating only: payments pays
        Escrow.objects.filter(pk=escrow.pk).update(status=Escrow.Status.PAID, payment_tx_hash=_demo_hash(f"t1-{t1.pk}"), released_at=now)
        services.mark_paid(t1)
        payment_services.sync_project_status(t1.project)  # what confirm_direct_pay / confirm_release do live
        services.apply(t2, a, "I have already wired Freighter and Horizon into a Django back office.", ["stellar"])
        services.apply(t2, b, "Stellar/JS specialist: SEP-53, trustlines, Soroban.", ["stellar", "js"])

        # 2. A draft project with open tasks and no candidate.
        p2 = services.create_project(
            company,
            "Brand and showcase website redesign for a bakery",
            "Vector logo, mini brand guide (colors, fonts) and a 5-page showcase website with opening hours and menu. "
            "Photos need light retouching, hosting already in place.",
        )
        services.add_task(p2, company, "Logo and brand guide", "Vector logo, 2 variants, mini brand guide. Figma files + exports.", "250", ["design", "figma"])
        services.add_task(p2, company, "WordPress showcase website", "5 pages, custom theme, green Core Web Vitals.", "600", ["wordpress", "seo"])
        services.add_task(p2, company, "Photo retouching", "30 product photos: cutouts, color grading, web exports.", "120", ["photo"])

        # 3. The anti-scam showcase: a delivery sent back for changes then delivered again, and a dispute.
        p3, t4, t5 = self._food_truck(company, a, b, arbiter)

        p4 = None
        if with_deposits:
            # 4. A ghost listing: candidates applied, nobody was chosen, the company cancelled → forfeited.
            p4 = services.create_project(
                company,
                "Pop-up bakery branding",
                "Logo, packaging and a one-page site for a pop-up bakery. Cancelled after the applications came in.",
            )
            t6 = services.add_task(p4, company, "Packaging design", "Boxes, bags and labels, print-ready files.", "300", ["design"])
            _demo_deposit(p4, company, ProjectDeposit.Status.FORFEITED)
            services.apply(t6, b, "Packaging for three food brands, print-ready in a week.", ["design"])
            services.cancel_project(p4, company)

        scores = {app.freelancer.display_name: f"{app.score:.1f}" for app in t2.applications.select_related("freelancer")}
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  payment mode {mode} (LOWBID_PAYMENT_MODE={os.environ.get('LOWBID_PAYMENT_MODE', '') or 'auto'}), asset {stellar.asset_code()}")
        self.stdout.write(f"  company      {company.stellar_address}")
        self.stdout.write(f"  freelancer A {a.stellar_address}")
        self.stdout.write(f"  freelancer B {b.stellar_address}")
        self.stdout.write(f"  arbiter      {arbiter.stellar_address}")
        self.stdout.write(f"  projects: pitch=#{p1.pk} (T1 #{t1.pk} paid, T2 #{t2.pk} open A+B, T3 #{t3.pk} open)  draft=#{p2.pk}")
        self.stdout.write(f"  T1 payment: direct, demo hash {_demo_hash(f't1-{t1.pk}')[:12]}… → {stellar.explorer_tx_url(_demo_hash(f't1-{t1.pk}'))}")
        self.stdout.write(f"  T2 scores: {scores}")
        p3.refresh_from_db()
        self.stdout.write(
            f"  food truck=#{p3.pk} ({p3.status}): T4 #{t4.pk} {t4.status} to B after {t4.revision_count} change request "
            f"({t4.deliveries.count()} deliveries, direct row), T5 #{t5.pk} {t5.status} (escrow row, funds locked, "
            f"contract {t5.escrow.contract_id[:8]}…)"
        )
        if resolver and resolver == arbiter.stellar_address:
            self.stdout.write("  /litiges/ opens for the arbiter wallet (= LOWBID_DISPUTE_RESOLVER / LOWBID_PLATFORM_ADDRESS).")
        else:
            self.stdout.write(self.style.WARNING(
                f"  /litiges/ is visible only to the wallet equal to LOWBID_DISPUTE_RESOLVER (or LOWBID_PLATFORM_ADDRESS): "
                f"set LOWBID_DISPUTE_RESOLVER={arbiter.stellar_address} in .env and restart to open it as the arbiter "
                f"(currently {resolver or 'unset'})."
            ))

        if with_deposits:
            self.stdout.write(f"  deposits: pitch=#{p1.pk} funded, draft=#{p2.pk} not published, ghost listing=#{p4.pk} forfeited (/fonds/)")

    def _food_truck(self, company: WalletUser, a: WalletUser, b: WalletUser, arbiter: WalletUser):
        """Project 3: T4 delivered again after a change request (direct row), T5 disputed (escrow row)."""
        now = timezone.now()
        p3 = services.create_project(
            company,
            "Mobile app for a food truck",
            "Mobile-first web app for a street-food truck: today's menu, live order tracking and a loyalty card. "
            "Two fixed-price tasks, each delivered with a fingerprint and checked before payment.",
        )
        t4 = services.add_task(
            p3, company, "Menu page", "Mobile-first menu page with daily specials, allergens and prices.",
            "350", ["ui", "mobile"],
        )
        t5 = services.add_task(
            p3, company, "Order tracking", "Live order status for customers (queued, cooking, ready) with a map of the truck.",
            "450", ["js", "maps"],
        )

        # T4 — chosen freelance B; delivered, sent back for changes, delivered again. Direct-mode row frozen
        # BEFORE the DB-only deliveries (escrow mode refuses them), moved like prepare_deliver does in direct mode.
        services.apply(t4, b, "Mobile-first UI is my daily job; I deliver a Vercel preview for every iteration.", ["ui", "mobile"])
        services.choose(t4, Application.objects.get(task=t4, freelancer=b), company)
        hash_1, hash_2 = _demo_hash(f"t4-v1-{t4.pk}")[:40], _demo_hash(f"t4-v2-{t4.pk}")[:40]
        link_1 = "https://foodtruck-menu-v1.vercel.app/menu"
        link_2 = "https://foodtruck-menu-v2.vercel.app/menu"
        source_1 = "https://github.com/nora-dev/foodtruck-menu/archive/v1.zip"
        source_2 = "https://github.com/nora-dev/foodtruck-menu/archive/v2.zip"
        escrow4 = Escrow.objects.create(
            task=t4, mode=Escrow.Mode.DIRECT, status=Escrow.Status.DELIVERED, amount=t4.price,
            payer_address=company.stellar_address, payee_address=b.stellar_address, engagement_id=f"taskvault-task-{t4.pk}",
            delivery_note=payment_services.build_evidence(link_1, hash_1), delivered_at=now - timedelta(days=2),
        )
        services.deliver(t4, b, link_1, delivery_hash=hash_1, source_link=source_1)
        services.request_changes(t4, company, "Please fix the mobile layout on the menu page.")  # escrow row → created
        t4 = services.deliver(t4, b, link_2, delivery_hash=hash_2, source_link=source_2)
        Escrow.objects.filter(pk=escrow4.pk).update(
            status=Escrow.Status.DELIVERED, delivery_note=payment_services.build_evidence(link_2, hash_2), delivered_at=t4.delivered_at,
        )
        # Spread the history over the last two days so the timeline reads like a real exchange.
        first, _second = list(t4.deliveries.order_by("created_at", "pk"))
        Delivery.objects.filter(pk=first.pk).update(created_at=now - timedelta(days=2))
        RevisionRequest.objects.filter(task=t4).update(created_at=now - timedelta(days=1))

        # T5 — chosen freelance A; an ESCROW-mode row as if deploy / fund / deliver / dispute had been signed
        # (demo hashes: the seed cannot sign), the delivery recorded with on_chain=True, then the company's dispute.
        services.apply(t5, a, "I built live order queues for two restaurants (polling + Leaflet maps).", ["js", "maps"])
        services.choose(t5, Application.objects.get(task=t5, freelancer=a), company)
        hash_5 = _demo_hash(f"t5-{t5.pk}")[:40]
        link_5 = "https://foodtruck-tracking.example.net/demo"  # an unknown domain: the page warns about it
        deliver_hash = _demo_hash(f"t5-deliver-{t5.pk}")
        escrow5 = Escrow.objects.create(
            task=t5, mode=Escrow.Mode.ESCROW, status=Escrow.Status.DELIVERED, amount=t5.price,
            payer_address=company.stellar_address, payee_address=a.stellar_address,
            platform_address=(getattr(settings, "LOWBID_PLATFORM_ADDRESS", "") or "").strip() or arbiter.stellar_address,
            resolver_address=arbiter.stellar_address, engagement_id=f"taskvault-task-{t5.pk}",
            contract_id=_demo_contract(f"t5-{t5.pk}"),
            deploy_tx_hash=_demo_hash(f"t5-deploy-{t5.pk}"), fund_tx_hash=_demo_hash(f"t5-fund-{t5.pk}"),
            deliver_tx_hash=deliver_hash, delivery_note=payment_services.build_evidence(link_5, hash_5),
            funded_at=now - timedelta(days=4), delivered_at=now - timedelta(days=1),
        )
        services.deliver(t5, a, link_5, delivery_hash=hash_5, on_chain=True, tx_hash=deliver_hash)
        t5 = services.mark_disputed(t5, company, "The demo does not match the agreed scope.")
        Escrow.objects.filter(pk=escrow5.pk).update(
            status=Escrow.Status.DISPUTED, dispute_tx_hash=_demo_hash(f"t5-dispute-{t5.pk}"), disputed_at=now,
        )
        payment_services.sync_project_status(p3)  # what confirm_fund / confirm_dispute do live
        t4.refresh_from_db()
        t5.refresh_from_db()
        return p3, t4, t5


def _demo_deposit(project: Project, company: WalletUser, status: str) -> ProjectDeposit:
    """A deposit row with demo hashes (nothing on chain): `funded` publishes the project, `forfeited` also
    carries the dispute / resolve hashes so /fonds/ lists it."""
    now = timezone.now()
    budget = project.total_amount
    label = f"deposit-{project.pk}"
    row = ProjectDeposit.objects.create(
        project=project,
        kind=ProjectDeposit.Kind.PUBLICATION,
        amount=deposits.deposit_amount(budget),
        covered_budget=budget,
        payer_address=company.stellar_address,
        platform_address=(os.environ.get("LOWBID_PLATFORM_ADDRESS") or "").strip() or company.stellar_address,
        resolver_address=company.stellar_address,
        fund_address=deposits.fund_address(),
        engagement_id=f"taskvault-deposit-{project.pk}-1",
        deploy_tx_hash=_demo_hash(f"{label}-deploy"),
        fund_tx_hash=_demo_hash(f"{label}-fund"),
        status=status,
        funded_at=now,
    )
    if status == ProjectDeposit.Status.FORFEITED:
        row.dispute_tx_hash = _demo_hash(f"{label}-dispute")
        row.resolve_tx_hash = _demo_hash(f"{label}-resolve")
        row.settled_at = now
        row.save(update_fields=["dispute_tx_hash", "resolve_tx_hash", "settled_at"])
    Project.objects.filter(pk=project.pk, published_at__isnull=True).update(published_at=now)
    project.refresh_from_db()
    return row
