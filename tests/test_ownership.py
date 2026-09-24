"""Root-package and direct-owner checks."""

from pathlib import Path

import pytest

from bsa_linter.architecture import WellFormed, lint_architecture
from bsa_linter.extract import extract

from .support import TACH, findings, tree


def test_empty_tree_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one application root package"):
        findings(tmp_path)


def test_multiple_application_roots_fail_closed(tmp_path: Path) -> None:
    root = tree(tmp_path, {"other/__init__.py": ""})
    with pytest.raises(ValueError, match="exactly one application root package"):
        extract(root, tach=TACH)


def test_new_capability_is_inferred_from_tree(tmp_path: Path) -> None:
    architecture = extract(tree(tmp_path, {"app/three/__init__.py": ""}), tach=TACH)
    assert "app.three" in architecture.boundaries
    assert isinstance(lint_architecture(architecture), WellFormed)


def test_unowned_root_module_is_a_violation(tmp_path: Path) -> None:
    assert "ownership" in findings(tree(tmp_path, {"app/loose.py": ""}))
