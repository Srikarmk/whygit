import os
import sys

import pytest
from mcp import Client, StdioServerParameters

from whygit.server import mcp

pytestmark = pytest.mark.anyio

TOOLS = {"diagnose_repo", "explain_git_error", "explain_state"}


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


async def test_lists_three_read_only_tools(client):
    result = await client.list_tools()
    tools = {t.name: t for t in result.tools}
    assert set(tools) == TOOLS
    for t in tools.values():
        assert t.description and len(t.description) < 400
        assert t.annotations.read_only_hint is True
        assert t.annotations.destructive_hint is False
        assert t.annotations.idempotent_hint is True
        assert t.annotations.open_world_hint is False
    assert tools["explain_git_error"].input_schema["required"] == ["error_text"]


async def test_diagnose_repo(client, build):
    path = build("rebase_conflict")
    result = await client.call_tool("diagnose_repo", {"path": str(path)})
    assert not result.is_error
    data = result.structured_content
    assert data["findings"][0]["rule"] == "rebase_in_progress"


async def test_relative_path_and_tilde(client, build, monkeypatch, sandbox):
    path = build("ahead")
    monkeypatch.chdir(path.parent)
    result = await client.call_tool("explain_state", {"path": path.name})
    assert result.structured_content["ahead"] == 1
    result = await client.call_tool("explain_state", {"path": "~/" + path.name})
    assert result.structured_content["ahead"] == 1


async def test_explain_git_error(client, build):
    path = build("diverged")
    result = await client.call_tool(
        "explain_git_error",
        {
            "error_text": "hint: You have divergent branches and need to specify how to reconcile them.",
            "path": str(path),
        },
    )
    data = result.structured_content
    assert data["recognised"] and data["matches"][0]["rule"] == "divergent_pull"


async def test_explain_git_error_without_path(client):
    result = await client.call_tool("explain_git_error", {"error_text": "fatal: refusing to merge unrelated histories"})
    assert result.structured_content["matches"][0]["rule"] == "unrelated_histories"


async def test_missing_path_is_a_recoverable_error(client, sandbox):
    result = await client.call_tool("diagnose_repo", {"path": str(sandbox.root / "no-such-folder")})
    assert result.is_error
    text = result.content[0].text
    assert "does not exist" in text and "repository root" in text


async def test_stdio_server_starts_and_lists_tools(sandbox):
    params = StdioServerParameters(command=sys.executable, args=["-m", "whygit", "mcp"], env=dict(os.environ))
    async with Client(params) as c:
        result = await c.list_tools()
        assert {t.name for t in result.tools} == TOOLS
        res = await c.call_tool("explain_state", {"path": str(sandbox.root)})
        assert res.structured_content["is_repo"] is False
