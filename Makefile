.PHONY: install fixtures test test-integration test-all record-cassettes probe-case-01 api ui dev clean

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

# Re-record ALL agent + orchestrator cassettes against the live API.
# Costs money — roughly the sum of one live pipeline run per case
# (~5 cases, each ~$0.50-$1 on Opus 4.7). Use when request-shape
# changes (model, thinking config, token budget) make recorded
# responses unrepresentative of current behavior.
record-cassettes:
	RECORD_CASSETTES=1 .venv/bin/pytest tests/test_orchestrator.py \
		tests/test_anthropic_client.py tests/test_denial_analyzer.py \
		tests/test_policy_reader.py tests/test_chart_miner.py \
		tests/test_guideline_citer.py tests/test_letter_writer.py \
		tests/test_independent_reviewer.py tests/test_fixtures.py -v

# Minimal live probe: run case_01 end-to-end and record its cassette.
# ~$0.50-$1 on Opus 4.7. Use as the surgical "does the real pipeline
# still work?" check after changing request shape.
probe-case-01:
	RECORD_CASSETTES=1 .venv/bin/pytest -v \
		"tests/test_fixtures.py::test_orchestrator_runs_on_each_case[case_01_ozempic_bmi34]"

# Backend only (FastAPI on :8000).
api:
	.venv/bin/uvicorn auto_appeal_agent.api.main:app --reload --port 8000

# Frontend only (Next.js on :3000). Requires `make install-ui` once.
ui:
	cd ui && PATH="$$HOME/.local/node/bin:$$PATH" npm run dev

clean:
	rm -rf .venv .pytest_cache .mypy_cache **/__pycache__ *.egg-info output/
