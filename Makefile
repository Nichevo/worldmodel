# One-word commands for the common jobs. Each is a thin wrapper; the README
# lists the plain commands for machines without make (Windows).

PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: setup setup-data setup-app update refresh build status api web dev test typecheck

setup: setup-data setup-app  ## install everything

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

setup-data: $(BIN)/python  ## the data pipeline only
	$(BIN)/pip install -e contract -e "data[test]"

setup-app: $(BIN)/python  ## the API and web app only
	$(BIN)/pip install -e contract -e "app/api[test]"
	cd app/web && npm install

update:  ## latest code from GitHub, then any new packages (your data in var/ is untouched)
	git checkout -q main && git pull --ff-only origin main
	$(MAKE) setup

refresh:  ## fetch every source, then build and validate a new warehouse
	$(BIN)/worldmodel-data refresh

build:  ## rebuild the warehouse from stored vintages
	$(BIN)/worldmodel-data build

status:
	$(BIN)/worldmodel-data status

api:  ## the local API on http://127.0.0.1:8000 (docs at /docs)
	$(BIN)/worldmodel-api

web:  ## the web app on http://localhost:3000 (needs the API running)
	cd app/web && npm run dev

dev:  ## API and web app together
	$(BIN)/worldmodel-api & cd app/web && npm run dev

test:
	$(BIN)/pytest -q contract/tests data/tests app/api/tests

typecheck:
	cd app/web && npm run typecheck
