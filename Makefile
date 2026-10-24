# Lowbid — hackathon toolchain. `make dev` is the only command a teammate needs.
PY      ?= python3.13
VENV    ?= .venv
PIP     := $(VENV)/bin/pip
PYTHON  := $(VENV)/bin/python
RUFF    := $(VENV)/bin/ruff
HOST    ?= 0.0.0.0
PORT    ?= 8000

.PHONY: dev venv env migrate run test lint fmt css watch-css vendor check clean

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

vendor: node_modules/.package-lock.json
	npm run vendor

check: lint test

clean:
	rm -rf $(VENV) node_modules staticfiles .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
