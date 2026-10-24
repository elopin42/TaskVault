# Lowbid — Architecture

Task board for freelancers on Stellar (Hack Meridian). Django 5.2 server-rendered pages, SQLite by default,
a wallet (Freighter) as the only identity, USDC on testnet, one Trustless Work escrow per task.
Deliberately hackathon-sized: no DRF, no Redis, no SPA, no background worker.

## Tree

```
Lowbid/
├── manage.py
├── lowbid/                 # project: settings.py (env-driven), urls.py, wsgi.py
├── core/                   # landing, /healthz/, error handlers, context processors, templatetags/lowbid_extras.py
├── accounts/               # WalletUser + Freighter login (challenge / verify / logout), wallet_required, get_wallet
├── projects/               # Project / Task / Application / Rating, services (rules + payment hooks), scoring,
│                           # forms, pages + JSON endpoints, management/commands/seed_demo.py         mounted at /
├── payments/               # Escrow (1-1 Task), services (prepare/confirm per step, both modes), trustless_work.py,
│                           # stellar.py, JSON endpoints, templatetags/payments_extras.py              mounted at /pay/
├── dashboard/              # no models: signed-in home (/tableau-de-bord/) + public wallet profile (/profil/<addr>/),
│                           # templates in dashboard/templates/dashboard/
├── templates/              # base.html, partials/{navbar,tabbar,toasts,modal,page_header}.html, core/landing.html,
│   │                       # 400/403/404/500.html, payments/_escrow_panel.html
│   ├── components/         # wallet, status_badge, tags, kpi, price, empty_state, pager, next_card, section_head
│   └── projects/           # project_list, project_form, project_detail, task_detail, board, my_projects
│                           # + _project_card, _task_row, _task_form, _candidates, _funding_panel, _board_card
├── static/
│   ├── css/  lowbid-tokens.css  lowbid-components.css  tailwind.src.css  tailwind.css (BUILT, committed)
│   ├── js/   lowbid-base.js  lowbid-ui.js  lowbid-wallet.js  lowbid-pay.js  lowbid-projects.js
│   ├── vendor/  fontawesome/  freighter-api.js (→ window.freighterApi)  stellar-sdk.min.js (→ window.StellarSdk)
│   └── img/favicon.svg
├── tests/e2e/              # run.js (Playwright scenario), fake-freighter.js, fake-horizon.js
├── data/                   # db.sqlite3 (gitignored), e2e.sqlite3 + e2e-server.log during make e2e
├── docs/                   # PRODUCT, PITCH, STELLAR_NOTES, FRONTEND, HACKATHON_DAY, DEMO_RUNBOOK, this file, screenshots/
├── CLAUDE.md               # project instructions for an AI assistant
├── requirements.txt  requirements-dev.txt  ruff.toml  Makefile  .env.example
├── package.json  tailwind.config.js        # npm run build:css / npm run vendor
├── Dockerfile  compose.yml                 # optional: django + postgres
└── .github/workflows/ci.yml                # ruff · django check + migrations + tests · tailwind-in-sync
```

## Run it

```bash
make dev          # venv + pip install + .env from .env.example + migrate + runserver 0.0.0.0:8000
make test         # manage.py check + makemigrations --check + test (222 tests)
make lint         # ruff check .
make css          # npm ci + tailwind build  (commit static/css/tailwind.css!)
make css-check    # rebuild and fail when the committed tailwind.css is stale (= CI tailwind-in-sync)
make check        # lint + test + css-check — the pre-commit gate
make seed         # python manage.py seed_demo --flush (3 wallets, the pitch-state project, a draft project)
make vendor       # re-copy Font Awesome / freighter-api / stellar-sdk from node_modules
make e2e          # Playwright end-to-end (see E2E below); `make shots` is an alias
```

Settings come from `.env` (python-dotenv, read once at boot). `DJANGO_DEBUG=0` **requires** `DJANGO_SECRET_KEY`.
Set `DJANGO_DB_HOST` to switch from SQLite to PostgreSQL (`DJANGO_DB_NAME/USER/PASSWORD/PORT`);
`LOWBID_SQLITE_PATH` moves the SQLite file (default `data/db.sqlite3`, `make e2e` uses `data/e2e.sqlite3`).

## E2E

`make e2e` picks two free ports, boots `runserver` against a fresh `data/e2e.sqlite3` in **direct** payment mode
with `STELLAR_HORIZON_URL` pointed at `tests/e2e/fake-horizon.js` (started by `run.js`), runs `node tests/e2e/run.js`
(plain `playwright` library, Chromium) and kills the server.

- `fake-freighter.js` is injected with `addInitScript` and replaces `window.freighterApi` with a keypair-backed fake
  (SEP-53 `signMessage`, `signTransaction` through the vendored `StellarSdk`), so the real login and the real payment
  signatures run end to end.
- `fake-horizon.js` is a toy ledger: accounts exist once "friendbotted", `change_trust` adds a trustline, a `payment`
  needs a funded source, a trustline on the destination and enough balance; rejections use Horizon's real
  `extras.result_codes`, so `payments.stellar` produces its usual French messages.
- The scenario: the company creates the project and three tasks inline → A and B apply to T1 (a third freelance applies
  through the API while the company's page polls) → the company chooses A → A delivers a link → the company validates
  with 5 stars → the chained payment fails gracefully (company unknown on Horizon, French message, `last_error`
  persisted) → the wallets are funded, A adds the USDC trustline from the panel, the company resumes « Payer le
  freelance » → T1 « Payé » with its stellar.expert link and A's balance at 300 → A and B apply to T2 → A ranks first
  with « Validé » + « Recommandé » (90.0 vs 20.0). Plus role refusals, the kanban, list filters, Mes projets,
  dashboard, profile, mobile at 390×844 (no horizontal scroll, tap targets), theme toggle, logout and 404s.
- Screenshots land in `docs/screenshots/` (`01-landing.png` … `15-financement-projet.png`, `mobile-*.png`). Any uncaught
  page error or unexpected `console.error` fails the run. The escrow steps are covered by `payments/tests_flow.py`
  (Trustless Work mocked), not by the e2e.

## Apps

| App | Owns | URLs |
|-----|------|------|
| `core` | landing (`core:landing`, live stats + latest projects), `GET /healthz/` (`core:healthz`), error handlers, context processors `site` (asset version, Stellar config, `asset_code` / `asset_issuer` / `asset_native` / `payment_mode`) and `nav_links`, template filters (`{% load lowbid_extras %}`) | `/`, `/healthz/` |
| `accounts` | `WalletUser(stellar_address, display_name, created_at, last_login_at)`, wallet auth, `wallet_required`, `get_wallet()`; context processor `wallet` (`wallet_address`, `wallet_user`) | `/auth/challenge/`, `/auth/verify/`, `/auth/logout/` |
| `projects` | the task board: models, `services.py` (every rule + the payment hooks), `scoring.py`, pages + JSON endpoints, `seed_demo` | `/projets/…`, `/taches/…`, `/mes-projets/` |
| `payments` | `Escrow` (1-1 `Task`), `services.py`, `trustless_work.py`, `stellar.py`, `{% escrow_panel task wallet %}` | `/pay/…` |
| `dashboard` | no models. `home` (`@wallet_required`): to-do list built from `payments.services.next_action()` and the projects data, KPIs as company and as freelance, recent activity. `profile` (public): identicon, display name (POST by its owner), projects posted, tasks paid, ratings received | `/tableau-de-bord/`, `/profil/<address>/` |

### Routes

| URL | View | Name | Auth |
|-----|------|------|------|
| `GET /projets/` | `project_list` | `projects:project_list` | public |
| `GET/POST /projets/nouveau/` | `project_create` (`ProjectForm`) | `projects:project_create` | wallet |
| `GET /projets/<pk>/` | `project_detail` | `projects:project_detail` | public |
| `GET /taches/` | `board` (kanban) | `projects:board` | wallet |
| `GET /taches/<pk>/` | `task_detail` | `projects:task_detail` | public |
| `GET /mes-projets/` | `my_projects` | `projects:my_projects` | wallet |
| `POST /projets/<pk>/taches/ajouter/` | `task_add` → 201 `{ok, task, count, total, message}` | `projects:task_add` | wallet |
| `POST /taches/<pk>/supprimer/` | `task_delete` | `projects:task_delete` | wallet |
| `POST /taches/<pk>/postuler/` | `apply_create` → 201 `{ok, application{id, score, tags}, message}` | `projects:apply_create` | wallet |
| `POST /taches/<pk>/choisir/<app_pk>/` | `task_choose` | `projects:task_choose` | wallet |
| `POST /taches/<pk>/livrer/` | `task_deliver` (DB-only delivery, refused in escrow mode) | `projects:task_deliver` | wallet |
| `POST /taches/<pk>/valider/` | `task_validate` → `{ok, status, project_status, next, message}` | `projects:task_validate` | wallet |
| `GET /taches/<pk>/candidats.json` | `task_candidates_json` → `{ok, status, count, fingerprint, candidates[], html}` | `projects:task_candidates_json` | public |
| `POST /pay/prepare/<task_pk>/<step>/` | `payments.views.prepare` | `payments:prepare` | wallet |
| `POST /pay/send/<task_pk>/<step>/` | `payments.views.send` | `payments:send` | wallet |
| `POST /pay/trustline/prepare/`, `POST /pay/trustline/send/` | trustline of the session wallet | `payments:trustline_prepare` / `_send` | wallet |
| `GET /pay/project/<pk>/pending.json` | `project_pending` → the tasks « Financer le projet » chains | `payments:project_pending` | wallet (company) |
| `GET /pay/<task_pk>/` | `task_pay` → 302 to the task page `#paiement` | `payments:task_pay` | public |
| `GET /tableau-de-bord/`, `GET/POST /profil/<address>/` | `dashboard.views.home` / `profile` | `dashboard:home` / `dashboard:profile` | wallet / public |

Projects refusals are 4xx `{ok:false, error, message}` (`ERROR_STATUS` in `projects/views.py`: 403 `forbidden`
`own_task` `not_assigned`, 409 `wrong_state` `duplicate`, 400 `invalid` `bad_tags`). Payments refusals are HTTP 200
`{ok:false, error, message}` so `Lowbid.api` resolves and the panel shows `message`. A `fetch` caller without a session
gets 401 `{ok:false, error:"wallet_required"}`; a browser gets a 302 to `/?next=…`.

## Data model

```
WalletUser ─┬─< Project (company, PROTECT) ──< Task (CASCADE) ──< Application (CASCADE) >── WalletUser (freelancer, PROTECT)
            │                                   │  └── assigned_to ─> WalletUser (PROTECT, null until chosen)
            │                                   ├── Rating (1-1, CASCADE): company, freelancer, note 1–5, comment
            │                                   └── Escrow (1-1, CASCADE, payments): mode, status, contract_id, hashes
```

| Model | Fields that matter |
|-------|--------------------|
| `projects.Project` | `company` (FK WalletUser), `title` (≤120), `description`, `status` `draft`/`funded`/`closed`. `Project.objects.with_totals()` annotates `total` (Σ task prices), `tasks_total`, `paid_total`, `open_total` in one query; `progress_pct` = paid / tasks |
| `projects.Task` | `project`, `title`, `description`, `price` `Decimal(18,7)`, `tags` (JSON list, ≤3), `status` `open`/`taken`/`delivered`/`paid`, `assigned_to`, `delivery_link` (≤500), `delivered_at`, `paid_at`, `position` (order in the project) |
| `projects.Application` | `task`, `freelancer`, `message` (≤280), `tags`, `score` `Decimal(5,1)` (stored, refreshed by `services.rescore`), `status` `pending`/`chosen`/`rejected`; unique (`task`, `freelancer`); default ordering `-score, created_at` |
| `projects.Rating` | `task` (1-1), `company`, `freelancer`, `note` 1–5, `comment` (≤280) |
| `payments.Escrow` | `task` (1-1, `related_name="escrow"`), `mode` `escrow`/`direct` (frozen at the first prepare), `amount` (= task price), `payer_address` (company), `payee_address` (freelance), `platform_address`, `contract_id`, `engagement_id` (`lowbid-task-<pk>`), `deploy/fund/deliver/approve/release/payment_tx_hash`, `status`, `delivery_note` (the evidence sent on chain, ≤280), `last_error`, `funded_at`, `delivered_at`, `released_at` |

Nothing Stellar-related is stored on the projects models: the escrow row is the only on-chain record.

## How auth works (wallet = identity)

1. Browser: `Lowbid.wallet.connect(next)` → `freighterApi.isConnected()` → `getNetwork()` (must match
   `STELLAR_NETWORK_PASSPHRASE`, else a French toast) → `requestAccess()` → address.
2. `POST /auth/challenge/` → the server stores `{"nonce","message","ts"}` in the session and returns
   `message = "Lowbid login <nonce> <unix ts>"` (TTL `WALLET_CHALLENGE_TTL_SECONDS`, 300 s).
3. Browser: `freighterApi.signMessage(message, {address})` → `{signedMessage, signerAddress}`.
   **Freighter ≥ 5.34 signs per SEP-53**: Ed25519 over `sha256("Stellar Signed Message:\n" + message)`,
   returned as a **base64 string** (API v4+; the older API returned a Buffer — `lowbid-wallet.js` normalises both).
4. `POST /auth/verify/ {address, signature, next}` → `accounts/signing.py::verify_signature` tries, in
   order, `sep53` → `raw` (UTF-8 bytes, pre-5.34 Freighter) → `sha256(message)`, and logs the scheme that
   matched. Success: `get_or_create(WalletUser)`, `session.cycle_key()`, session keys `wallet_address` +
   `wallet_user_id`, challenge consumed. Failure: 400 `{"ok": false, "error": "bad_signature" | "challenge_expired" |
   "no_challenge" | "invalid_address" | "invalid_signature_encoding"}`.
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
3. Rows come from `views._candidate_rows`: rank, score parts (`scoring.score_parts`), `Validé` (`scoring.is_validated` on `company_history`), `Recommandé` (`scoring.recommended_pk`, open tasks only), matched tags.

### Company: choose
`[data-choose]` → `Lowbid.confirm` → `/taches/<pk>/choisir/<app_pk>/` → `services.choose` (row lock, others `rejected`, task `taken`, `assigned_to`). Nothing touches the chain.

### Company: fund (escrow mode)
`[data-fund]` (« Financer le projet », project page header) → `Lowbid.pay.fundProject` → `GET /pay/project/<pk>/pending.json` (`payments.services.project_funding`: every `taken` task whose escrow is still `created`/`deployed`, with the company's `next` step) → for each task `Lowbid.pay.runChain(next, {stopAfter: ["fund"]})`: `prepare deploy` → Freighter → `send deploy` (stores `contract_id`) → `prepare fund` → Freighter → `send fund`. `confirm_fund` calls `sync_project_status`, which moves the project to `funded` once every assigned task holds its money. The same steps are available one by one on the task's payment panel (« Créer l’escrow », « Bloquer les fonds »).

### Freelance: deliver
- Escrow mode: `#deliver-form` + `[data-pay-step="deliver"]` → `POST /pay/prepare/<task>/deliver/ {delivery_link}` (link validated by `projects.services.clean_link`) → Trustless Work `change-milestone-status` XDR with the link as `newEvidence` → Freighter (freelance) → `POST /pay/send/<task>/deliver/ {signed_xdr, delivery_link}` → `confirm_deliver` sends it, then calls `projects.services.deliver(task, wallet, link, on_chain=True)`.
- Direct mode: the same button; `prepare_deliver` sees a `no_tx` step and calls `projects.services.deliver` directly — nothing to sign.
- `POST /taches/<pk>/livrer/` is the DB-only path; `_before_deliver` → `payments.services.check_db_deliver` refuses it in escrow mode.

### Company: validate, rate, pay
`#validate-form` → `POST /taches/<pk>/valider/ {note, comment}` → `services.validate`: stores the `Rating`, rescores the company's open tasks, calls `_after_validate` → `payments.services.on_task_validated` (makes sure the `Escrow` row exists, logs the next step, **pays nothing**) → the view answers `next` = `payments.services.next_action(task, company)`. `lowbid-projects.js` then runs `Lowbid.pay.runChain(next)`: `approve` → `release` (escrow) or `direct_pay` (direct), each a prepare → Freighter → send round trip. `confirm_release` / `confirm_direct_pay` call `projects.services.mark_paid(task)` and `sync_project_status`. If the chain stops (declined signature, Horizon down), the panel shows the remaining step as a `[data-pay-step]` button and the error in `[data-pay-error]` / `[data-last-error]`.

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
deliver     freelance  funded → delivered         taken → delivered    TW change-milestone-status (delivery link = evidence);
                                                                       confirm calls projects.services.deliver(link)
validate    company    —                          delivered (+Rating)  (projects) saves the Rating, answers `next` = approve
approve     company    delivered → approved       delivered            TW approve-milestone → approve_tx_hash
release     company    approved → released        delivered → paid     TW release-funds → release_tx_hash, released_at;
                                                                       confirm calls projects.services.mark_paid(task)

DIRECT mode (fallback: one `payment` op; "funded" and "approved" do not exist)
deliver     freelance  created → delivered        taken → delivered    NO transaction: projects.services.deliver(link)
validate    company    —                          delivered (+Rating)  (projects) saves the Rating, answers `next` = direct_pay
direct_pay  company    created|delivered → paid   delivered → paid     Django builds the payment XDR, Freighter signs,
                                                                       Django checks it (source/destination/amount/asset)
                                                                       and submits to Horizon → payment_tx_hash, released_at;
                                                                       mark_paid(task); project draft → funded on the first payment
trustline   anyone     —                          —                    changeTrust XDR, or nothing when Horizon already shows it
```

The validate view saves the Rating **first** (database), then the page chains the signatures (approve → release, or
direct_pay) from the `next` it gets back. Stopping half-way is fine: the panel shows the remaining step (« Libérer les
fonds »).

### Modes

- `payments.stellar.payment_mode()` is **the** switch: `LOWBID_PAYMENT_MODE=escrow` | `direct` | empty = auto (`escrow`
  when `TRUSTLESS_WORK_API_KEY` is set, else `direct`). A native-XLM asset (`STELLAR_ASSET_CODE=XLM`, empty issuer) is
  forced to `direct` (warning logged once per process), because Trustless Work v1 needs an issuer.
- The mode is **frozen on the Escrow row** at its first prepare (`ensure_escrow`). While the row is still `created`
  (nothing on chain) it is re-frozen to the configured mode, so `LOWBID_PAYMENT_MODE=direct` + restart after a failed
  deploy just works. A task whose escrow is deployed stays in escrow mode.
- `effective_mode(escrow)` = the row's mode, or the configured one while nothing is on chain; `display_status()` makes a
  direct-mode task delivered through the DB endpoint read as `delivered`, and a paid task always terminal.
- Escrow mode roles (Trustless Work): company = deploy signer, `approver`, `releaseSigner`, funder; chosen freelance =
  `serviceProvider` + `receiver`; `LOWBID_PLATFORM_ADDRESS` = `disputeResolver` + `platformAddress` (fee
  `LOWBID_PLATFORM_FEE`). When `LOWBID_PLATFORM_ADDRESS` is empty the company wallet takes both platform roles (warning
  logged, `[data-platform-fallback]` alert in the panel); Trustless Work may refuse that.

### Hooks between `projects` and `payments`

| Hook | Where | Called by | Does |
|------|-------|-----------|------|
| `projects.services.mark_paid(task)` | projects | `payments.services.confirm_release`, `_finalize_direct_pay` (and `seed_demo`) | the **only** function that flips a task to `paid` (idempotent); closes the project when every task is paid; rescores the company's open tasks |
| `projects.services._after_validate(task)` | projects | `projects.services.validate`, inside its transaction, after the Rating | lazily imports `payments.services` and calls `on_task_validated(task)` |
| `payments.services.on_task_validated(task)` | payments | `_after_validate` | `ensure_escrow(task)` and logs the next step (approve → release, or direct_pay). Pays nothing |
| `projects.services._before_deliver(task)` | projects | `projects.services.deliver` when `on_chain=False` | calls `payments.services.check_db_deliver(task)`, which refuses a DB-only delivery in escrow mode |
| `projects.services.deliver(..., on_chain=True)` | projects | `payments.services.confirm_deliver` (escrow) / `prepare_deliver` (direct, `no_tx`) | records the delivery once the milestone change is confirmed |
| `payments.services.sync_project_status(project)` | payments | `confirm_fund`, `confirm_release`, `_finalize_direct_pay` | project `draft → funded` (escrow: every assigned task holds funds; direct: first payment) |

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
« Financer le projet » simply chains those steps task after task. Cost: two company signatures per task instead of two
per project.

### Endpoints and response shapes (`payments/views.py`)

- `POST /pay/prepare/<task_pk>/<step>/` (body `{delivery_link}` for `deliver`) → `{ok, xdr, send_url, extra}`, or
  `{ok, redirect, message, next}` when there is nothing to sign (direct delivery, reconciled payment).
- `POST /pay/send/<task_pk>/<step>/ {signed_xdr, ...extra}` → `{ok, redirect, status, task_status, tx_hash, hash,
  contract_id, explorer_url, message, pending, next}`.
- `next` = the viewer's following step (`{step, label, prepare_url, mine, who, evidence, no_tx, hint, task}` or `null`):
  `lowbid-pay.js` chains it while it is the viewer's own signature.
- Refusals: HTTP 200 `{ok:false, error, message}`, codes `not_chosen · forbidden · wrong_state · wrong_mode ·
  unknown_step · tampered · provider · stellar · invalid · not_assigned`.

### Guarantees

- Role and state gates run in **both** halves (prepare and confirm), pinned to the session wallet; every role field in a
  Trustless Work body or a payment XDR comes from the `Escrow` row, never from the request.
- `confirm_direct_pay` parses the signed XDR (`stellar.parse_payment_xdr`) and refuses anything but one payment
  payer → payee of `amount` in the configured asset (`tampered`).
- Idempotency: a replayed send for a step already recorded with the same hash answers « Étape déjà confirmée. ».
- A provider failure never flips a status; the message is stored in `Escrow.last_error` after the transaction rolled back
  (`_records_errors`). A Horizon 504 on a direct payment stores the locally computed hash as pending; the next
  `prepare_direct_pay` reconciles it with `stellar.transaction_status(hash)` without a second signature.
- View-models: `next_action(task, wallet)` (the panel and the dashboard agree on the pending step), `stepper(mode,
  status)`, `project_funding(project)` (banner: total, funded, paid, pending tasks, per-task rows and explorer links,
  `can_fund` + hint).

## Where Stellar lives

- `lowbid/settings.py` → `STELLAR_NETWORK` (`testnet`), `STELLAR_NETWORK_PASSPHRASE`, `STELLAR_HORIZON_URL`,
  `STELLAR_SOROBAN_RPC_URL`, `STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER` (defaults to the legacy `STELLAR_USDC_CODE` /
  `STELLAR_USDC_ISSUER`, i.e. Circle testnet USDC), `TRUSTLESS_WORK_API_URL`, `TRUSTLESS_WORK_API_KEY`,
  `LOWBID_PAYMENT_MODE`, `LOWBID_PLATFORM_ADDRESS`, `LOWBID_PLATFORM_FEE`.
- Python: `stellar-sdk` (login verification, XDR building and parsing); `requests` for Horizon and Trustless Work, both
  wrapped in a never-raising `{ok, status, data, error}` envelope.
- Browser: `window.LOWBID` = `{network, networkPassphrase, horizonUrl, sorobanRpcUrl, asset:{code, issuer, native},
  paymentMode, walletAddress, urls:{challenge, verify, logout, landing, dashboard, trustlinePrepare, trustlineSend}}`;
  `window.StellarSdk` (vendored, `defer`); `window.freighterApi`; `Lowbid.signTransaction(xdr, {networkPassphrase?,
  address?})`.

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
- Session cookie 8 h, `SameSite=Lax`, secure when `DJANGO_FORCE_HTTPS=1`.
- Frontend assets are build artifacts that get **committed**; CI `tailwind-in-sync` fails on a stale
  `static/css/tailwind.css`. Nothing loads from a CDN (fonts = system stack, icons = vendored Font Awesome).
- Tokens → components → Tailwind load order; colours only via `var(--*)` so light mode is free.
