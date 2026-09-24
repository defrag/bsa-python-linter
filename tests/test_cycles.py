"""Module cycles and dependency cycles between owners."""

from pathlib import Path

from bsa_linter.extract import extract

from .support import EDGE, TACH, findings, tree, violations


def test_observed_owner_dependency_cycle(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app/one/item.py": "from app.two import Rel\nclass Item: pass\n"})
    architecture = extract(root, tach=TACH)
    assert architecture.owner_dependencies == {EDGE, ("app.one", "app.two")}
    assert any(v.rule == "owner-dependency-cycle" for v in violations(architecture))


def test_module_cycle(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/one/item.py": "from app.one.other import Other\n",
            "app/one/other.py": "from app.one.item import Item\n",
        },
    )
    assert "cycles" in findings(root)
