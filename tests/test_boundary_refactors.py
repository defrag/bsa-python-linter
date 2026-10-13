"""Source-only examples of folder refactors, selective exports, and hidden owner cycles."""

from pathlib import Path

import pytest

from bsa_linter.architecture import OwnershipTree, establish_ownership_tree, owner_of
from bsa_linter.extract import extract

from .support import TACH, violations


def write_sources(root: Path, sources: dict[str, str]) -> None:
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


@pytest.mark.parametrize("folder", ["", "_work", "_work/nested", "packing"])
def test_moving_files_into_folders_preserves_file_cycle_detection(
    tmp_path: Path, folder: str
) -> None:
    base = "workshop/fulfillment"
    location = f"{base}/{folder}" if folder else base
    sources = {
        "workshop/__init__.py": "",
        f"{base}/__init__.py": "",
        f"{location}/a.py": "from .b import B\nclass A: pass\n",
        f"{location}/b.py": "class B: pass\n",
    }
    if folder:
        sources[f"{location}/__init__.py"] = ""
    if folder == "_work/nested":
        sources[f"{base}/_work/__init__.py"] = ""
    write_sources(tmp_path, sources)
    expected = OwnershipTree(
        owner="workshop",
        children=(
            OwnershipTree(
                owner="workshop.fulfillment",
                children=(OwnershipTree(owner="workshop.fulfillment.packing"),)
                if folder == "packing"
                else (),
            ),
        ),
    )
    architecture = extract(tmp_path, tach=TACH)
    module = location.replace("/", ".")
    direct_owner = module if folder == "packing" else "workshop.fulfillment"
    assert owner_of(architecture, f"{module}.a") == direct_owner
    assert establish_ownership_tree(architecture) == expected

    # A public child changes ownership; a private branch (even with public-named
    # descendants) does not. Neither arrangement can hide an actual file cycle.
    path = tmp_path / f"{location}/b.py"
    path.write_text("from .a import A\nclass B: pass\n")
    broken = extract(tmp_path, tach=TACH)
    reported = violations(broken)
    assert {v.rule for v in reported} == {"cycles"}
    assert all(f"{module}.a" in v.reason and f"{module}.b" in v.reason for v in reported)
    assert establish_ownership_tree(broken) == reported
    path.write_text(sources[f"{location}/b.py"])
    assert establish_ownership_tree(extract(tmp_path, tach=TACH)) == expected


@pytest.mark.parametrize("folder", ["packing", "_work", "_work/nested"])
def test_removing_folder_initializer_cannot_silently_merge_ownership(
    tmp_path: Path, folder: str
) -> None:
    sources = {
        "workshop/__init__.py": "",
        "workshop/fulfillment/__init__.py": "",
        f"workshop/fulfillment/{folder}/__init__.py": "",
        f"workshop/fulfillment/{folder}/parcel.py": "class Parcel: pass\n",
    }
    if folder == "_work/nested":
        sources["workshop/fulfillment/_work/__init__.py"] = ""
    write_sources(tmp_path, sources)
    expected = establish_ownership_tree(extract(tmp_path, tach=TACH))
    assert isinstance(expected, OwnershipTree)
    initializer = tmp_path / f"workshop/fulfillment/{folder}/__init__.py"
    initializer.unlink()
    broken = extract(tmp_path, tach=TACH)
    reported = violations(broken)
    assert [(v.rule, v.src) for v in reported] == [
        ("python-layout", f"workshop.fulfillment.{folder.replace('/', '.')}")
    ]
    assert establish_ownership_tree(broken) == reported
    initializer.write_text("")
    assert establish_ownership_tree(extract(tmp_path, tach=TACH)) == expected


@pytest.mark.parametrize("scope", ["fulfillment", "fulfillment.packing", "foundation"])
@pytest.mark.parametrize("private", [False, True], ids=["child-owners", "private-branches"])
def test_disjoint_file_paths_can_form_owner_cycles_but_private_folders_are_not_owners(
    tmp_path: Path, scope: str, private: bool
) -> None:
    base = "workshop/" + scope.replace(".", "/")
    left, right = ("_left", "_right") if private else ("left", "right")
    left_module, right_module = f"workshop.{scope}.{left}", f"workshop.{scope}.{right}"
    sources = {
        "workshop/__init__.py": "",
        "workshop/fulfillment/__init__.py": "",
        f"{base}/__init__.py": "",
        f"{base}/{left}/__init__.py": "class Left: pass\n",
        f"{base}/{right}/__init__.py": "class Right: pass\n",
        f"{base}/{left}/_work.py": f"from {right_module} import Right\n",
        f"{base}/{right}/_work.py": "",
    }
    write_sources(tmp_path, sources)
    baseline = extract(tmp_path, tach=TACH)
    expected = establish_ownership_tree(baseline)
    assert isinstance(expected, OwnershipTree)
    if private:
        # No child boundaries means no sibling-owner graph at this scope.
        assert f"workshop.{scope}" not in baseline.dependency_graphs_by_owner
    else:
        assert baseline.dependency_graphs_by_owner[f"workshop.{scope}"] == {
            (left_module, right_module)
        }
    assert owner_of(baseline, f"{left_module}._work") == (
        f"workshop.{scope}" if private else left_module
    )

    path = tmp_path / f"{base}/{right}/_work.py"
    path.write_text(f"from {left_module} import Left\n")
    reverse = extract(tmp_path, tach=TACH)
    if private:
        # Two disjoint one-way file imports inside one owner are not a cycle.
        assert establish_ownership_tree(reverse) == expected
    else:
        # Neither package root imports _work: there is no module cycle. The
        # opposing dependencies nevertheless form a cycle between child owners.
        assert reverse.dependency_graphs_by_owner[f"workshop.{scope}"] == {
            (left_module, right_module),
            (right_module, left_module),
        }
        reported = violations(reverse)
        assert {v.rule for v in reported} == {"owner-dependency-cycle"}
        assert len(reported) == 1
        assert reported[0].reason == f"{left_module} -> {right_module} -> {left_module}"
        assert establish_ownership_tree(reverse) == reported
    path.write_text("")
    assert establish_ownership_tree(extract(tmp_path, tach=TACH)) == expected


@pytest.mark.parametrize(
    "public_import",
    [
        "from workshop.inventory import Record\n",
        "import workshop.inventory as inventory\nRecord = inventory.Record\n",
        "from ..inventory import Record\n",
    ],
    ids=["absolute", "module-alias", "relative"],
)
def test_owner_can_selectively_publish_its_own_private_definition(
    tmp_path: Path, public_import: str
) -> None:
    write_sources(
        tmp_path,
        {
            "workshop/__init__.py": "",
            "workshop/inventory/__init__.py": (
                "from ._storage.record import _Record as Record\n__all__ = ['Record']\n"
            ),
            "workshop/inventory/_storage/__init__.py": "",
            "workshop/inventory/_storage/record.py": "class _Record: pass\n",
            "workshop/fulfillment/__init__.py": "",
            "workshop/fulfillment/queries.py": public_import,
        },
    )
    architecture = extract(tmp_path, tach=TACH)
    assert owner_of(architecture, "workshop.inventory._storage.record") == "workshop.inventory"
    assert establish_ownership_tree(architecture) == OwnershipTree(
        owner="workshop",
        children=(
            OwnershipTree(owner="workshop.fulfillment"),
            OwnershipTree(owner="workshop.inventory"),
        ),
        dependencies=frozenset({("workshop.fulfillment", "workshop.inventory")}),
    )
    path = tmp_path / "workshop/fulfillment/queries.py"
    path.write_text("from workshop.inventory._storage.record import _Record as Record\n")
    reported = violations(extract(tmp_path, tach=TACH))
    assert {v.rule for v in reported} == {"private-access", "public-surfaces"}
    assert all(v.src == "workshop.fulfillment.queries" and v.line == 1 for v in reported)
    path.write_text(public_import)
    assert violations(extract(tmp_path, tach=TACH)) == []


@pytest.mark.parametrize(
    ("target", "expected_rules"),
    [
        ("workshop.inventory", {"private-access"}),
        ("workshop.inventory._record", {"private-access", "public-surfaces"}),
        ("workshop.fulfillment.child", {"private-access"}),
    ],
    ids=["foreign-private-symbol", "foreign-private-module", "child-private-symbol"],
)
def test_reexport_chain_does_not_erase_an_illegal_import_at_its_origin(
    tmp_path: Path, target: str, expected_rules: set[str]
) -> None:
    write_sources(
        tmp_path,
        {
            "workshop/__init__.py": "",
            "workshop/api.py": "from workshop.fulfillment.commands import Record\n",
            "workshop/inventory/__init__.py": "from ._record import _Record\n",
            "workshop/inventory/_record.py": "class _Record: pass\n",
            "workshop/fulfillment/__init__.py": "",
            "workshop/fulfillment/child/__init__.py": "class _Record: pass\n",
            "workshop/fulfillment/_record.py": "class _Record: pass\n",
            "workshop/fulfillment/_exports.py": "from ._record import _Record as Record\n",
            "workshop/fulfillment/commands.py": (
                "from ._exports import Record\n__all__ = ['Record']\n"
            ),
        },
    )
    baseline = establish_ownership_tree(extract(tmp_path, tach=TACH))
    assert isinstance(baseline, OwnershipTree)
    path = tmp_path / "workshop/fulfillment/_exports.py"
    path.write_text(f"from {target} import _Record as Record\n__all__ = ['Record']\n")
    broken = extract(tmp_path, tach=TACH)
    reported = violations(broken)
    assert {v.rule for v in reported} == expected_rules
    assert all(
        v.src == "workshop.fulfillment._exports" and v.tgt == target and v.line == 1
        for v in reported
    )
    assert establish_ownership_tree(broken) == reported
    path.write_text("from ._record import _Record as Record\n")
    assert establish_ownership_tree(extract(tmp_path, tach=TACH)) == baseline
