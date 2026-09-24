"""Composition imports and transport checks."""

from pathlib import Path

from .support import VALID, findings, tree


def test_business_module_cannot_import_factory(tmp_path: Path) -> None:
    root = tree(
        tmp_path, {"app/one/item.py": VALID["app/one/item.py"] + "from .deps import get_items\n"}
    )
    assert "composition" in findings(root)


def test_business_module_cannot_import_transport(tmp_path: Path) -> None:
    assert "composition" in findings(
        tree(tmp_path, {"app/one/item.py": "from fastapi import FastAPI\n"})
    )
