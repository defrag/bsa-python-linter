"""Shared Python layout and naming checks."""

from pathlib import Path

import pytest

from bsa_linter.extract import extract

from .support import TACH, tree, violations


@pytest.mark.parametrize(
    "path",
    [
        "app/one/models.py",
        "app/one/book_models.py",
        "app/one/dto.py",
        "app/one/book_dto.py",
        "app/one/capabilities/__init__.py",
        "app/one/assembly.py",
        "app/one/_stores/__init__.py",
        "app/one/in_memory_items.py",
    ],
)
def test_technical_names_are_violations(tmp_path: Path, path: str) -> None:
    architecture = extract(tree(tmp_path, {path: ""}), tach=TACH)
    module = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    assert any(
        finding.rule == "python-layout" and finding.src == module
        for finding in violations(architecture)
    )
