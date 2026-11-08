"""MCP tool surfaces retain ownership while allowing server composition."""

from pathlib import Path

import pytest

from bsa_linter.architecture import WellFormed, lint_architecture, owner_of
from bsa_linter.extract import extract

from .support import TACH, tree, violations

MCP = {
    "app/server.py": "from app.one.mcp_tools import register_tools\n",
    "app/one/mcp_tools.py": (
        "from app.one import Item\n"
        "from app.one.commands import Add\n"
        "from app.one.deps import get_items\n"
        "from app.two.deps import get_items as get_other_items\n"
        "import app.scope\n"
        "import app.settings\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "def register_tools(server: FastMCP): pass\n"
    ),
    "app/one/commands.py": "from ._commands.add import Add\n",
    "app/one/_commands/__init__.py": "",
    "app/one/_commands/add.py": "class Add: pass\n",
    "app/scope.py": "",
    "app/settings.py": "",
    # Avoid the fixture's two -> one connection when testing one -> two.
    "app/two/rel.py": "class Rel: pass\n",
    "app/two/deps.py": "def get_items(): return []\n",
}


def test_server_assembles_owned_mcp_tools(tmp_path: Path) -> None:
    architecture = extract(tree(tmp_path, MCP), tach=TACH)
    assert violations(architecture) == []
    assert architecture.mcp_entries == {"app.server"}
    assert architecture.mcp_tools == {"app.one.mcp_tools"}
    assert owner_of(architecture, "app.one.mcp_tools") == "app.one"
    assert ("app.one", "app.two") in architecture.owner_dependencies
    assert ("app.server", "app.one") in architecture.dependency_graphs_by_owner["app"]


@pytest.mark.parametrize(
    "source",
    [
        "app/api.py",
        "app/main.py",
        "app/cli.py",
        "app/bootstrap.py",
        "app/shared.py",
        "app/one/__init__.py",
        "app/one/item.py",
        "app/one/deps.py",
        "app/one/api_routes.py",
        "app/two/mcp_tools.py",
        "tests/test_tools.py",
    ],
)
def test_only_server_imports_tool_surfaces(tmp_path: Path, source: str) -> None:
    root = tree(tmp_path, MCP | {source: "from app.one.mcp_tools import register_tools\n"})
    assert any(
        v.rule == "direction" and v.file == source and v.tgt == "app.one.mcp_tools"
        for v in violations(extract(root, tach=TACH))
    )


@pytest.mark.parametrize(
    "target, rule",
    [
        ("app.one._commands.add", "private-access"),
        ("app.two._secret", "private-access"),
        ("app.two.rel", "public-surfaces"),
        ("app.one.api_routes", "direction"),
        ("app.api_support", "direction"),
        ("app.server", "direction"),
        ("fastapi", "composition"),
    ],
)
def test_tool_adapters_preserve_restrictions(tmp_path: Path, target: str, rule: str) -> None:
    sources = MCP | {
        "app/two/_secret.py": "",
        "app/one/api_routes.py": "",
        "app/api_support.py": "",
        "app/one/mcp_tools.py": f"import {target}\ndef register_tools(server): pass\n",
    }
    root = tree(tmp_path, sources)
    assert any(
        v.rule == rule and v.src == "app.one.mcp_tools" and v.tgt == target
        for v in violations(extract(root, tach=TACH))
    )


@pytest.mark.parametrize("framework", ["mcp", "mcp.server.fastmcp", "fastmcp"])
def test_mcp_framework_audience(tmp_path: Path, framework: str) -> None:
    allowed = {"app/server.py", "app/one/mcp_tools.py", "tests/test_mcp.py"}
    forbidden = {
        "app/api.py",
        "app/cli.py",
        "app/main.py",
        "app/bootstrap.py",
        "app/one/item.py",
        "app/one/deps.py",
        "app/one/api_routes.py",
        "app/api_support.py",
        "app/foundation.py",
        "app/one/server.py",
    }
    root = tree(tmp_path, {path: f"import {framework}\n" for path in allowed | forbidden})
    found = violations(extract(root, tach=TACH))
    assert {(v.file, v.tgt) for v in found if v.rule == "composition"} == {
        (path, framework) for path in forbidden
    }


def test_nested_capability_tools_keep_their_direct_owner(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/server.py": "from app.one.child.mcp_tools import register_tools\n",
            "app/one/child/__init__.py": "",
            "app/one/child/deps.py": "def get_items(): return []\n",
            "app/one/child/mcp_tools.py": (
                "from app.one.child.deps import get_items\ndef register_tools(server): pass\n"
            ),
        },
    )
    architecture = extract(root, tach=TACH)
    assert violations(architecture) == []
    assert owner_of(architecture, "app.one.child.mcp_tools") == "app.one.child"


@pytest.mark.parametrize("path", ["app/mcp_tools.py", "app/shared/mcp_tools.py"])
def test_tool_role_requires_a_capability(tmp_path: Path, path: str) -> None:
    sources = {path: "from app.one.deps import get_items\n"}
    if "shared/" in path:
        sources["app/shared/__init__.py"] = ""
    architecture = extract(tree(tmp_path, sources), tach=TACH)
    assert not architecture.mcp_tools
    assert violations(architecture)


def test_mcp_role_never_hides_owner_cycles(tmp_path: Path) -> None:
    root = tree(tmp_path, MCP | {"app/two/deps.py": "from app.one.deps import get_items\n"})
    architecture = extract(root, tach=TACH)
    assert {("app.one", "app.two"), ("app.two", "app.one")} <= architecture.owner_dependencies
    assert any(v.rule == "owner-dependency-cycle" for v in violations(architecture))


def test_scoped_mcp_checks_include_incoming_imports_and_cycles(tmp_path: Path) -> None:
    root = tree(tmp_path, MCP)
    assert isinstance(lint_architecture(extract(root, tach=TACH), scope="app.one"), WellFormed)
    (root / "app/api.py").write_text("from app.one.mcp_tools import register_tools\n")
    result = lint_architecture(extract(root, tach=TACH), scope="app.one")
    assert isinstance(result, list)
    assert any(v.rule == "direction" and v.src == "app.api" for v in result)
    (root / "app/api.py").write_text("")
    (root / "app/two/deps.py").write_text("from app.one.deps import get_items\n")
    result = lint_architecture(extract(root, tach=TACH), scope="app.one")
    assert isinstance(result, list)
    assert any(v.rule == "owner-dependency-cycle" for v in result)
