"""Check ownership without application roles, test adapters, or sample fixtures.

The source fixtures have no tests/, entries, factories, commands, HTTP, support,
or composition. Graph expectations use a separate topological-elimination oracle.
These are bounded structural checks, not a proof of arbitrary Python programs.
"""

import sys
from dataclasses import replace
from itertools import permutations
from pathlib import Path

import pytest

from bsa_linter.architecture import (
    Architecture,
    ImportEdge,
    OwnershipTree,
    WellFormed,
    cycle_paths,
    establish_ownership_tree,
    lint_architecture,
    owner_of,
)
from bsa_linter.extract import extract

TACH = str(Path(sys.executable).with_name("tach"))


def assert_no_application_roles(architecture: Architecture) -> None:
    assert not (
        architecture.entries
        | architecture.api_entries
        | architecture.routes
        | architecture.support
        | architecture.http_support
        | architecture.composition
    )
    assert not any(
        module == "tests" or module.startswith("tests.") for module in architecture.modules
    )


SOURCES = {
    "atlas/__init__.py": "",
    "atlas/fleet/__init__.py": "from .vehicle import Vehicle\n",
    "atlas/fleet/vehicle.py": "class Vehicle: pass\n",
    "atlas/freight/__init__.py": "from .shipment import Shipment\n",
    "atlas/freight/shipment.py": "class Shipment: pass\n",
    "atlas/freight/_join.py": "from .parcels import Parcel\n",
    "atlas/freight/parcels/__init__.py": "from .parcel import Parcel\n",
    "atlas/freight/parcels/parcel.py": (
        "from atlas.freight import Shipment\nfrom atlas.fleet import Vehicle\nclass Parcel: pass\n"
    ),
    "atlas/freight/parcels/_storage/__init__.py": "",
    "atlas/freight/parcels/_storage/record.py": "class Record: pass\n",
    "atlas/freight/parcels/_work.py": "from ._storage.record import Record\n",
    "atlas/freight/returns/__init__.py": "class Return: pass\n",
    "atlas/freight/returns/_work.py": "",
}
TREE = OwnershipTree(
    owner="atlas",
    dependencies=frozenset({("atlas.freight", "atlas.fleet")}),
    children=(
        OwnershipTree(owner="atlas.fleet"),
        OwnershipTree(
            owner="atlas.freight",
            children=(
                OwnershipTree(owner="atlas.freight.parcels"),
                OwnershipTree(owner="atlas.freight.returns"),
            ),
        ),
    ),
)


def write_library(root: Path) -> None:
    for name, source in SOURCES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def test_plain_library_establishes_ownership_without_application_machinery(tmp_path: Path) -> None:
    write_library(tmp_path)
    architecture = extract(tmp_path, tach=TACH)
    assert_no_application_roles(architecture)
    assert isinstance(lint_architecture(architecture), WellFormed)
    assert establish_ownership_tree(architecture) == TREE
    assert owner_of(architecture, "atlas.freight.parcels._storage.record") == (
        "atlas.freight.parcels"
    )
    # Parent implementation -> child root -> parent vocabulary is legitimate.
    # Containment arrows must not be mixed into the module dependency graph.
    assert {(e.src, e.tgt) for e in architecture.imports} >= {
        ("atlas.freight._join", "atlas.freight.parcels"),
        ("atlas.freight.parcels.parcel", "atlas.freight"),
    }


@pytest.mark.parametrize(
    ("file", "source", "rules"),
    [
        (
            "atlas/freight/_join.py",
            "from .parcels._storage.record import Record\n",
            {"private-access", "public-surfaces"},
        ),
        (
            "atlas/freight/returns/_work.py",
            "from ..parcels._storage.record import Record\n",
            {"private-access", "public-surfaces"},
        ),
        (
            "atlas/freight/parcels/parcel.py",
            "from atlas.fleet.vehicle import Vehicle\nclass Parcel: pass\n",
            {"public-surfaces"},
        ),
        (
            "atlas/freight/__init__.py",
            "from .shipment import Shipment\nfrom .parcels import Parcel\n",
            {"direction", "cycles"},
        ),
        (
            "atlas/freight/parcels/__init__.py",
            "from .parcel import Parcel\nfrom ..returns import Return\n",
            {"direction"},
        ),
        (
            "atlas/freight/parcels/_storage/record.py",
            "from .._work import Record\n",
            {"cycles"},
        ),
    ],
    ids=[
        "parent-cannot-reach-child-private",
        "sibling-cannot-reach-private",
        "foreign-leaf-bypass",
        "parent-reexport-creates-return-edge",
        "root-cannot-reexport-foreign-vocabulary",
        "private-file-cycle",
    ],
)
def test_structural_breaks_still_fail_without_roles_or_tests(
    tmp_path: Path, file: str, source: str, rules: set[str]
) -> None:
    write_library(tmp_path)
    assert establish_ownership_tree(extract(tmp_path, tach=TACH)) == TREE
    path = tmp_path / file
    path.write_text(source)
    architecture = extract(tmp_path, tach=TACH)
    assert_no_application_roles(architecture)
    result = establish_ownership_tree(architecture)
    assert isinstance(result, list)
    assert {finding.rule for finding in result} == rules
    assert lint_architecture(architecture) == result
    path.write_text(SOURCES[file])
    assert establish_ownership_tree(extract(tmp_path, tach=TACH)) == TREE


def test_selective_reexport_and_private_folder_do_not_create_a_new_owner(tmp_path: Path) -> None:
    write_library(tmp_path)
    root = tmp_path / "atlas/freight/parcels/__init__.py"
    root.write_text(root.read_text() + "from ._storage.record import Record\n")
    (tmp_path / "atlas/freight/_join.py").write_text("from .parcels import Record\n")
    architecture = extract(tmp_path, tach=TACH)
    assert_no_application_roles(architecture)
    assert establish_ownership_tree(architecture) == TREE
    assert "atlas.freight.parcels._storage" not in architecture.packages


def acyclic_by_elimination(nodes: tuple[str, ...], edges: set[tuple[str, str]]) -> bool:
    """Independent oracle: repeatedly remove nodes with no incoming edges (not DFS)."""
    remaining = set(nodes)
    while remaining:
        incoming = {target for source, target in edges if source in remaining}
        removable = remaining - incoming
        if not removable:
            return False
        remaining -= removable
    return True


def edge_subsets(nodes: tuple[str, ...]):
    possible = tuple(permutations(nodes, 2))
    for mask in range(1 << len(possible)):
        yield {edge for bit, edge in enumerate(possible) if mask & (1 << bit)}


def test_cycle_detector_matches_independent_oracle_for_every_four_node_graph() -> None:
    nodes = ("a", "b", "c", "d")
    # All 4,096 directed graphs without self edges, including disconnected
    # components, overlapping cycles, diamonds, chains, and isolated vertices.
    for edges in edge_subsets(nodes):
        cycles = cycle_paths(edges)
        assert bool(cycles) is not acyclic_by_elimination(nodes, edges), edges
        for cycle in cycles:
            assert cycle[0] == cycle[-1]
            assert all(edge in edges for edge in zip(cycle, cycle[1:], strict=False))


@pytest.mark.parametrize("scope", ["atlas", "atlas.freight", "atlas.freight.parcels"])
def test_every_three_owner_graph_collapses_descendants_at_the_correct_scope(scope: str) -> None:
    ancestors = {".".join(scope.split(".")[:i]) for i in range(1, len(scope.split(".")) + 1)}
    owners = tuple(f"{scope}.{name}" for name in ("east", "north", "west"))
    packages = ancestors | set(owners) | {f"{owner}.detail" for owner in owners}
    modules = packages | {f"{owner}.detail._work" for owner in owners}
    baseline = Architecture(
        namespace="atlas",
        modules=frozenset(modules),
        packages=frozenset(packages),
        boundaries=frozenset(packages - {"atlas"}),
        entries=frozenset(),
        api_entries=frozenset(),
        routes=frozenset(),
        support=frozenset(),
        http_support=frozenset(),
        composition=frozenset(),
    )
    for edges in edge_subsets(owners):
        # Roots have no outgoing imports, so these files cannot form a module
        # cycle. Cycles appear only when descendants collapse to sibling owners.
        architecture = replace(
            baseline,
            imports=tuple(
                ImportEdge(f"{source}.detail._work", target, "Item")
                for source, target in sorted(edges)
            ),
        )
        assert_no_application_roles(architecture)
        graphs = architecture.dependency_graphs_by_owner
        assert graphs[scope] == edges
        assert all(not graph for owner, graph in graphs.items() if owner != scope)
        result = establish_ownership_tree(architecture)
        if acyclic_by_elimination(owners, edges):
            assert isinstance(result, OwnershipTree), edges
            assert isinstance(lint_architecture(architecture), WellFormed)
        else:
            assert isinstance(result, list), edges
            assert {finding.rule for finding in result} == {"owner-dependency-cycle"}, edges
            assert lint_architecture(architecture) == result


def test_ordinary_name_changes_do_not_change_structural_results(tmp_path: Path) -> None:
    write_library(tmp_path)
    original = extract(tmp_path, tach=TACH)
    assert_no_application_roles(original)

    # These are ordinary names, not reserved Python profile names.
    def rename(name: str) -> str:
        replacements = {"atlas": "harbor", "freight": "cargo", "parcels": "packages"}
        return ".".join(replacements.get(part, part) for part in name.split("."))

    renamed = replace(
        original,
        namespace=rename(original.namespace),
        modules=frozenset(map(rename, original.modules)),
        packages=frozenset(map(rename, original.packages)),
        boundaries=frozenset(map(rename, original.boundaries)),
        imports=tuple(replace(e, src=rename(e.src), tgt=rename(e.tgt)) for e in original.imports),
    )
    assert isinstance(lint_architecture(renamed), WellFormed)
    assert renamed.owner_dependencies == {
        (rename(source), rename(target)) for source, target in original.owner_dependencies
    }
    for module in original.modules:
        owner = owner_of(original, module)
        assert owner is not None
        assert owner_of(renamed, rename(module)) == rename(owner)
