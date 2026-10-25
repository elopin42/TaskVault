# TaskVault — Hackathon day checklist

One page to open in the morning and keep in sight. The demo details (accounts, timing, fallback minute by minute) are in [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md); the code map in [`ARCHITECTURE.md`](ARCHITECTURE.md); the design system in [`FRONTEND.md`](FRONTEND.md); the rules for an assistant (Claude Code) in [`../CLAUDE.md`](../CLAUDE.md).

---

## 1. Setup in 10 lines (≈ 5 min)

```bash
git pull
make                               # hands-off: venv, .env, migrate, ruff, tests, tailwind in sync, npm + Chromium, e2e, then the server on :8000
#   then fill .env (see §2), Ctrl-C and `make dev` (venv, migrate, runserver 0.0.0.0:8000 — no checks)
# new terminal
make seed                          # 3 wallets, the pitch-state project (T1 paid, T2 with A 90 / B 20), a draft project
make check                         # ruff + tests + tailwind in sync → must be green BEFORE touching the code
npm run watch:css                  # (optional) if you add Tailwind classes to templates
```

Prerequisites: Python 3.13 or 3.14 (auto-detected), Node 22+ (for `make css` / `make e2e`, so for a bare `make` too), the **Freighter** extension on **TESTNET** with a funded account.

## 2. Stellar accounts & `.env` (see `DEMO_RUNBOOK.md` §1.1 → §1.7)

| What | Where | Note |
|------|-------|------|
| 3 Chrome profiles (company, freelance A, freelance B) + Freighter testnet | Runbook §1.1 | one wallet per profile |
| XLM (friendbot) on the 4 accounts (3 actors + platform) | §1.2 | `https://friendbot.stellar.org/?addr=G…` |
| USDC trustline on the 4 accounts | §1.3 | Freighter → *Manage assets*, or "Add the USDC trustline" in the payment panel |
| Test USDC (Circle faucet, 10 USDC / address / 24 h) | §1.4 | hence the small live task prices (3 / 5 / 2 USDC) |
| Trustless Work API key (testnet) | §1.5 | `TRUSTLESS_WORK_API_KEY=`; empty ⇒ direct mode automatically |
| Payment asset | `.env` | `STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER` (default testnet USDC); `XLM` + empty issuer = native XLM, direct mode only |
| `.env` | §1.6 | `LOWBID_PLATFORM_ADDRESS=G…` (account with the trustline); `LOWBID_DEMO_CLIENT/FREELANCE1/FREELANCE2=G…` make `make seed` use **your** wallets — leave them empty before the live recording (runbook §1.7) |
| Trustless Work smoke test | §1.8 / `STELLAR_NOTES.md` §6 | once, keep the `contractId` as a screenshot |

`.env` is read **once** at startup: after any change, `Ctrl-C` then `make run`.

## 3. 5-minute check (before coding, before filming)

1. `curl -s localhost:8000/healthz/` → `{"ok": true, "db": true, "network": "testnet"}`.
2. `/` → "Connect my Freighter wallet" (or "Connect wallet" in the navbar) → signature popup → the short address appears in the navbar; the wallet menu offers "Dashboard" / "My public profile" / "Log out".
3. `/tableau-de-bord/` → KPIs + "To do".
4. "New project" → create a project → add two tasks inline (price, tags) → the task table and the "Total budget" KPI update.
5. Second profile → `/taches/` (kanban) → open one of those tasks → "Send my application" → the company's task page shows the candidate **without reloading** (live dot).
6. Company → "Choose" → confirm dialog → task "Taken".
7. Payment: escrow mode → "Fund the project" (2 signatures), then the freelance "Declare the delivery" (1), then "Validate + rate" → "Validate and release" (2). Direct mode → the delivery is a declaration, "Validate and pay" (1). stellar.expert links after each step.
8. Phone (DevTools 390×844): no horizontal scroll, bottom tab bar, sticky button on the forms, kanban columns snap-scroll.

## 4. Suggested split (by folder, no git conflicts)

| Person | Folders | Topics |
|--------|---------|--------|
| **Product / pitch** | `docs/`, `README.md`, `docs/screenshots/` | video, deck, README (testnet addresses, "Status / what works"), `make shots` |
| **Payments / Stellar** | `payments/`, `templates/payments/`, `templates/projects/_funding_panel.html`, `static/js/lowbid-pay.js`, `static/js/lowbid-wallet.js` | Trustless Work live, trustlines, direct mode, error messages |
| **Task board / UI** | `projects/`, `templates/projects/`, `static/js/lowbid-projects.js`, `static/css/` | rules, score, list, project and task pages, kanban, mobile |
| **Dashboard / accounts** | `dashboard/`, `accounts/`, `core/`, `templates/partials/`, `templates/components/` | dashboard, profiles, nav, landing |

Direct `main` (small team) or one branch per person + PR: CI = ruff · tests · tailwind-in-sync.

## 5. "Where do I change…?"

| I want to change… | File(s) |
|-------------------|---------|
| a UI text | the template under `templates/<app>/` (grep the sentence); business error messages in `projects/services.py` / `payments/services.py` |
| colours / theme | `static/css/lowbid-tokens.css` (`:root` = light « Papier » base, dark « Coffre » under `html[data-theme="dark"]` / `.theme-coffre`; the site renders dark only) — never inside a component |
| a component (button, badge, card…) | `static/css/lowbid-components.css` (+ bump `LOWBID_ASSET_VERSION`) |
| the navbar / mobile tab bar | `NAV_LINKS` in `core/context_processors.py`; markup in `templates/partials/navbar.html` and `tabbar.html` |
| the wallet menu | `templates/partials/navbar.html` (`lb-wallet-dropdown` block) |
| a new page | `CLAUDE.md` § "How to add a page": view → url → template (`components/`) → JS → test |
| the project list (search, tags, sort, pagination) | `projects/views.py::project_list` (`LIST_TABS`, `LIST_SORTS`), `templates/projects/project_list.html`, `_project_card.html` |
| the project page | `projects/views.py::project_detail`, `templates/projects/project_detail.html`, `_task_row.html`, `_task_form.html`, `_funding_panel.html` |
| the task page / candidates | `projects/views.py::task_detail` + `_candidate_rows`, `templates/projects/task_detail.html`, `_candidates.html`, `static/js/lowbid-projects.js` |
| the kanban | `projects/views.py::board` (`BOARD_COLUMNS`), `templates/projects/board.html`, `_board_card.html` |
| the score (40 / ×8 / 20) or the badges | `projects/scoring.py` (`HISTORY_POINTS`, `RATING_FACTOR`, `TAGS_POINTS`, `VALIDATED_MIN_NOTE`) + the legend in `_candidates.html` + `PRODUCT.md` §4 |
| a task-board rule (`PRODUCT.md` §3) | `projects/services.py` (+ a test in `projects/tests.py`) |
| a payment step | `payments/services.py` (`FLOW`, `prepare_<step>` / `confirm_<step>`, `stepper()`, `next_action()`, `project_funding()`), `payments/trustless_work.py`, `templates/payments/_escrow_panel.html`; the state table is the docstring of `services.py` |
| the payment asset | `STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER` in `.env` (read through `payments/stellar.py`) |
| the dashboard / profile | `dashboard/services.py` (to-dos, KPIs, activity), `dashboard/views.py`, `dashboard/templates/dashboard/` |
| the demo seed | `projects/management/commands/seed_demo.py` |
| the fallback panel | `LOWBID_PAYMENT_MODE` in `.env` (see §6) |
| an environment variable | `lowbid/settings.py` + `.env.example` |

## 6. Fallback during the demo

- Trustless Work goes down → `.env`: `LOWBID_PAYMENT_MODE=direct`, `Ctrl-C`, `make run`. Same pages: the panels switch to "Direct payment USDC" ("no escrow" badge), the delivery is a declaration, the company signs one "Pay the freelancer" after rating. A task whose escrow is **already deployed** stays in escrow mode.
- A ready-made end state: `make seed` with your real wallets produces Studio Nova's project with T1 paid and T2 showing A 90.0 "Validated" + "Recommended" vs B 20.0 (the T1 payment is seeded, nothing on chain). Ids keep counting after `--flush`: read them from the command's output.
- Scenario details (failed signature, Horizon down, everything broken): `DEMO_RUNBOOK.md` §4.

## 7. Commit hygiene

```bash
npm run build:css        # if a template / JS gained a Tailwind class (CI tailwind-in-sync)
# bump LOWBID_ASSET_VERSION in lowbid/settings.py if lowbid-*.css / lowbid-*.js changed
make check               # ruff + tests + tailwind in sync
git add -A && git commit -m "scope: what changed"
```

- One commit = one topic; message in English, prefixed by app (`projects:`, `payments:`, `docs:`, `e2e:`).
- Never commit `.env`, `data/*.sqlite3` or `staticfiles/` (already ignored).
- Pitch screenshots: `make shots` (updates `docs/screenshots/`; `make` / `make verify` write theirs to `data/e2e-shots/`).

## 8. If it breaks — triage

| Symptom | Look at | Fix |
|---------|---------|-----|
| `ImproperlyConfigured: DJANGO_SECRET_KEY is required when DJANGO_DEBUG is off` at startup | `.env` | `DJANGO_DEBUG=1` in dev, or set the key |
| `Freighter is on "…"; switch to TESTNET.` | Freighter → network | switch the extension to Testnet, reload |
| Login fails, 400 `bad_signature` | Freighter version | `accounts/signing.py` tries SEP-53 → raw → sha256; see the `scheme=` log line |
| The page ignores my CSS / JS | 30-day cache | bump `LOWBID_ASSET_VERSION` (or `DJANGO_DEBUG=1` ⇒ no cache) |
| CI `tailwind-in-sync` red | `tailwind.css` not rebuilt | `npm run build:css` then commit |
| "The project is closed: no new tasks." | project status | normal: a project is "Closed" once every task is paid; tasks can be added while it is "Draft" or "Funded". Create another project |
| "Only an open task can be deleted." | task status | a task with a chosen freelance stays in the project |
| "You cannot apply to your own task." | wrong Freighter account | the company cannot apply to its own tasks; switch profile |
| "Fund the project" greyed out | the hint under it | choose a freelance first (the receiver is fixed at deploy), or everything assigned is already funded |
| "Escrow task: declare the delivery from the payment panel (Freighter signature), once the company has locked the funds." | escrow mode | the freelance delivers from the payment panel, once the company funded |
| "Validate and rate the delivery before the payment." | rating missing | "Validate + rate" first; the payment chains after it |
| Panel alert "Platform address not configured: roles merged with the company (`LOWBID_PLATFORM_ADDRESS` empty)." | `.env` | `LOWBID_PLATFORM_ADDRESS=G…` with a USDC trustline, restart |
| Trustless Work 4xx/5xx, `provider` | `trustless_work:` log lines, the panel's `last_error` | retry; otherwise the fallback (§6) |
| Horizon 504 after a signature | panel: "Transaction sent, confirmation pending — check the explorer." | the next click reconciles through `/transactions/{hash}`, no second signature |
| USDC balance "…" that never moves | missing trustline | "Add the USDC trustline", Circle faucet |
| e2e red | `data/e2e-server.log` | read the first FAIL step; Horizon 404s are expected and ignored |
| Tests red after a model change | `makemigrations --check` | `python manage.py makemigrations <app>` and commit |
