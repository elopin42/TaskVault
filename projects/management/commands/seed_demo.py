"""Seed the demo dataset (SPEC §8): 3 wallets, 2 projects.

  1. "Plateforme de réservation" at the pitch state — T1 "Landing page" paid to freelance A
     (note 5, with its Escrow row: a direct payment and a demo tx hash so the explorer links render),
     T2 "Intégration Freighter" open with A + B applying (A is Validé + Recommandé:
     40 + 5·8 + 20·(1/2) = 90 vs B 0 + 0 + 20·(2/2) = 20), T3 "Dashboard" open, no candidate.
  2. A draft project with open tasks and no application.

Addresses come from LOWBID_DEMO_CLIENT / LOWBID_DEMO_FREELANCE1 / LOWBID_DEMO_FREELANCE2 (so the
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
        parser.add_argument("--flush", action="store_true", help="Delete every Project (tasks, applications, ratings, escrows) first.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            escrows, _ = Escrow.objects.all().delete()
            ratings, _ = Rating.objects.all().delete()
            apps, _ = Application.objects.all().delete()
            tasks, _ = Task.objects.all().delete()
            projects, _ = Project.objects.all().delete()
            self.stdout.write(f"flushed projects={projects} tasks={tasks} applications={apps} ratings={ratings} escrows={escrows}")

        company = _wallet("LOWBID_DEMO_CLIENT", "Studio Nova (entreprise)")
        a = _wallet("LOWBID_DEMO_FREELANCE1", "Yanis (freelance A)")
        b = _wallet("LOWBID_DEMO_FREELANCE2", "Nora (freelance B)")
        mode = stellar.payment_mode()

        # 1. The pitch project: T1 paid to A, T2 open with A + B, T3 open.
        p1 = services.create_project(
            company,
            "Plateforme de réservation pour un studio de yoga",
            "Site de réservation de cours (planning, abonnements, paiement USDC via Freighter) pour un studio "
            "de 3 salles. Maquettes Figma fournies, déploiement sur notre VPS. Découpé en trois tâches à prix fixe.",
        )
        t1 = services.add_task(
            p1, company, "Landing page", "Page d’accueil responsive (Django + Tailwind) depuis la maquette, formulaire de contact.",
            "300", ["django", "ui"],
        )
        t2 = services.add_task(
            p1, company, "Intégration Freighter",
            "Connexion wallet, signature SEP-53 et paiement USDC d’un abonnement depuis le navigateur.",
            "500", ["stellar", "js"],
        )
        t3 = services.add_task(
            p1, company, "Dashboard", "Tableau de bord du studio : taux de remplissage, revenus USDC, export CSV.",
            "400", ["django", "charts"],
        )
        services.apply(t1, a, "Django + Tailwind au quotidien, je livre en 5 jours avec le déploiement.", ["django", "ui"])
        services.apply(t1, b, "Intégration propre depuis Figma, 2 itérations comprises.", ["django"])
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
        services.validate(t1, company, 5, "Impeccable, pixel-perfect et en avance.")  # Rating only: payments pays
        Escrow.objects.filter(pk=escrow.pk).update(status=Escrow.Status.PAID, payment_tx_hash=_demo_hash(f"t1-{t1.pk}"), released_at=now)
        services.mark_paid(t1)
        payment_services.sync_project_status(t1.project)  # what confirm_direct_pay / confirm_release do live
        services.apply(t2, a, "J’ai déjà branché Freighter et Horizon sur un back-office Django.", ["stellar"])
        services.apply(t2, b, "Spécialiste Stellar/JS : SEP-53, trustlines, Soroban.", ["stellar", "js"])

        # 2. A draft project with open tasks and no candidate.
        p2 = services.create_project(
            company,
            "Refonte de la charte et du site vitrine d’une boulangerie",
            "Logo vectoriel, mini charte (couleurs, typos) et site vitrine 5 pages avec horaires et carte. "
            "Photos à retoucher légèrement, hébergement déjà en place.",
        )
        services.add_task(p2, company, "Logo et charte", "Logo vectoriel, 2 déclinaisons, mini charte. Fichiers Figma + exports.", "250", ["design", "figma"])
        services.add_task(p2, company, "Site vitrine WordPress", "5 pages, thème sur mesure, Core Web Vitals verts.", "600", ["wordpress", "seo"])
        services.add_task(p2, company, "Retouche photos", "30 photos produits : détourage, colorimétrie, exports web.", "120", ["photo"])

        scores = {app.freelancer.display_name: f"{app.score:.1f}" for app in t2.applications.select_related("freelancer")}
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  payment mode {mode} (LOWBID_PAYMENT_MODE={os.environ.get('LOWBID_PAYMENT_MODE', '') or 'auto'}), asset {stellar.asset_code()}")
        self.stdout.write(f"  entreprise  {company.stellar_address}")
        self.stdout.write(f"  freelance A {a.stellar_address}")
        self.stdout.write(f"  freelance B {b.stellar_address}")
        self.stdout.write(f"  projects: pitch=#{p1.pk} (T1 #{t1.pk} paid, T2 #{t2.pk} open A+B, T3 #{t3.pk} open)  draft=#{p2.pk}")
        self.stdout.write(f"  T1 payment: direct, demo hash {_demo_hash(f't1-{t1.pk}')[:12]}… → {stellar.explorer_tx_url(_demo_hash(f't1-{t1.pk}'))}")
        self.stdout.write(f"  T2 scores: {scores}")
