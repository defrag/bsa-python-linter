"""Gradual adoption keeps full graph evidence while gating a selected module."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from bsa_linter.architecture import (
    Violation,
    WellFormed,
    cycle_paths_through,
    lint_architecture,
)
from bsa_linter.extract import extract

from .support import TACH, tree


def scoped(root: Path, scope: str) -> list[Violation]:
    result = lint_architecture(extract(root, tach=TACH), scope=scope)
    return [] if isinstance(result, WellFormed) else result


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bsa_linter.cli", "--root", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_unrelated_findings_do_not_block_scoped_pass(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app/two/values.py": "value = 1\n"})
    result = cli(root, "--scope", "app.one", "--json", "--ownership-tree")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "pass": True,
        "scope": "app.one",
        "application_pass": False,
        "violations": [],
    }
    result = cli(root, "--scope", "app.one")
    assert result.stdout == "OK for scope app.one (whole application has violations).\n"
    assert cli(root).returncode == 1


@pytest.mark.parametrize("scope", ["app.one", "app.one.item", "app"])
def test_valid_scopes_can_report_whole_application_success(tmp_path: Path, scope: str) -> None:
    result = cli(tree(tmp_path), "--scope", scope, "--ownership-tree", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["pass"] is True
    assert payload["application_pass"] is True
    assert payload["scope"] == scope
    assert payload["ownership_tree"]["owner"] == "app"


@pytest.mark.parametrize("scope", ["", "app.missing", "app/one", "app.one.*", "one", "tests"])
def test_invalid_scope_is_an_invocation_error(tmp_path: Path, scope: str) -> None:
    result = cli(tree(tmp_path), "--scope", scope, "--json")
    assert result.returncode == 2
    assert "existing application module or package" in result.stderr
    assert result.stdout == ""


def test_internal_descendants_and_prefix_siblings(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/one/child/__init__.py": "",
            "app/one/child/values.py": "value = 1\n",
            "app/one_extra/__init__.py": "",
            "app/one_extra/values.py": "value = 1\n",
        },
    )
    assert {v.src for v in scoped(root, "app.one")} == {"app.one.child.values"}
    assert scoped(root, "app.one.item") == []


@pytest.mark.parametrize("caller", ["app/two/rel.py", "tests/testkit.py"])
def test_incoming_private_imports_remain_in_scope(tmp_path: Path, caller: str) -> None:
    root = tree(
        tmp_path,
        {
            "app/one/_store.py": "secret = 1\n",
            caller: "from app.one._store import secret\n",
        },
    )
    findings = scoped(root, "app.one")
    assert any(v.rule == "private-access" and v.file == caller and v.line == 1 for v in findings)
    result = cli(root, "--scope", "app.one")
    assert result.returncode == 1
    assert "BSA scope app.one failed" in result.stdout


def test_outgoing_private_import_and_parent_role_are_preserved(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/two/_store.py": "secret = 1\n",
            "app/one/item.py": "from app.two._store import secret\n",
            "app/one/deps.py": "from app.two.deps import get_items\n",
        },
    )
    assert any(v.rule == "private-access" for v in scoped(root, "app.one.item"))
    # Factories retain their actual role even when selected as an individual module.
    assert any(v.rule == "owner-dependency-cycle" for v in scoped(root, "app.one.deps"))
    (root / "app/two/rel.py").write_text("class Rel: pass\n")
    (root / "app/two/deps.py").write_text("def get_items(): return []\n")
    assert scoped(root, "app.one.deps") == []


def test_cycle_scope_is_not_just_the_diagnostic_source(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/one/a.py": "from . import b, c\n",
            "app/one/b.py": "from . import a\n",
            "app/one/c.py": "from . import b\n",
        },
    )
    findings = scoped(root, "app.one.c")
    assert any(
        v.rule == "cycles" and v.src == "app.one.a" and "app.one.c" in v.reason for v in findings
    )
    assert scoped(root, "app.two") == []


@pytest.mark.parametrize("prefix", ["app", "app.one", "app.foundation"])
def test_disjoint_files_in_owner_cycle_and_unrelated_leaf(tmp_path: Path, prefix: str) -> None:
    folder = prefix.replace(".", "/")
    changes = {
        f"{folder}/a/__init__.py": "",
        f"{folder}/a/first.py": f"from {prefix}.b import value\n",
        f"{folder}/b/__init__.py": "",
        f"{folder}/b/second.py": f"from {prefix}.c import value\n",
        f"{folder}/c/__init__.py": "",
        f"{folder}/c/third.py": f"from {prefix}.a import value\n",
        f"{folder}/c/unrelated.py": "value = 1\n",
    }
    if prefix == "app.foundation":
        changes[f"{folder}/__init__.py"] = ""
    root = tree(tmp_path, changes)
    findings = scoped(root, f"{prefix}.c.third")
    assert any(v.rule == "owner-dependency-cycle" for v in findings)
    assert not any(v.rule == "cycles" for v in findings)
    assert scoped(root, f"{prefix}.c.unrelated") == []


def test_extraction_issues_outside_scope_cannot_be_hidden(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app/two/rel.py": "def broken(:\n"})
    assert any(
        "Cannot parse source" in v.reason and v.src == "app.two.rel"
        for v in scoped(root, "app.one")
    )


def test_outside_import_extraction_and_missing_initializers_remain_visible(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/two/rel.py": "def run():\n    import app.one\n",
            "app/two/missing/item.py": "value = 1\n",
        },
    )
    assert {v.rule for v in scoped(root, "app.one")} >= {"explicit-imports", "python-layout"}


def test_scope_cannot_bypass_global_ownership_prerequisite(tmp_path: Path) -> None:
    architecture = extract(tree(tmp_path), tach=TACH)
    result = lint_architecture(replace(architecture, boundaries=frozenset()), scope="app.one")
    assert isinstance(result, list)
    assert any("not a vacuous pass" in v.reason for v in result)


def test_tach_failure_stays_a_tool_error(tmp_path: Path) -> None:
    root = tree(tmp_path)
    (root / "tach.toml").write_text("invalid = [")
    result = cli(root, "--scope", "app.one", "--json")
    assert result.returncode == 2
    assert "Tach map failed" in result.stderr
    assert result.stdout == ""


def test_scoped_cycles_against_reachability_oracle() -> None:
    # Every four-node graph: an edge is cyclic exactly when its target reaches its source.
    nodes = ("a", "b", "c", "d")
    possible = [(src, tgt) for src in nodes for tgt in nodes if src != tgt]
    for mask in range(1 << len(possible)):
        edges = {edge for bit, edge in enumerate(possible) if mask & (1 << bit)}
        reachable = set(edges)
        for via in nodes:
            reachable |= {
                (src, tgt)
                for src in nodes
                for tgt in nodes
                if (src, via) in reachable and (via, tgt) in reachable
            }
        for selected_node in nodes:
            selected = {edge for edge in edges if selected_node in edge}
            paths = cycle_paths_through(edges, selected)
            assert bool(paths) == ((selected_node, selected_node) in reachable)
            for path in paths:
                assert path[0] == path[-1]
                assert selected_node in path
                assert all(edge in edges for edge in zip(path, path[1:], strict=False))
