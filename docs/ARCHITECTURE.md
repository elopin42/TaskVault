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
├── auctions/               # PLACEHOLDER — Need / Bid / scoring (next agent)      mounted at /
├── payments/               # PLACEHOLDER — Trustless Work escrow (next agent)     mounted at /pay/
├── templates/              # base.html, partials/{navbar,toasts,page_header}.html, core/landing.html, 400/403/404/500.html
├── static/
│   ├── css/  lowbid-tokens.css  lowbid-components.css  tailwind.src.css  tailwind.css (BUILT, committed)
│   ├── js/   lowbid-base.js (theme, toasts, Lowbid.api)  lowbid-wallet.js (Freighter)
│   ├── vendor/  fontawesome/  freighter-api.js (UMD → window.freighterApi)  stellar-sdk.min.js (→ window.StellarSdk)
│   └── img/favicon.svg
├── data/                   # db.sqlite3 (gitignored)
├── docs/                   # PRODUCT.md, PITCH.md, STELLAR_NOTES.md, this file
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
make vendor       # re-copy Font Awesome / freighter-api / stellar-sdk from node_modules
```

Settings come from `.env` (python-dotenv). `DJANGO_DEBUG=0` **requires** `DJANGO_SECRET_KEY`.
Set `DJANGO_DB_HOST` to switch from SQLite to PostgreSQL (`DJANGO_DB_NAME/USER/PASSWORD/PORT`).

## Apps

| App | Owns | URLs |
|-----|------|------|
| `core` | landing (`core:landing`), `GET /healthz/` (`core:healthz`), error handlers, context processors `core.context_processors.site` (asset version + Stellar config) and `nav_links`, filters `short_addr`, `usdc` (`{% load lowbid_extras %}`) | `/` |
| `accounts` | `WalletUser(stellar_address, display_name, created_at, last_login_at)`, wallet auth, `wallet_required`, `get_wallet()` | `/auth/challenge/` `accounts:challenge`, `/auth/verify/` `accounts:verify`, `/auth/logout/` `accounts:logout` |
| `auctions` | *(empty)* Need / Bid / scoring / "Recommandé" | `/` — expected names `auctions:need_list` (`/besoins/`), `auctions:need_create` (`/besoins/nouveau/`), `auctions:my_bids` (`/mes-encheres/`) |
| `payments` | *(empty)* escrow fund / release via Trustless Work | `/pay/` |

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

## Adding `auctions` / `payments`

- Models in `<app>/models.py`, `python manage.py makemigrations <app>` — commit the migration (CI runs
  `makemigrations --check`). Use `WalletUser` FKs (`on_delete=PROTECT`) for client / freelancer.
- Views are plain function views; return `render(...)` or `JsonResponse`. Unsafe JSON calls from the
  browser go through `Lowbid.api(url, {method:"POST", body:{…}})` (CSRF + JSON handled).
- Register URL names in `<app>/urls.py` (namespaces `auctions` / `payments`); the navbar lights up
  automatically for the three names above (`core/context_processors.py::NAV_LINKS`).
- Templates extend `base.html`; blocks: `title`, `meta_description`, `extra_head`, `body_class`,
  `content`, `extra_js`. Header: `{% include "partials/page_header.html" with title=… subtitle=… %}`.
- UI vocabulary (all theme-token driven, dark + light): `.glass-card`, `.glass-soft`, `.ui-panel`
  (+`-head/-title/-sub`), `.ui-page-header/-title/-sub/-actions`, `.ui-btn` (+`-primary -ghost -danger
  -danger-solid -sm -lg -block`), `.ui-field .ui-label .ui-input .ui-select .ui-textarea .ui-help
  .ui-error .ui-form-grid .ui-field-wide .ui-input-group .ui-input-addon`, `.ui-badge` (+`-ok -attn
  -danger -info -brand -neutral`; **`.ui-badge-brand` is the "Recommandé" badge**), `.ui-tag` (+`.is-match`),
  `.ui-alert` (+`-ok -attn -danger -info`), `.ui-kpi-band .ui-kpi-tile/-label/-value/-hint`,
  `.ui-countdown` (+`.is-urgent`), `.ui-price .ui-price-unit`, `.ui-list .ui-list-row .ui-rank`,
  `.empty-state/-icon/-title/-desc`, `.seg-tabs .seg-tab.is-active`, `.ui-meta .ui-link .ui-num`,
  and `.rcard` (wrapper div around a `<table>`; each `<td data-label="…">` — stacks into cards under
  640 px of container width, no horizontal scroll). Tailwind utilities are available on top
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
