"""Seed the demo dataset: 3 wallets, 4 needs (2 open with bids, 1 closed ready to
award, 1 awarded). Every amount stays under 10 USDC — what the Circle testnet faucet
hands out per day — so a seeded awarded need can really be paid live. Addresses come from LOWBID_DEMO_CLIENT / LOWBID_DEMO_FREELANCE1 /
LOWBID_DEMO_FREELANCE2 (so the Freighter accounts you own are the actors), else random.

    python manage.py seed_demo [--flush]
"""

import os
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from stellar_sdk import Keypair

from accounts.models import WalletUser
from auctions import services
from auctions.models import Bid, Need


def _wallet(env_name: str, display: str) -> WalletUser:
    address = (os.environ.get(env_name) or "").strip() or Keypair.random().public_key
    wallet, _ = WalletUser.objects.get_or_create(stellar_address=address, defaults={"display_name": display})
    if not wallet.display_name:
        wallet.display_name = display
        wallet.save(update_fields=["display_name"])
    return wallet


class Command(BaseCommand):
    help = "Create the Lowbid demo data (wallets, needs, bids)."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete every Need and Bid first.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            bids, _ = Bid.objects.all().delete()
            needs, _ = Need.objects.all().delete()
            self.stdout.write(f"flushed bids={bids} needs={needs}")

        client = _wallet("LOWBID_DEMO_CLIENT", "Claire (client)")
        f1 = _wallet("LOWBID_DEMO_FREELANCE1", "Yanis (freelance 1)")
        f2 = _wallet("LOWBID_DEMO_FREELANCE2", "Nora (freelance 2)")
        f3, _ = WalletUser.objects.get_or_create(
            stellar_address=Keypair.random().public_key, defaults={"display_name": "Freelance démo 3"}
        )
        now = timezone.now()

        def need(title, description, budget, delay, tags, ends_in: timedelta) -> Need:
            return Need.objects.create(
                client=client,
                title=title,
                description=description,
                budget_max=budget,
                delay_max_days=delay,
                tags=tags,
                bidding_ends_at=now + ends_in,
            )

        # 1. Open, the PRODUCT.md worked example scaled to faucet money (A = 9/8j/2 tags, B = 8/9j/1 tag).
        n1 = need(
            "Landing page Django + paiement Stellar",
            "Une landing page pour notre PME (12 salariés) : présentation, formulaire de contact, "
            "et un bouton de paiement USDC via Freighter. Maquette fournie, déploiement sur notre VPS.",
            "10", 10, ["django", "stellar", "ui"], timedelta(hours=2),
        )
        services.place_bid(n1, f1, "9", 8, ["django", "ui"], "Django + Tailwind, je livre en 8 jours avec le déploiement.")
        services.place_bid(n1, f2, "8", 9, ["stellar"], "Spécialiste Stellar, intégration Freighter incluse.")

        # 2. Open, closes soon, shows the "replace own bid" rule (f2 re-bids → outbid).
        n2 = need(
            "Dashboard analytics pour une boutique Shopify",
            "Tableau de bord ventes / stock avec export CSV. API Shopify déjà disponible, charte graphique à respecter.",
            "8", 7, ["react", "api"], timedelta(minutes=25),
        )
        services.place_bid(n2, f2, "7.5", 6, ["react", "api"], "React + Recharts, livraison en 6 jours.")
        services.place_bid(n2, f1, "7", 7, ["api"], "Backend solide, front sobre.")
        services.place_bid(n2, f2, "6.5", 5, ["react", "api"], "Je baisse à 6,50 et je livre en 5 jours.")

        # 3. Closed with 3 counting bids: the client can play with the sliders and choose.
        n3 = need(
            "Intégration paiement USDC (escrow Soroban)",
            "Brancher Trustless Work sur notre back-office : création de l’escrow, suivi des étapes, release. "
            "Testnet d’abord, mainnet si concluant.",
            "10", 14, ["stellar", "soroban", "rust"], timedelta(hours=1),
        )
        services.place_bid(n3, f1, "9", 12, ["stellar", "soroban"], "J’ai déjà intégré Trustless Work sur un projet.")
        services.place_bid(n3, f2, "8", 14, ["stellar"], "Prix serré, délai au max.")
        services.place_bid(n3, f3, "7", 10, ["rust"], "Dév Rust, découverte de Soroban.")
        Need.objects.filter(pk=n3.pk).update(status=Need.Status.CLOSED, bidding_ends_at=now - timedelta(minutes=10))

        # 4. Awarded: the payments panel takes over from here.
        n4 = need(
            "Refonte du logo et de la charte",
            "Logo vectoriel, 2 déclinaisons, mini charte (couleurs, typos). Fichiers Figma + exports.",
            "6", 5, ["design", "figma"], timedelta(hours=1),
        )
        won = services.place_bid(n4, f1, "5", 4, ["design", "figma"], "3 pistes, 2 itérations.")
        services.place_bid(n4, f2, "4.5", 5, ["design"], "Logo seul, charte en option.")
        services.close_bidding_now(n4, client)
        services.award(n4, won, client)
        Need.objects.filter(pk=n4.pk).update(bidding_ends_at=now - timedelta(hours=3), awarded_at=now - timedelta(hours=2))

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  client      {client.stellar_address}")
        self.stdout.write(f"  freelance 1 {f1.stellar_address}")
        self.stdout.write(f"  freelance 2 {f2.stellar_address}")
        self.stdout.write(f"  freelance 3 {f3.stellar_address}  (extra, random)")
        self.stdout.write(f"  needs: open=#{n1.pk} #{n2.pk}  closed=#{n3.pk}  awarded=#{n4.pk}")
