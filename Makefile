# TaskVault — hackathon toolchain. A bare `make` (= `make all`) does everything hands-off: venv + deps,
# .env, migrations, lint, tests, tailwind in sync, Playwright e2e, THEN the dev server on :8000.
# `make verify` is the same without the server (CI-like); `make dev` starts the server without the
# checks; `make check` (lint + tests + tailwind in sync) is the pre-commit gate; `make seed` loads
# the demo data.
.DEFAULT_GOAL := all

# Interpreter: python3.13 (the pinned target) when installed, else python3.14, else whatever python3 is.
PY      ?= $(or $(shell command -v python3.13 2>/dev/null),$(shell command -v python3.14 2>/dev/null),python3)
VENV    ?= .venv
PIP     := $(VENV)/bin/pip
PYTHON  := $(VENV)/bin/python
RUFF    := $(VENV)/bin/ruff
HOST    ?= 0.0.0.0
PORT    ?= 8000

.PHONY: all verify dev venv env migrate run seed test lint fmt css css-check watch-css vendor check e2e shots playwright clean

$(VENV)/bin/activate: requirements.txt requirements-dev.txt
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements-dev.txt
	touch $(VENV)/bin/activate

venv: $(VENV)/bin/activate

env:
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

migrate: venv env
	$(PYTHON) manage.py migrate

run: venv env
	$(PYTHON) manage.py runserver $(HOST):$(PORT)

dev: venv env migrate run

# Demo dataset: 3 wallets (LOWBID_DEMO_* or random), 2 projects with tasks / applications / a paid task. Flushes projects first.
seed: venv env migrate
	$(PYTHON) manage.py seed_demo --flush

test: venv env
	$(PYTHON) manage.py check
	$(PYTHON) manage.py makemigrations --check --dry-run
	$(PYTHON) manage.py test -v 2

lint: venv
	$(RUFF) check .

fmt: venv
	$(RUFF) check --fix .

# Frontend assets (node 22 + npm). Outputs are COMMITTED — rebuild after any template/JS class change.
node_modules/.package-lock.json: package.json package-lock.json
	npm ci --no-audit --no-fund
	touch node_modules/.package-lock.json

css: node_modules/.package-lock.json
	npm run build:css

watch-css: node_modules/.package-lock.json
	npm run watch:css

# Same gate as the CI job `tailwind-in-sync`: a diff means a template/JS gained a class without a rebuild.
css-check: css
	git diff --exit-code -- static/css/tailwind.css

vendor: node_modules/.package-lock.json
	npm run vendor

check: lint test css-check

# Every check, hands-off: toolchain, .env, dev DB migrated, lint + tests + tailwind, then the e2e with its
# screenshots kept OUT of docs/ (data/e2e-shots/) so the working tree stays clean. `make shots` updates docs/.
verify: E2E_SHOTS_DIR := data/e2e-shots
verify: venv env migrate check e2e
	@echo ""
	@echo "============================================================"
	@echo " TaskVault: everything is green."
	@echo "   python      : $(PY)"
	@echo "   lint + tests: make check      (ok)"
	@echo "   e2e         : make e2e        (ok, screenshots in $(E2E_SHOTS_DIR)/)"
	@echo "============================================================"

# The default goal: verify, then serve. Nothing to type afterwards; Ctrl-C stops the server.
all: verify
	@echo " Starting the server: http://localhost:$(PORT)  (Ctrl-C to stop, 'make seed' for the demo data)"
	@$(MAKE) --no-print-directory run

# End-to-end (Playwright, simulated Freighter + a fake Horizon): fresh SQLite at data/e2e.sqlite3,
# runserver on a free port in DIRECT payment mode pointed at tests/e2e/fake-horizon.js (started by
# run.js on E2E_HORIZON_PORT, so the payment chain really signs and submits — the sandbox has no
# network), node tests/e2e/run.js (screenshots -> docs/screenshots/), server killed on exit.
# `playwright` comes from package.json (npm ci); its Chromium is downloaded once by `make playwright`
# (no-op when the browser is already in ~/.cache/ms-playwright). E2E_SHOTS_DIR overrides the screenshot
# folder (default: docs/screenshots/, the committed pitch images).
E2E_DB ?= data/e2e.sqlite3
E2E_SHOTS_DIR ?=

playwright: node_modules/.package-lock.json
	npx playwright install chromium

e2e: venv playwright
	@rm -f $(E2E_DB)
	@port=$$($(PYTHON) -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'); \
	hport=$$($(PYTHON) -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'); \
	export LOWBID_SQLITE_PATH=$(E2E_DB) DJANGO_DEBUG=1 LOWBID_PAYMENT_MODE=direct STELLAR_HORIZON_URL=http://127.0.0.1:$$hport; \
	$(PYTHON) manage.py migrate --noinput -v 0 || exit 1; \
	$(PYTHON) manage.py runserver 127.0.0.1:$$port --noreload >data/e2e-server.log 2>&1 & pid=$$!; \
	trap 'kill $$pid 2>/dev/null' EXIT; \
	echo "e2e: server pid=$$pid port=$$port horizon=$$hport log=data/e2e-server.log"; \
	E2E_BASE_URL=http://127.0.0.1:$$port E2E_HORIZON_PORT=$$hport E2E_SHOTS_DIR=$(E2E_SHOTS_DIR) node tests/e2e/run.js; status=$$?; \
	if [ $$status -ne 0 ]; then echo "--- data/e2e-server.log (tail) ---"; tail -n 40 data/e2e-server.log; fi; \
	exit $$status

# Regenerate the pitch screenshots in docs/screenshots/ (the e2e with its default screenshot folder).
shots: E2E_SHOTS_DIR :=
shots: e2e

clean:
	rm -rf $(VENV) node_modules staticfiles .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
