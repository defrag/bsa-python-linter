"""Private implementation and command-branch access checks."""

from pathlib import Path

import pytest

from .support import findings, tree


@pytest.mark.parametrize(
    "changes",
    [
        {
            "app/one/commands.py": "from app.two._commands.add import Add\n",
            "app/two/_commands/__init__.py": "",
            "app/two/_commands/add.py": "class Add: pass\n",
        },
        {
            "app/one/child/__init__.py": "",
            "app/one/child/_private.py": "class Thing: pass\n",
            "app/one/item.py": "from app.one.child._private import Thing\n",
        },
        {
            "app/one/_commands/__init__.py": "",
            "app/one/_commands/add.py": "class Add: pass\n",
            "app/one/item.py": "from app.one._commands.add import Add\n",
        },
    ],
)
def test_private_branch_import_is_a_violation(tmp_path: Path, changes: dict[str, str]) -> None:
    assert "private-access" in findings(tree(tmp_path, changes))
