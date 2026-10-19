import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from scenarios import SCENARIOS, Sandbox  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    sb = Sandbox(tmp_path / "sb")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "NO_COLOR", "GIT_TEST_ASSUME_DIFFERENT_OWNER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in sb.env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(sb.root)
    return sb


@pytest.fixture
def build(sandbox, monkeypatch):
    """build(name) creates the named scenario and returns its path, with any
    extra environment whygit should see already applied."""

    def _build(name: str) -> Path:
        builder, _, env = SCENARIOS[name]
        path = builder(sandbox)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return path

    return _build


@pytest.fixture
def anyio_backend():
    return "asyncio"
