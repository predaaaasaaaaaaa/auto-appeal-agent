"""Shared pytest fixtures."""
from pathlib import Path

import pytest

from tests._cassettes import patch_client

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def all_case_dirs(fixtures_dir: Path) -> list[Path]:
    return sorted(p for p in fixtures_dir.iterdir() if p.is_dir() and p.name.startswith("case_"))


@pytest.fixture
def cassette(monkeypatch, request):
    """Per-test VCR cassette: record real API calls or replay from disk.

    Cassette filename is the test's nodeid (sanitized), stored in
    tests/cassettes/. Set RECORD_CASSETTES=1 to refresh; otherwise the
    cassette is replayed and the test costs nothing.
    """
    name = request.node.name.replace("[", "_").replace("]", "").replace("/", "_")
    cas = patch_client(monkeypatch, name)
    yield cas
    cas.save()
