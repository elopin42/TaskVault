# Lowbid — hackathon toolchain. `make dev` is the only command a teammate needs;
# `make check` (lint + tests + tailwind in sync) is the pre-commit gate; `make seed` loads the demo data.
PY      ?= python3.13
VENV    ?= .venv
PIP     := $(VENV)/bin/pip
PYTHON  := $(VENV)/bin/python
RUFF    := $(VENV)/bin/ruff
HOST    ?= 0.0.0.0
PORT    ?= 8000

.PHONY: dev venv env migrate run seed test lint fmt css css-check watch-css vendor check e2e shots clean

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

# End-to-end (Playwright, simulated Freighter + a fake Horizon): fresh SQLite at data/e2e.sqlite3,
# runserver on a free port in DIRECT payment mode pointed at tests/e2e/fake-horizon.js (started by
# run.js on E2E_HORIZON_PORT, so the payment chain really signs and submits — the sandbox has no
# network), node tests/e2e/run.js (screenshots -> docs/screenshots/), server killed on exit.
# Needs node 22 with the `playwright` package + Chromium resolvable from `require("playwright")`.
E2E_DB ?= data/e2e.sqlite3
e2e: venv
	@rm -f $(E2E_DB)
	@port=$$($(PYTHON) -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'); \
	hport=$$($(PYTHON) -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'); \
	export LOWBID_SQLITE_PATH=$(E2E_DB) DJANGO_DEBUG=1 LOWBID_PAYMENT_MODE=direct STELLAR_HORIZON_URL=http://127.0.0.1:$$hport; \
	$(PYTHON) manage.py migrate --noinput -v 0 || exit 1; \
	$(PYTHON) manage.py runserver 127.0.0.1:$$port --noreload >data/e2e-server.log 2>&1 & pid=$$!; \
	trap 'kill $$pid 2>/dev/null' EXIT; \
	echo "e2e: server pid=$$pid port=$$port horizon=$$hport log=data/e2e-server.log"; \
	E2E_BASE_URL=http://127.0.0.1:$$port E2E_HORIZON_PORT=$$hport node tests/e2e/run.js; status=$$?; \
	if [ $$status -ne 0 ]; then echo "--- data/e2e-server.log (tail) ---"; tail -n 40 data/e2e-server.log; fi; \
	exit $$status

# Regenerate the pitch screenshots in docs/screenshots/ (alias of e2e).
shots: e2e

clean:
	rm -rf $(VENV) node_modules staticfiles .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
