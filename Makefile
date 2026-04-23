.PHONY: install fixtures test test-fast clean

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"

fixtures:
	.venv/bin/python -m auto_appeal_agent.scripts.generate_fixtures

test:
	.venv/bin/pytest

test-fast:
	.venv/bin/pytest -m "not integration"

clean:
	rm -rf .venv .pytest_cache .mypy_cache **/__pycache__ *.egg-info fixtures/case_*/
