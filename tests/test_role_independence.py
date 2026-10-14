"""A role may constrain connections, but cannot erase structural dependencies."""

import sys
from pathlib import Path

import pytest

from bsa_linter.architecture import OwnershipTree, establish_ownership_tree
from bsa_linter.extract import extract

TACH = str(Path(sys.executable).with_name("tach"))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("east", "north"),
        ("shared", "database"),
        ("bootstrap", "scope"),
        ("api_support", "foundation"),
    ],
    ids=["business", "support", "composition", "http-support"],
)
def test_roles_never_hide_a_cycle_between_top_level_owners(
    tmp_path: Path, left: str, right: str
) -> None:
    sources = {
        "atlas/__init__.py": "",
        "atlas/freight/__init__.py": "",
        f"atlas/{left}/__init__.py": "class Left: pass\n",
        f"atlas/{right}/__init__.py": "class Right: pass\n",
        f"atlas/{left}/_work.py": f"from atlas.{right} import Right\n",
        f"atlas/{right}/_work.py": "",
    }
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    tach = str(Path(sys.executable).with_name("tach"))
    baseline = extract(tmp_path, tach=tach)
    assert isinstance(establish_ownership_tree(baseline), OwnershipTree)
    forward = (f"atlas.{left}", f"atlas.{right}")
    assert baseline.dependency_graphs_by_owner["atlas"] == {forward}
    assert baseline.owner_dependencies == ({forward} if left == "east" else set())

    path = tmp_path / f"atlas/{right}/_work.py"
    path.write_text(f"from atlas.{left} import Left\n")
    broken = extract(tmp_path, tach=tach)
    assert broken.dependency_graphs_by_owner["atlas"] == {forward, forward[::-1]}
    result = establish_ownership_tree(broken)
    assert isinstance(result, list)
    # Some reversed imports also violate role direction; keep those findings.
    assert any(finding.rule == "owner-dependency-cycle" for finding in result)
    assert not any(finding.rule == "cycles" for finding in result)
    path.write_text("")
    assert establish_ownership_tree(extract(tmp_path, tach=tach)) == (
        establish_ownership_tree(baseline)
    )


def test_entry_connections_remain_observed_without_becoming_business_dependencies(
    tmp_path: Path,
) -> None:
    sources = {
        "atlas/__init__.py": "",
        "atlas/freight/__init__.py": "class Shipment: pass\n",
        "atlas/api.py": "from atlas.freight import Shipment\n",
        "atlas/cli.py": "from atlas.freight import Shipment\n",
    }
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    architecture = extract(tmp_path, tach=TACH)
    assert isinstance(establish_ownership_tree(architecture), OwnershipTree)
    assert not architecture.owner_dependencies
    assert architecture.dependency_graphs_by_owner["atlas"] == {
        ("atlas.api", "atlas.freight"),
        ("atlas.cli", "atlas.freight"),
    }
