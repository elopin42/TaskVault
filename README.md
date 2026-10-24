> The demo and the interface are in French. This README is in English for the judges.

# Lowbid

**A company splits a project into fixed-price tasks, freelances apply, the company picks one per task, and each task is paid in USDC from its own Trustless Work escrow on Stellar.**

- **Demo video:** TODO: link
- **Pitch deck:** TODO: link
- **Hackathon:** Hack Meridian (Stellar), track **Composed**

> History: Lowbid v1 was a reverse auction; the task board replaced it on 2026-10-25.

![Task page: two candidates, A carries « Validé » and « Recommandé »](docs/screenshots/08-tache-valide-recommande.png)

---

## What it does

```
   COMPANY                          LOWBID (Django)                        STELLAR (testnet)
   -------                          ---------------                        -----------------
1. Connect Freighter  ------------> signMessage check (SEP-53)  <--------- Freighter wallet
2. Create a project + tasks ------> project "Brouillon", tasks "Ouvert"
   (title, fixed price, ≤ 3 tags)
                        FREELANCES
3.                      Connect Freighter, open the kanban (/taches/)
4.                      « Postuler »: message + tags --> application scored (no price)
5. See ranked candidates ---------> score = history + ratings + skills, « Validé » / « Recommandé »
6. « Choisir » one freelance -----> task "Pris", the others "Non retenu"
7. « Financer le projet » --------> Trustless Work API (proxied) -------> one single-release escrow
   2 signatures per task:           deploy, then fund                     PER TASK, USDC locked
8.                      « Déclarer la livraison » + link -----------------> milestone marked done
                        (1 signature)                                       (link = on-chain evidence)
9. « Valider + noter » (1–5) -----> Rating saved, then 2 signatures:
                                    approve ---------------------------> milestone approved
                                    release ---------------------------> USDC to the freelance
                                    task "Payé"
Fallback (LOWBID_PAYMENT_MODE=direct): no escrow; delivery is a declaration and step 9
ends with one « Payer le freelance » payment signed in Freighter.
```

1. The **company** connects its **Freighter** wallet (Stellar testnet). Login is a signed message, no password.
2. It creates a **project** (title, description) and splits it into **tasks**, each with a title, a **fixed price** in USDC and up to 3 skill tags. Tasks can be added or deleted while the project is a draft.
3. **Freelances** connect their own wallet. The kanban (`/taches/`) shows every open task of other companies plus their own tasks, in four columns: Ouvert, Pris, Livré, Payé.
4. A freelance **applies** to a task with a short message and their skills. There is no price to fight over: the price is fixed by the company.
5. Lowbid ranks the candidates with a **deterministic score** (no AI). Two badges help: **« Validé »** (already paid by this company with an average rating ≥ 3) and **« Recommandé »** (the best score).
6. **The company chooses** any candidate. The score is a hint, not a rule.
7. Once a freelance is chosen, the company clicks **« Financer le projet »**. For every task with a chosen freelance, Trustless Work deploys a **single-release escrow** (first Freighter signature) and the company funds it with the task's price (second signature).
8. The freelance delivers: a link to the PR, the demo or the repository. In escrow mode, **« Déclarer la livraison »** marks the milestone done on chain with the link as evidence (one signature by the freelance).
9. The company checks the delivery, gives a **rating from 1 to 5** (« Valider + noter »), and signs the approval then the **release**. The escrow pays the freelance (minus fees) and the task becomes « Payé ». When every task is paid, the project is « Terminé ».

The next task gets easier: a freelance who has delivered well for a company climbs to the top of that company's next candidate list, with « Validé » and « Recommandé ».

Around the flow: a **dashboard** (`/tableau-de-bord/`, the signed-in home) lists what the wallet has to do next (candidates to choose, tasks to fund, deliveries to validate, payments to sign, tasks to deliver), with KPIs as company and as freelance; every wallet has a **public profile** (`/profil/<address>/`: identicon, display name, ratings received). The project list has text search, tag chips, sorting and pagination. Dark and light themes, mobile-first (stacked cards, bottom tab bar), no horizontal scroll.

## Why Stellar

- **USDC** on Stellar: the freelance gets a dollar-stable payment, not a volatile token.
- **Speed and cost:** settlement in about 5 seconds, fees around 0.00001 XLM, so a 300 USDC task is not eaten by fees.
- **Escrow on Soroban via Trustless Work:** each task's money is locked in a smart contract before the work starts, and released to the freelance's own wallet when the company approves. Neither side can run away with it, and the platform never holds it.
- **Freighter:** the wallet is the identity. Login and every payment step are signed by the user in their own wallet; Lowbid never holds a private key.
- **No bank in the loop:** no 10 to 20% platform cut, no wire delays.

## Scoring

For each application, against the company that owns the task:

```
score = 40 × [the freelance already has at least one PAID task with this company]
      +  8 × average rating given by this company (0 without rating)
      + 20 × (common tags / task tags)                 (0 when the task has no tags)
```

Maximum 100, stored with one decimal and refreshed after every rating and every payment. Worked example from the demo scenario, task « Intégration Freighter » (tags `stellar, js`): freelance A was paid 5/5 for the landing page and applies with `stellar` → 40 + 5 × 8 + 20 × ½ = **90**; freelance B, first collaboration, applies with `stellar, js` → 0 + 0 + 20 × 2/2 = **20**. Details in [`docs/PRODUCT.md`](docs/PRODUCT.md).

## Run it locally

Prerequisites: **Python 3.13**, **Node 22** (only to rebuild the CSS or run the e2e), the **Freighter** browser extension set to **TESTNET** with a funded account.

```bash
cp .env.example .env
make dev
# open http://localhost:8000
make seed   # optional: demo data (3 wallets, a project at the pitch state, a draft project)
```

`.env` is read once at startup: after any change (API key, `LOWBID_PAYMENT_MODE`, asset, demo wallets…) stop the server and run `make run` again. Without `TRUSTLESS_WORK_API_KEY` the app runs in direct-payment mode.

Tests: `make test` (222 Django tests: rules, scoring, payment flow in both modes, network mocked) and `make e2e` (Playwright, the full task-board scenario in a real browser with a simulated Freighter and a fake Horizon, on a throwaway SQLite; screenshots land in `docs/screenshots/`). `make check` = lint + tests + Tailwind-in-sync (run it before every commit).

## Where Stellar lives in the code

| Path | What it does |
|------|--------------|
| `accounts/signing.py` | Verifies the Freighter `signMessage` login signature (SEP-53, with legacy fallbacks) |
| `payments/trustless_work.py` | Trustless Work v1 REST client: deploy / fund / milestone / approve / release, `send-transaction` |
| `payments/stellar.py` | The asset (`STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER`), the mode switch `payment_mode()`, `payment` / `changeTrust` XDR builders, signed-XDR parser, Horizon submit, balances, trustline checks, stellar.expert links |
| `payments/services.py` | The flow: one `prepare_<step>` / `confirm_<step>` pair per step, role + state gates, both modes, project funding view-model (state table in its docstring) |
| `payments/models.py` | `Escrow`, one per task: mode, contract id, every tx hash, status |
| `payments/views.py` + `payments/urls.py` | JSON endpoints under `/pay/`: `prepare/<task>/<step>/`, `send/<task>/<step>/`, `trustline/…`, `project/<pk>/pending.json` |
| `templates/payments/_escrow_panel.html` | The payment panel on the task page: stepper, the next step's button, delivery and rating forms, trustline helper, live balance, stellar.expert links |
| `templates/projects/_funding_panel.html` | The project's funding banner: total / funded / paid, every task's escrow status and hashes |
| `static/js/lowbid-wallet.js` | Freighter connection, login signature, `Lowbid.signTransaction(xdr)` |
| `static/js/lowbid-pay.js` | Prepare → Freighter sign → send driver, chained steps (deploy → fund, approve → release), « Financer le projet », trustline, live balance from Horizon |

## Docs

| File | What is in it |
|------|---------------|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product spec: personas, the flow, testable rules R1–R24, the score with the worked example, states of Project / Task / Application / Escrow, screens |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Apps, data model, request flows, the Payments section (state table, modes, hooks, why one escrow per task) |
| [`docs/STELLAR_NOTES.md`](docs/STELLAR_NOTES.md) | Trustless Work single-release reference, why multi-release was rejected, asset configuration, Freighter, Horizon, smoke test |
| [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) | The end-to-end live demo: env setup, trustlines, seed, clicks, signatures, what to show on stellar.expert, fallback mode |
| [`docs/PITCH.md`](docs/PITCH.md) | Video script, 5-slide deck, judge Q&A |
| [`docs/FRONTEND.md`](docs/FRONTEND.md) | Design system: tokens, every `ui-` component with markup, template components, `window.Lowbid` JS API, responsive & a11y rules |
| [`docs/HACKATHON_DAY.md`](docs/HACKATHON_DAY.md) | Day-of checklist: setup, 5-minute smoke test, "where do I change X", fallback, triage |
| [`CLAUDE.md`](CLAUDE.md) | Project instructions for an AI coding assistant: commands, repo map, conventions, e2e DOM contract, don'ts |

## Screenshots

Regenerated by `make e2e` (direct mode against a fake Horizon). Desktop: `01-landing`, `02-liste-projets`, `03-projet-entreprise`, `04-tache-candidats`, `05-tache-livree-freelance`, `06-valider-noter`, `07-tableau-kanban`, `08-tache-valide-recommande`, `09-mes-projets`, `10-tableau-de-bord`, `11-profil`, `12-tache-light`, `13-paiement-echec`, `14-paiement-tache`, `15-financement-projet`. Phone (390×844): `mobile-landing`, `mobile-liste`, `mobile-kanban`, `mobile-projet`, `mobile-tache-candidats`, `mobile-tableau-de-bord`. All in [`docs/screenshots/`](docs/screenshots/).

## Testnet addresses

| Role | Public key | stellar.expert |
|------|------------|----------------|
| Company | | |
| Freelance A | | |
| Freelance B | | |
| Platform (dispute resolver, fee) | | |
| Escrow contract (task T1) | | |

## Track: Composed (Freighter + USDC + Trustless Work)

Three Stellar building blocks composed into one flow: **Freighter** for identity and signing, **USDC** as the unit of payment, **Trustless Work** escrow on Soroban for trustless settlement, one escrow per task.

**The fallback, stated honestly:** if escrow creation fails during the demo, Lowbid switches to a direct USDC payment (`Operation.payment`) from the company to the freelance (`LOWBID_PAYMENT_MODE=direct`, restart). The panels then read « Paiement direct USDC » with a « sans escrow » badge, the delivery is a plain declaration, and validating ends with one « Payer le freelance » signature. It still settles on Stellar in seconds, but without the escrow guarantee: nothing is locked before the work. The same fallback is used automatically when the configured asset is native XLM, which Trustless Work v1 cannot escrow.

## Status / what works

- [ ] Wallet login (Freighter signMessage) on a live testnet
- [x] Projects, fixed-price tasks, applications, scoring, choice, delivery, rating (unit + e2e tested)
- [x] Direct payment end to end in the e2e (fake Horizon: trustline, payment, explorer link)
- [ ] Escrow deploy + fund on the live testnet
- [ ] Escrow deliver + approve + release on the live testnet
- [ ] Direct payment on the live testnet

## Live checklist before demo

See [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) §1 for the full version.

1. `TRUSTLESS_WORK_API_KEY=` (testnet key from dapp.trustlesswork.com → Settings → API Keys) in `.env`; leave `LOWBID_PAYMENT_MODE=` empty (auto → escrow).
2. `LOWBID_PLATFORM_ADDRESS=G…` set to a funded testnet account **with a USDC trustline** (it is the dispute resolver and receives `LOWBID_PLATFORM_FEE`).
3. USDC trustline on the company and both freelances (Freighter → Manage assets, or « Ajouter la trustline USDC » in the payment panel); the company holds at least the price of the task it funds (Circle faucet: 10 USDC per address per 24 h, so keep live task prices small).
4. Smoke test §6 of `docs/STELLAR_NOTES.md` once (deploy → sign → send-transaction) and keep the `contractId` as a backup screenshot.
5. If Trustless Work fails live: `LOWBID_PAYMENT_MODE=direct`, restart. A task whose escrow is already deployed keeps escrow mode.

## Built during the hackathon

Everything. Product, code, design and docs were built during Hack Meridian.

## Team

TODO: names, roles, links

## License

MIT
