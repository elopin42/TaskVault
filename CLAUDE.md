# Lowbid — project instructions

**Lowbid** is a reverse auction for freelancers on Stellar (Hack Meridian, track *Composed*): a client posts a need and a maximum budget, freelancers bid the price **down**, the client picks a winner, and the winner is paid in **USDC through a Trustless Work escrow on Soroban** (Plan B: a direct USDC payment). UI copy is **French**; code, docs and commits are English.

There is **no GSD workflow** in this repo. Edit files directly, run `make check`, commit.

## Stack

- Python 3.13 · Django 5.2 (server-rendered templates, function views, no DRF) · SQLite by default (`data/db.sqlite3`), PostgreSQL when `DJANGO_DB_HOST` is set · whitenoise for static files · gunicorn in Docker.
- Frontend: **self-hosted Tailwind v3** compiled into the committed `static/css/tailwind.css`, two hand-written CSS files (`lowbid-tokens.css`, `lowbid-components.css`), vanilla JS (`static/js/lowbid-*.js`). Vendored under `static/vendor/`: Font Awesome, `@stellar/freighter-api` (global `freighterApi`), `@stellar/stellar-sdk` (global `StellarSdk`). **Nothing loads from a CDN.**
- Stellar: Freighter wallet = identity (SEP-53 `signMessage` login), USDC (Circle testnet issuer), Trustless Work v1 REST for the escrow, Horizon for balances / direct payments. Python side: `stellar-sdk`.
- Tests: Django test runner (`manage.py test`, 146+ tests, network mocked) and a Playwright e2e run with a simulated Freighter (`make e2e`). Linter: ruff (baseline rules only, see `ruff.toml`).

## Commands

```bash
make dev        # venv + pip install + .env from .env.example + migrate + runserver 0.0.0.0:8000
make test       # manage.py check + makemigrations --check + test
make lint       # ruff check .
make css        # npm ci (once) + tailwind build → static/css/tailwind.css  (COMMIT the output)
make css-check  # rebuild and fail if the committed tailwind.css is stale (same as CI)
make check      # lint + test + css-check — run before every commit
make seed       # python manage.py seed_demo --flush (3 wallets, 4 needs, bids)
make e2e        # Playwright flow with fake Freighter on a throwaway SQLite; screenshots → docs/screenshots/
make shots      # alias of e2e (regenerates the pitch screenshots)
npm run build:css / npm run watch:css / npm run vendor
```

`.env` is read once at boot (python-dotenv): restart `make run` after any change. `DJANGO_DEBUG=0` requires `DJANGO_SECRET_KEY`.

**Asset cache rule:** static files are served with a 30-day `max-age` outside DEBUG and cache-busted only by `?v={{ LOWBID_ASSET_VERSION }}`. After editing any `static/css/lowbid-*.css` or `static/js/lowbid-*.js`, bump `LOWBID_ASSET_VERSION` (default in `lowbid/settings.py`, override in `.env`).

## Repo map

| Path | Owns |
|------|------|
| `lowbid/` | `settings.py` (every value from env, `_csv`/`_bool` helpers), `urls.py` (mounts below), `wsgi.py` |
| `core/` | landing (`core:landing`), `/healthz/`, error handlers, context processors `site` + `nav_links` (`NAV_LINKS` = navbar **and** mobile tab bar), templatetags `lowbid_extras` (`short_addr`, `usdc`, `plain`, `qs`, `pct`, `hue`) |
| `accounts/` | `WalletUser`, Freighter login (`/auth/challenge/`, `/auth/verify/`, `/auth/logout/`), `signing.py` (SEP-53 verify), `wallet_required`, `get_wallet()` |
| `auctions/` | `Need` / `Bid` models, `services.py` (rules R1–R14, the only place that decides), `scoring.py` (40/30/30 score, sliders), pages + JSON endpoints under `/besoins/…`, `/mes-encheres/`, `/mes-besoins/`, `seed_demo` command |
| `payments/` | `Escrow` (1-1 Need), `services.py` (`prepare_<step>` / `confirm_<step>`, both modes), `trustless_work.py`, `stellar.py`, JSON endpoints under `/pay/`, `{% escrow_panel %}` tag |
| `dashboard/` | no models: `/tableau-de-bord/` (`dashboard:home`, signed-in home: to-do list, KPIs, activity) and `/profil/<address>/` (`dashboard:profile`, public wallet profile) |
| `templates/` | `base.html`, `partials/` (navbar, tabbar, toasts, modal, page_header), `components/` (reusable includes), `core/`, `auctions/`, `payments/`, error pages |
| `static/css/` | `lowbid-tokens.css` → `lowbid-components.css` → `tailwind.css` (built) |
| `static/js/` | `lowbid-base.js` (theme, toasts, `Lowbid.api`), `lowbid-ui.js` (confirm modal, menus, identicons, sparklines, `Lowbid.poll`), `lowbid-wallet.js` (Freighter), `lowbid-pay.js` (sign & send), `lowbid-auctions.js` (countdowns, bid form, polling, sliders) |
| `tests/e2e/` | `run.js` (Playwright flow) + `fake-freighter.js` |
| `docs/` | `PRODUCT.md` (spec, rules, states), `ARCHITECTURE.md`, `FRONTEND.md` (design system), `STELLAR_NOTES.md`, `DEMO_RUNBOOK.md`, `PITCH.md`, `HACKATHON_DAY.md` |

URL mounts (`lowbid/urls.py`): `/auth/` accounts · `/pay/` payments · `/` core + auctions + dashboard · `/django-admin/`.

## Conventions

- 4-space, `snake_case`, type hints where cheap, `logger = logging.getLogger(__name__)`, structured `level=… logger=… msg=…` logs on stdout. No `print()`.
- Broad `except Exception` only around network hops **and always with `logger.exception(...)`**. Never a silent `except: pass`.
- Business rules live in `<app>/services.py` and raise `AuctionError` / `PaymentError(code, message)`; views only map codes to HTTP (`ERROR_STATUS` in `auctions/views.py`); templates never decide a rule.
- Unsafe browser calls go through `Lowbid.api(url, {method:"POST", body})` (CSRF + JSON + `X-Requested-With: fetch`, so `wallet_required` answers 401 JSON instead of redirecting). Business refusals from `/pay/` are HTTP 200 `{ok:false, error, message}`; from auctions they are 4xx with the same body.
- Money is `Decimal(18,7)`; format with `{{ x|usdc }}` / `Lowbid.formatUsdc`; data attributes use `{{ x|plain }}` / `dec_str()` (never `'4.5E+2'`).
- Migrations are committed (`makemigrations --check` in CI). `WalletUser` FKs use `on_delete=PROTECT`.
- Config only via env / `.env` (`.env.example` lists everything). Never hardcode hosts, secrets or colours.

## Frontend rules

1. **Load order is law:** `lowbid-tokens.css` (the `:root` palette, light mode under `html[data-theme="light"]`) → `lowbid-components.css` (the `ui-` vocabulary) → `tailwind.css`. Components read `var(--*)` only; **never hardcode a colour**. Dark is the default, light comes for free.
2. **Tailwind is a build artifact.** Any new utility class in a template or `static/js/*.js` needs `npm run build:css` and the rebuilt `static/css/tailwind.css` committed, or the `tailwind-in-sync` CI job fails. Classes assembled at runtime must be in the `safelist` of `tailwind.config.js`.
3. Prefer the vocabulary over utilities: `.ui-panel`, `.ui-btn*`, `.ui-badge*`, `.ui-field/.ui-input/.ui-form-grid`, `.ui-kpi-*`, `.ui-toolbar/.ui-search`, `.ui-pager`, `.ui-timeline`, `.ui-next-card`, `.ui-modal`, `.ui-menu`, `.ui-wallet/.ui-identicon`, `.ui-sparkline`, `.ui-skeleton`, `.seg-tabs/.seg-radio`, `.rcard`, `.empty-state`. Full reference with markup: `docs/FRONTEND.md`.
4. Reuse the includes in `templates/components/` (`wallet`, `status_badge`, `countdown`, `tags`, `kpi`, `price`, `empty_state`, `pager`, `next_card`, `section_head`) instead of re-typing markup; their parameters are documented in each file's `{% comment %}` header.
5. JS: one global `window.Lowbid` (`api`, `toast`, `confirm`, `modal`, `identicon`, `timeAgo`, `sparkline`, `poll`, `refreshUI`, `setBusy`, `wallet`, `signTransaction`, `pay`). Per-request values reach the static JS only through `window.LOWBID` (base.html) and `window.LOWBID_NEED` (need detail). After swapping a fragment with `innerHTML`, call `Lowbid.refreshUI(root)`.
6. Mobile: dense tables go in a `.rcard` wrapper with `data-label` on every `<td>` (stacked cards under 640px of container width — never horizontal scroll); form actions in `.ui-sticky-actions` inside a `.ui-form-scope`; the signed-in bottom tab bar (`partials/tabbar.html`) is fed by `NAV_LINKS`. Touch targets are 44px.
7. Confirmations use `Lowbid.confirm({...})` (the `#lb-confirm` dialog in `partials/modal.html`), never `window.confirm`.

## Payments

The escrow / direct-payment state table (who signs, Escrow status, Need status, on-chain call per step) is the docstring of `payments/services.py` and the **Payments** section of `docs/ARCHITECTURE.md`. `payments` owns `awarded → funded → delivered → released`; `auctions` never moves a need past `awarded`. Plan B switch: `LOWBID_PAYMENT_MODE=direct` + restart.

## How to add a page (5 steps)

1. View in `<app>/views.py` (function view, `@wallet_required` if it needs a session, `get_wallet(request)` for the caller), rules in `services.py`.
2. Route in `<app>/urls.py` under its namespace; add it to `NAV_LINKS` in `core/context_processors.py` if it belongs in the navbar / tab bar.
3. Template extends `base.html` (blocks: `title`, `meta_description`, `extra_head`, `body_class`, `content`, `extra_js`); start with `{% include "partials/page_header.html" with title=… subtitle=… %}` and compose with `templates/components/*`.
4. Page JS goes in `static/js/` (then bump `LOWBID_ASSET_VERSION`); new Tailwind classes → `npm run build:css` and commit `tailwind.css`.
5. Tests in `<app>/tests.py` (status code, key strings, role gates) and `make check`.

## Testing

- `make test` must stay green; mock every network call (`requests`, Horizon, Trustless Work) — see `payments/tests_flow.py` for the pattern.
- `make e2e` drives the real browser flow with `tests/e2e/fake-freighter.js`. It depends on these DOM contracts — keep them when editing templates/JS: `[data-wallet-connect]` + `.lb-wallet-btn.is-connected`, `#id_title/#id_description/#id_budget_max/#id_delay_max_days/#id_tags/#id_duration` on the need form, `[data-bids][data-count="N"]` + `.bid-row` in the bids list, `#bid-price/#bid-delay/#bid-tags`, `[data-bid-submit]`, `[data-error-for="price"]`, `[data-kpi-count]/[data-kpi-best]`, `[data-live-dot]`, `[data-choose]`, `[data-need-close]`, `[data-need-cancel]`, `[data-weight]`, `[data-recommended]`, `[data-pay-step]`, `[data-nav-toggle]` + `#lb-mobile-nav`, `[data-theme-toggle]`, and the confirm modal `#lb-confirm` with `[data-modal-ok]` / `[data-modal-cancel]` (the e2e clicks `[data-modal-ok]`; a native `window.confirm` is no longer auto-accepted).
- Any uncaught page error or unexpected `console.error` fails the e2e run.

## Don'ts

- No CDN, no web fonts (system stack), no new JS framework, no SPA, no DRF, no Channels / WebSockets (the detail page polls `encheres.json` every 5 s).
- No silent `except`, no `print()`, no hardcoded colours / hosts / secrets.
- No `window.confirm` / `alert` — `Lowbid.confirm` / `Lowbid.toast`.
- No business rule in a view or a template.
- Never commit `static/css/tailwind.css` out of sync with the templates, and never edit it by hand.
- Do not add a cron: the auction timer is lazy (`Need.objects.close_expired()` at the top of the auctions views).
