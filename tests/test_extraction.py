"""Extraction failures must not produce a passing architecture."""

from pathlib import Path

import pytest

from bsa_linter.extract import extract

from .support import MERIDIAN, TACH, findings, tree


def test_parse_issue_fails_closed(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app/one/item.py": "this is not valid python!\n"})
    assert "ownership" in findings(root)


def test_dynamic_import_fails_closed(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app/one/item.py": "x = __import__('app.two')\n"})
    assert "explicit-imports" in findings(root)


def test_tach_literals_are_not_imports() -> None:
    graph = extract(MERIDIAN, tach=TACH)
    assert not [
        edge
        for edge in graph.imports
        if edge.src == "tests.conventions" and edge.tgt.startswith("meridian.")
    ]


def test_tach_failure_is_not_a_pass(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Tach map failed"):
        extract(tree(tmp_path), tach="/usr/bin/false")
