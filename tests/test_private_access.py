"""Private implementation and command-branch access checks."""

from pathlib import Path

import pytest

from bsa_linter.architecture import owner_of
from bsa_linter.extract import extract

from .support import TACH, findings, tree, violations


@pytest.mark.parametrize("branch", ["_private", "_storage"])
@pytest.mark.parametrize("source", ["deps.py", "queries.py", "_work/run.py"])
def test_same_owner_implementation_can_reach_private_descendants(
    tmp_path: Path, branch: str, source: str
) -> None:
    architecture = extract(
        tree(
            tmp_path,
            {
                f"app/one/{branch}/__init__.py": "",
                f"app/one/{branch}/a/__init__.py": "",
                f"app/one/{branch}/a/lookup.py": f"from app.one.{branch}.b import value\n",
                f"app/one/{branch}/b.py": "value = 1\n",
                "app/one/_work/__init__.py": "",
                f"app/one/{source}": f"from app.one.{branch}.a.lookup import value\n",
            },
        ),
        tach=TACH,
    )
    assert owner_of(architecture, f"app.one.{branch}.a.lookup") == "app.one"
    assert violations(architecture) == []


@pytest.mark.parametrize("source", ["_work/run.py", "queries.py"])
def test_same_owner_implementation_can_use_operations_but_anchors_stay_independent(
    tmp_path: Path, source: str
) -> None:
    assert (
        findings(
            tree(
                tmp_path,
                {
                    "app/one/_work/__init__.py": "",
                    "app/one/_commands/__init__.py": "",
                    "app/one/_commands/add.py": "class Add: pass\n",
                    f"app/one/{source}": "from app.one._commands.add import Add\n",
                },
            )
        )
        == set()
    )


@pytest.mark.parametrize(
    "source",
    [
        "app/one/deps.py",
        "app/one/sibling/deps.py",
        "app/two/deps.py",
        "tests/test_private.py",
    ],
)
def test_foreign_owners_cannot_reach_child_private_code(tmp_path: Path, source: str) -> None:
    result = violations(
        extract(
            tree(
                tmp_path,
                {
                    "app/one/child/__init__.py": "",
                    "app/one/child/_private/__init__.py": "",
                    "app/one/child/_private/a.py": "class Hidden: pass\n",
                    "app/one/sibling/__init__.py": "",
                    source: "from app.one.child._private.a import Hidden\n",
                },
            ),
            tach=TACH,
        )
    )
    assert any(v.rule == "private-access" and v.tgt == "app.one.child._private.a" for v in result)


def test_child_cannot_reach_up_into_parent_private_code(tmp_path: Path) -> None:
    result = violations(
        extract(
            tree(
                tmp_path,
                {
                    "app/one/_private/__init__.py": "",
                    "app/one/_private/b.py": "class Hidden: pass\n",
                    "app/one/child/__init__.py": "",
                    "app/one/child/deps.py": "from app.one._private.b import Hidden\n",
                },
            ),
            tach=TACH,
        )
    )
    assert any(v.rule == "private-access" and v.src == "app.one.child.deps" for v in result)


def test_private_collaboration_remains_acyclic(tmp_path: Path) -> None:
    assert "cycles" in findings(
        tree(
            tmp_path,
            {
                "app/one/_private/__init__.py": "",
                "app/one/_private/a.py": "from .b import B\nclass A: pass\n",
                "app/one/_private/b.py": "from .a import A\nclass B: pass\n",
            },
        )
    )


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


@pytest.mark.parametrize("source", ["app/api.py", "app/one/api_routes.py"])
@pytest.mark.parametrize(
    "access",
    [
        "from app.api_support.errors import _hidden as visible\n",
        "import app.api_support.errors as errors\nvisible = errors._hidden\n",
    ],
)
def test_http_public_leaf_exception_does_not_expose_private_symbols(
    tmp_path: Path, source: str, access: str
) -> None:
    root = tree(
        tmp_path,
        {
            "app/api_support/__init__.py": "",
            "app/api_support/errors.py": "visible = object()\n_hidden = object()\n",
            source: access.replace("_hidden", "visible"),
        },
    )
    assert violations(extract(root, tach=TACH)) == []
    (root / source).write_text(access)
    reported = violations(extract(root, tach=TACH))
    assert [(v.rule, v.file, v.tgt, v.line) for v in reported] == [
        ("private-access", source, "app.api_support.errors", len(access.splitlines()))
    ]
