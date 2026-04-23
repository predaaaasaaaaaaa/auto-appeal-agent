.PHONY: install fixtures test test-integration test-all api ui dev clean

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"

fixtures:
	.venv/bin/python -m auto_appeal_agent.scripts.generate_fixtures

# Default: fast tests only. No API calls. No cost.
test:
	.venv/bin/pytest

# Integration tests only. These call the Anthropic API and cost money.
test-integration:
	.venv/bin/pytest -m integration

# Everything — fast + integration. Costs money.
test-all:
	.venv/bin/pytest -m 'integration or not integration'

# Backend only (FastAPI on :8000).
api:
	.venv/bin/uvicorn auto_appeal_agent.api.main:app --reload --port 8000

# Frontend only (Next.js on :3000). Requires `make install-ui` once.
ui:
	cd ui && PATH="$$HOME/.local/node/bin:$$PATH" npm run dev

clean:
	rm -rf .venv .pytest_cache .mypy_cache **/__pycache__ *.egg-info fixtures/case_*/ output/
