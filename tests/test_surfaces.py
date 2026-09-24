"""Cross-owner imports must use public surfaces."""

from pathlib import Path

import pytest

from .support import findings, tree


@pytest.mark.parametrize(
    "changes",
    [
        {"app/api.py": "from app.one.item import Item\n"},
        {"app/api.py": "import app.one as o\nx = o.item.Item\n"},
        {"app/two/rel.py": "from app.one.item import Item\nclass Rel: pass\n"},
    ],
)
def test_foreign_concept_leaf_is_a_violation(tmp_path: Path, changes: dict[str, str]) -> None:
    assert "public-surfaces" in findings(tree(tmp_path, changes))
