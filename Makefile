.PHONY: dev test lint format seed typecheck demo-cli fixtures

dev:            ## docker compose up --build (web mode)
	docker compose up --build

test:           ## run the test suite with coverage gate
	uv run pytest -x --cov=savesong --cov-report=term-missing --cov-fail-under=85

lint:           ## ruff + web lint
	uv run ruff check src tests
	uv run ruff format --check src tests
	cd web && npm run lint

format:         ## autofix formatting
	uv run ruff check --fix src tests
	uv run ruff format src tests
	cd web && npm run format

seed:           ## seed demo library rows (bundled CC0 audio + covers)
	uv run python -m savesong.db.seed

typecheck:      ## mypy strict + tsc
	uv run mypy
	cd web && npx tsc --noEmit

demo-cli:       ## offline scripted demo against fixtures (asciinema-friendly)
	uv run python scripts/demo_cli.py

fixtures:       ## regenerate binary test fixtures (CC0 opus/mp3 clips, cover PNG)
	uv run python scripts/gen_fixtures.py
