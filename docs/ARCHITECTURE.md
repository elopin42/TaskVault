# TaskVault — Architecture

Task board for freelancers on Stellar (Hack Meridian). Django 5.2 server-rendered pages, SQLite by default,
a wallet (Freighter) as the only identity, USDC on testnet (asset configurable), one Trustless Work escrow per task.
The product is branded **TaskVault**; the code keeps the `lowbid` names (Django project `lowbid/`, `LOWBID_*` settings,
`lowbid-*.css/js`, `window.Lowbid`).
Deliberately hackathon-sized: no DRF, no Redis, no SPA, no background worker.

## Tree

```
TaskVault/
├── manage.py
├── lowbid/                 # project: settings.py (env-driven), urls.py, wsgi.py
├── core/                   # landing (stats, ledger tape, 3D cube story), /healthz/, error handlers, context processors,
│                           # templatetags/lowbid_extras.py
├── accounts/               # WalletUser + Freighter login (challenge / verify / logout), wallet_required, get_wallet
├── projects/               # Project / Task / Application / Rating / Delivery / RevisionRequest / Dispute,
│                           # services (rules + payment hooks + link_info), scoring,
│                           # forms, pages + JSON endpoints, management/commands/seed_demo.py         mounted at /
├── payments/               # Escrow (1-1 Task), services (prepare/confirm per step, both modes), trustless_work.py,
│                           # stellar.py, JSON endpoints, templatetags/payments_extras.py              mounted at /pay/
├── dashboard/              # no models: signed-in home (/tableau-de-bord/) + public wallet profile (/profil/<addr>/),
│                           # services.py (view-models + `set_display_name`), templates in dashboard/templates/dashboard/
├── templates/              # base.html, partials/{navbar,tabbar,toasts,modal,page_header}.html, core/landing.html,
│   │                       # 400/403/404/500.html, payments/_escrow_panel.html, payments/_dispute_form.html
│   ├── components/         # wallet, status_badge, tags, kpi, price, empty_state, pager, next_card, section_head, ext_link
│   └── projects/           # project_list, project_form, project_detail, task_detail, board, my_projects, disputes
│                           # + _project_card, _task_row, _task_form, _candidates, _funding_panel, _board_card
├── static/
│   ├── css/  lowbid-tokens.css  lowbid-components.css  tailwind.src.css  tailwind.css (BUILT, committed)
│   ├── js/   lowbid-base.js  lowbid-ui.js  lowbid-wallet.js  lowbid-pay.js  lowbid-projects.js  lowbid-disputes.js  lowbid-landing.js
│   ├── vendor/  fontawesome/  freighter-api.js (→ window.freighterApi)  stellar-sdk.min.js (→ window.StellarSdk)  anime.umd.min.js (→ window.anime, landing only)
│   └── img/favicon.svg
├── tests/e2e/              # run.js (Playwright scenario), fake-freighter.js, fake-horizon.js
├── data/                   # gitignored: db.sqlite3; e2e.sqlite3 + e2e-server.log (make e2e); e2e-shots/ (make / make verify)
├── docs/                   # PRODUCT, PITCH, STELLAR_NOTES, FRONTEND, HACKATHON_DAY, DEMO_RUNBOOK, this file, screenshots/
├── README.md  CLAUDE.md    # overview for the judges · project instructions for an AI assistant
├── requirements.txt  requirements-dev.txt  ruff.toml  Makefile  .env.example
├── package.json  tailwind.config.js        # npm run build:css / npm run vendor
├── Dockerfile  compose.yml                 # optional: django + postgres
└── .github/workflows/ci.yml                # ruff · django check + migrations + tests · tailwind-in-sync
```

## Run it

```bash
make              # = make all: venv + .env + migrate + check + e2e (screenshots in data/e2e-shots/), then runserver
make verify       # the same checks, without starting the server
make dev          # venv + pip install + .env from .env.example + migrate + runserver 0.0.0.0:8000
make test         # manage.py check + makemigrations --check + test (315 tests)
make lint         # ruff check .
make css          # npm ci + tailwind build  (commit static/css/tailwind.css!)
make css-check    # rebuild and fail when the committed tailwind.css is stale (= CI tailwind-in-sync)
make check        # lint + test + css-check — the pre-commit gate
make seed         # python manage.py seed_demo --flush (4 wallets, the pitch-state project, a draft, the food-truck project:
                  # a task delivered again after a change request + a disputed escrow task)
make vendor       # re-copy Font Awesome / freighter-api / stellar-sdk / anime.js from node_modules
make e2e          # Playwright end-to-end (see E2E below); `make shots` = the e2e writing to docs/screenshots/
```

Settings come from `.env` (python-dotenv, read once at boot). `DJANGO_DEBUG=0` **requires** `DJANGO_SECRET_KEY`.
Set `DJANGO_DB_HOST` to switch from SQLite to PostgreSQL (`DJANGO_DB_NAME/USER/PASSWORD/PORT`);
`LOWBID_SQLITE_PATH` moves the SQLite file (default `data/db.sqlite3`, `make e2e` uses `data/e2e.sqlite3`).

## E2E

`make e2e` picks two free ports, migrates and boots `runserver` against a fresh `data/e2e.sqlite3` in **direct** payment mode
with `STELLAR_HORIZON_URL` pointed at `tests/e2e/fake-horizon.js` (started by `run.js`), runs `node tests/e2e/run.js`
(plain `playwright` library, Chromium) and kills the server.

- `fake-freighter.js` is injected with `addInitScript` and replaces `window.freighterApi` with a keypair-backed fake
  (SEP-53 `signMessage`, `signTransaction` through the vendored `StellarSdk`), so the real login and the real payment
  signatures run end to end.
- `fake-horizon.js` is a toy ledger: accounts exist once "friendbotted", `change_trust` adds a trustline, a `payment`
  needs a funded source, a trustline on the destination and enough balance; rejections use Horizon's real
  `extras.result_codes`, so `payments.stellar` produces its usual (English) messages.
- The scenario: login + `?next=` round trip → the company creates the project and three tasks inline (plus a second
  project through the API) → A and B apply to T1 (a third freelance C applies through the API while the company's page
  polls) → the company chooses A → A delivers a link (direct mode: no transaction) → the company validates with
  5 stars → the chained payment fails gracefully (company unknown on Horizon: `stellar` error, `last_error` persisted)
  → the wallets are funded, A adds the USDC trustline from the panel, the company resumes "Pay the freelancer" → T1
  "Paid" with its stellar.expert link, A's balance at 300, the project "Funded" → A and B apply to T2 → A ranks first
  with "Validated" + "Recommended" (90.0 vs 20.0). Before the payment of T1 the run also covers the fingerprint (a bad
  hash refused, the stored one lowercased), the full deliverable hidden from the company until paid, two change requests
  then the `too_many_revisions` cap, the delivery history, the direct-mode "unprotected payment" warning and the
  company's 403 on `/litiges/`. Plus role refusals, the kanban, list filters, My projects,
  dashboard, profile, mobile at 390×844 (no horizontal scroll, tap targets), the dark-only theme (no toggle), logout
  and 404s.
- Screenshots land in `docs/screenshots/` (`01-landing.png` … `15-financement-projet.png`, `mobile-*.png`), or in
  `E2E_SHOTS_DIR` (`make` / `make verify` use `data/e2e-shots/`). Any uncaught
  page error or unexpected `console.error` fails the run. The escrow steps are covered by `payments/tests_flow.py`
  (Trustless Work mocked), not by the e2e.

## Apps

| App | Owns | URLs |
|-----|------|------|
| `core` | landing (`core:landing`: live stats, the 3 latest projects with an open task, a ledger tape of the latest stored tx hashes, the decorative 3D project cube story), `GET /healthz/` (`core:healthz`), error handlers, context processors `site` (asset version, Stellar config, `asset_code` / `asset_issuer` / `asset_native` / `payment_mode`) and `nav_links`, template filters (`{% load lowbid_extras %}`) | `/`, `/healthz/` |
| `accounts` | `WalletUser(stellar_address, display_name, created_at, last_login_at)`, wallet auth, `wallet_required`, `get_wallet()`; context processor `wallet` (`wallet_address`, `wallet_user`) | `/auth/challenge/`, `/auth/verify/`, `/auth/logout/` |
| `projects` | the task board: models, `services.py` (every rule + the payment hooks), `scoring.py`, pages + JSON endpoints, `seed_demo` | `/projets/…`, `/taches/…`, `/mes-projets/` |
| `payments` | `Escrow` (1-1 `Task`), `services.py`, `trustless_work.py`, `stellar.py`, `{% escrow_panel task wallet %}` | `/pay/…` |
| `dashboard` | no models; `services.py` holds the view-models and `set_display_name` (the profile rename). `home` (`@wallet_required`): to-do list (`todo_items`, built from `payments.services.next_action()` and the projects data, `act` items first), KPIs as company and as freelance, recent activity. `profile` (public, 404 for an unknown wallet): identicon, display name (≤80, POST by its owner only, else 403), projects posted, tasks paid, earned, average rating, latest projects and tasks, ratings received | `/tableau-de-bord/`, `/profil/<address>/` |
| `reputation` | `CompanyRating` (1-1 `Task`: the freelance rates the company once the task is settled), `GithubIdentity` (1-1 `WalletUser`, unique `github_id`), `services.py` (`rate_company`, `company_rating_summary`, `payer_profile` from confirmed on-chain payouts only, `wallet_badges`, `has_history`, `verify_github` / `unlink_github` against api.github.com, merge hooks `_disputes_lost` / `_deposits_forfeited`), inclusion tags `{% load reputation_extras %}` (`reputation_badges`, `company_rating_badge`, `payer_profile_panel`, `rate_company_panel`, `history_signal`, `github_panel`) so the projects / dashboard views stay unchanged, `static/js/lowbid-reputation.js`. Never feeds `projects.scoring` | `/taches/<pk>/noter-entreprise/`, `/profil/github/…` |

### Routes

| URL | View | Name | Auth |
|-----|------|------|------|
| `GET /projets/` | `project_list` | `projects:project_list` | public |
| `GET/POST /projets/nouveau/` | `project_create` (`ProjectForm`) | `projects:project_create` | wallet |
| `GET /projets/<pk>/` | `project_detail` | `projects:project_detail` | public |
| `GET /taches/` | `board` (kanban) | `projects:board` | wallet |
| `GET /taches/<pk>/` | `task_detail` | `projects:task_detail` | public |
| `GET /mes-projets/` | `my_projects` | `projects:my_projects` | wallet |
| `GET /litiges/` | `disputes` (the arbiter's desk: open disputes with `#resolve-form-<task>`, then the resolved ones) | `projects:disputes` | wallet; 403 unless `payments.services.is_arbiter` |
| `POST /projets/<pk>/taches/ajouter/` | `task_add` → 201 `{ok, task, count, total, message}` | `projects:task_add` | wallet |
| `POST /taches/<pk>/supprimer/` | `task_delete` → `{ok, message, redirect}` | `projects:task_delete` | wallet |
| `POST /taches/<pk>/postuler/` | `apply_create` → 201 `{ok, application{id, score, tags}, message}` | `projects:apply_create` | wallet |
| `POST /taches/<pk>/choisir/<app_pk>/` | `task_choose` → `{ok, status, assigned_to, message}` | `projects:task_choose` | wallet |
| `POST /taches/<pk>/livrer/` | `task_deliver` → `{ok, status, message}` (DB-only delivery, refused in escrow mode) | `projects:task_deliver` | wallet |
| `POST /taches/<pk>/valider/` | `task_validate` → `{ok, status, project_status, next, message}` | `projects:task_validate` | wallet |
| `POST /taches/<pk>/modifications/` | `task_request_changes` `{message}` → `{ok, status, revision_count, revisions_left, message}` (the company sends the delivery back; 409 `too_many_revisions` after `LOWBID_MAX_REVISIONS`) | `projects:task_request_changes` | wallet |
| `GET /taches/<pk>/candidats.json` | `task_candidates_json` → `{ok, task, status, count, fingerprint, candidates[], html}` | `projects:task_candidates_json` | public |
| `POST /pay/prepare/<task_pk>/<step>/` | `payments.views.prepare` (steps `deploy fund deliver approve release direct_pay dispute resolve`) | `payments:prepare` | wallet |
| `POST /pay/send/<task_pk>/<step>/` | `payments.views.send` | `payments:send` | wallet |
| `POST /pay/trustline/prepare/`, `POST /pay/trustline/send/` | trustline of the session wallet | `payments:trustline_prepare` / `_send` | wallet |
| `GET /pay/project/<pk>/pending.json` | `project_pending` → `{ok, project, mode, total, funded, can_fund, hint, tasks[]}`: the tasks "Fund the project" chains | `payments:project_pending` | wallet (company) |
| `GET /pay/<task_pk>/` | `task_pay` → 302 to the task page `#paiement` | `payments:task_pay` | public |
| `POST /projets/<pk>/annuler/` | `project_cancel` → `{ok, status, message, redirect}` (company, before any choice) | `projects:project_cancel` | wallet |
| `POST /pay/caution/<pk>/prepare/<step>/`, `POST /pay/caution/<pk>/send/<step>/` | `deposit_views.deposit_prepare` / `deposit_send` (step `deploy` \| `fund`) | `payments:deposit_prepare` / `deposit_send` | wallet (company) |
| `GET /pay/caution/<pk>/pending.json` | `deposit_pending` → `{ok, project, active, amount, next}` | `payments:deposit_pending` | wallet (company) |
| `POST /pay/caution/<pk>/recuperer/` | `deposit_refund` → `{ok, status, message, explorer_urls, next}` (verdict refund) | `payments:deposit_refund` | wallet (company) |
| `POST /pay/caution/<pk>/signaler/` | `deposit_report` → same shape (verdict forfeit) | `payments:deposit_report` | wallet (any) |
| `GET /fonds/` | `deposit_views.fund_page` (guarantee fund) | `payments:fund_page` | public |
| `GET /tableau-de-bord/`, `GET/POST /profil/<address>/` | `dashboard.views.home` / `profile` | `dashboard:home` / `dashboard:profile` | wallet / public |
| `POST /taches/<pk>/noter-entreprise/` | `reputation.views.rate_company` ← `{note, comment}` → `{ok, note, avg, count, message}` | `reputation:rate_company` | wallet (assignee) |
| `GET /profil/github/message/` | `github_message` → `{ok, message}` (`lowbid:<G…>` of the session wallet) | `reputation:github_message` | wallet |
| `POST /profil/github/verifier/` | `github_verify` ← `{gist}` → `{ok, login, verified_at, message}` | `reputation:github_verify` | wallet |
| `POST /profil/github/retirer/` | `github_unlink` → `{ok, message}` | `reputation:github_unlink` | wallet |

Projects refusals are 4xx `{ok:false, error, message}` (`ERROR_STATUS` in `projects/views.py`: 403 `forbidden`
`own_task` `not_assigned`, 409 `wrong_state` `duplicate` `too_many_revisions` `not_published` `not_covered`, 400 `invalid` `bad_tags`, any other code 400; an unknown
project / task / application is a 404). Payments refusals are HTTP 200
`{ok:false, error, message}` so `Lowbid.api` resolves and the panel shows `message`. A caller without a session that sends
`X-Requested-With: fetch` or `Accept: application/json` gets 401 `{ok:false, error:"wallet_required"}`; a browser gets a
302 to `/?next=…`.

## Data model

```
WalletUser ─┬─< Project (company, PROTECT) ──< Task (CASCADE) ──< Application (CASCADE) >── WalletUser (freelancer, PROTECT)
            │                                   │  └── assigned_to ─> WalletUser (PROTECT, null until chosen)
            │                                   ├── Rating (1-1, CASCADE): company, freelancer, note 1–5, comment
            │                                   ├──< Delivery (CASCADE): freelancer (PROTECT), link, hash, source link, tx_hash
            │                                   ├──< RevisionRequest (CASCADE): company (PROTECT), message
            │                                   ├── Dispute (1-1, CASCADE): opened_by (PROTECT), reason, freelance_pct, resolved_at
            │                                   └── Escrow (1-1, CASCADE, payments): mode, status, contract_id, hashes
```

| Model | Fields that matter |
|-------|--------------------|
| `accounts.WalletUser` | `stellar_address` (unique, 56), `display_name` (≤80), `created_at`, `last_login_at` |
| `projects.Project` | `company` (FK WalletUser), `title` (≤120), `description`, `status` `draft`/`funded`/`closed`; default ordering `-created_at`. `Project.objects.with_totals()` annotates `total` (Σ task prices), `tasks_total`, `paid_total`, `resolved_total`, `open_total` in one query; `progress_pct` = settled (paid + resolved) / tasks |
| `projects.Task` | `project`, `title`, `description`, `price` `Decimal(18,7)`, `tags` (JSON list, ≤3 enforced by `services.clean_tags`), `status` `open`/`taken`/`delivered`/`paid`/`disputed`/`resolved`, `assigned_to`, `delivery_link` (≤500, the latest demo / preview link), `delivery_hash` ("" or 40 / 64 lowercase hex), `source_link` (≤500, the full deliverable, revealed by `source_visible`), `revision_count`, `delivered_at` (cleared by a change request), `paid_at`, `resolved_at`, `position` (1-based order in the project) |
| `projects.Application` | `task`, `freelancer`, `message` (≤280), `tags`, `score` `Decimal(5,1)` (stored, refreshed by `services.rescore`), `status` `pending`/`chosen`/`rejected`; unique (`task`, `freelancer`); default ordering `-score, created_at, pk` |
| `projects.Rating` | `task` (1-1), `company`, `freelancer`, `note` 1–5, `comment` (≤280) |
| `projects.Delivery` | `task` (FK, `related_name="deliveries"`), `freelancer` (PROTECT), `delivery_link`, `delivery_hash`, `source_link`, `tx_hash` (the change-milestone-status in escrow mode, "" otherwise), `created_at` — one row per (re)delivery, written by `services.deliver` |
| `projects.RevisionRequest` | `task` (FK, `related_name="revision_requests"`), `company` (PROTECT), `message` (≤280), `created_at` — written by `services.request_changes` |
| `projects.Dispute` | `task` (1-1, `related_name="dispute"`), `opened_by` (FK WalletUser, PROTECT: the party who signed dispute-escrow), `reason` (≤280, database only: Trustless Work v1 has no reason field), `freelance_pct` (0–100, null until resolved), `created_at`, `resolved_at` — written by `mark_disputed` / `mark_resolved` |
| `payments.Escrow` | `task` (1-1, `related_name="escrow"`), `mode` `escrow`/`direct` (frozen when the row is created), `amount` (= task price), `payer_address` (company), `payee_address` (freelance), `platform_address`, `resolver_address` (the `disputeResolver` fixed at deploy = `LOWBID_DISPUTE_RESOLVER`), `contract_id`, `engagement_id` (`taskvault-task-<pk>`), `deploy/fund/deliver/approve/release/payment/dispute/resolve_tx_hash`, `status` `created`/`deployed`/`funded`/`delivered`/`approved`/`released`/`paid`/`disputed`/`resolved`/`failed` (`failed` is never set), `delivery_note` (the evidence sent on chain, ≤280), `last_error`, `funded_at`, `delivered_at`, `released_at`, `disputed_at`, `resolved_at` |

Nothing Stellar-related is stored on the projects models: the escrow row is the only on-chain record.

## How auth works (wallet = identity)

1. Browser: `Lowbid.wallet.connect(next)` → `freighterApi.isConnected()` → `getNetwork()` (must match
   `STELLAR_NETWORK_PASSPHRASE`, else an error toast asking to switch network) → `requestAccess()` → address.
2. `POST /auth/challenge/` → the server stores `{"nonce","message","ts"}` in the session and returns
   `{ok, message, expires_in}` with `message = "TaskVault login <32-hex nonce> <unix ts>"` (TTL
   `WALLET_CHALLENGE_TTL_SECONDS`, 300 s).
3. Browser: `freighterApi.signMessage(message, {address, networkPassphrase})` → `{signedMessage, signerAddress}`.
   **Freighter ≥ 5.34 signs per SEP-53**: Ed25519 over `sha256("Stellar Signed Message:\n" + message)`,
   returned as a **base64 string** (API v4+; the older API returned a Buffer — `lowbid-wallet.js` normalises both).
4. `POST /auth/verify/ {address, signature, next}` → checks, in order: a challenge in the session (`no_challenge`),
   its age (`challenge_expired`, the challenge is dropped), the address shape (`invalid_address`), the signature
   decoding (base64, or hex, 64 bytes: `invalid_signature_encoding`); then `accounts/signing.py::verify_signature`
   tries `sep53` → `raw` (UTF-8 bytes, pre-5.34 Freighter) → `sha256(message)` and the view logs the scheme that
   matched (`bad_signature` otherwise). Success: `get_or_create(WalletUser)`, `last_login_at`, `session.cycle_key()`,
   session keys `wallet_address` + `wallet_user_id`, challenge consumed by every verify attempt (success or failure), `{ok, address, created, next}` (`next`
   sanitised by `core.views.safe_next`). Failures are 400 `{"ok": false, "error": <code>}`.
5. `POST /auth/logout/` flushes the session (302 to the landing, or `{"ok": true}` for fetch callers).

```python
from accounts.decorators import wallet_required   # redirect → /?next=…  (401 JSON for fetch)
from accounts.identity import get_wallet

@wallet_required
def my_projects(request):
    wallet = get_wallet(request)       # WalletUser, cached per request
```

## Request flows

### Company: project and tasks
1. `POST /projets/nouveau/` (`ProjectForm`, classic form with `data-submit-once`) → `Project(status=draft)` → redirect to the project page.
2. The inline form `#task-form` posts through `Lowbid.api` to `/projets/<pk>/taches/ajouter/` → `services.add_task` (company, project not `closed`, price/tags parsed) → 201; the page reloads with `[data-tasks][data-count]` incremented. Field errors land in `[data-error-for="<field>"]`.
3. `[data-task-delete]` → `Lowbid.confirm` → `/taches/<pk>/supprimer/` → `services.delete_task`.

### Freelance: apply, then the company's live list
1. `#apply-form` → `/taches/<pk>/postuler/` → `services.apply` → `scoring.score_application` stores the score → 201 with the score; the page shows `#my-application`.
2. The task page polls `GET /taches/<pk>/candidats.json` every 5 s through `Lowbid.poll` (paused when the tab is hidden, backoff on errors) while the task is open. When `fingerprint` (status, count, assignee, ids and scores) changes, it swaps the `html` fragment (`projects/_candidates.html`), updates `[data-kpi-count]`, shows `[data-live-dot]` and calls `Lowbid.refreshUI`.
3. Rows come from `views._candidate_rows`: rank, score parts (`scoring.score_parts`), "Validated" (`scoring.is_validated` on `company_history`), "Recommended" (`scoring.recommended_pk`, open tasks only), matched tags.

### Company: choose
`[data-choose]` → `Lowbid.confirm` → `/taches/<pk>/choisir/<app_pk>/` → `services.choose` (row lock, others `rejected`, task `taken`, `assigned_to`). Nothing touches the chain.

### Company: fund (escrow mode)
`[data-fund]` ("Fund the project", project page header) → `Lowbid.pay.fundProject` → `GET /pay/project/<pk>/pending.json` (`payments.services.project_funding`: every `taken` task whose escrow is still `created`/`deployed`, with the company's `next` step) → for each task `Lowbid.pay.runChain(next, {stopAfter: ["fund"]})`: `prepare deploy` → Freighter → `send deploy` (stores `contract_id`) → `prepare fund` → Freighter → `send fund`. `confirm_fund` calls `sync_project_status`, which moves the project to `funded` once every assigned task holds its money. The button is rendered in escrow mode only, and enabled only when `can_fund`. The same steps are available one by one on the task's payment panel ("Create the escrow", "Lock the funds").

### Freelance: deliver
- Escrow mode (once the escrow is `funded`): `#deliver-form` + `[data-pay-step="deliver"]` → `POST /pay/prepare/<task>/deliver/ {delivery_link}` (link validated by `projects.services.clean_link`) → Trustless Work `change-milestone-status` XDR with the link as `newEvidence` → Freighter (freelance) → `POST /pay/send/<task>/deliver/ {signed_xdr, delivery_link}` → `confirm_deliver` sends it, then calls `projects.services.deliver(task, wallet, link, on_chain=True, tx_hash=…)`. After a change request the same step runs again ("Deliver again"): a new XDR, a new `Delivery` row; the previous signed XDR is refused (`tampered`).
- Company, while `delivered` and unrated: `[data-request-changes]` reveals `#request-changes-form` (`#request-changes-message`) → `Lowbid.confirm` → `POST /taches/<pk>/modifications/ {message}` → `services.request_changes` (task `taken`, `revision_count` += 1, `RevisionRequest` row, escrow row back through `payments.services.on_changes_requested`). The page shows the review deadline (`[data-review-deadline]`, `review_deadline()` at read time, countdown in JS) and the history (`[data-delivery-history]`).
- Direct mode: the same button (behind a `Lowbid.confirm`); `prepare_deliver` sees a `no_tx` step, calls `projects.services.deliver(task, wallet, link)` (its `_before_deliver` check passes in direct mode) and marks the escrow row `delivered` — nothing to sign.
- `POST /taches/<pk>/livrer/` is the DB-only path; `_before_deliver` → `payments.services.check_db_deliver` refuses it in escrow mode.

### Company: validate, rate, pay
`#validate-form` → `POST /taches/<pk>/valider/ {note, comment}` → `services.validate`: stores the `Rating`, rescores the company's open tasks, calls `_after_validate` → `payments.services.on_task_validated` (makes sure the `Escrow` row exists, logs the next step, **pays nothing**) → the view answers `next` = `payments.services.next_action(task, company)`. `lowbid-projects.js` then runs `Lowbid.pay.runChain(next)`: `approve` → `release` (escrow) or `direct_pay` (direct), each a prepare → Freighter → send round trip. `confirm_release` / `confirm_direct_pay` call `projects.services.mark_paid(task)` and `sync_project_status`. If the chain stops (declined signature, Horizon down), the panel shows the remaining step as a `[data-pay-step]` button and the error in `[data-pay-error]` / `[data-last-error]`.

### Dispute and resolution (escrow mode)
- A party, from the payment panel: `[data-open-dispute]` (shown when `payments.services.can_dispute`) reveals `#dispute-form` (`#dispute-reason`) → `[data-dispute-submit]` = `[data-pay-step="dispute"]` inside `form[data-pay-form]` → `Lowbid.confirm` → `POST /pay/prepare/<task>/dispute/ {reason}` → Trustless Work `dispute-escrow {contractId, signer}` (signer = the session wallet = the row's payer or payee) → Freighter → `POST /pay/send/<task>/dispute/ {signed_xdr, reason}` → `confirm_dispute` sends it and calls `projects.services.mark_disputed(task, wallet, reason)`.
- The arbiter, on `/litiges/`: `#resolve-form-<task>` (slider `[data-freelance-pct]`, live split preview in `lowbid-disputes.js`) → `[data-pay-step="resolve"]` → `POST /pay/prepare/<task>/resolve/ {freelance_pct}` → `get-escrow?validateOnChain=true` for the balance (fallback `Escrow.amount`) → `resolve-dispute {contractId, disputeResolver, distributions}` (addresses from the row, zero entries dropped, sum = balance) → Freighter → `send` → `confirm_resolve` → `projects.services.mark_resolved(task, pct)` + `sync_project_status`.

### Trustline
`[data-pay-trustline]` → `POST /pay/trustline/prepare/` → nothing to sign when Horizon already shows the trustline (or the asset is native), else a `changeTrust` XDR → Freighter → `POST /pay/trustline/send/` → Horizon. Nothing is persisted.

## Payments (`payments/`)

### State table

Verbatim from the docstring of `payments/services.py` (the authoritative copy):

```
State table — Escrow.status (payments) and Task.status (projects):

ESCROW mode (Trustless Work single-release, one milestone)
step        who        Escrow: before → after     Task                 on chain / persisted
choose      company    —                          open → taken         (projects) no tx
deploy      company    (none|created) → deployed  taken                TW deployer → contract_id, deploy_tx_hash
fund        company    deployed → funded          taken                TW fund-escrow → fund_tx_hash, funded_at;
                                                                       project draft → funded when every assigned task holds funds
                                                                       (choose sends a funded project back to draft)
deliver     freelance  funded → delivered         taken → delivered    TW change-milestone-status, newEvidence =
                                                                       build_evidence(link, hash): "sha256:<64hex> <link>" /
                                                                       "git:<40hex> <link>" / "<link>", ≤ 280 chars → deliver_tx_hash,
                                                                       delivered_at, delivery_note; confirm calls
                                                                       projects.services.deliver(link, hash, source_link)
request_    company    delivered → funded         delivered → taken    (projects) no tx: RevisionRequest row, revision_count += 1,
changes                                                                 delivered_at cleared; max LOWBID_MAX_REVISIONS times, only
                                                                       before the Rating; every tx hash is kept (history); the
                                                                       freelance delivers again (a second change-milestone-status
                                                                       with the new evidence; the contract accepts it)
validate    company    —                          delivered (+Rating)  (projects) saves the Rating, answers `next` = approve
approve     company    delivered → approved       delivered            TW approve-milestone → approve_tx_hash
release     company    approved → released        delivered → paid     TW release-funds → release_tx_hash, released_at;
                                                                       confirm calls projects.services.mark_paid(task)
dispute     a party    delivered|approved         delivered → disputed TW dispute-escrow (signer = the session wallet, which
            (company   → disputed                                      must be payer_address or payee_address; no reason field
            or                                                         in v1, the reason stays in the DB) → dispute_tx_hash,
            freelance)                                                 disputed_at; confirm calls projects.services
                                                                       .mark_disputed(task, wallet, reason) → Dispute row.
                                                                       Gate = projects.services.can_dispute: the company while
                                                                       unrated, the freelance once the review window is over.
                                                                       Funds stay locked (holds_funds); approve / release /
                                                                       request_changes / validate are now wrong_state
resolve     arbiter    disputed → resolved        disputed → resolved  TW resolve-dispute (disputeResolver = resolver_address =
                                                                       the session wallet; distributions = balance read with
                                                                       get-escrow validateOnChain=true (fallback: amount) split
                                                                       freelance_pct % to payee_address, the rest to
                                                                       payer_address, zero entries dropped) → resolve_tx_hash,
                                                                       resolved_at; confirm calls projects.services
                                                                       .mark_resolved(task, pct) (the ONLY gate to `resolved`);
                                                                       project closes when every task is paid or resolved

DIRECT mode (fallback: one `payment` op; "funded" and "approved" do not exist; no dispute step: nothing is locked)
deliver     freelance  created → delivered        taken → delivered    NO transaction: projects.services.deliver(link, hash,
                                                                       source_link); delivery_note = build_evidence(link, hash)
                                                                       (database only — nothing on chain)
request_    company    delivered → created        delivered → taken    (projects) no tx: same rules as in escrow mode; the
changes                                                                 freelance delivers again (database only)
validate    company    —                          delivered (+Rating)  (projects) saves the Rating, answers `next` = direct_pay
direct_pay  company    created|delivered → paid   delivered → paid     Django builds the payment XDR, Freighter signs,
                                                                       Django checks it (source/destination/amount/asset)
                                                                       and submits to Horizon → payment_tx_hash, released_at;
                                                                       mark_paid(task); project draft → funded on the first payment
trustline   anyone     —                          —                    changeTrust XDR, or nothing when Horizon already shows it
```

The validate view saves the Rating **first** (database), then the page chains the signatures (approve → release, or
direct_pay) from the `next` it gets back. Stopping half-way is fine: the panel shows the remaining step ("Release the
funds").

Review window and revisions: `projects.services.review_deadline(task)` (= `delivered_at` + `LOWBID_REVIEW_DAYS`, read
time, no timer) bounds the company's review; `projects.services.request_changes` sends a delivery back (max
`LOWBID_MAX_REVISIONS`, before the Rating) and its hook `payments.services.on_changes_requested` moves the Escrow row
`delivered → funded` (escrow mode) or `delivered → created` (direct mode), keeping every hash. The freelance then runs the
`deliver` step again (a second `change-milestone-status`); `confirm_deliver` refuses a replay of a previous delivery's
signed XDR (`tampered`). Every delivery is a `projects.Delivery` row (with its tx hash), every request a
`projects.RevisionRequest` row.

Disputes (escrow mode only; direct mode answers `wrong_mode` and the panel shows `[data-direct-warning]`): `dispute` is a
`who="party"` step (`_gate` accepts the company or the chosen freelance, then `projects.services.can_dispute` decides:
the company while delivered + unrated, the freelance once `is_review_overdue`); it is an alternative (`alt`), never the
`next` step. `resolve` is `who="arbiter"`: the session wallet must be `LOWBID_DISPUTE_RESOLVER` (`is_arbiter`,
`viewer_role` → `"arbiter"` for a non-party) and the row's `resolver_address`. `split_amounts(balance, pct)` rounds the
freelance share down to a stroop; the company gets the exact remainder. Once disputed, the stepper switches to
… Delivered → In dispute → Resolved, and `next_action` answers `resolve` (mine for the arbiter, "Waiting for the
arbiter's decision." for the parties).

### Deposit (`payments/deposits.py`)

The publication deposit is a project-level Trustless Work single-release escrow, separate from the per-task escrows.
Active iff `LOWBID_DEPOSIT_ENABLED` and `payment_mode() == "escrow"`; otherwise `projects.services.create_project` /
`ProjectForm` set `published_at` at creation and nothing below runs. The authoritative state table is the docstring of
`payments/deposits.py`:

```
step       who signs           deposit: before → after   TW call                            project / persisted
deploy     company (Freighter) (none|created) → deployed deployer/single-release            contract_id, deploy_tx_hash
fund       company (Freighter) deployed → funded         fund-escrow                        fund_tx_hash, funded_at; published_at = now if None
milestone  platform key        funded                    change-milestone-status            milestone_tx_hash      ┐ refund chain
approve    platform key        funded                    approve-milestone                  approve_tx_hash        │ (verdict refund)
release    platform key        funded → refunded         release-funds (→ company)          release_tx_hash        ┘
dispute    platform key        funded                    dispute-escrow                     dispute_tx_hash        ┐ forfeit chain
resolve    resolver key        funded → forfeited        resolve-dispute [(fund, balance)]  resolve_tx_hash        ┘ (verdict forfeit)
```

Roles at deploy: signer + receiver = company; approver = serviceProvider = releaseSigner = platformAddress = the platform
key (`LOWBID_PLATFORM_SECRET`, whose public key must be `LOWBID_PLATFORM_ADDRESS`); disputeResolver = the deposit resolver
key (`LOWBID_DEPOSIT_RESOLVER_SECRET`) — a second key because the contract refuses a dispute opened by the resolver.
`payments/signer.py` builds the keypairs on demand and signs (`TransactionEnvelope.from_xdr(...).sign(kp)`); only public
addresses are logged. `payments/checks.py` (Tags.security) warns on a missing key (deposits then stay off) and fails `manage.py check` on an invalid / overlapping key
or fund address while deposits are active.

Verdict (`deposit_verdict(project, now)`, pure, PRODUCT R65): closed → refund; cancelled without application → refund;
no application for `LOWBID_NO_APPLICATION_DAYS` → refund; first application `LOWBID_CHOICE_DAYS` old and nobody ever chosen,
or cancelled with applications → forfeit; else locked.

Serialization and idempotence: company steps gate the role and the state in both halves, replay of the same signed XDR
answers ok, the send runs outside any transaction and the row is re-read under `select_for_update` before the write. The
server chains build → sign → send each step inside the request (a TW XDR is single use, valid about a minute), skip any
step whose hash is stored, store `last_error` and stop on the first failure (status unchanged), and re-read the row under
`select_for_update` before each write — a rerun sends only the missing steps.

Triggers: `payments/apps.py` connects `post_save` on `projects.Project` to `deposits.on_project_saved`: when the saved
project is `closed` (from `mark_paid`) or `cancelled` (from `cancel_project`) and holds a funded deposit, it registers
`transaction.on_commit(_settle_after_commit)`, which settles every funded row inside `try/except Exception:
logger.exception`. The manual endpoints `/pay/caution/<pk>/recuperer/` (company, verdict refund) and `/signaler/` (any
wallet, verdict forfeit) run the same `settle_project` and serve as the retry. `projects.services.apply` calls the hook
`_check_applications_open` → `deposits.check_can_apply` (`not_published`, `not_covered`, cancelled → `wrong_state`).
The UI is `{% deposit_panel project wallet %}` / `{% deposit_badge project %}` (payments_extras) +
`static/js/lowbid-deposit.js`; `/fonds/` lists the forfeited deposits.

### Modes

- `payments.stellar.payment_mode()` is **the** switch: `LOWBID_PAYMENT_MODE=escrow` | `direct` | empty (or any other
  value) = auto (`escrow` when `TRUSTLESS_WORK_API_KEY` is set, else `direct`). A native-XLM asset (`STELLAR_ASSET_CODE=XLM`, empty issuer) is
  forced to `direct` (warning logged once per process), because Trustless Work v1 needs an issuer.
- The mode is **frozen on the Escrow row** when `ensure_escrow` creates it: at the task's first prepare, or in
  `on_task_validated`. While the row is still `created`
  (nothing on chain) it is re-frozen to the configured mode, so `LOWBID_PAYMENT_MODE=direct` + restart after a failed
  deploy just works. A task whose escrow is deployed stays in escrow mode.
- `effective_mode(escrow)` = the row's mode, or the configured one while nothing is on chain; `display_status()` makes a
  direct-mode task delivered through the DB endpoint read as `delivered`, and a paid task always terminal (`paid` in
  direct mode, `released` in escrow mode). `project_funding` and "Fund the project" follow the **configured** mode.
- Escrow mode roles (Trustless Work): company = deploy signer, `approver`, `releaseSigner`, funder; chosen freelance =
  `serviceProvider` + `receiver`; `LOWBID_PLATFORM_ADDRESS` = `platformAddress` (fee `LOWBID_PLATFORM_FEE`);
  `LOWBID_DISPUTE_RESOLVER` (default: the platform address) = `disputeResolver`, stored on the row as
  `resolver_address`. When `LOWBID_PLATFORM_ADDRESS` is empty the company wallet takes both platform roles (warning
  logged, `[data-platform-fallback]` alert in the panel); Trustless Work may refuse that.

### Hooks between `projects` and `payments`

| Hook | Where | Called by | Does |
|------|-------|-----------|------|
| `projects.services.mark_paid(task)` | projects | `payments.services.confirm_release`, `_finalize_direct_pay` (and `seed_demo`) | the **only** function that flips a task to `paid` (idempotent); closes the project when every task is paid or resolved; rescores the company's open tasks |
| `projects.services.mark_disputed(task, opened_by, reason)` | projects | `payments.services.confirm_dispute`, once dispute-escrow is confirmed | re-checks `can_dispute` and the reason, Task `delivered → disputed`, writes the `Dispute` row |
| `projects.services.mark_resolved(task, freelance_share)` | projects | `payments.services.confirm_resolve`, once resolve-dispute is confirmed | the **only** function that flips a task to `resolved` (idempotent; `wrong_state` on a non-disputed task); stores `freelance_pct` + `resolved_at`; closes the project when every task is paid or resolved; rescores the company's open tasks |
| `projects.services._after_validate(task)` | projects | `projects.services.validate`, inside its transaction, after the Rating | lazily imports `payments.services` and calls `on_task_validated(task)` |
| `payments.services.on_task_validated(task)` | payments | `_after_validate` | `ensure_escrow(task)` and logs the next step (approve → release, or direct_pay). Pays nothing |
| `projects.services._before_deliver(task)` | projects | `projects.services.deliver` when `on_chain=False` | calls `payments.services.check_db_deliver(task)`, which refuses a DB-only delivery in escrow mode |
| `projects.services.deliver(...)` | projects | `payments.services.confirm_deliver` (escrow, `on_chain=True`, `tx_hash`), `prepare_deliver` (direct `no_tx`, `on_chain=False`), the `task_deliver` view | records the delivery (link, fingerprint, source, `delivered_at`, task `delivered`) and writes the `Delivery` history row |
| `projects.services._after_request_changes(task)` | projects | `projects.services.request_changes`, inside its transaction, once the task is back to `taken` | lazily imports `payments.services` and calls `on_changes_requested(task)`; a `PaymentError` becomes `ProjectError("wrong_state")` |
| `payments.services.on_changes_requested(task)` | payments | `_after_request_changes` | Escrow `delivered → funded` (escrow mode) / `delivered → created` (direct mode), `last_error` cleared, every hash kept; no row = nothing to move; any other stage → `wrong_state` |
| `payments.services.sync_project_status(project)` | payments | `confirm_fund`, `confirm_release`, `confirm_resolve`, `_finalize_direct_pay` (and `seed_demo`) | project `draft → funded` (escrow: every assigned task holds funds; direct: first payment) |

`payments.services` imports `projects.services` at module level; the projects hooks import `payments.services` lazily to
avoid the cycle.

### Why one escrow per task

Trustless Work v1 fixes the escrow's `receiver` when the escrow is **deployed** and freezes the escrow once it holds funds.
A project-wide escrow funded before the freelances are chosen could therefore never pay them. A multi-release escrow
(one milestone per task, `receiver` per milestone) was studied and rejected: it has a single `serviceProvider` for the
whole escrow, so freelances could not sign their own delivery; receivers must be known at deploy or appended through
`update-escrow` signed by the platform; and its balance is pooled across milestones. Details and sources:
`docs/STELLAR_NOTES.md` §8. So each task gets its own **single-release** escrow (one milestone), deployed and funded by
the company once its freelance is chosen: amount = task price, payer = project company, payee = `task.assigned_to`.
"Fund the project" simply chains those steps task after task. Cost: two company signatures per task instead of two
per project.

### Endpoints and response shapes (`payments/views.py`)

- `POST /pay/prepare/<task_pk>/<step>/` (body `{delivery_link}` for `deliver`, `{reason}` for `dispute`, `{freelance_pct}` for `resolve`) → `{ok, xdr, send_url, extra}`, or
  `{ok, redirect, message, next}` when there is nothing to sign (direct delivery, reconciled payment).
- `POST /pay/send/<task_pk>/<step>/ {signed_xdr, ...extra}` → `{ok, redirect, status, task_status, tx_hash, hash,
  contract_id, explorer_url, message, pending, next}`.
- `next` = the viewer's following step (`{step, label, prepare_url, mine, who, evidence, no_tx, hint, task}` or `null`):
  `lowbid-pay.js` chains it while it is the viewer's own signature.
- `POST /pay/trustline/prepare/` → `{ok, message}` when there is nothing to sign, else `{ok, xdr, send_url, extra}`;
  `POST /pay/trustline/send/ {signed_xdr}` → `{ok, tx_hash, hash, explorer_url, message, pending}`.
- Refusals: HTTP 200 `{ok:false, error, message}`, codes `not_chosen · forbidden · wrong_state · wrong_mode ·
  unknown_step · tampered · provider · stellar · invalid · not_assigned`.

### Guarantees

- Role and state gates run in **both** halves (prepare and confirm), pinned to the session wallet; every role field in a
  Trustless Work body or a payment XDR comes from the `Escrow` row, never from the request.
- `confirm_direct_pay` parses the signed XDR (`stellar.parse_payment_xdr`) and refuses anything but one payment
  payer → payee of `amount` in the configured asset (`tampered`); the payment Django builds carries the memo
  `taskvault:task:<pk>`. `confirm_trustline` likewise requires one `change_trust` from the session wallet for the asset code and issuer of the
  configured issuer.
- Disputes: the dispute signer is the session wallet and must equal the row's payer or payee address; every address in
  the resolve `distributions` is the row's `payee_address` / `payer_address` (a body field is ignored), the amounts sum
  to the balance read on chain, zero entries are dropped; `confirm_dispute` / `confirm_resolve` refuse a signed XDR whose
  hash is already stored for another step of the escrow (`tampered`). `mark_resolved` is the only gate to `resolved`.
- Idempotency: a replayed send for a step already recorded with the same hash answers "Step already confirmed." (checked
  before the state gate, so it is not a `wrong_state`).
- A provider failure never flips a status; the message is stored in `Escrow.last_error` (directly when a prepare fails,
  after the transaction rolled back when a send fails: `_records_errors`); every successful confirm clears it. A Horizon 504 on a direct payment stores the locally computed hash as pending; the next
  `prepare_direct_pay` reconciles it with `stellar.transaction_status(hash)` without a second signature.
- View-models: `next_action(task, wallet)` (the panel and the dashboard agree on the pending step), `stepper(mode,
  status)`, `project_funding(project)` (banner: total, funded, paid, pending tasks, per-task rows and explorer links,
  `can_fund` + hint).

## Where Stellar lives

- `lowbid/settings.py` → `STELLAR_NETWORK` (`testnet`), `STELLAR_NETWORK_PASSPHRASE`, `STELLAR_HORIZON_URL`,
  `STELLAR_SOROBAN_RPC_URL`, `STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER` (defaults to the legacy `STELLAR_USDC_CODE` /
  `STELLAR_USDC_ISSUER`, i.e. Circle testnet USDC), `TRUSTLESS_WORK_API_URL`, `TRUSTLESS_WORK_API_KEY`,
  `LOWBID_PAYMENT_MODE`, `LOWBID_PLATFORM_ADDRESS`, `LOWBID_PLATFORM_FEE`, `LOWBID_DISPUTE_RESOLVER`.
- Python: `stellar-sdk` (login verification, XDR building and parsing); `requests` for Horizon and Trustless Work, never
  raising: Trustless Work calls return `{ok, status, data, error}`, `stellar.submit_xdr` the same plus `hash`, and the
  Horizon reads return `None` when Horizon is unreachable.
- Browser: `window.LOWBID` = `{network, networkPassphrase, horizonUrl, sorobanRpcUrl, asset:{code, issuer, native},
  paymentMode, walletAddress, urls:{challenge, verify, logout, landing, dashboard, trustlinePrepare, trustlineSend}}`;
  `window.StellarSdk` (vendored, `defer`); `window.freighterApi`; `Lowbid.signTransaction(xdr, {networkPassphrase?,
  address?})`. The panel's live balance reads Horizon `/accounts/<addr>` straight from the browser.

## Adding code

The five-step page recipe, the frontend rules and the e2e DOM contract are in `CLAUDE.md`; the component reference is
`docs/FRONTEND.md`. In short: rules in `services.py` raising `ProjectError` / `PaymentError`, function views that map
codes to HTTP, templates that extend `base.html` and compose `templates/components/*`, page JS in `static/js/` (bump
`LOWBID_ASSET_VERSION`), new Tailwind classes rebuilt and committed, migrations committed.

## Conventions kept from SIPS

- Python 3.13, 4-space, `snake_case`, type hints where cheap, `logger = logging.getLogger(__name__)`.
- Broad `except Exception` only with `logger.exception(...)` — never a silent `except: pass`. No `print()`.
- Config via `.env` / environment only (`_csv` / `_bool` helpers); never hardcode hosts or secrets.
- Structured `level=… logger=… msg=…` logs on stdout, level from `DJANGO_LOG_LEVEL`.
- Session cookie `lowbid_sessionid`, 8 h, not refreshed per request, `SameSite=Lax`, secure when `DJANGO_FORCE_HTTPS=1`.
- Frontend assets are build artifacts that get **committed**; CI `tailwind-in-sync` fails on a stale
  `static/css/tailwind.css`. Nothing loads from a CDN (fonts = system stack, icons = vendored Font Awesome).
- Tokens → components → Tailwind load order; colours only via `var(--*)`. The site renders dark only
  (`<html data-theme="dark">`, no toggle).
