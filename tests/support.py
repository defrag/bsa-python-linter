"""Synthetic application shared by focused linter rule tests."""

from __future__ import annotations

import sys
from pathlib import Path

from bsa_linter.architecture import Architecture, Violation, WellFormed, lint_architecture
from bsa_linter.extract import extract

TACH = str(Path(sys.executable).with_name("tach"))
VALID = {
    "app/__init__.py": "",
    "app/api.py": "from app.one.deps import get_items\n",
    "app/one/__init__.py": "from .item import Item\n",
    "app/one/item.py": "class Item: pass\nclass Items: pass\nclass InMemoryItems: pass\n",
    "app/one/deps.py": (
        "from app.one import InMemoryItems, Items\n"
        "def get_items() -> Items:\n    return InMemoryItems()\n"
    ),
    "app/two/__init__.py": "from .rel import Rel\n",
    "app/two/rel.py": "from app.one import Item\nclass Rel: pass\n",
    "app/two/deps.py": "from app.one.deps import get_items\nfrom app.two.rel import Rel\n",
    "tests/__init__.py": "",
    "tests/testkit.py": "from app.one.deps import get_items\n",
}
EDGE = ("app.two", "app.one")


def tree(root: Path, changes: dict[str, str] | None = None) -> Path:
    for name, content in (VALID | (changes or {})).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return root


def violations(architecture: Architecture) -> list[Violation]:
    result = lint_architecture(architecture)
    return [] if isinstance(result, WellFormed) else result


def findings(root: Path) -> set[str]:
    return {violation.rule for violation in violations(extract(root, tach=TACH))}
