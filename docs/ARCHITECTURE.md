# Lowbid — Architecture

Reverse auction for freelancers on Stellar (Hack Meridian). Django 5.2 server-rendered
pages, SQLite by default, a wallet (Freighter) as the only identity, USDC on testnet.
Deliberately hackathon-sized: no DRF, no Redis, no SPA.

## Tree

```
Lowbid/
├── manage.py
├── lowbid/                 # project: settings.py (env-driven), urls.py, wsgi.py
├── core/                   # landing, /healthz/, context processors, templatetags/lowbid_extras.py
├── accounts/               # WalletUser + Freighter login (challenge / verify / logout), wallet_required
├── auctions/               # Need / Bid, services (R1–R14), scoring, seed_demo          mounted at /
├── payments/               # Escrow model + services (Trustless Work / Plan B), JSON endpoints  mounted at /pay/
├── dashboard/              # no models: signed-in home (/tableau-de-bord/) + public wallet profile (/profil/<addr>/)
├── templates/              # base.html, partials/{navbar,tabbar,toasts,modal,page_header}.html, core/landing.html, 400/403/404/500.html
│   └── components/         # reusable includes: wallet, status_badge, countdown, tags, kpi, price, empty_state, pager, next_card, section_head
├── static/
│   ├── css/  lowbid-tokens.css  lowbid-components.css  tailwind.src.css  tailwind.css (BUILT, committed)
│   ├── js/   lowbid-base.js (theme, toasts, Lowbid.api)  lowbid-ui.js (confirm modal, menus, identicons, sparklines, Lowbid.poll)
│   │         lowbid-wallet.js (Freighter)  lowbid-pay.js (sign & send)  lowbid-auctions.js (countdowns, bid form, polling, sliders)
│   ├── vendor/  fontawesome/  freighter-api.js (UMD → window.freighterApi)  stellar-sdk.min.js (→ window.StellarSdk)
│   └── img/favicon.svg
├── data/                   # db.sqlite3 (gitignored)
├── docs/                   # PRODUCT.md, PITCH.md, STELLAR_NOTES.md, FRONTEND.md (design system), HACKATHON_DAY.md, DEMO_RUNBOOK.md, this file
├── CLAUDE.md               # project instructions for an AI assistant (commands, conventions, don'ts)
├── requirements.txt  requirements-dev.txt  ruff.toml  Makefile  .env.example
├── package.json  tailwind.config.js        # npm run build:css / npm run vendor
├── Dockerfile  compose.yml                 # optional: django + postgres
└── .github/workflows/ci.yml                # ruff · django tests · tailwind-in-sync
```

## Run it

```bash
make dev          # venv + pip install + .env from .env.example + migrate + runserver 0.0.0.0:8000
make test         # manage.py check + makemigrations --check + test
make lint         # ruff check .
make css          # npm ci + tailwind build  (commit static/css/tailwind.css!)
make css-check    # rebuild and fail when the committed tailwind.css is stale (= CI tailwind-in-sync)
make check        # lint + test + css-check — the pre-commit gate
make seed         # python manage.py seed_demo --flush (demo wallets, needs, bids)
make vendor       # re-copy Font Awesome / freighter-api / stellar-sdk from node_modules
make e2e          # Playwright end-to-end with a simulated Freighter (see E2E below); `make shots` is an alias
```

Settings come from `.env` (python-dotenv). `DJANGO_DEBUG=0` **requires** `DJANGO_SECRET_KEY`.
Set `DJANGO_DB_HOST` to switch from SQLite to PostgreSQL (`DJANGO_DB_NAME/USER/PASSWORD/PORT`);
`LOWBID_SQLITE_PATH` moves the SQLite file (default `data/db.sqlite3`, `make e2e` uses `data/e2e.sqlite3`).

## E2E

`make e2e` boots `runserver` on a free port against a fresh `data/e2e.sqlite3` (`LOWBID_SQLITE_PATH`), runs
`node tests/e2e/run.js` (plain `playwright` library, Chromium, no `@playwright/test`) and kills the server.
`tests/e2e/fake-freighter.js` is injected with `addInitScript` before any page script and replaces
`window.freighterApi` with a keypair-backed fake: SEP-53 `signMessage` and `signTransaction` via the vendored
`window.StellarSdk`, so the real login (`/auth/challenge/` → `/auth/verify/`) runs end to end. Three contexts
(client, freelance1, freelance2) walk the whole flow at 1280×800 — post, descending bids with the `not_lower`
refusal, polling, close, sliders, choosing a non-recommended bid, Mes enchères / Mes besoins, the client's payment
button ("Payer le freelance" / "Valider et payer" in direct mode, "Créer l’escrow" / "Bloquer les fonds" in escrow
mode) failing gracefully without network, theme + logout — and the key screens are re-checked at 390×844 (no horizontal
scroll, tap targets). Screenshots land in `docs/screenshots/` (`01-landing.png` … `10-mobile-liste.png`, used by
the pitch). Any uncaught page error or unexpected `console.error` fails the run; on-chain steps (Horizon,
Trustless Work) are out of scope.

## Apps

| App | Owns | URLs |
|-----|------|------|
| `core` | landing (`core:landing`), `GET /healthz/` (`core:healthz`), error handlers, context processors `core.context_processors.site` (asset version + Stellar config) and `nav_links`, filters `short_addr`, `usdc` (`{% load lowbid_extras %}`) | `/` |
| `accounts` | `WalletUser(stellar_address, display_name, created_at, last_login_at)`, wallet auth, `wallet_required`, `get_wallet()` | `/auth/challenge/` `accounts:challenge`, `/auth/verify/` `accounts:verify`, `/auth/logout/` `accounts:logout` |
| `auctions` | `Need` / `Bid`, `services.py` (R1–R14), `scoring.py`, pages + JSON endpoints, `seed_demo` command — see **Auctions** below | `/besoins/…`, `/mes-encheres/`, `/mes-besoins/` |
| `payments` | `Escrow` (1-1 `Need`), `services.py` (prepare/confirm per step, both modes), `trustless_work.py`, `stellar.py`, `{% escrow_panel %}` tag — see **Payments** below | `/pay/…` |
| `dashboard` | No models. `home` (`dashboard:home`, `@wallet_required`): the signed-in landing — what the viewer has to do next (needs to award, payments to sign, deliveries to declare), KPIs as client and as freelancer, recent activity. `profile` (`dashboard:profile`, public): a wallet's identicon, display name (editable by its owner), needs posted, bids won. Reads `auctions` / `payments` only | `/tableau-de-bord/` `dashboard:home`, `/profil/<address>/` `dashboard:profile` |

`datagrid`-style engines were NOT ported from SIPS — list pages here are plain templates.

## How auth works (wallet = identity)

1. Browser: `Lowbid.wallet.connect(next)` → `freighterApi.isConnected()` → `getNetwork()` (must match
   `STELLAR_NETWORK_PASSPHRASE`, else a French toast) → `requestAccess()` → address.
2. `POST /auth/challenge/` → server stores `{"nonce","message","ts"}` in the session and returns
   `message = "Lowbid login <nonce> <unix ts>"` (TTL `WALLET_CHALLENGE_TTL_SECONDS`, 300 s).
3. Browser: `freighterApi.signMessage(message, {address})` → `{signedMessage, signerAddress}`.
   **Freighter ≥ 5.34 signs per SEP-53**: Ed25519 over `sha256("Stellar Signed Message:\n" + message)`,
   returned as a **base64 string** (API v4+; older API returned a Buffer — `lowbid-wallet.js` normalises both).
4. `POST /auth/verify/ {address, signature, next}` → `accounts/signing.py::verify_signature` tries, in
   order, `sep53` → `raw` (UTF-8 bytes, pre-5.34 Freighter) → `sha256(message)`, and logs the scheme that
   matched (`wallet login ok address=… scheme=sep53`). Success: `get_or_create(WalletUser)`,
   `session.cycle_key()`, session keys `wallet_address` + `wallet_user_id`, challenge consumed.
   Failure: 400 `{"ok": false, "error": "bad_signature" | "challenge_expired" | "no_challenge" |
   "invalid_address" | "invalid_signature_encoding"}`.
5. `POST /auth/logout/` flushes the session (302 to landing, or `{"ok": true}` for fetch callers).

Server-side helpers:

```python
from accounts.decorators import wallet_required   # redirect → /?next=…  (401 JSON for fetch)
from accounts.identity import get_wallet, get_wallet_address

@wallet_required
def need_create(request):
    wallet = get_wallet(request)       # WalletUser, cached per request
```

Templates get `wallet_address` and `wallet_user` on every page.

## Where Stellar lives

- `lowbid/settings.py` → `STELLAR_NETWORK` (`testnet`), `STELLAR_NETWORK_PASSPHRASE`, `STELLAR_HORIZON_URL`,
  `STELLAR_SOROBAN_RPC_URL`, `STELLAR_USDC_ISSUER` (Circle testnet), `STELLAR_USDC_CODE`,
  `TRUSTLESS_WORK_API_URL`, `TRUSTLESS_WORK_API_KEY`.
- Python: `stellar-sdk` (used today only for `Keypair.verify*`; it also builds/submits transactions).
- Browser: `window.LOWBID` = `{network, networkPassphrase, horizonUrl, sorobanRpcUrl, usdc:{code,issuer},
  walletAddress, urls:{challenge,verify,logout,landing}}`; `window.StellarSdk` (vendored, loaded `defer`);
  `window.freighterApi`; `window.Lowbid.signTransaction(xdr, {networkPassphrase?, address?}) → signedXdr`.

## Auctions (`auctions/`)

**Models** (`auctions/models.py`, migration `0001`):

- `Need(client→WalletUser PROTECT, title, description, budget_max Decimal(18,7), delay_max_days,
  tags JSON ≤3 slugs, bidding_ends_at, status, winning_bid OneToOne→Bid null, awarded_at, created_at, updated_at)`.
  `status`: `open → closed → awarded → funded → delivered → released`, plus `cancelled`.
  **The timer is lazy**: `need.effective_status()` returns `closed` for an `open` need past its deadline,
  `Need.objects.close_expired()` persists that and runs at the top of every auctions view — no cron.
  Helpers: `is_bidding_open()`, `best_price` (None without bids), `current_price` (best or budget),
  `bids_count`, `ranked_bid_qs()` (everything but `outbid`), `active_bid_for(wallet)`, `is_client(wallet)`,
  `can_cancel`, `badge_class` / `effective_status_label` for templates. `Need.objects.with_stats()` annotates
  `bid_count` / `lowest_price` for list pages.
- `Bid(need, freelancer→WalletUser PROTECT, price, delay_days, tags, message ≤280, status, created_at)`.
  `status`: `active | outbid | won | lost`. DB constraint: one `active` bid per (need, freelancer).

**Services** (`auctions/services.py`) — every rule in one place, views only map codes to HTTP:

```python
place_bid(need, freelancer, price, delay_days, tags, message="") -> Bid
    # BidError codes: closed · own_need · not_lower · over_budget · over_delay · bad_tags · invalid (R7)
    # atomic + select_for_update(need); re-bidding supersedes the freelancer's own active bid (→ outbid)
close_bidding_now(need, client) -> Need   # NeedError: forbidden · not_open   (demo shortcut, sets ends_at=now)
award(need, bid, client) -> Need          # NeedError: forbidden · not_closed · bad_bid  → winner won, others lost
cancel(need, client) -> Need              # NeedError: forbidden · too_late  (allowed while open/closed/awarded, R14)
clean_tags(raw) / parse_price(raw) / dec_str(decimal)
```

**Scoring** (`auctions/scoring.py`): `score_bid(bid, need, weights=(40,30,30)) -> {total, price_part, delay_part,
skills_part, *_ratio}` (ratios clamped to [0,1], no requested tag ⇒ skills ratio 1), `rank_bids(need, weights)`
(desc total, then cheaper, then earlier), `normalise_weights(wp, wd, ws)` (ints → sum exactly 100, invalid ⇒ default).
Weights come from `?wp=&wd=&ws=`; the detail page re-ranks client-side from `data-*-ratio` attributes.

**URLs** (namespace `auctions`, mounted at `/`):

| Name | Path | Method | Who |
|------|------|--------|-----|
| `need_list` | `/besoins/?tab=open|closed|all&tag=&q=&sort=ending|newest|budget|bids&page=` | GET | public — toolbar: text search `q`, tag filter, sort, pagination (`components/pager.html` keeps the query string via `{% qs %}`) |
| `need_create` | `/besoins/nouveau/` (`?demo=1` shows a 5-min deadline) | GET/POST | wallet |
| `need_detail` | `/besoins/<pk>/?wp=&wd=&ws=` | GET | public (form / sliders by role) |
| `my_bids` | `/mes-encheres/` | GET | wallet |
| `my_needs` | `/mes-besoins/` | GET | wallet |
| `need_bids_json` | `/besoins/<pk>/encheres.json` | GET | public — polled every 5 s; `{status, fingerprint, best_price, count, bids[], html}` |
| `bid_create` | `/besoins/<pk>/encherir/` | POST JSON `{price, delay_days, tags, message}` | wallet → 201 / 400 `{error, message}` |
| `need_close` | `/besoins/<pk>/cloturer/` | POST | client → 200 / 403 / 409 |
| `need_award` | `/besoins/<pk>/choisir/<bid_pk>/` | POST | client → `{status:"awarded", payee, amount}` |
| `need_cancel` | `/besoins/<pk>/annuler/` | POST | client |

Templates: `templates/auctions/{need_list,need_form,need_detail,my_bids,my_needs}.html`, partials
`_need_card.html`, `_bids_list.html` (also returned as `html` by `encheres.json`). The detail page also shows a
**price history sparkline** (`svg.ui-sparkline[data-points][data-cap]`, drawn by `Lowbid.sparkline`), a **bid timeline**
(`.ui-timeline`, every bid including superseded ones) and a **share** button (`[data-share]`, Web Share or copy). Page JS:
`static/js/lowbid-auctions.js` (countdowns on every page, bid form, polling, sliders, choose/close/cancel);
the detail page passes its config through `window.LOWBID_NEED`. Demo data: `python manage.py seed_demo [--flush]`
(addresses from `LOWBID_DEMO_CLIENT` / `LOWBID_DEMO_FREELANCE1` / `LOWBID_DEMO_FREELANCE2`).

**Contract with `payments`**: the detail page includes `templates/payments/_escrow_panel.html` with `need` and
`winning_bid` once `status` is `awarded` or later (a stub lives there today). Payee =
`need.winning_bid.freelancer.stellar_address`, amount = `need.winning_bid.price` (USDC, Decimal(18,7)),
payer = `need.client.stellar_address`. The transitions `awarded → funded → delivered → released` belong to
`payments` (write `need.status`, keep `updated_at`); `auctions` never moves a need past `awarded`, and
`services.cancel` already refuses once `funded` (R14). `Need.Status` is the enum to import.

## Payments (`payments/`)

**Model** `Escrow` (`payments/models.py`, migration `0001`), one per `Need` (`need.escrow`, created at the
first prepare): `mode` (`escrow` | `direct`, frozen from `stellar.payment_mode()`, re-frozen while still
`created`), `amount`, `payer_address` (client), `payee_address` (winner), `platform_address`, `contract_id`,
`engagement_id` (`lowbid-<need_id>`), one `*_tx_hash` per step (`deploy / fund / deliver / approve / release /
payment`), `status`, `delivery_note` (≤ 280), `last_error`, `funded_at / delivered_at / released_at`.
Helpers: `status_label`, `badge_class`, `is_done`, `explorer_links()` (stellar.expert, contract + every hash).

**State table** (`Escrow.status` ⇢ `Need.status`; `payments` owns `awarded → funded → delivered → released`):

| Mode | Step | Who signs | Escrow before → after | Need before → after | On chain |
|------|------|-----------|-----------------------|---------------------|----------|
| escrow | `deploy` | client | created → deployed | awarded | TW `/deployer/single-release` → `contract_id` |
| escrow | `fund` | client | deployed → funded | awarded → **funded** | TW `fund-escrow` |
| escrow | `deliver` | winner | funded → delivered | funded → **delivered** | TW `change-milestone-status` (+ evidence) |
| escrow | `approve` | client | delivered → approved | delivered | TW `approve-milestone` |
| escrow | `release` | client | approved → released | delivered → **released** | TW `release-funds` |
| direct | `deliver` | winner | created → delivered | awarded → **delivered** | **nothing** (DB only) |
| direct | `direct_pay` | client | created\|delivered → paid | awarded\|delivered → **released** | one USDC `payment` op via Horizon |
| any | `trustline` | the wallet | — | — | `changeTrust` (skipped when Horizon already shows it) |

Direct mode (**Plan B**) therefore skips `funded`/`approved`: awarded → (deliver, optional) → direct_pay → released;
the client's "Valider et payer" *is* the payment. Every signed XDR in direct mode is parsed server-side
(`stellar.parse_payment_xdr`) and must match source = client, destination = winner, amount = bid, USDC
issuer — else `tampered`. A Horizon 504 keeps the status, stores the hash and the next prepare reconciles it
through `/transactions/{hash}` (no second signature). Provider/Horizon refusals never change the status: the
message is kept in `last_error` and the user retries.

**Services** (`payments/services.py`, no HTTP of its own): `prepare_<step>(need, wallet, data) → {xdr, extra,
message, done}` / `confirm_<step>(need, wallet, signed_xdr) → {tx_hash, contract_id, explorer_url, message,
pending}` with role + state gates in both halves, pinned to the session wallet; `prepare(...)` / `confirm(...)`
dispatchers; `next_action(need, wallet)` (the pending step as this viewer should see it: `step, who, label,
hint, prepare_url, mine, waiting, evidence, no_tx`); `stepper(mode, status)`; `viewer_role()`;
`PaymentError(code, message)` with codes `not_awarded · forbidden · wrong_state · wrong_mode · unknown_step ·
tampered · provider · stellar`.

**URLs** (namespace `payments`, mounted at `/pay/`, all JSON, `@wallet_required` → 401 JSON for fetch):

| Name | Path | Returns |
|------|------|---------|
| `prepare` | `POST /pay/prepare/<need_pk>/<step>/` (body: `{evidence?}`) | `{ok, xdr, send_url, extra}` or `{ok, redirect, message}` when nothing to sign |
| `send` | `POST /pay/send/<need_pk>/<step>/` `{signed_xdr}` | `{ok, redirect, status, tx_hash, contract_id, explorer_url, message, pending}` |
| `trustline_prepare` | `POST /pay/trustline/prepare/` | `{ok, xdr, send_url}` or `{ok, message}` when present |
| `trustline_send` | `POST /pay/trustline/send/` `{signed_xdr}` | `{ok, tx_hash, explorer_url, message}` |
| `need_pay` | `GET /pay/<need_pk>/` | 302 → `/besoins/<pk>/#paiement` |

Business refusals are **HTTP 200 `{ok:false, error:<code>, message}`** (the JS renders `message`).

**UI**: `templates/payments/_escrow_panel.html` is rendered by `{% escrow_panel need wallet %}`
(`payments/templatetags/payments_extras.py`) from `need_detail.html` once the need is awarded: stepper, amount,
payee + copy, live `[data-usdc-balance][data-watch]` (Horizon, from the browser), the viewer's next-action
button (`[data-pay-step][data-prepare-url]`, delivery form for the winner), trustline helper for both parties,
explorer links. `static/js/lowbid-pay.js` (loaded in `base.html` after the wallet module) does prepare → Freighter
sign → send → reload; `LOWBID.urls.trustlinePrepare/trustlineSend` are set in `base.html`.

**Switching to Plan B**: `LOWBID_PAYMENT_MODE=direct` in `.env` and restart. Empty = auto (`escrow` when
`TRUSTLESS_WORK_API_KEY` is set, else `direct`). Needs already deployed on Trustless Work keep their frozen
`escrow` mode; needs still `created` switch.

## Adding `auctions` / `payments`

- Models in `<app>/models.py`, `python manage.py makemigrations <app>` — commit the migration (CI runs
  `makemigrations --check`). Use `WalletUser` FKs (`on_delete=PROTECT`) for client / freelancer.
- Views are plain function views; return `render(...)` or `JsonResponse`. Unsafe JSON calls from the
  browser go through `Lowbid.api(url, {method:"POST", body:{…}})` (CSRF + JSON handled).
- Register URL names in `<app>/urls.py` (namespaces `auctions` / `payments` / `dashboard`); the navbar **and** the
  mobile tab bar entries live in `core/context_processors.py::NAV_LINKS` (Besoins · Mes enchères · Poster un besoin ·
  Mes besoins · Tableau de bord).
- Templates extend `base.html`; blocks: `title`, `meta_description`, `extra_head`, `body_class`,
  `content`, `extra_js`. Header: `{% include "partials/page_header.html" with title=… subtitle=… %}`.
- Compose with the includes in `templates/components/` — `wallet` (identicon + short address, links to the profile),
  `status_badge`, `countdown`, `tags`, `kpi`, `price`, `empty_state`, `pager` (Django `Page`), `next_card`
  (`act|wait|done`), `section_head` — parameters are documented in each file's `{% comment %}` header and in
  `docs/FRONTEND.md`. Template tags: `{% qs page=2 %}` (current query string with keys replaced), `|pct`, `|hue`.
- `static/js/lowbid-ui.js` (loaded on every page): `Lowbid.confirm({...})` (the `#lb-confirm` dialog from
  `partials/modal.html` — never `window.confirm`), `Lowbid.modal`, `Lowbid.identicon` / `[data-identicon]`,
  `Lowbid.timeAgo` / `[data-time-ago]`, `Lowbid.sparkline`, `Lowbid.poll(fn, {interval})` (visibility-aware, backoff),
  `Lowbid.refreshUI(root)` after an `innerHTML` swap, `Lowbid.setBusy(btn, on, label)`, and the declarative
  `[data-share]`, `form[data-confirm]`, `[data-search-clear]`, `[data-auto-submit]`, `details.ui-menu`.
- Mobile: tables in `.rcard` (+ `data-label` per cell), form buttons in `.ui-sticky-actions` inside a `.ui-form-scope`,
  and the signed-in bottom tab bar (`partials/tabbar.html`, fed by `NAV_LINKS` — `short` label, `primary` flag).
- UI vocabulary (all theme-token driven, dark + light): `.glass-card`, `.glass-soft`, `.ui-panel`
  (+`-head/-title/-sub`), `.ui-page-header/-title/-sub/-actions`, `.ui-btn` (+`-primary -ghost -danger
  -danger-solid -sm -lg -block`), `.ui-field .ui-label .ui-input .ui-select .ui-textarea .ui-help
  .ui-error .ui-form-grid .ui-field-wide .ui-input-group .ui-input-addon`, `.ui-badge` (+`-ok -attn
  -danger -info -brand -neutral`; **`.ui-badge-brand` is the "Recommandé" badge**), `.ui-tag` (+`.is-match`),
  `.ui-alert` (+`-ok -attn -danger -info`), `.ui-kpi-band .ui-kpi-tile/-label/-value/-hint`,
  `.ui-countdown` (+`.is-urgent`), `.ui-price .ui-price-unit`, `.ui-list .ui-list-row .ui-rank`,
  `.empty-state/-icon/-title/-desc`, `.seg-tabs .seg-tab.is-active`, `.seg-radio`, `.ui-meta .ui-link .ui-num`,
  `.ui-toolbar .ui-search .ui-select-inline .ui-chip-row`, `.ui-pager`, `.ui-menu .ui-menu-panel .ui-menu-item`,
  `.ui-modal .ui-modal-card`, `.ui-timeline .ui-timeline-item.is-brand/.is-ok/.is-muted`, `.ui-next-card.act/.wait/.done`,
  `.ui-wallet .ui-identicon`, `.ui-sparkline`, `.ui-skeleton`, `.ui-progress`, `.ui-facts`, `.ui-live`, `.ui-split .ui-stack`,
  `.ui-section-head`, `.ui-sticky-actions` (+ `.ui-form-scope`), `.lb-tabbar .lb-tab`,
  and `.rcard` (wrapper div around a `<table>`; each `<td data-label="…">` — stacks into cards under
  640 px of container width, no horizontal scroll). Full reference with markup: `docs/FRONTEND.md`. Tailwind utilities are available on top
  (`brand-*` colours follow the theme) — **rebuild `tailwind.css` after adding classes**.
- Toasts: `Lowbid.toast("…", "success|error|warning|info", {title, duration})`.
- Money / addresses in templates: `{{ amount|usdc }}` → `1,234.50 USDC`, `{{ addr|short_addr }}` → `GABC…WXYZ`.
- Keep the shell JS in `static/js/`; bump `LOWBID_ASSET_VERSION` (settings or `.env`) when editing
  `lowbid-*.css` / `lowbid-*.js` (30-day static cache in non-DEBUG).

## Conventions kept from SIPS

- Python 3.13, 4-space, `snake_case`, type hints where cheap, `logger = logging.getLogger(__name__)`.
- Broad `except Exception` only with `logger.exception(...)` — never a silent `except: pass`. No `print()`.
- Config via `.env` / environment only (`_csv` / `_bool` helpers); never hardcode hosts or secrets.
- Structured `level=… logger=… msg=…` logs on stdout, level from `DJANGO_LOG_LEVEL`.
- Session cookie 8 h, `SameSite=Lax`, secure when `DJANGO_FORCE_HTTPS=1`.
- Frontend assets are build artifacts that get **committed**; CI `tailwind-in-sync` fails on a stale
  `static/css/tailwind.css`. Nothing loads from a CDN (fonts = system stack, icons = vendored Font Awesome).
- Tokens → components → Tailwind load order; colours only via `var(--*)` so light mode is free.
