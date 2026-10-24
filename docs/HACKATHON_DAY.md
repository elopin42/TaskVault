# Lowbid — Jour J (checklist hackathon)

Une page à ouvrir le matin et à garder sous les yeux. Le détail de la démo (comptes, minutage, Plan B minute par minute) est dans [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) ; la carte du code dans [`ARCHITECTURE.md`](ARCHITECTURE.md) ; le design system dans [`FRONTEND.md`](FRONTEND.md) ; les règles pour un assistant (Claude Code) dans [`../CLAUDE.md`](../CLAUDE.md).

---

## 1. Setup en 10 lignes (≈ 5 min)

```bash
git pull
cp -n .env.example .env            # puis remplir : voir §2
make dev                           # venv, deps, migrate, runserver 0.0.0.0:8000
# nouveau terminal
make seed                          # 3 wallets, 4 besoins (ouvert / bientôt clos / clos / attribué)
make check                         # ruff + 146 tests + tailwind à jour → doit être vert AVANT de toucher au code
npm run watch:css                  # (optionnel) si vous ajoutez des classes Tailwind dans les templates
```

Pré-requis : Python 3.13, Node 22 (seulement pour `make css` / `make e2e`), extension **Freighter** réglée sur **TESTNET** avec un compte financé.

## 2. Comptes Stellar & `.env` (voir `DEMO_RUNBOOK.md` §1.1 → §1.7)

| Quoi | Où | Note |
|------|----|------|
| 3 profils Chrome (client, freelance 1, freelance 2) + Freighter testnet | Runbook §1.1 | 1 wallet par profil |
| XLM (friendbot) sur les 4 comptes (3 acteurs + plateforme) | §1.2 | `https://friendbot.stellar.org/?addr=G…` |
| Trustline USDC sur les 4 comptes | §1.3 | Freighter → *Manage assets*, ou le bouton « Ajouter la trustline USDC » du panneau de paiement |
| USDC de test (faucet Circle, 10 USDC / adresse / 24 h) | §1.4 | d'où les montants ≤ 10 USDC de `seed_demo` |
| Clé API Trustless Work (testnet) | §1.5 | `TRUSTLESS_WORK_API_KEY=` ; vide ⇒ Plan B automatique |
| `.env` | §1.6 | `LOWBID_PLATFORM_ADDRESS=G…` (compte avec trustline), `LOWBID_DEMO_CLIENT/FREELANCE1/FREELANCE2=G…` pour que `make seed` utilise **vos** wallets |
| Smoke test Trustless Work | §1.8 / `STELLAR_NOTES.md` §6 | une fois, garder le `contractId` en capture |

`.env` est lu **une seule fois** au démarrage : après toute modification, `Ctrl-C` puis `make run`.

## 3. Vérification en 5 minutes (avant de coder, avant de filmer)

1. `curl -s localhost:8000/healthz/` → `{"ok": true, "db": true, "network": "testnet"}`.
2. `/` → « Connecter mon wallet Freighter » → popup de signature → l'adresse abrégée apparaît dans la barre, le menu wallet propose **Tableau de bord** / **Mon profil public**.
3. `/tableau-de-bord/` → KPIs + « À faire » (le besoin clos de la seed attend un choix).
4. `/besoins/nouveau/?demo=1` → publier un besoin (durée 5 min) → page détail avec compte à rebours.
5. Profil freelance → « Faire une offre » sous le plafond → la liste du client se met à jour **sans recharger** (point « live »).
6. Client → « Clôturer les enchères maintenant » → modale de confirmation → curseurs → « Choisir » sur une offre (pas forcément la recommandée).
7. Panneau Paiement : en mode escrow « Créer l'escrow » / « Bloquer les fonds » ; en Plan B « Payer le freelance ». Liens stellar.expert visibles après chaque étape.
8. Mobile (DevTools 390×844) : pas de scroll horizontal, barre d'onglets en bas, bouton collant sur le formulaire.

## 4. Répartition suggérée (par dossier, zéro conflit git)

| Personne | Dossiers | Sujets |
|----------|----------|--------|
| **Produit / pitch** | `docs/`, `README.md`, `docs/screenshots/` | vidéo, deck, README (adresses testnet, « Status / what works »), `make shots` |
| **Paiements / Stellar** | `payments/`, `templates/payments/`, `static/js/lowbid-pay.js`, `static/js/lowbid-wallet.js` | Trustless Work live, trustlines, Plan B, messages d'erreur |
| **Enchères / UI** | `auctions/`, `templates/auctions/`, `static/js/lowbid-auctions.js`, `static/css/` | règles, liste, détail, curseurs, mobile |
| **Dashboard / comptes** | `dashboard/`, `accounts/`, `core/`, `templates/partials/`, `templates/components/` | tableau de bord, profils, nav, landing |

Branche `main` directe (petit groupe) ou une branche par personne + PR : CI = ruff · tests · tailwind-in-sync.

## 5. « Où je change… ? »

| Je veux changer… | Fichier(s) |
|------------------|-----------|
| un texte de l'interface | le template sous `templates/<app>/` (grep la phrase), messages d'erreur métier dans `auctions/services.py` / `payments/services.py` |
| les couleurs / le thème | `static/css/lowbid-tokens.css` (dark `:root`, light `html[data-theme="light"]`) — jamais dans un composant |
| un composant (bouton, badge, carte…) | `static/css/lowbid-components.css` (+ bump `LOWBID_ASSET_VERSION`) |
| la navbar / la barre d'onglets mobile | `NAV_LINKS` dans `core/context_processors.py` ; markup `templates/partials/navbar.html` et `tabbar.html` |
| le menu du wallet | `templates/partials/navbar.html` (bloc `lb-wallet-dropdown`) |
| une nouvelle page | `CLAUDE.md` § « How to add a page » : vue → url → template (`components/`) → JS → test |
| la liste des besoins (filtres, tri, pagination) | `auctions/views.py::need_list`, `templates/auctions/need_list.html`, `_need_card.html` |
| la page d'un besoin | `auctions/views.py::need_detail` + `_bids_context`, `templates/auctions/need_detail.html`, `_bids_list.html`, `static/js/lowbid-auctions.js` |
| les poids du score (40/30/30) | `DEFAULT_WEIGHTS` dans `auctions/scoring.py` (+ texte landing / détail / `PRODUCT.md` §4) |
| les durées d'enchère proposées | `DURATION_CHOICES` / `DEMO_DURATION` dans `auctions/forms.py` |
| une règle d'enchère (R1–R14) | `auctions/services.py` (+ test dans `auctions/tests.py`) |
| une étape de paiement | `payments/services.py` (`prepare_<step>` / `confirm_<step>`, `stepper()`, `next_action()`), `payments/trustless_work.py`, `templates/payments/_escrow_panel.html` ; table d'états dans la docstring de `services.py` |
| le tableau de bord / le profil | `dashboard/views.py`, `dashboard/templates/dashboard/` |
| la seed de démo | `auctions/management/commands/seed_demo.py` |
| le panneau Plan B | `LOWBID_PAYMENT_MODE` dans `.env` (voir §6) |
| une variable d'environnement | `lowbid/settings.py` + `.env.example` |

## 6. Plan B pendant la démo

- Trustless Work tombe → `.env` : `LOWBID_PAYMENT_MODE=direct`, `Ctrl-C`, `make run`. Même page : le panneau passe en « Paiement direct USDC » (badge **Plan B**), un seul bouton client « Payer le freelance » / « Valider et payer ». Un besoin dont l'escrow est **déjà déployé** reste en mode escrow.
- Besoin de secours déjà attribué : `make seed` en produit un (`awarded=#<id>` dans la sortie) — ne pas hardcoder l'id (SQLite continue à compter après `--flush`).
- Détail des scénarios (signature qui échoue, Horizon en panne, tout cassé) : `DEMO_RUNBOOK.md` §4.

## 7. Hygiène de commit

```bash
npm run build:css        # si un template / JS a gagné une classe Tailwind (CI tailwind-in-sync)
# bump LOWBID_ASSET_VERSION dans lowbid/settings.py si lowbid-*.css / lowbid-*.js a changé
make check               # ruff + tests + tailwind à jour
git add -A && git commit -m "scope: what changed"
```

- Un commit = un sujet ; message en anglais, préfixe par app (`auctions:`, `payments:`, `docs:`).
- Jamais de `.env`, de `data/*.sqlite3` ni de `staticfiles/` dans git (déjà ignorés).
- Captures pour le pitch : `make shots` (met à jour `docs/screenshots/`).

## 8. Si ça casse — triage

| Symptôme | Regarder | Remède |
|----------|----------|--------|
| 500 au démarrage, `DJANGO_SECRET_KEY is required` | `.env` | `DJANGO_DEBUG=1` en dev, ou définir la clé |
| « Freighter est sur … ; passez sur TESTNET » | Freighter → réseau | basculer l'extension sur Testnet, recharger |
| Connexion impossible, 400 `bad_signature` | version de Freighter | `accounts/signing.py` essaie SEP-53 → brut → sha256 ; voir le log `scheme=` |
| La page semble ne pas prendre mon CSS / JS | cache 30 jours | bumper `LOWBID_ASSET_VERSION` (ou `DJANGO_DEBUG=1` ⇒ pas de cache) |
| CI `tailwind-in-sync` rouge | `tailwind.css` pas rebuild | `npm run build:css` puis commit |
| Offre refusée « strictement inférieur à X » | règle R1 | normal : le prix doit baisser ; la liste se rafraîchit |
| « Attendez la fin des enchères avant de choisir » | besoin encore `open` | « Clôturer les enchères maintenant » ou attendre le minuteur |
| Bouton de paiement : « Adresse plateforme non configurée » | `.env` | `LOWBID_PLATFORM_ADDRESS=G…` avec trustline USDC, restart |
| Trustless Work 4xx/5xx, `provider` | log `trustless_work:` | relancer ; sinon Plan B (§6) |
| Horizon 504 après signature | panneau : « transaction en attente » | le prochain `prepare` réconcilie via `/transactions/{hash}`, pas de 2ᵉ signature |
| Solde USDC « … » qui ne bouge pas | trustline manquante | bouton « Ajouter la trustline USDC », faucet Circle |
| e2e rouge | `data/e2e-server.log` | lire la première étape FAIL ; les erreurs Horizon sont attendues hors réseau |
| Tests rouges après une migration | `makemigrations --check` | `python manage.py makemigrations <app>` et committer |
