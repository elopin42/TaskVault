"""Seed the demo dataset (SPEC §8): 4 wallets, 2 projects, a small trust network.

  1. "Booking platform" at the pitch state — T1 "Landing page" paid to freelance A
     (note 5, with its Escrow row: a direct payment and a demo tx hash so the explorer links render),
     T2 "Freighter integration" open with A + B applying (A is Validated + Recommended:
     40 + 5·8 + 20·(1/2) = 90 vs B 0 + 0 + 20·(2/2) = 20), T3 "Dashboard" open with C applying.
  2. A draft project with open tasks and no application.
  3. The trust network (one hop, never touches a score): the company follows A, A recommends C
     (with a message) and A follows B. Signed in as the company you therefore see
     "Yanis (freelancer A) recommends" on C's candidate row on T3, "Followed by Yanis (freelancer A)"
     on B's row on T2, and "Following" on A.

Wallets: the company, freelancers A (Yanis), B (Nora) and C (Chloé). Addresses come from
LOWBID_DEMO_CLIENT / LOWBID_DEMO_FREELANCE1 / LOWBID_DEMO_FREELANCE2 / LOWBID_DEMO_FREELANCE3 (so the
Freighter accounts you own are the actors), else random. The dev DB is throwaway: `rm data/db.sqlite3`
then `make dev` after a models change.

    python manage.py seed_demo [--flush]
"""

import hashlib
import os

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from network import services as network
from network.models import Follow, Recommendation
from payments import services as payment_services
from payments import stellar
from payments.models import Escrow
from projects import services
from projects.models import Application, Project, Rating, Task


def _wallet(env_name: str, display: str) -> WalletUser:
    address = (os.environ.get(env_name) or "").strip() or Keypair.random().public_key
    wallet, _ = WalletUser.objects.get_or_create(stellar_address=address, defaults={"display_name": display})
    if not wallet.display_name:
        wallet.display_name = display
        wallet.save(update_fields=["display_name"])
    return wallet


def _demo_hash(label: str) -> str:
    """A deterministic 64-hex "tx hash" for the seeded payment (explorer links render, nothing on chain)."""
    return hashlib.sha256(f"lowbid-demo:{label}".encode()).hexdigest()


class Command(BaseCommand):
    help = "Create the Lowbid demo data (wallets, projects, tasks, applications, one paid task with its escrow row)."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete every Project (tasks, applications, ratings, escrows), Follow and Recommendation first.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            escrows, _ = Escrow.objects.all().delete()
            ratings, _ = Rating.objects.all().delete()
            apps, _ = Application.objects.all().delete()
            tasks, _ = Task.objects.all().delete()
            projects, _ = Project.objects.all().delete()
            follows, _ = Follow.objects.all().delete()
            recommendations, _ = Recommendation.objects.all().delete()
            self.stdout.write(
                f"flushed projects={projects} tasks={tasks} applications={apps} ratings={ratings} escrows={escrows} "
                f"follows={follows} recommendations={recommendations}"
            )

        company = _wallet("LOWBID_DEMO_CLIENT", "Studio Nova (company)")
        a = _wallet("LOWBID_DEMO_FREELANCE1", "Yanis (freelancer A)")
        b = _wallet("LOWBID_DEMO_FREELANCE2", "Nora (freelancer B)")
        c = _wallet("LOWBID_DEMO_FREELANCE3", "Chloé (freelancer C)")
        mode = stellar.payment_mode()

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
            payer_address=company.stellar_address, payee_address=a.stellar_address, engagement_id=f"lowbid-task-{t1.pk}",
            delivery_note=link, delivered_at=now,
        )
        services.deliver(t1, a, link)
        services.validate(t1, company, 5, "Flawless, pixel-perfect and ahead of schedule.")  # Rating only: payments pays
        Escrow.objects.filter(pk=escrow.pk).update(status=Escrow.Status.PAID, payment_tx_hash=_demo_hash(f"t1-{t1.pk}"), released_at=now)
        services.mark_paid(t1)
        payment_services.sync_project_status(t1.project)  # what confirm_direct_pay / confirm_release do live
        services.apply(t2, a, "I have already wired Freighter and Horizon into a Django back office.", ["stellar"])
        services.apply(t2, b, "Stellar/JS specialist: SEP-53, trustlines, Soroban.", ["stellar", "js"])
        services.apply(t3, c, "Django dashboards with Chart.js and CSV exports are my daily job, 6 days.", ["django", "charts"])

        # 3. The trust network (one hop): company → A, A recommends C, A → B. Scores are untouched.
        network.follow(company, a)
        recommendation = "Chloé shipped our analytics dashboard in a week, clean Django and sharp charts."
        network.recommend(a, c, recommendation)
        network.follow(a, b)

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

        scores = {app.freelancer.display_name: f"{app.score:.1f}" for app in t2.applications.select_related("freelancer")}
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  payment mode {mode} (LOWBID_PAYMENT_MODE={os.environ.get('LOWBID_PAYMENT_MODE', '') or 'auto'}), asset {stellar.asset_code()}")
        self.stdout.write(f"  company      {company.stellar_address}")
        self.stdout.write(f"  freelancer A {a.stellar_address}")
        self.stdout.write(f"  freelancer B {b.stellar_address}")
        self.stdout.write(f"  freelancer C {c.stellar_address}")
        self.stdout.write(f"  projects: pitch=#{p1.pk} (T1 #{t1.pk} paid, T2 #{t2.pk} open A+B, T3 #{t3.pk} open C)  draft=#{p2.pk}")
        self.stdout.write("  network: company follows A, A recommends C, A follows B")
        self.stdout.write("    as the company: T3 C \"Yanis (freelancer A) recommends\", T2 B \"Followed by Yanis (freelancer A)\"")
        self.stdout.write(f"  T1 payment: direct, demo hash {_demo_hash(f't1-{t1.pk}')[:12]}… → {stellar.explorer_tx_url(_demo_hash(f't1-{t1.pk}'))}")
        self.stdout.write(f"  T2 scores: {scores}")
