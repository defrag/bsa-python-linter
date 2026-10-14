"""Opt-in type-only syntax preserves the complete architecture graph."""

import json
import sys
from pathlib import Path

import pytest

from bsa_linter.architecture import OwnershipTree, establish_ownership_tree
from bsa_linter.cli import main
from bsa_linter.extract import extract

TACH = str(Path(sys.executable).with_name("tach"))
ENABLED = "[tool.bsa]\nallow-type-checking-imports = true\n"


def application(root: Path, source: str, config: str = ENABLED) -> Path:
    files = {
        "pyproject.toml": config,
        "app/__init__.py": "",
        "app/catalog/__init__.py": "from .item import Item\n",
        "app/catalog/item.py": "class Item: pass\n",
        "app/catalog/_private.py": "class Secret: pass\n",
        "app/loans/__init__.py": "class Loan: pass\n",
        "app/loans/loan.py": source,
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


@pytest.mark.parametrize(
    ("binding", "guard"),
    [
        ("from typing import TYPE_CHECKING", "TYPE_CHECKING"),
        ("from typing import TYPE_CHECKING as TC", "TC"),
        ("import typing", "typing.TYPE_CHECKING"),
        ("import typing as t", "t.TYPE_CHECKING"),
    ],
)
def test_allowed_guard_preserves_local_and_external_edges(
    tmp_path: Path, binding: str, guard: str
) -> None:
    root = application(
        tmp_path,
        f"{binding}\nif {guard}:\n"
        "    from app.catalog import Item\n"
        "    from external_stubs.client import Client\n",
    )
    architecture = extract(root, tach=TACH)
    assert isinstance(establish_ownership_tree(architecture), OwnershipTree)
    assert ("app.loans", "app.catalog") in architecture.owner_dependencies
    assert any(
        edge.tgt == "external_stubs.client" and edge.symbol == "Client"
        for edge in architecture.imports
    )


@pytest.mark.parametrize("config", ["", "[tool.bsa]\nallow-type-checking-imports = false\n"])
def test_strict_default_is_preserved(tmp_path: Path, config: str) -> None:
    root = application(
        tmp_path,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.catalog import Item\n",
        config,
    )
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert isinstance(result, list)
    assert any(v.rule == "explicit-imports" for v in result)


@pytest.mark.parametrize(
    ("statement", "rule"),
    [
        ("from app.catalog.item import Item", "public-surfaces"),
        ("from app.catalog._private import Secret", "private-access"),
        ("from app.catalog import *", "explicit-imports"),
        ("from app.catalog.deps import build", "composition"),
    ],
)
def test_guard_does_not_grant_import_permissions(tmp_path: Path, statement: str, rule: str) -> None:
    root = application(
        tmp_path, f"from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    {statement}\n"
    )
    (root / "app/catalog/deps.py").write_text("def build(): pass\n")
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert isinstance(result, list)
    assert any(v.rule == rule for v in result)


def test_guard_cannot_hide_owner_cycle(tmp_path: Path) -> None:
    root = application(
        tmp_path,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.catalog import Item\n",
    )
    (root / "app/catalog/item.py").write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        "    from app.loans import Loan\nclass Item: pass\n"
    )
    architecture = extract(root, tach=TACH)
    assert architecture.owner_dependencies == frozenset(
        {("app.loans", "app.catalog"), ("app.catalog", "app.loans")}
    )
    result = establish_ownership_tree(architecture)
    assert isinstance(result, list)
    assert any(v.rule == "owner-dependency-cycle" for v in result)


def test_support_direction_still_checked(tmp_path: Path) -> None:
    root = application(tmp_path, "")
    (root / "app/foundation.py").write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.catalog import Item\n"
    )
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert isinstance(result, list)
    assert any(v.rule == "direction" for v in result)


@pytest.mark.parametrize(
    "source",
    [
        "if True:\n    from app.catalog import Item\n",
        "if TYPE_CHECKING:\n    from app.catalog import Item\n",
        "from another import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.catalog import Item\n",
        "from typing import TYPE_CHECKING\nTYPE_CHECKING = True\nif TYPE_CHECKING:\n"
        "    from app.catalog import Item\n",
        "import typing as t\nt = object()\nif t.TYPE_CHECKING:\n    from app.catalog import Item\n",
        "import typing\ntyping.TYPE_CHECKING = True\nif typing.TYPE_CHECKING:\n"
        "    from app.catalog import Item\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING or True:\n"
        "    from app.catalog import Item\n",
        "from typing import TYPE_CHECKING\ndef f():\n    if TYPE_CHECKING:\n"
        "        from app.catalog import Item\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    if True:\n"
        "        from app.catalog import Item\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n"
        "    from app.catalog import Item\n",
        "if TYPE_CHECKING:\n    from app.catalog import Item\nfrom typing import TYPE_CHECKING\n",
    ],
)
def test_other_conditional_imports_remain_rejected(tmp_path: Path, source: str) -> None:
    result = establish_ownership_tree(extract(application(tmp_path, source), tach=TACH))
    assert isinstance(result, list)
    assert any(v.rule == "explicit-imports" for v in result)


@pytest.mark.parametrize(
    "config",
    [
        "[tool.bsa]\nallow-type-checking-imports = 'true'\n",
        "[tool.bsa]\nallow-type-checking-imports = 1\n",
        "[tool.bsa]\nignore-type-checking = true\n",
        "[tool]\nbsa = true\n",
        "tool = true\n",
        "[tool.bsa\n",
    ],
)
def test_invalid_configuration_is_a_tool_error(tmp_path: Path, config: str) -> None:
    root = application(tmp_path, "", config)
    with pytest.raises(SystemExit) as failure:
        main(["--root", str(root), "--json"])
    assert failure.value.code == 2


def test_cli_reads_root_config_independently_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = application(
        tmp_path / "project",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.catalog import Item\n",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True
