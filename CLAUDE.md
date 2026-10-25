# TaskVault — project instructions

**TaskVault** (formerly Lowbid: the code, settings and static files keep the `lowbid` / `LOWBID_` / `Lowbid` prefix) is a task board for freelancers on Stellar (Hack Meridian, track *Composed*). A company splits a project into **fixed-price tasks**. Freelances apply to a task with a message and their skills (no price). The company picks one freelance per task, with a deterministic score as a hint. The chosen freelance delivers a link, the company validates and rates the delivery (1–5), and the task's price is released in **USDC from a Trustless Work escrow on Soroban**: one single-release escrow **per task**, deployed and funded once the freelance is chosen. The fallback is a direct USDC payment at validation. The payment asset can be configured. UI copy, code, docs and commits are **English** (URL paths stay French: `/projets/`, `/taches/`, …).

There is **no GSD workflow** in this repo. Edit files directly, run `make check`, commit.

## Stack

- Python 3.13 · Django 5.2 (server-rendered templates, function views, no DRF) · SQLite by default (`data/db.sqlite3`, moved by `LOWBID_SQLITE_PATH`), PostgreSQL when `DJANGO_DB_HOST` is set · whitenoise for static files · gunicorn in Docker.
- Frontend: **self-hosted Tailwind v3** compiled into the committed `static/css/tailwind.css`, two hand-written CSS files (`lowbid-tokens.css`, `lowbid-components.css`), vanilla JS (`static/js/lowbid-*.js`). Vendored under `static/vendor/`: Font Awesome, `@stellar/freighter-api` (global `freighterApi`), `@stellar/stellar-sdk` (global `StellarSdk`), anime.js v4 (`anime.umd.min.js`, global `anime`, landing only). **Nothing loads from a CDN.**
- Stellar: the Freighter wallet is the identity (SEP-53 `signMessage` login). The payment asset is `STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER` (default: Circle testnet USDC; `XLM` with an empty issuer means native XLM, which forces direct mode). Trustless Work v1 REST runs the escrow; Horizon serves balances, trustlines and direct payments. Python side: `stellar-sdk`.
- Tests: Django test runner (`manage.py test`, 268 tests, network mocked) and a Playwright e2e run with a simulated Freighter and a fake Horizon (`make e2e`). Linter: ruff (baseline rules only, see `ruff.toml`).

## Commands

```bash
make            # = make all: venv + .env + migrate + check + e2e (screenshots in data/e2e-shots/), then runserver — hands-off
make verify     # the same checks, without starting the server
make dev        # venv + pip install + .env from .env.example + migrate + runserver 0.0.0.0:8000
make test       # manage.py check + makemigrations --check --dry-run + test -v 2
make lint       # ruff check .
make css        # npm ci (once) + tailwind build → static/css/tailwind.css  (COMMIT the output)
make css-check  # rebuild and fail if the committed tailwind.css is stale (same as CI)
make check      # lint + test + css-check — run before every commit
make seed       # python manage.py seed_demo --flush (3 wallets, 2 projects: the pitch state + a draft)
make e2e        # Playwright task-board scenario, fake Freighter + fake Horizon, direct mode, throwaway SQLite; screenshots → docs/screenshots/ (E2E_SHOTS_DIR overrides; Chromium fetched once by `make playwright`)
make shots      # e2e with the default folder (regenerates the pitch screenshots in docs/screenshots/)
make fmt        # ruff check --fix .
make run        # runserver $(HOST):$(PORT) (default 0.0.0.0:8000), no migrate
npm run build:css / npm run watch:css / npm run vendor
```

`PY` is detected (python3.13, else python3.14, else python3; override with `make PY=…`). `.env` is read once at boot (python-dotenv): restart `make run` after any change. `DJANGO_DEBUG=0` requires `DJANGO_SECRET_KEY` (and running `manage.py` without a `.env` falls back to `DEBUG=0`, so set `DJANGO_DEBUG=1` or create `.env` first).

**Asset cache rule:** static files are served with a 30-day `max-age` outside DEBUG and cache-busted only by `?v={{ LOWBID_ASSET_VERSION }}`. After editing any `static/css/lowbid-*.css` or `static/js/lowbid-*.js`, bump `LOWBID_ASSET_VERSION` (default in `lowbid/settings.py`, override in `.env`).

## Repo map

| Path | Owns |
|------|------|
| `lowbid/` | `settings.py` (every value from env, `_csv`/`_bool` helpers), `urls.py` (mounts below), `wsgi.py` |
| `core/` | landing (`core:landing`), `/healthz/`, error handlers, context processors `site` (Stellar config, `asset_code` / `asset_issuer` / `asset_native` / `payment_mode`) + `nav_links` (`NAV_LINKS` = navbar **and** mobile tab bar), templatetags `lowbid_extras` (`short_addr`, `usdc`, `usdc_parts`, `plain`, `qs`, `pct`, `hue`, `underline_last`) |
| `accounts/` | `WalletUser`, Freighter login (`/auth/challenge/`, `/auth/verify/`, `/auth/logout/`), `signing.py` (SEP-53 verify), `decorators.wallet_required`, `identity.get_wallet()` |
| `projects/` | `Project` / `Task` / `Application` / `Rating` / `Delivery` / `RevisionRequest` models, `services.py` (the task-board rules, the only place that decides; payment hooks `mark_paid` / `_after_validate` / `_before_deliver` / `_after_request_changes`; review window `review_deadline` / `is_review_overdue` / `request_changes`, computed at read time), `scoring.py` (40 + 8 × note + 20 × tags score, « Validated » `is_validated` / « Recommended » `recommended_pk`), `forms.py` (`ProjectForm`), pages + JSON endpoints under `/projets/…`, `/taches/…`, `/mes-projets/`, `seed_demo` command |
| `payments/` | `Escrow` (1-1 `Task`), `services.py` (`prepare_<step>` / `confirm_<step>`, both modes, `next_action`, `project_funding`, `on_task_validated`, `on_changes_requested`; **the state table is its docstring**), `trustless_work.py`, `stellar.py` (asset, mode switch, XDR, Horizon), JSON endpoints under `/pay/`, `{% escrow_panel task wallet %}` tag |
| `dashboard/` | no models, `services.py` (read view-models `todo_items`, `company_stats`, `freelancer_stats`, `recent_activity`, `profile_stats`, and the one write `set_display_name`): `/tableau-de-bord/` (`dashboard:home`, signed-in home: to-do list, KPIs as company and as freelance, activity) and `/profil/<address>/` (`dashboard:profile`, public wallet profile, the owner edits the display name). Templates live in `dashboard/templates/dashboard/` |
| `templates/` | `base.html`, `partials/` (navbar, tabbar, toasts, modal, page_header), `components/` (reusable includes), `core/`, `projects/` (pages + `_board_card`, `_candidates`, `_funding_panel`, `_project_card`, `_task_form`, `_task_row`), `payments/_escrow_panel.html`, error pages |
| `static/css/` | `lowbid-tokens.css` → `lowbid-components.css` → `tailwind.css` (built) |
| `static/js/` | `lowbid-base.js` (toasts, `Lowbid.csrf` / `Lowbid.api`, `formatUsdc`, small helpers), `lowbid-ui.js` (confirm modal, menus, identicons, `Lowbid.poll`, `refreshUI`), `lowbid-wallet.js` (Freighter), `lowbid-pay.js` (prepare → sign → send, `runChain`, `fundProject`, trustline, live balance), `lowbid-projects.js` (add/delete task, apply, candidates polling, choose, validate + rate → payment chain), `lowbid-landing.js` (landing: the CSS 3D project cube in the hero, four chapters scrubbed by anime.js `onScroll`) |
| `tests/e2e/` | `run.js` (Playwright scenario) + `fake-freighter.js` + `fake-horizon.js` |
| `docs/` | `PRODUCT.md` (spec, rules, score, states), `ARCHITECTURE.md`, `FRONTEND.md` (design system), `STELLAR_NOTES.md`, `DEMO_RUNBOOK.md`, `PITCH.md`, `HACKATHON_DAY.md` |

URL mounts (`lowbid/urls.py`): `/auth/` accounts · `/pay/` payments · `/` core + projects + dashboard · `/django-admin/`.

Pages: `/projets/` (list, public) · `/projets/nouveau/` · `/projets/<pk>/` (public) · `/taches/` (freelance kanban) · `/taches/<pk>/` (public) · `/mes-projets/` · `/tableau-de-bord/` · `/profil/<address>/` (public).

## Conventions

- 4-space, `snake_case`, type hints where cheap, `logger = logging.getLogger(__name__)`, structured `level=… logger=… msg=…` logs on stdout. No `print()`.
- Broad `except Exception` only around network hops **and always with `logger.exception(...)`**. Never a silent `except: pass`.
- Business rules live in `<app>/services.py` and raise `ProjectError` / `PaymentError(code, message)`; views only map codes to HTTP (`ERROR_STATUS` in `projects/views.py`); templates never decide a rule.
- `projects/services.py` never imports `payments` at module level (`payments.services` imports it, so its hooks import `payments.services` lazily); views may import both. `payments` owns everything on chain; `projects.services.mark_paid(task)` is the **only** way a task becomes `paid`.
- Unsafe browser calls go through `Lowbid.api(url, {method:"POST", body})` (CSRF + JSON + `X-Requested-With: fetch`, so `wallet_required` answers 401 JSON instead of redirecting). Business refusals from `/pay/` are HTTP 200 `{ok:false, error, message}`; from projects they are 4xx with the same body.
- Money is `Decimal(18,7)`; format with `{{ x|usdc }}` (unit = the configured asset) / `Lowbid.formatUsdc`; data attributes use `{{ x|plain }}` / `dec_str()` (never `'4.5E+2'`).
- Migrations are committed (`makemigrations --check` in CI). `WalletUser` FKs use `on_delete=PROTECT`.
- Config only via env / `.env` (`.env.example` lists everything). Never hardcode hosts, secrets, colours or the asset.

## Frontend rules

1. **Load order is law:** `lowbid-tokens.css` (the `:root` base palette = the light « Papier » values, overridden by the « Coffre » dark palette under `html[data-theme="dark"]` and on `.theme-coffre`; Signal mint means money, on-chain figures are mono) → `lowbid-components.css` (the `ui-` vocabulary) → `tailwind.css`. Components read `var(--*)` only; **never hardcode a colour**. **The site is dark only**: `base.html` renders `<html data-theme="dark">`, there is no theme toggle.
2. **Tailwind is a build artifact.** Any new utility class in a template or `static/js/*.js` needs `npm run build:css` and the rebuilt `static/css/tailwind.css` committed, or the `tailwind-in-sync` CI job fails. Classes assembled at runtime must be in the `safelist` of `tailwind.config.js`.
3. Prefer the vocabulary over utilities: `.ui-panel`, `.ui-btn*`, `.ui-badge*`, `.ui-field/.ui-input/.ui-form-grid`, `.ui-kpi-*`, `.ui-toolbar/.ui-search`, `.ui-pager`, `.ui-timeline`, `.ui-next-card`, `.ui-modal`, `.ui-menu`, `.ui-wallet/.ui-identicon`, `.ui-stepper`, `.ui-stars`, `.ui-scorebar`, `.cand-row`, `.kanban*`, `.ui-progress`, `.seg-tabs`, `.rcard`, `.empty-state`. Full reference with markup: `docs/FRONTEND.md`.
4. Reuse the includes in `templates/components/` (`wallet`, `status_badge`, `tags`, `kpi`, `price`, `empty_state`, `pager`, `next_card`, `section_head`) instead of re-typing markup; their parameters are documented in each file's `{% comment %}` header.
5. JS: one global `window.Lowbid` (`api`, `csrf`, `toast`, `confirm`, `modal`, `identicon`, `timeAgo`, `sparkline`, `poll`, `refreshUI`, `setBusy`, `parseTags`, `shortAddr`, `escapeHtml`, `formatUsdc`, `wallet`, `signTransaction`, `pay`). Per-request values reach the static JS only through `window.LOWBID` (base.html: `network`, `networkPassphrase`, `horizonUrl`, `sorobanRpcUrl`, `asset`, `paymentMode`, `walletAddress`, `urls`), `window.LOWBID_PROJECT` (project page) and `window.LOWBID_TASK` (task page). After swapping a fragment with `innerHTML`, call `Lowbid.refreshUI(root)`.
6. Mobile: dense tables go in a `.rcard` wrapper with `data-label` on every `<td>` (stacked cards under 720px of container width; a multi-block cell such as title + tags + description gets `td.is-stack` — never horizontal scroll; the kanban is the one deliberate exception, snap-scrolling full-width columns); form actions in `.ui-sticky-actions` inside a `.ui-form-scope`; the signed-in bottom tab bar (`partials/tabbar.html`) is fed by `NAV_LINKS` (Projects · Board · Create · My projects · Home). Touch targets are 44px.
7. Confirmations use `Lowbid.confirm({...})` (the `#lb-confirm` dialog in `partials/modal.html`), never `window.confirm`.

## Payments

The escrow / direct-payment state table (who signs, Escrow status, Task status, on-chain call per step) is the docstring of `payments/services.py` and the **Payments** section of `docs/ARCHITECTURE.md`. Summary: escrow mode = company `deploy` + `fund` once a freelance is chosen (« Fund the project » chains both for every assigned task) → freelance `deliver` (milestone change, link as evidence) → company validates + rates (DB) → company `approve` + `release` (chained). Direct mode = freelance delivers (no transaction) → company validates + rates → company `direct_pay`. Review window: after a delivery the company has `LOWBID_REVIEW_DAYS` days (deadline computed at read time) to validate or to `request_changes` (max `LOWBID_MAX_REVISIONS`, before the Rating): task `delivered → taken`, Escrow `delivered → funded` | `created` through `payments.services.on_changes_requested`, the freelance delivers again (a second milestone change; a replay of the old XDR is `tampered`). Every delivery is a `Delivery` row, every request a `RevisionRequest` row. `projects` owns `open → taken → delivered`; `payments` confirms on chain and calls `projects.services.mark_paid` (`delivered → paid`), and moves the project `draft → funded` (`mark_paid` closes it once every task is paid). Fallback switch: `LOWBID_PAYMENT_MODE=direct` + restart (a native-XLM asset forces it).

## How to add a page (5 steps)

1. View in `<app>/views.py` (function view, `@wallet_required` if it needs a session, `get_wallet(request)` for the caller), rules in `services.py`.
2. Route in `<app>/urls.py` under its namespace; add it to `NAV_LINKS` in `core/context_processors.py` if it belongs in the navbar / tab bar.
3. Template extends `base.html` (blocks: `title`, `meta_description`, `extra_head`, `body_class`, `content`, `extra_js`); start with `{% include "partials/page_header.html" with title=… subtitle=… %}` and compose with `templates/components/*`.
4. Page JS goes in `static/js/` (then bump `LOWBID_ASSET_VERSION`); new Tailwind classes → `npm run build:css` and commit `tailwind.css`.
5. Tests in `<app>/tests.py` (status code, key strings, role gates) and `make check`.

## Testing

- `make test` must stay green; mock every network call (`requests`, Horizon, Trustless Work) — see `payments/tests_flow.py` for the pattern.
- `make e2e` drives the real browser flow (company + freelances A/B/C, direct mode, a fake Horizon so the payment really signs and submits) with `tests/e2e/fake-freighter.js` and `tests/e2e/fake-horizon.js`. It depends on these DOM contracts — keep them when editing templates/JS:
  - shell: `html[data-theme="dark"]` and no `[data-theme-toggle]`, `.lb-nav [data-wallet-connect]` (+ `[data-next]`) + `.lb-wallet-btn.is-connected`, `details.lb-wallet-menu`, `[data-nav-toggle]` + `#lb-mobile-nav`, `.lb-tabbar`, `.lb-toast`, the confirm modal `#lb-confirm` with `[data-modal-body]` / `[data-modal-ok]` / `[data-modal-cancel]` (the e2e clicks `[data-modal-ok]`; a native `window.confirm` is not auto-accepted);
  - landing: `.lb-hero` (with `[data-wallet-connect]`, `a.ui-btn-primary`, the `?next=` `.ui-alert`), `.lb-hero-title`, `[data-landing-stats]`; `lowbid-landing.js` also needs `[data-story]` › `[data-story-grid]` › `.lb-hero[data-story-hero]`, `[data-cube]`, `[data-slab]`, `[data-bid="chosen|other"]`, `[data-story-step]` × 4;
  - project form + page: `#project-form`, `#id_title`, `#id_description`, `[data-status-badge]`, `[data-tasks][data-count="N"]`, `.task-row[data-task-id][data-status]`, `#task-form` with `#task-title/#task-description/#task-price/#task-tags` + `[data-task-add]`, `[data-error-for="<field>"]`, `[data-task-delete]`, `[data-kpi-total]`, `[data-fund]`, `#funding-panel[data-mode]`, `#candidates-<task_pk>`;
  - task page: `#apply-message/#apply-tags/[data-apply-submit]`, `#my-application`, `#candidates-panel`, `[data-candidates][data-count="N"]`, `.cand-row[data-freelancer]` (`.is-chosen` / `.is-rejected`), `[data-score]`, `[data-recommended]`, `[data-badge="valide"]` / `.badge-validated`, `[data-choose]`, `[data-kpi-count]`, `[data-live-dot]`, `[data-delivery-link]`, `[data-rating]`;
  - payment panel: `#escrow-panel[data-mode][data-escrow-status]`, `[data-pay-step]`, `[data-pay-error]`, `[data-last-error]`, `[data-pay-trustline]`, `[data-explorer-links]`, `[data-usdc-balance="G…"]`, `#deliver-panel #deliver-link #deliver-hash #deliver-source [data-deliver]`, `[data-delivery-hash]`, `[data-source-link]` (only for the assignee, or the company once paid), `#validate-panel #validate-form[data-validate] [data-rate] #validate-comment [data-validate-submit]`, `[data-request-changes]` (company, delivered + unrated; `disabled` once `revisions_left` is 0) + `#request-changes-form #request-changes-message [data-request-changes-submit]`, `[data-review-deadline][data-deadline="ISO"]` (+ `[data-countdown]`, everyone, while delivered), `[data-changes-requested="n"]` (freelance alert in `#deliver-panel` after a change request, deliver button labelled "Deliver again"), `[data-delivery-history][data-count="N"] .ui-timeline-item[data-kind="delivery|revision"]` (task page, everyone; `[data-history-hash]`, `[data-source-link]` only when visible);
  - kanban, lists, dashboard, profile: `.kanban-col[data-col]`, `.kanban-card[data-task-id]`, `.kanban-empty`, `.project-card`, `.ui-chip-row .ui-tag`, `select[name="sort"]`, `.empty-state`, `tbody tr` on Mes projets, `#todo`, `[data-todo-list] .ui-next-card(.act)`, `#activity .ui-timeline-item`, `.ui-kpi-tile`, `[data-avg-note]`, `#edit-name` + `#display_name`, `.ui-wallet-name`.
- Any uncaught page error or unexpected `console.error` fails the e2e run.

## Don'ts

- No CDN, no web fonts (system stack), no new JS framework, no SPA, no DRF, no Channels / WebSockets (the task page polls `candidats.json` every 5 s through `Lowbid.poll`).
- No silent `except`, no `print()`, no hardcoded colours / hosts / secrets / asset.
- No `window.confirm` / `alert` — `Lowbid.confirm` / `Lowbid.toast`.
- No business rule in a view or a template.
- Never flip `Task.status` to `paid` outside `projects.services.mark_paid`, and never move money from `projects`.
- Never commit `static/css/tailwind.css` out of sync with the templates, and never edit it by hand.
- No cron or background worker: every state change happens in a request (there is no timer anywhere in the task board).
