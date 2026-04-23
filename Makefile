.PHONY: install fixtures test test-integration test-all clean

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

clean:
	rm -rf .venv .pytest_cache .mypy_cache **/__pycache__ *.egg-info fixtures/case_*/
