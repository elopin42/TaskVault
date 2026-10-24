> 🇫🇷 La démo et l'interface sont en français. This README is in English for the judges.

# Lowbid 📉

**A client posts a need and a maximum budget, freelancers bid the price down, and the winner is paid in USDC through an on-chain escrow on Stellar.**

- **Demo video:** TODO: link
- **Pitch deck:** TODO: link
- **Hackathon:** Hack Meridian (Stellar), track **Composed**

---

## What it does

```
   CLIENT                         LOWBID (Django)                     STELLAR (testnet)
   ------                         ---------------                     -----------------
1. Connect Freighter  ----------> signMessage check     <----------- Freighter wallet
2. Post a need        ----------> need saved (open)
   budget max, delay max,         countdown starts
   3 tags, duration
                       FREELANCERS
3.                     Connect Freighter -------------> signMessage check
4.                     Bid: price < last bid ---------> rule checked, bid saved
                       + delay, tags, message
5.                                timer ends (or client closes) -> need closed
6.                                score each bid, "Recommandé" badge
7. Review offers, adjust sliders
8. Choose a freelancer ---------> need awarded
9. "Créer l'escrow"    ---------> Trustless Work API --------------> Soroban escrow deployed
   "Bloquer les fonds" ---------> (proxied by Django) -------------> USDC locked in the escrow
                       "Déclarer la livraison" (freelancer) -------> milestone marked done
10. "Valider la livraison" -----> approve -------------------------> milestone approved
    "Libérer les fonds" --------> release -------------------------> escrow releases USDC
                                                                     to the freelancer wallet
Plan B (LOWBID_PAYMENT_MODE=direct): steps 9-10 become one "Payer le freelance" USDC payment.
```

1. The client connects their **Freighter** wallet (Stellar testnet). Login is a signed message, no password.
2. The client posts a need: title, description, **maximum budget (USDC)**, **maximum delay (days)**, up to 3 skill tags, and a bidding duration (30 min, 2 h, 24 h or 3 days; `?demo=1` adds a 5-minute option).
3. Freelancers connect their own Freighter wallet.
4. Each freelancer bids: price, delay in days, tags, short message. **A bid must be strictly lower than the previous bid**, or it is refused.
5. When the countdown ends (or the client clicks "Clôturer les enchères maintenant"), bidding closes.
6. Lowbid computes a score for every bid and puts a **"Recommandé"** badge on the best one.
7. The client can reweight price / delay / skills with three sliders.
8. **The client chooses.** The recommendation is an aid, not a rule: any bid can win.
9. The client funds the job in two Freighter signatures: **"Créer l'escrow"** (Trustless Work deploys a Soroban single-release escrow) then **"Bloquer les fonds"** (the USDC moves into the contract).
10. The freelancer clicks **"Déclarer la livraison"**; the client clicks **"Valider la livraison"** then **"Libérer les fonds"**, and the escrow pays the USDC to the freelancer (minus fees). Every button is one signature by the wallet that holds that role.

Around the flow: a **dashboard** (`/tableau-de-bord/`, the signed-in home) lists what the wallet has to do next (offers to choose, payments to sign, deliveries to declare) with KPIs as client and as freelancer, and every wallet has a **public profile** (`/profil/<address>/`: identicon, display name, needs posted, bids won). The needs list has text search, tag filters, sorting and pagination; the need page shows the price history and the full bid timeline. Dark and light themes, mobile-first (stacked cards, bottom tab bar), no horizontal scroll.

## Why Stellar

- **USDC** on Stellar: the freelancer gets a dollar-stable payment, not a volatile token.
- **Speed and cost:** settlement in about 5 seconds, fees around 0.00001 XLM. A 50 USDC job is not eaten by fees.
- **Escrow on Soroban via Trustless Work:** funds are locked by a smart contract, not held by a platform for weeks. Neither side can run away with the money.
- **Freighter:** the wallet is the identity. Both login and every payment are signed by the user in their own wallet; Lowbid never holds a private key.
- **No bank in the loop:** no 10 to 20% platform cut, no wire delays.

## Scoring

For each bid, after the deadline:

```
score = 40 * (1 - price / max_budget)
      + 30 * (1 - delay / max_delay)
      + 30 * (common_tags / requested_tags)
```

Each term is clamped to `[0, 1]` before weighting. Default weights are 40 / 30 / 30; the client can move three sliders (they always sum to 100). The highest score gets the "Recommandé" badge. Worked examples are in [`docs/PRODUCT.md`](docs/PRODUCT.md).

## Run it locally

Prerequisites: **Python 3.13**, **Node 22** (only if you rebuild the CSS), the **Freighter** browser extension set to **TESTNET** with a funded account.

```bash
cp .env.example .env
make dev
# open http://localhost:8000
```

`.env` is read once at startup: after any change (API key, `LOWBID_PAYMENT_MODE`, demo wallets…) stop the server and run `make run` again.

Tests: `make test` (Django unit + payment-flow tests, network mocked) and `make e2e` (Playwright flow test in a real browser with a simulated Freighter, on a throwaway SQLite; screenshots land in `docs/screenshots/`). `make check` = lint + tests + Tailwind-in-sync (run it before every commit); `make seed` loads the demo dataset (3 wallets, 4 needs, bids).

## Where Stellar lives in the code

| Path | What it does |
|------|--------------|
| `accounts/signing.py` | Verifies the Freighter `signMessage` login signature (SEP-53, with legacy fallbacks) |
| `payments/trustless_work.py` | Trustless Work v1 REST client: deploy / fund / milestone / approve / release, `send-transaction` |
| `payments/stellar.py` | Plan B + Horizon helpers: build USDC `payment` / `changeTrust` XDR, parse & check signed XDR, submit, balances, `payment_mode()` |
| `payments/services.py` | The flow: one `prepare_<step>` / `confirm_<step>` pair per step, role + state gates, both modes (state table in its docstring) |
| `payments/models.py` | `Escrow`: contract id, every tx hash, status, per-need |
| `payments/views.py` + `payments/urls.py` | JSON endpoints under `/pay/`: `prepare/<need_pk>/<step>/`, `send/<need_pk>/<step>/`, `trustline/prepare/`, `trustline/send/` |
| `templates/payments/_escrow_panel.html` | The payment panel on the need page: stepper, one button per step, trustline helper, stellar.expert links |
| `static/js/lowbid-wallet.js` | Freighter connection, login signature, `Lowbid.signTransaction(xdr)` |
| `static/js/lowbid-pay.js` | Prepare → Freighter sign → send driver for every payment button, live USDC balance from Horizon |
| `docs/STELLAR_NOTES.md` | Network, USDC asset, trustlines, Trustless Work field reference, smoke test, the shipped payment endpoints |
| `docs/ARCHITECTURE.md` | Payments section: endpoints, state table, how to switch to Plan B |

## Docs

| File | What is in it |
|------|---------------|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product spec (French): personas, the 10-step flow, business rules R1–R15, scoring with worked examples, state tables, screens |
| [`docs/PITCH.md`](docs/PITCH.md) | The pitch (French): 2:30–3:00 video script, 5-slide deck, judge Q&A, demo-day checklist |
| [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) | Step-by-step live demo script (French): accounts, faucet, trustlines, clicks and lines to say, troubleshooting |
| [`docs/STELLAR_NOTES.md`](docs/STELLAR_NOTES.md) | Stellar / Trustless Work / Freighter integration notes: endpoints, payloads, USDC asset, gotchas, smoke test |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code layout, apps, payment endpoints and state table, how to switch to Plan B |
| [`docs/FRONTEND.md`](docs/FRONTEND.md) | Design system (French): tokens, every `ui-` component with markup, template components, `window.Lowbid` JS API, responsive & a11y rules, page recipes |
| [`docs/HACKATHON_DAY.md`](docs/HACKATHON_DAY.md) | Day-of checklist (French): setup in 10 lines, 5-minute smoke test, team split, "where do I change X", Plan B, commit hygiene, triage |
| [`CLAUDE.md`](CLAUDE.md) | Project instructions for an AI coding assistant: commands, repo map, conventions, frontend rules, e2e DOM contracts, don'ts |

## Testnet addresses

| Role | Public key | stellar.expert |
|------|------------|----------------|
| Client | | |
| Freelance 1 | | |
| Freelance 2 | | |
| Escrow contract | | |

## Track: Composed (Freighter + USDC + Trustless Work)

Three Stellar building blocks composed into one flow: **Freighter** for identity and signing, **USDC** as the unit of payment, **Trustless Work** escrow on Soroban for trustless settlement.

**Plan B, stated honestly:** if escrow creation fails during the demo, Lowbid falls back to a direct USDC payment (`Operation.payment`) from the client to the freelancer (`LOWBID_PAYMENT_MODE=direct`). The panel then reads "Paiement direct USDC" with a **Plan B** badge, and the client has one button, "Payer le freelance" ("Valider et payer" once the freelancer has declared delivery). It still settles on Stellar in seconds, but without the escrow guarantee: in direct mode the client can pay before delivery is declared. The "Status" list below says which path actually works.

## Status / what works

- [ ] Wallet login (Freighter signMessage)
- [x] Post a need
- [x] Bid with the descending-price rule
- [x] Scoring + "Recommandé" badge
- [x] Client chooses any bid
- [ ] Escrow create (USDC locked)
- [ ] Escrow release (USDC to freelancer)
- [ ] Plan B: direct USDC payment

## Live checklist before demo

1. `TRUSTLESS_WORK_API_KEY=` (testnet key from dapp.trustlesswork.com → Settings → API Keys) in `.env`; leave `LOWBID_PAYMENT_MODE=` empty (auto → escrow).
2. `LOWBID_PLATFORM_ADDRESS=G…` set to a funded testnet account **with a USDC trustline** (it receives `LOWBID_PLATFORM_FEE`).
3. USDC trustline on all three Freighter accounts (client, freelance 1, freelance 2) — Freighter → Manage assets, or the "Ajouter la trustline USDC" button in the payment panel of an awarded need (shown to the client and the winner); the client also needs ≥ bid USDC (Circle faucet: 10 USDC per address per 24 h, so keep demo amounts ≤ 10 USDC).
4. `python manage.py seed_demo --flush` with `LOWBID_DEMO_CLIENT` / `LOWBID_DEMO_FREELANCE1` / `LOWBID_DEMO_FREELANCE2` set to those addresses, then open `/besoins/<id>/` for the awarded need id printed by `seed_demo` (`awarded=#<id>`; SQLite ids keep counting after `--flush`, so do not hardcode it).
5. Smoke test §6 of `docs/STELLAR_NOTES.md` once (deploy → sign → send-transaction) and keep the `contractId` as a backup screenshot.
6. If Trustless Work fails live: `LOWBID_PAYMENT_MODE=direct`, restart — same page, the panel switches to "Paiement direct USDC" (Plan B) and the client's single button ("Payer le freelance" / "Valider et payer") sends one USDC payment instead of the escrow. A need whose escrow is already deployed on Trustless Work stays in escrow mode.

## Built during the hackathon

Everything. Product, code, design and docs were built during Hack Meridian (Sunday build, Monday 11:00 submission).

## Team

TODO: names, roles, links

## License

MIT
