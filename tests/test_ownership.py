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


@pytest.mark.parametrize("namespace", ["testshop", "testsuite"])
def test_application_name_starting_with_tests_is_not_test_code(
    tmp_path: Path, namespace: str
) -> None:
    root = tree(tmp_path)
    for path in (root / "app").rglob("*.py"):
        path.write_text(path.read_text().replace("app.", f"{namespace}."))
    for path in (root / "tests").rglob("*.py"):
        path.write_text(path.read_text().replace("app.", f"{namespace}."))
    (root / "app").rename(root / namespace)
    architecture = extract(root, tach=TACH)
    assert architecture.namespace == namespace
    assert f"{namespace}.one" in architecture.boundaries
    assert isinstance(lint_architecture(architecture), WellFormed)
    # A similarly named production owner still cannot import actual test code.
    source = root / namespace / "one/item.py"
    source.write_text(source.read_text() + "from tests.testkit import get_items\n")
    reported = lint_architecture(extract(root, tach=TACH))
    assert isinstance(reported, list)
    assert any(v.rule == "ownership" and v.src == f"{namespace}.one.item" for v in reported)
