"""Ownership tree establishment: self-contained, illustrative Folio scenarios.

This fixture extends the lending-library domain with child owners for borrowing,
eligibility, limits, history, editions, and titles. It is a source-only example,
not the runnable Folio sample. Each case returns an OwnershipTree or violations.
"""

import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from bsa_linter.architecture import (
    OwnershipTree,
    Violation,
    establish_ownership_tree,
    owner_of,
)
from bsa_linter.cli import main as cli_main
from bsa_linter.extract import extract

TACH = str(Path(sys.executable).with_name("tach"))
UNBOUNDED_FOLIO = Path(__file__).resolve().parents[2] / "samples/folio-unbounded"

# Folio source fixture and the complete expected ownership tree.

FOLIO_SOURCES = {
    "folio/__init__.py": "",
    "folio/loans/__init__.py": "class LoanId: pass\n",
    "folio/loans/borrowing/__init__.py": "from .request import BorrowingRequest\n",
    "folio/loans/borrowing/request.py": (
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True)\n"
        "class BorrowingRequest:\n"
        "    book_id: str\n"
        "    borrower: str\n"
        "    requested_days: int\n"
    ),
    "folio/loans/borrowing/eligibility/__init__.py": "class EligibilityDecision: pass\n",
    "folio/loans/borrowing/limits/__init__.py": "class BorrowingLimit: pass\n",
    "folio/loans/history/__init__.py": "class LoanRecord: pass\n",
    "folio/catalog/__init__.py": "class BookId: pass\n",
    "folio/catalog/editions/__init__.py": "class Edition: pass\n",
    "folio/catalog/titles/__init__.py": "class Title: pass\n",
    "folio/loans/borrowing/eligibility/check.py": (
        "from folio.loans.borrowing import BorrowingRequest\n"
        "from folio.loans.borrowing.limits import BorrowingLimit\n"
    ),
    "folio/loans/borrowing/limits/policy.py": (
        "from folio.loans.borrowing import BorrowingRequest\n"
        "from folio.loans.history import LoanRecord\n"
    ),
    "folio/loans/history/record.py": "from folio.catalog.editions import Edition\n",
    "folio/catalog/editions/edition.py": "from folio.catalog.titles import Title\n",
    "folio/catalog/titles/title.py": "class Title: pass\n",
}

FOLIO_DEPENDENCIES_BY_OWNER = {
    "folio": frozenset({("folio.loans", "folio.catalog")}),
    "folio.catalog": frozenset({("folio.catalog.editions", "folio.catalog.titles")}),
    "folio.loans": frozenset({("folio.loans.borrowing", "folio.loans.history")}),
    "folio.loans.borrowing": frozenset(
        {("folio.loans.borrowing.eligibility", "folio.loans.borrowing.limits")}
    ),
}


def write_sources(root: Path, sources: dict[str, str]) -> Path:
    for name, content in sources.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return root


def folio_tree(root: Path, changes: dict[str, str] | None = None) -> Path:
    return write_sources(root, FOLIO_SOURCES | (changes or {}))


# Explicit expected containment and dependencies; do not derive these from sources.
@pytest.mark.parametrize("source", ["folio/api.py", "folio/loans/borrowing/check.py"])
@pytest.mark.parametrize("target", ["tests", "tests.helpers", "tests.missing"])
def test_production_cannot_import_test_code(tmp_path: Path, source: str, target: str) -> None:
    root = folio_tree(
        tmp_path,
        {
            "tests/__init__.py": "book = None\n",
            "tests/helpers.py": "book = None\n",
            source: f"from {target} import book\n",
        },
    )
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert isinstance(result, list)
    assert (
        Violation(
            rule="ownership",
            src=source.removesuffix(".py").replace("/", "."),
            tgt=target,
            reason="Production source depends on test code",
            file=source,
            line=1,
        )
        in result
    )


FOLIO_OWNERSHIP_TREE = OwnershipTree(
    owner="folio",
    dependencies=frozenset({("folio.loans", "folio.catalog")}),
    children=(
        OwnershipTree(
            owner="folio.catalog",
            dependencies=frozenset({("folio.catalog.editions", "folio.catalog.titles")}),
            children=(
                OwnershipTree(owner="folio.catalog.editions"),
                OwnershipTree(owner="folio.catalog.titles"),
            ),
        ),
        OwnershipTree(
            owner="folio.loans",
            dependencies=frozenset({("folio.loans.borrowing", "folio.loans.history")}),
            children=(
                OwnershipTree(
                    owner="folio.loans.borrowing",
                    dependencies=frozenset(
                        {("folio.loans.borrowing.eligibility", "folio.loans.borrowing.limits")}
                    ),
                    children=(
                        OwnershipTree(owner="folio.loans.borrowing.eligibility"),
                        OwnershipTree(owner="folio.loans.borrowing.limits"),
                    ),
                ),
                OwnershipTree(owner="folio.loans.history"),
            ),
        ),
    ),
)


# Successful establishment: assert the returned tree.


def test_folio_returns_the_complete_ownership_tree(tmp_path: Path) -> None:
    architecture = extract(folio_tree(tmp_path), tach=TACH)

    result = establish_ownership_tree(architecture)

    assert result == FOLIO_OWNERSHIP_TREE
    assert architecture.owner_dependencies == {("folio.loans", "folio.catalog")}
    assert architecture.dependency_graphs_by_owner == FOLIO_DEPENDENCIES_BY_OWNER
    assert owner_of(architecture, "folio.loans.borrowing.eligibility.check") == (
        "folio.loans.borrowing.eligibility"
    )


def test_eligibility_and_limits_use_the_parent_borrowing_anchor(tmp_path: Path) -> None:
    architecture = extract(folio_tree(tmp_path), tach=TACH)

    assert establish_ownership_tree(architecture) == FOLIO_OWNERSHIP_TREE
    assert owner_of(architecture, "folio.loans.borrowing.request") == "folio.loans.borrowing"
    assert {
        (edge.src, edge.tgt) for edge in architecture.imports if edge.symbol == "BorrowingRequest"
    } == {
        ("folio.loans.borrowing", "folio.loans.borrowing.request"),
        ("folio.loans.borrowing.eligibility.check", "folio.loans.borrowing"),
        ("folio.loans.borrowing.limits.policy", "folio.loans.borrowing"),
    }
    # The anchor's only import is the standard-library dataclass decorator.
    assert {
        (edge.tgt, edge.symbol)
        for edge in architecture.imports
        if edge.src == "folio.loans.borrowing.request"
    } == {("dataclasses", "dataclass")}


def test_eligibility_cannot_bypass_the_parent_borrowing_surface(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/borrowing/eligibility/request.py": (
                    "from folio.loans.borrowing.request import BorrowingRequest\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="public-surfaces",
            src="folio.loans.borrowing.eligibility.request",
            tgt="folio.loans.borrowing.request",
            reason=(
                "folio.loans.borrowing.eligibility.request -> folio.loans.borrowing.request: "
                "Foreign concept leaf/private module bypasses its public surface"
            ),
            file="folio/loans/borrowing/eligibility/request.py",
            line=1,
        )
    ]


def test_removing_imports_preserves_ownership_but_removes_dependencies(tmp_path: Path) -> None:
    architecture = extract(folio_tree(tmp_path), tach=TACH)
    result = establish_ownership_tree(replace(architecture, imports=()))

    assert isinstance(result, OwnershipTree)
    assert result.owner == "folio"
    assert [child.owner for child in result.children] == ["folio.catalog", "folio.loans"]
    assert result.children[1].children[0].children == (
        OwnershipTree(owner="folio.loans.borrowing.eligibility"),
        OwnershipTree(owner="folio.loans.borrowing.limits"),
    )
    assert replace(architecture, imports=()).dependency_graphs_by_owner == {
        "folio": frozenset(),
        "folio.catalog": frozenset(),
        "folio.loans": frozenset(),
        "folio.loans.borrowing": frozenset(),
    }


@pytest.mark.parametrize(
    "edition_import",
    [
        pytest.param("from folio.catalog.editions import Edition\n", id="public-symbol"),
        pytest.param("import folio.catalog.editions\n", id="qualified-module"),
        pytest.param("import folio.catalog.editions as editions\n", id="module-alias"),
        pytest.param("from folio.catalog import editions\n", id="child-module"),
        pytest.param("from ....catalog.editions import Edition\n", id="relative-import"),
    ],
)
def test_eligibility_can_use_catalog_editions_without_changing_internal_ownership(
    tmp_path: Path, edition_import: str
) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/loans/borrowing/eligibility/edition.py": edition_import}),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == FOLIO_OWNERSHIP_TREE


def test_dependencies_are_directed_and_do_not_include_transitive_imports(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/members/__init__.py": "class MemberId: pass\n",
                "folio/members/borrowing.py": "from folio.loans import LoanId\n",
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == replace(
        FOLIO_OWNERSHIP_TREE,
        children=FOLIO_OWNERSHIP_TREE.children + (OwnershipTree(owner="folio.members"),),
        dependencies=frozenset(
            {("folio.members", "folio.loans"), ("folio.loans", "folio.catalog")}
        ),
    )


def test_imports_from_descendants_collapse_to_their_top_level_owners(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/members/__init__.py": "class MemberId: pass\n",
                "folio/members/reading/__init__.py": "class ReadingHistory: pass\n",
                "folio/members/reading/history.py": (
                    "from folio.loans import LoanId\nfrom folio.catalog import BookId\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == replace(
        FOLIO_OWNERSHIP_TREE,
        children=FOLIO_OWNERSHIP_TREE.children
        + (
            OwnershipTree(
                owner="folio.members", children=(OwnershipTree(owner="folio.members.reading"),)
            ),
        ),
        dependencies=frozenset(
            {
                ("folio.loans", "folio.catalog"),
                ("folio.members", "folio.loans"),
                ("folio.members", "folio.catalog"),
            }
        ),
    )


def test_duplicate_edition_imports_do_not_duplicate_dependencies(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/history/edition.py": (
                    "from folio.catalog.editions import Edition\n"
                    "from folio.catalog.editions import Edition as BorrowedEdition\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == FOLIO_OWNERSHIP_TREE


def test_isolated_notifications_and_same_owner_imports_preserve_the_tree(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/borrowing/eligibility/decision.py": (
                    "class EligibilityDecision:\n    pass\n"
                ),
                "folio/loans/borrowing/eligibility/review.py": (
                    "from .decision import EligibilityDecision\n"
                ),
                "folio/notifications/__init__.py": "",
                "folio/notifications/reminders/__init__.py": "class DueDateReminder: pass\n",
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == replace(
        FOLIO_OWNERSHIP_TREE,
        children=FOLIO_OWNERSHIP_TREE.children
        + (
            OwnershipTree(
                owner="folio.notifications",
                children=(OwnershipTree(owner="folio.notifications.reminders"),),
            ),
        ),
    )


def test_support_and_entries_have_owners_but_do_not_become_business_dependencies(
    tmp_path: Path,
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                ".importlinter": "Not a graph or even valid configuration.\n",
                "folio/foundation/__init__.py": "class Clock: pass\n",
                "folio/foundation/_clock/__init__.py": "",
                "folio/bootstrap/__init__.py": "",
                "folio/bootstrap/wiring.py": (
                    "from folio.loans.borrowing import BorrowingRequest\n"
                ),
                "folio/api_support/__init__.py": "",
                "folio/api.py": "from folio.loans.borrowing import BorrowingRequest\n",
                "tests/__init__.py": "",
                "tests/test_titles.py": "from folio.catalog.titles import Title\n",
                "folio/loans/history/clock.py": (
                    "from folio.foundation import Clock\nfrom pathlib import Path\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert architecture.dependency_graphs_by_owner == FOLIO_DEPENDENCIES_BY_OWNER
    assert establish_ownership_tree(architecture) == replace(
        FOLIO_OWNERSHIP_TREE,
        children=(
            OwnershipTree(owner="folio.api"),
            OwnershipTree(owner="folio.api_support"),
            OwnershipTree(owner="folio.bootstrap"),
            FOLIO_OWNERSHIP_TREE.children[0],
            OwnershipTree(owner="folio.foundation"),
            FOLIO_OWNERSHIP_TREE.children[1],
        ),
    )


# Forbidden connections: assert returned violations and observed dependencies.


@dataclass(frozen=True)
class ForbiddenImport:
    source_file: str
    source_module: str
    import_statement: str
    target_module: str
    replaced_import_file: str
    expected_rules: frozenset[str]


@pytest.mark.parametrize(
    "connection",
    [
        pytest.param(
            ForbiddenImport(
                source_file="folio/loans/borrowing/eligibility/title.py",
                source_module="folio.loans.borrowing.eligibility.title",
                import_statement="from folio.catalog.titles.title import Title\n",
                target_module="folio.catalog.titles.title",
                replaced_import_file="folio/loans/history/record.py",
                expected_rules=frozenset({"public-surfaces"}),
            ),
            id="eligibility-bypasses-public-title-surface",
        ),
        pytest.param(
            ForbiddenImport(
                source_file="folio/loans/borrowing/eligibility/title.py",
                source_module="folio.loans.borrowing.eligibility.title",
                import_statement="from folio.catalog.titles._index import TitleIndex\n",
                target_module="folio.catalog.titles._index",
                replaced_import_file="folio/loans/history/record.py",
                expected_rules=frozenset({"private-access", "public-surfaces"}),
            ),
            id="eligibility-accesses-private-catalog-index",
        ),
        pytest.param(
            ForbiddenImport(
                source_file="folio/loans/borrowing/eligibility/quota.py",
                source_module="folio.loans.borrowing.eligibility.quota",
                import_statement="from folio.loans.borrowing.limits._quota import Quota\n",
                target_module="folio.loans.borrowing.limits._quota",
                replaced_import_file="folio/loans/borrowing/eligibility/check.py",
                expected_rules=frozenset({"private-access", "public-surfaces"}),
            ),
            id="eligibility-accesses-private-sibling-quota",
        ),
        pytest.param(
            ForbiddenImport(
                source_file="folio/loans/borrowing/request.py",
                source_module="folio.loans.borrowing.request",
                import_statement="from folio.loans.borrowing.limits import BorrowingLimit\n",
                target_module="folio.loans.borrowing.limits",
                replaced_import_file="folio/loans/borrowing/request.py",
                expected_rules=frozenset({"direction"}),
            ),
            id="borrowing-anchor-imports-child-limit",
        ),
        pytest.param(
            ForbiddenImport(
                source_file="folio/loans/borrowing/request.py",
                source_module="folio.loans.borrowing.request",
                import_statement="from folio.loans.borrowing.limits._quota import Quota\n",
                target_module="folio.loans.borrowing.limits._quota",
                replaced_import_file="folio/loans/borrowing/request.py",
                expected_rules=frozenset({"private-access", "public-surfaces", "direction"}),
            ),
            id="borrowing-anchor-accesses-private-child-quota",
        ),
    ],
)
def test_forbidden_folio_import_returns_violations(
    tmp_path: Path, connection: ForbiddenImport
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/titles/_index.py": "class TitleIndex: pass\n",
                "folio/loans/borrowing/limits/_quota.py": "class Quota: pass\n",
                # The forbidden import is the only evidence for its dependency.
                connection.replaced_import_file: "",
                connection.source_file: "# Forbidden connection\n" + connection.import_statement,
            },
        ),
        tach=TACH,
    )

    result = establish_ownership_tree(architecture)

    assert isinstance(result, list)
    assert {(v.rule, v.src, v.tgt, v.file, v.line) for v in result} == {
        (rule, connection.source_module, connection.target_module, connection.source_file, 2)
        for rule in connection.expected_rules
    }
    assert architecture.dependency_graphs_by_owner == FOLIO_DEPENDENCIES_BY_OWNER


def test_dynamic_catalog_import_returns_an_extraction_violation(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/borrowing/eligibility/catalog.py": (
                    "catalog = __import__('folio.catalog')\n"
                ),
            },
        ),
        tach=TACH,
    )
    result = establish_ownership_tree(architecture)

    assert isinstance(result, list)
    assert [(v.rule, v.file, v.line, v.reason) for v in result] == [
        (
            "explicit-imports",
            "folio/loans/borrowing/eligibility/catalog.py",
            1,
            "Unsupported dynamic dependency mechanism: __import__",
        )
    ]
    assert architecture.dependency_graphs_by_owner == FOLIO_DEPENDENCIES_BY_OWNER


# Dependency cycles at each level of ownership.


@dataclass(frozen=True)
class ReverseDependency:
    source_file: str
    import_statement: str
    owner: str
    expected_dependencies: frozenset[tuple[str, str]]
    expected_violation: Violation


@pytest.mark.parametrize(
    "connection",
    [
        pytest.param(
            ReverseDependency(
                source_file="folio/catalog/titles/loan_history.py",
                import_statement="from folio.loans.history import LoanRecord\n",
                owner="folio",
                expected_dependencies=frozenset(
                    {("folio.catalog", "folio.loans"), ("folio.loans", "folio.catalog")}
                ),
                expected_violation=Violation(
                    rule="owner-dependency-cycle",
                    src="folio.catalog",
                    tgt="folio.catalog",
                    reason="folio.catalog -> folio.loans -> folio.catalog",
                    file="folio/catalog/__init__.py",
                    line=1,
                ),
            ),
            id="catalog-depends-back-on-loans",
        ),
        pytest.param(
            ReverseDependency(
                source_file="folio/loans/history/borrowing.py",
                import_statement="from folio.loans.borrowing import BorrowingRequest\n",
                owner="folio.loans",
                expected_dependencies=frozenset(
                    {
                        ("folio.loans.borrowing", "folio.loans.history"),
                        ("folio.loans.history", "folio.loans.borrowing"),
                    }
                ),
                expected_violation=Violation(
                    rule="owner-dependency-cycle",
                    src="folio.loans.borrowing",
                    tgt="folio.loans.borrowing",
                    reason="folio.loans.borrowing -> folio.loans.history -> folio.loans.borrowing",
                    file="folio/loans/borrowing/__init__.py",
                    line=1,
                ),
            ),
            id="loan-history-depends-back-on-borrowing",
        ),
        pytest.param(
            ReverseDependency(
                source_file="folio/loans/borrowing/limits/eligibility.py",
                import_statement=(
                    "from folio.loans.borrowing.eligibility import EligibilityDecision\n"
                ),
                owner="folio.loans.borrowing",
                expected_dependencies=frozenset(
                    {
                        ("folio.loans.borrowing.eligibility", "folio.loans.borrowing.limits"),
                        ("folio.loans.borrowing.limits", "folio.loans.borrowing.eligibility"),
                    }
                ),
                expected_violation=Violation(
                    rule="owner-dependency-cycle",
                    src="folio.loans.borrowing.eligibility",
                    tgt="folio.loans.borrowing.eligibility",
                    reason=(
                        "folio.loans.borrowing.eligibility -> folio.loans.borrowing.limits -> "
                        "folio.loans.borrowing.eligibility"
                    ),
                    file="folio/loans/borrowing/eligibility/__init__.py",
                    line=1,
                ),
            ),
            id="borrowing-limits-depend-back-on-eligibility",
        ),
    ],
)
def test_reverse_dependency_returns_the_exact_cycle_violation(
    tmp_path: Path, connection: ReverseDependency
) -> None:
    architecture = extract(
        folio_tree(tmp_path, {connection.source_file: connection.import_statement}), tach=TACH
    )

    assert establish_ownership_tree(architecture) == [connection.expected_violation]
    assert architecture.dependency_graphs_by_owner == FOLIO_DEPENDENCIES_BY_OWNER | {
        connection.owner: connection.expected_dependencies
    }


@dataclass(frozen=True)
class CircularDependencies:
    owner: str
    source_files: dict[str, str]
    expected_path: str


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            CircularDependencies(
                owner="folio",
                source_files={
                    "folio/catalog/recommendations.py": "import folio.members\n",
                    "folio/members/borrowing.py": "import folio.loans\n",
                    "folio/loans/edition.py": "import folio.catalog\n",
                },
                expected_path="folio.catalog -> folio.members -> folio.loans -> folio.catalog",
            ),
            id="catalog-members-and-loans",
        ),
        pytest.param(
            CircularDependencies(
                owner="folio.loans",
                source_files={
                    "folio/loans/borrowing/history.py": "import folio.loans.history\n",
                    "folio/loans/history/renewal.py": "import folio.loans.renewals\n",
                    "folio/loans/renewals/borrowing.py": "import folio.loans.borrowing\n",
                },
                expected_path=(
                    "folio.loans.borrowing -> folio.loans.history -> folio.loans.renewals -> "
                    "folio.loans.borrowing"
                ),
            ),
            id="borrowing-history-and-renewals",
        ),
        pytest.param(
            CircularDependencies(
                owner="folio.loans.borrowing",
                source_files={
                    "folio/loans/borrowing/eligibility/limit.py": (
                        "import folio.loans.borrowing.limits\n"
                    ),
                    "folio/loans/borrowing/limits/reservation.py": (
                        "import folio.loans.borrowing.reservations\n"
                    ),
                    "folio/loans/borrowing/reservations/eligibility.py": (
                        "import folio.loans.borrowing.eligibility\n"
                    ),
                },
                expected_path=(
                    "folio.loans.borrowing.eligibility -> folio.loans.borrowing.limits -> "
                    "folio.loans.borrowing.reservations -> folio.loans.borrowing.eligibility"
                ),
            ),
            id="eligibility-limits-and-reservations",
        ),
        pytest.param(
            CircularDependencies(
                owner="folio.loans.borrowing.eligibility.membership",
                source_files={
                    "folio/loans/borrowing/eligibility/membership/expiry/renewal.py": (
                        "import folio.loans.borrowing.eligibility.membership.renewals\n"
                    ),
                    "folio/loans/borrowing/eligibility/membership/renewals/suspension.py": (
                        "import folio.loans.borrowing.eligibility.membership.suspensions\n"
                    ),
                    "folio/loans/borrowing/eligibility/membership/suspensions/expiry.py": (
                        "import folio.loans.borrowing.eligibility.membership.expiry\n"
                    ),
                },
                expected_path=(
                    "folio.loans.borrowing.eligibility.membership.expiry -> "
                    "folio.loans.borrowing.eligibility.membership.renewals -> "
                    "folio.loans.borrowing.eligibility.membership.suspensions -> "
                    "folio.loans.borrowing.eligibility.membership.expiry"
                ),
            ),
            id="deep-membership-expiry-renewals-and-suspensions",
        ),
    ],
)
def test_three_owner_cycle_is_reported_at_each_depth(
    tmp_path: Path, scenario: CircularDependencies
) -> None:
    sources = dict(scenario.source_files)
    for source_file in scenario.source_files:
        for directory in Path(source_file).parents:
            if directory != Path("."):
                sources[str(directory / "__init__.py")] = ""
    architecture = extract(write_sources(tmp_path, sources), tach=TACH)
    cycle_start = scenario.expected_path.split(" -> ")[0]

    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="owner-dependency-cycle",
            src=cycle_start,
            tgt=cycle_start,
            reason=scenario.expected_path,
            file=cycle_start.replace(".", "/") + "/__init__.py",
            line=1,
        )
    ]
    assert {owner for owner, edges in architecture.dependency_graphs_by_owner.items() if edges} == {
        scenario.owner
    }


def test_independent_catalog_and_loan_cycles_are_all_returned(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/history/borrowing.py": (
                    "from folio.loans.borrowing import BorrowingRequest\n"
                ),
                "folio/loans/borrowing/limits/eligibility.py": (
                    "from folio.loans.borrowing.eligibility import EligibilityDecision\n"
                ),
                "folio/catalog/titles/edition.py": "from folio.catalog.editions import Edition\n",
            },
        ),
        tach=TACH,
    )
    result = establish_ownership_tree(architecture)

    assert isinstance(result, list)
    assert architecture.owner_dependencies == {("folio.loans", "folio.catalog")}
    assert {(v.rule, v.reason) for v in result} == {
        (
            "owner-dependency-cycle",
            "folio.catalog.editions -> folio.catalog.titles -> folio.catalog.editions",
        ),
        (
            "owner-dependency-cycle",
            "folio.loans.borrowing -> folio.loans.history -> folio.loans.borrowing",
        ),
        (
            "owner-dependency-cycle",
            "folio.loans.borrowing.eligibility -> folio.loans.borrowing.limits -> "
            "folio.loans.borrowing.eligibility",
        ),
    }


def test_cycle_inside_eligibility_is_a_file_cycle_not_an_ownership_cycle(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/borrowing/eligibility/decision.py": (
                    "from .review import EligibilityReview\n"
                ),
                "folio/loans/borrowing/eligibility/review.py": (
                    "from .decision import EligibilityDecision\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="cycles",
            src="folio.loans.borrowing.eligibility.decision",
            tgt="folio.loans.borrowing.eligibility.decision",
            reason=(
                "folio.loans.borrowing.eligibility.decision -> "
                "folio.loans.borrowing.eligibility.review -> "
                "folio.loans.borrowing.eligibility.decision"
            ),
            file="folio/loans/borrowing/eligibility/decision.py",
            line=1,
        )
    ]
    assert architecture.dependency_graphs_by_owner == FOLIO_DEPENDENCIES_BY_OWNER


def test_reordering_imports_does_not_change_the_returned_cycle(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/loans/borrowing/limits/eligibility.py": (
                    "from folio.loans.borrowing.eligibility import EligibilityDecision\n"
                ),
            },
        ),
        tach=TACH,
    )
    reordered = replace(architecture, imports=tuple(reversed(architecture.imports)))
    result = establish_ownership_tree(architecture)

    assert isinstance(result, list)
    assert establish_ownership_tree(reordered) == result
    assert reordered.dependency_graphs_by_owner == architecture.dependency_graphs_by_owner


# CLI presentation uses the same concrete Folio cases and returned structure.


@dataclass(frozen=True)
class EstablishmentScenario:
    source_changes: dict[str, str]
    expected_violations: tuple[Violation, ...] = ()


@pytest.mark.parametrize("json_output", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("show_tree", [False, True], ids=["findings-only", "with-tree"])
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(EstablishmentScenario(source_changes={}), id="valid-folio"),
        pytest.param(
            EstablishmentScenario(
                source_changes={
                    "folio/loans/borrowing/limits/eligibility.py": (
                        "from folio.loans.borrowing.eligibility import EligibilityDecision\n"
                    ),
                },
                expected_violations=(
                    Violation(
                        rule="owner-dependency-cycle",
                        src="folio.loans.borrowing.eligibility",
                        tgt="folio.loans.borrowing.eligibility",
                        reason=(
                            "folio.loans.borrowing.eligibility -> folio.loans.borrowing.limits -> "
                            "folio.loans.borrowing.eligibility"
                        ),
                        file="folio/loans/borrowing/eligibility/__init__.py",
                        line=1,
                    ),
                ),
            ),
            id="limits-depend-back-on-eligibility",
        ),
        pytest.param(
            EstablishmentScenario(
                source_changes={
                    "folio/catalog/titles/_index.py": "class TitleIndex: pass\n",
                    "folio/loans/borrowing/eligibility/title.py": (
                        "# Forbidden catalog access\n"
                        "from folio.catalog.titles._index import TitleIndex\n"
                    ),
                },
                expected_violations=(
                    Violation(
                        rule="public-surfaces",
                        src="folio.loans.borrowing.eligibility.title",
                        tgt="folio.catalog.titles._index",
                        reason=(
                            "folio.loans.borrowing.eligibility.title -> "
                            "folio.catalog.titles._index: "
                            "Foreign concept leaf/private module bypasses its public surface"
                        ),
                        file="folio/loans/borrowing/eligibility/title.py",
                        line=2,
                    ),
                    Violation(
                        rule="private-access",
                        src="folio.loans.borrowing.eligibility.title",
                        tgt="folio.catalog.titles._index",
                        reason=(
                            "folio.loans.borrowing.eligibility.title -> "
                            "folio.catalog.titles._index: "
                            "Foreign owner accesses a private implementation"
                        ),
                        file="folio/loans/borrowing/eligibility/title.py",
                        line=2,
                    ),
                ),
            ),
            id="eligibility-accesses-private-title-index",
        ),
        pytest.param(
            EstablishmentScenario(
                source_changes={
                    "folio/loans/borrowing/eligibility/catalog.py": (
                        "catalog = __import__('folio.catalog')\n"
                    ),
                },
                expected_violations=(
                    Violation(
                        rule="explicit-imports",
                        src="folio.loans.borrowing.eligibility.catalog",
                        tgt="folio.loans.borrowing.eligibility.catalog",
                        reason="Unsupported dynamic dependency mechanism: __import__",
                        file="folio/loans/borrowing/eligibility/catalog.py",
                        line=1,
                    ),
                ),
            ),
            id="dynamic-catalog-import",
        ),
    ],
)
def test_cli_returns_the_folio_tree_or_violations(
    tmp_path: Path, json_output: bool, show_tree: bool, scenario: EstablishmentScenario
) -> None:
    root = folio_tree(tmp_path, scenario.source_changes)
    command = [sys.executable, "-m", "bsa_linter.cli", "--root", str(root)]
    if json_output:
        command.append("--json")
    if show_tree:
        command.append("--ownership-tree")
    result = subprocess.run(command, text=True, capture_output=True, check=False)

    assert result.returncode == int(bool(scenario.expected_violations)), result.stderr
    assert result.stderr == ""
    if json_output:
        expected_payload: dict[str, object] = {
            "pass": not scenario.expected_violations,
            "violations": [v.to_dict() for v in scenario.expected_violations],
        }
        if show_tree and not scenario.expected_violations:
            expected_payload["ownership_tree"] = FOLIO_OWNERSHIP_TREE.to_dict()
        assert json.loads(result.stdout) == expected_payload
    elif scenario.expected_violations:
        expected_lines = [
            f"BSA profile failed with {len(scenario.expected_violations)} violation(s). "
            "Review each finding against the project's architecture."
        ]
        expected_lines.extend(
            f"{v.file}:{v.line}: {v.rule}: {v.reason}" for v in scenario.expected_violations
        )
        assert result.stdout == "\n".join(expected_lines) + "\n"
    elif show_tree:
        assert result.stdout == (
            "Ownership tree establishment:\n"
            "folio\n"
            "  imports: folio.loans -> folio.catalog\n"
            "  folio.catalog\n"
            "    imports: folio.catalog.editions -> folio.catalog.titles\n"
            "    folio.catalog.editions\n"
            "    folio.catalog.titles\n"
            "  folio.loans\n"
            "    imports: folio.loans.borrowing -> folio.loans.history\n"
            "    folio.loans.borrowing\n"
            "      imports: folio.loans.borrowing.eligibility -> folio.loans.borrowing.limits\n"
            "      folio.loans.borrowing.eligibility\n"
            "      folio.loans.borrowing.limits\n"
            "    folio.loans.history\n"
            "OK\n"
        )
    else:
        assert result.stdout == "OK\n"


# Shared support may be a module, a package of modules, or nested owned packages.


@dataclass(frozen=True)
class SupportLayout:
    source_files: dict[str, str]
    support_module: str
    support_owner: str
    consumer_import: str
    expected_support_tree: OwnershipTree


SUPPORT_LAYOUTS = [
    pytest.param(
        SupportLayout(
            source_files={"folio/shared.py": "class Clock: pass\n"},
            support_module="folio.shared",
            support_owner="folio.shared",
            consumer_import="from folio.shared import Clock\n",
            expected_support_tree=OwnershipTree(owner="folio.shared"),
        ),
        id="shared-module",
    ),
    pytest.param(
        SupportLayout(
            source_files={"folio/foundation.py": "class Clock: pass\n"},
            support_module="folio.foundation",
            support_owner="folio.foundation",
            consumer_import="from folio.foundation import Clock\n",
            expected_support_tree=OwnershipTree(owner="folio.foundation"),
        ),
        id="foundation-module",
    ),
    pytest.param(
        SupportLayout(
            source_files={
                "folio/shared/__init__.py": "from .clock import Clock\n",
                "folio/shared/clock.py": (
                    "from .identifiers import Identifier\nclass Clock: pass\n"
                ),
                "folio/shared/identifiers.py": "class Identifier: pass\n",
            },
            support_module="folio.shared.clock",
            support_owner="folio.shared",
            consumer_import="from folio.shared import Clock\n",
            expected_support_tree=OwnershipTree(owner="folio.shared"),
        ),
        id="shared-package-with-clock-and-identifiers",
    ),
    pytest.param(
        SupportLayout(
            source_files={
                "folio/foundation/__init__.py": "from .clock import Clock\n",
                "folio/foundation/clock.py": (
                    "from .identifiers import Identifier\nclass Clock: pass\n"
                ),
                "folio/foundation/identifiers.py": "class Identifier: pass\n",
            },
            support_module="folio.foundation.clock",
            support_owner="folio.foundation",
            consumer_import="from folio.foundation import Clock\n",
            expected_support_tree=OwnershipTree(owner="folio.foundation"),
        ),
        id="foundation-package-with-clock-and-identifiers",
    ),
    pytest.param(
        SupportLayout(
            source_files={
                "folio/foundation/__init__.py": "",
                "folio/foundation/clock/__init__.py": "class Clock: pass\n",
                "folio/foundation/clock/timestamp.py": (
                    "from folio.foundation.identifiers import Identifier\n"
                ),
                "folio/foundation/identifiers/__init__.py": "class Identifier: pass\n",
            },
            support_module="folio.foundation.clock.timestamp",
            support_owner="folio.foundation.clock",
            consumer_import="from folio.foundation.clock import Clock\n",
            expected_support_tree=OwnershipTree(
                owner="folio.foundation",
                children=(
                    OwnershipTree(owner="folio.foundation.clock"),
                    OwnershipTree(owner="folio.foundation.identifiers"),
                ),
                dependencies=frozenset(
                    {("folio.foundation.clock", "folio.foundation.identifiers")}
                ),
            ),
        ),
        id="foundation-with-nested-clock-and-identifier-owners",
    ),
    pytest.param(
        SupportLayout(
            source_files={
                "folio/shared/__init__.py": "",
                "folio/shared/clock/__init__.py": "class Clock: pass\n",
                "folio/shared/clock/timestamp.py": (
                    "from folio.shared.identifiers import Identifier\n"
                ),
                "folio/shared/identifiers/__init__.py": "class Identifier: pass\n",
            },
            support_module="folio.shared.clock.timestamp",
            support_owner="folio.shared.clock",
            consumer_import="from folio.shared.clock import Clock\n",
            expected_support_tree=OwnershipTree(
                owner="folio.shared",
                children=(
                    OwnershipTree(owner="folio.shared.clock"),
                    OwnershipTree(owner="folio.shared.identifiers"),
                ),
                dependencies=frozenset({("folio.shared.clock", "folio.shared.identifiers")}),
            ),
        ),
        id="shared-with-nested-clock-and-identifier-owners",
    ),
]


@pytest.mark.parametrize("layout", SUPPORT_LAYOUTS)
def test_shared_support_returns_its_place_in_the_ownership_tree(
    tmp_path: Path, layout: SupportLayout
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            layout.source_files | {"folio/loans/history/timestamp.py": layout.consumer_import},
        ),
        tach=TACH,
    )

    assert establish_ownership_tree(architecture) == replace(
        FOLIO_OWNERSHIP_TREE,
        children=tuple(
            sorted(
                FOLIO_OWNERSHIP_TREE.children + (layout.expected_support_tree,),
                key=lambda child: child.owner,
            )
        ),
    )
    assert owner_of(architecture, layout.support_module) == layout.support_owner
    assert architecture.owner_dependencies == {("folio.loans", "folio.catalog")}


@pytest.mark.parametrize("layout", SUPPORT_LAYOUTS)
def test_support_at_every_depth_cannot_depend_on_loan_history(
    tmp_path: Path, layout: SupportLayout
) -> None:
    # Locate the concrete source module in the named layout, including file owners.
    source_file = layout.support_module.replace(".", "/") + ".py"
    architecture = extract(
        folio_tree(
            tmp_path,
            layout.source_files
            | {
                source_file: (
                    "# Forbidden business dependency\nfrom folio.loans.history import LoanRecord\n"
                )
            },
        ),
        tach=TACH,
    )

    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="direction",
            src=layout.support_module,
            tgt="folio.loans.history",
            reason=(
                f"{layout.support_module} -> folio.loans.history: "
                "Support source depends on a business capability"
            ),
            file=source_file,
            line=2,
        )
    ]


def test_foundation_child_private_access_returns_violations(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/foundation/__init__.py": "",
                "folio/foundation/clock/__init__.py": "class Clock: pass\n",
                "folio/foundation/clock/_timestamp.py": "class Timestamp: pass\n",
                "folio/foundation/formatting.py": (
                    "from folio.foundation.clock._timestamp import Timestamp\n"
                ),
                "folio/loans/history/timestamp.py": (
                    "from folio.foundation.clock._timestamp import Timestamp\n"
                ),
            },
        ),
        tach=TACH,
    )
    result = establish_ownership_tree(architecture)

    assert isinstance(result, list)
    assert {(v.rule, v.src, v.tgt, v.line) for v in result} == {
        (
            rule,
            source,
            "folio.foundation.clock._timestamp",
            1,
        )
        for rule in ("public-surfaces", "private-access")
        for source in ("folio.foundation.formatting", "folio.loans.history.timestamp")
    }
    assert owner_of(architecture, "folio.foundation.clock._timestamp") == "folio.foundation.clock"


def test_foundation_module_cycle_returns_a_file_cycle(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/foundation/__init__.py": "",
                "folio/foundation/clock.py": (
                    "from .identifiers import Identifier\nclass Clock: pass\n"
                ),
                "folio/foundation/identifiers.py": (
                    "from .clock import Clock\nclass Identifier: pass\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="cycles",
            src="folio.foundation.clock",
            tgt="folio.foundation.clock",
            reason=(
                "folio.foundation.clock -> folio.foundation.identifiers -> folio.foundation.clock"
            ),
            file="folio/foundation/clock.py",
            line=1,
        )
    ]


def test_foundation_child_cycle_returns_an_owner_dependency_cycle(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/foundation/__init__.py": "",
                "folio/foundation/clock/__init__.py": "class Clock: pass\n",
                "folio/foundation/clock/timestamp.py": (
                    "from folio.foundation.identifiers import Identifier\n"
                ),
                "folio/foundation/identifiers/__init__.py": "class Identifier: pass\n",
                "folio/foundation/identifiers/creation_time.py": (
                    "from folio.foundation.clock import Clock\n"
                ),
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="owner-dependency-cycle",
            src="folio.foundation.clock",
            tgt="folio.foundation.clock",
            reason=(
                "folio.foundation.clock -> folio.foundation.identifiers -> folio.foundation.clock"
            ),
            file="folio/foundation/clock/__init__.py",
            line=1,
        )
    ]


def test_foundation_modules_share_an_owner_but_business_uses_the_public_root(
    tmp_path: Path,
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/foundation/__init__.py": "from .clock import Clock\n",
                "folio/foundation/clock.py": "class Clock: pass\n",
                "folio/foundation/identifiers.py": "from .clock import Clock\n",
                "folio/loans/history/timestamp.py": "from folio.foundation.clock import Clock\n",
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="public-surfaces",
            src="folio.loans.history.timestamp",
            tgt="folio.foundation.clock",
            reason=(
                "folio.loans.history.timestamp -> folio.foundation.clock: "
                "Foreign concept leaf/private module bypasses its public surface"
            ),
            file="folio/loans/history/timestamp.py",
            line=1,
        )
    ]
    assert owner_of(architecture, "folio.foundation.clock") == "folio.foundation"
    assert owner_of(architecture, "folio.foundation.identifiers") == "folio.foundation"


# Class names do not determine implementation roles; source boundaries still apply.


def test_public_catalog_classes_are_treated_equally_regardless_of_name(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/__init__.py": (
                    "class Books: pass\n"
                    "class InMemoryBooks: pass\n"
                    "class SqliteBooks: pass\n"
                    "class SQLiteBooks: pass\n"
                ),
                "folio/loans/history/catalog.py": (
                    "from folio.catalog import Books, InMemoryBooks, SqliteBooks, SQLiteBooks\n"
                    "books = Books()\n"
                    "memory_books = InMemoryBooks()\n"
                    "sqlite_books = SqliteBooks()\n"
                    "database_books = SQLiteBooks()\n"
                ),
            },
        ),
        tach=TACH,
    )

    assert establish_ownership_tree(architecture) == FOLIO_OWNERSHIP_TREE


def test_catalog_class_still_requires_its_public_surface(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/book.py": "class InMemoryBooks: pass\n",
                "folio/loans/history/catalog.py": (
                    "from folio.catalog.book import InMemoryBooks\nbooks = InMemoryBooks()\n"
                ),
            },
        ),
        tach=TACH,
    )

    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="public-surfaces",
            src="folio.loans.history.catalog",
            tgt="folio.catalog.book",
            reason=(
                "folio.loans.history.catalog -> folio.catalog.book: "
                "Foreign concept leaf/private module bypasses its public surface"
            ),
            file="folio/loans/history/catalog.py",
            line=line,
        )
        for line in (1, 2)
    ]


# Private symbols and dynamic dependency mechanisms keep their meaning through aliases.


@dataclass(frozen=True)
class SymbolAccess:
    source: str
    expected_lines: tuple[int, ...]


@pytest.mark.parametrize(
    "access",
    [
        pytest.param(
            SymbolAccess(
                source="from folio.catalog import _BookIndex\n",
                expected_lines=(1,),
            ),
            id="direct-private-symbol",
        ),
        pytest.param(
            SymbolAccess(
                source="import folio.catalog as catalog\nindex = catalog._BookIndex\n",
                expected_lines=(2,),
            ),
            id="module-import-alias",
        ),
        pytest.param(
            SymbolAccess(
                source="import folio.catalog\nindex = folio.catalog._BookIndex\n",
                expected_lines=(2,),
            ),
            id="fully-qualified-private-symbol",
        ),
        pytest.param(
            SymbolAccess(
                source=(
                    "import folio.catalog as catalog\nbooks = catalog\nindex = books._BookIndex\n"
                ),
                expected_lines=(3,),
            ),
            id="assignment-module-alias",
        ),
        pytest.param(
            SymbolAccess(
                source=(
                    "import folio.catalog as catalog\n"
                    "def read_index():\n    return catalog._BookIndex\n"
                ),
                expected_lines=(3,),
            ),
            id="private-symbol-inside-function",
        ),
    ],
)
def test_private_catalog_symbols_are_rejected_through_aliases(
    tmp_path: Path, access: SymbolAccess
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/__init__.py": "class _BookIndex: pass\n",
                "folio/loans/history/index.py": access.source,
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="private-access",
            src="folio.loans.history.index",
            tgt="folio.catalog",
            reason=(
                "folio.loans.history.index -> folio.catalog: "
                "Foreign owner accesses a private implementation"
            ),
            file="folio/loans/history/index.py",
            line=line,
        )
        for line in access.expected_lines
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "import folio.catalog as catalog\nbook_id = catalog.BookId\n", id="public-symbol"
        ),
        pytest.param(
            "import folio.catalog as catalog\nbooks = catalog\nbook_id = books.BookId\n",
            id="public-symbol-through-assignment",
        ),
        pytest.param(
            "import folio.catalog as catalog\n"
            "def read_index(catalog):\n    return catalog._BookIndex\n",
            id="parameter-shadows-module-alias",
        ),
        pytest.param(
            "import folio.catalog as catalog\n"
            "def read_index():\n    catalog = object()\n    return catalog._BookIndex\n",
            id="local-assignment-shadows-module-alias",
        ),
        pytest.param(
            "import folio.catalog\ndef read_index(folio):\n    return folio.catalog._BookIndex\n",
            id="parameter-shadows-application-namespace",
        ),
        pytest.param(
            "import folio.catalog\nread_index = lambda folio: folio.catalog._BookIndex\n",
            id="lambda-shadows-application-namespace",
        ),
        pytest.param(
            "import folio.catalog\nfolio = object()\nindex = folio.catalog._BookIndex\n",
            id="assignment-shadows-application-namespace",
        ),
    ],
)
def test_public_symbols_and_local_objects_do_not_violate_module_privacy(
    tmp_path: Path, source: str
) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/loans/history/index.py": source}), tach=TACH
    )
    assert establish_ownership_tree(architecture) == FOLIO_OWNERSHIP_TREE


@dataclass(frozen=True)
class HiddenDependency:
    source: str
    mechanism: str
    expected_lines: tuple[int, ...]


@pytest.mark.parametrize(
    "dependency",
    [
        pytest.param(
            HiddenDependency(
                source="load = __import__\ncatalog = load('folio.catalog')\n",
                mechanism="__import__",
                expected_lines=(1, 2),
            ),
            id="aliased-import-builtin",
        ),
        pytest.param(
            HiddenDependency(
                source="load = __import__\nread = load\ncatalog = read('folio.catalog')\n",
                mechanism="__import__",
                expected_lines=(1, 2, 3),
            ),
            id="chained-import-alias",
        ),
        pytest.param(
            HiddenDependency(
                source="execute = exec\nexecute('import folio.catalog')\n",
                mechanism="exec",
                expected_lines=(1, 2),
            ),
            id="aliased-exec",
        ),
        pytest.param(
            HiddenDependency(
                source="evaluate = eval\nevaluate('folio.catalog')\n",
                mechanism="eval",
                expected_lines=(1, 2),
            ),
            id="aliased-eval",
        ),
        pytest.param(
            HiddenDependency(
                source="from builtins import __import__ as load\nload('folio.catalog')\n",
                mechanism="builtins.__import__",
                expected_lines=(2,),
            ),
            id="imported-builtin-alias",
        ),
        pytest.param(
            HiddenDependency(
                source="from importlib import import_module as load\nload('folio.catalog')\n",
                mechanism="importlib.import_module",
                expected_lines=(2,),
            ),
            id="importlib-function-alias",
        ),
        pytest.param(
            HiddenDependency(
                source="import sys\nmodules = sys.modules\n",
                mechanism="sys.modules",
                expected_lines=(2,),
            ),
            id="module-cache-reference",
        ),
        pytest.param(
            HiddenDependency(
                source="import sys\npaths = sys.path\n",
                mechanism="sys.path",
                expected_lines=(2,),
            ),
            id="import-path-reference",
        ),
    ],
)
def test_hidden_dependencies_return_explicit_import_violations(
    tmp_path: Path, dependency: HiddenDependency
) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/loans/history/loading.py": dependency.source}), tach=TACH
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="explicit-imports",
            src="folio.loans.history.loading",
            tgt="folio.loans.history.loading",
            reason=f"Unsupported dynamic dependency mechanism: {dependency.mechanism}",
            file="folio/loans/history/loading.py",
            line=line,
        )
        for line in dependency.expected_lines
    ]


# Factory audiences are structural: entries, composition, routes, and factories.


@dataclass(frozen=True)
class ImportAudience:
    source_file: str
    source_module: str
    expected_rules: tuple[str, ...] = ()
    additional_owner: str | None = None


@pytest.mark.parametrize(
    "audience",
    [
        pytest.param(
            ImportAudience(
                source_file="folio/api.py", source_module="folio.api", additional_owner="folio.api"
            ),
            id="api-entry",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/application.py",
                source_module="folio.application",
                additional_owner="folio.application",
            ),
            id="application-entry",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/cli.py", source_module="folio.cli", additional_owner="folio.cli"
            ),
            id="cli-entry",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/worker.py",
                source_module="folio.worker",
                additional_owner="folio.worker",
            ),
            id="worker-entry",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/bootstrap/wiring.py",
                source_module="folio.bootstrap.wiring",
                additional_owner="folio.bootstrap",
            ),
            id="composition",
        ),
        pytest.param(
            ImportAudience(source_file="folio/loans/deps.py", source_module="folio.loans.deps"),
            id="foreign-factory",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/api_routes.py", source_module="folio.loans.api_routes"
            ),
            id="http-route",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/request.py",
                source_module="folio.loans.borrowing.request",
                expected_rules=("public-surfaces", "direction", "composition"),
            ),
            id="borrowing-anchor-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/queries.py",
                source_module="folio.loans.queries",
                expected_rules=("public-surfaces", "composition"),
            ),
            id="ordinary-query-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/_commands/borrow.py",
                source_module="folio.loans._commands.borrow",
                expected_rules=("public-surfaces", "composition"),
            ),
            id="business-operation-rejected",
        ),
    ],
)
def test_catalog_factory_enforces_its_audience(tmp_path: Path, audience: ImportAudience) -> None:
    sources = {
        "folio/catalog/deps.py": "def get_books(): return ()\n",
        audience.source_file: "from folio.catalog.deps import get_books\n",
    }
    if audience.additional_owner == "folio.bootstrap":
        sources["folio/bootstrap/__init__.py"] = ""
    if audience.source_module == "folio.loans._commands.borrow":
        sources["folio/loans/_commands/__init__.py"] = ""
    architecture = extract(folio_tree(tmp_path, sources), tach=TACH)
    result = establish_ownership_tree(architecture)
    reasons = {
        "public-surfaces": "Factory surface used by an unsupported audience",
        "direction": "Anchor depends on an operation or composition surface",
        "composition": "Business source or anchor imports composition/settings",
    }
    if audience.expected_rules:
        assert result == [
            Violation(
                rule=rule,
                src=audience.source_module,
                tgt="folio.catalog.deps",
                reason=f"{audience.source_module} -> folio.catalog.deps: {reasons[rule]}",
                file=audience.source_file,
                line=1,
            )
            for rule in audience.expected_rules
        ]
    else:
        expected = FOLIO_OWNERSHIP_TREE
        if audience.additional_owner:
            expected = replace(
                expected,
                children=tuple(
                    sorted(
                        expected.children + (OwnershipTree(owner=audience.additional_owner),),
                        key=lambda child: child.owner,
                    )
                ),
            )
        assert result == expected


# Only the operation owner's surfaces and command branch can access private commands.


@pytest.mark.parametrize(
    "audience",
    [
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/commands.py",
                source_module="folio.loans.borrowing.commands",
            ),
            id="own-command-surface",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/deps.py",
                source_module="folio.loans.borrowing.deps",
            ),
            id="own-factory",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/_commands/renew.py",
                source_module="folio.loans.borrowing._commands.renew",
            ),
            id="own-command-branch",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/__init__.py",
                source_module="folio.loans.borrowing",
                expected_rules=("private-access",),
            ),
            id="own-root-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/request.py",
                source_module="folio.loans.borrowing.request",
                expected_rules=("private-access",),
            ),
            id="own-anchor-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/api_routes.py",
                source_module="folio.loans.borrowing.api_routes",
                expected_rules=("private-access",),
            ),
            id="own-route-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/borrowing/eligibility/operation.py",
                source_module="folio.loans.borrowing.eligibility.operation",
                expected_rules=("public-surfaces", "private-access"),
            ),
            id="child-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/history/operation.py",
                source_module="folio.loans.history.operation",
                expected_rules=("public-surfaces", "private-access"),
            ),
            id="sibling-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/deps.py",
                source_module="folio.loans.deps",
                expected_rules=("public-surfaces", "private-access"),
            ),
            id="parent-factory-rejected",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/catalog/deps.py",
                source_module="folio.catalog.deps",
                expected_rules=("public-surfaces", "private-access"),
            ),
            id="foreign-factory-rejected",
        ),
    ],
)
def test_borrowing_command_privacy_has_precise_exceptions(
    tmp_path: Path, audience: ImportAudience
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                # Isolate command privacy from the fixture's existing dependency paths.
                "folio/loans/history/record.py": "",
                "folio/loans/borrowing/limits/policy.py": "",
                "folio/loans/borrowing/_commands/__init__.py": "",
                "folio/loans/borrowing/_commands/borrow.py": "class BorrowBook: pass\n",
                audience.source_file: (
                    "from folio.loans.borrowing._commands.borrow import BorrowBook\n"
                ),
            },
        ),
        tach=TACH,
    )
    result = establish_ownership_tree(architecture)
    reasons = {
        "public-surfaces": "Foreign concept leaf/private module bypasses its public surface",
        "private-access": (
            "Operations are private to commands.py, deps.py, and their own command branch"
        ),
    }
    if audience.expected_rules:
        assert result == [
            Violation(
                rule=rule,
                src=audience.source_module,
                tgt="folio.loans.borrowing._commands.borrow",
                reason=(
                    f"{audience.source_module} -> folio.loans.borrowing._commands.borrow: "
                    f"{reasons[rule]}"
                ),
                file=audience.source_file,
                line=1,
            )
            for rule in audience.expected_rules
        ]
    else:
        assert result == replace(
            FOLIO_OWNERSHIP_TREE,
            dependencies=frozenset(),
            children=(
                FOLIO_OWNERSHIP_TREE.children[0],
                replace(FOLIO_OWNERSHIP_TREE.children[1], dependencies=frozenset()),
            ),
        )


# Application entries remain independent; domain code cannot import an entry.


@pytest.mark.parametrize(
    "entry", ["folio.api", "folio.cli", "folio.worker", "folio.main", "folio.application"]
)
def test_loan_history_cannot_import_an_entry(entry: str, tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                entry.replace(".", "/") + ".py": "def run(): pass\n",
                "folio/loans/queries.py": f"from {entry} import run\n",
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="direction",
            src="folio.loans.queries",
            tgt=entry,
            reason=f"folio.loans.queries -> {entry}: Domain source imports an entry adapter",
            file="folio/loans/queries.py",
            line=1,
        )
    ]


@dataclass(frozen=True)
class EntryConnection:
    source: str
    target: str


@pytest.mark.parametrize(
    "connection",
    [
        pytest.param(EntryConnection(source="folio.api", target="folio.cli"), id="api-to-cli"),
        pytest.param(
            EntryConnection(source="folio.application", target="folio.api"), id="application-to-api"
        ),
        pytest.param(
            EntryConnection(source="folio.api", target="folio.application"), id="api-to-application"
        ),
        pytest.param(EntryConnection(source="folio.cli", target="folio.api"), id="cli-to-api"),
        pytest.param(
            EntryConnection(source="folio.api", target="folio.worker"), id="api-to-worker"
        ),
        pytest.param(
            EntryConnection(source="folio.worker", target="folio.api"), id="worker-to-api"
        ),
        pytest.param(
            EntryConnection(source="folio.cli", target="folio.worker"), id="cli-to-worker"
        ),
        pytest.param(
            EntryConnection(source="folio.worker", target="folio.cli"), id="worker-to-cli"
        ),
        pytest.param(
            EntryConnection(source="folio.main", target="folio.worker"), id="main-to-worker"
        ),
    ],
)
def test_entries_cannot_import_one_another(tmp_path: Path, connection: EntryConnection) -> None:
    source_file = connection.source.replace(".", "/") + ".py"
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                source_file: f"from {connection.target} import run\n",
                connection.target.replace(".", "/") + ".py": "def run(): pass\n",
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="direction",
            src=connection.source,
            tgt=connection.target,
            reason=(
                f"{connection.source} -> {connection.target}: Entry adapters depend on one another"
            ),
            file=source_file,
            line=1,
        )
    ]


def test_application_root_remains_a_namespace(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/__init__.py": "from folio.catalog import BookId\n"}),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="direction",
            src="folio",
            tgt="folio.catalog",
            reason="folio -> folio.catalog: Company root must remain a namespace",
            file="folio/__init__.py",
            line=1,
        )
    ]


def test_http_support_cannot_depend_on_catalog(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/api_support/__init__.py": "",
                "folio/api_support/book_error.py": "from folio.catalog import BookId\n",
            },
        ),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="direction",
            src="folio.api_support.book_error",
            tgt="folio.catalog",
            reason=(
                "folio.api_support.book_error -> folio.catalog: "
                "Shared HTTP support depends on a business capability"
            ),
            file="folio/api_support/book_error.py",
            line=1,
        )
    ]


@pytest.mark.parametrize(
    "audience",
    [
        pytest.param(
            ImportAudience(
                source_file="folio/api.py", source_module="folio.api", additional_owner="folio.api"
            ),
            id="api-can-use-http-support",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/api_routes.py", source_module="folio.loans.api_routes"
            ),
            id="route-can-use-http-support",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/cli.py",
                source_module="folio.cli",
                expected_rules=("public-surfaces", "private-access", "direction"),
            ),
            id="cli-cannot-use-http-support",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/queries.py",
                source_module="folio.loans.queries",
                expected_rules=("public-surfaces", "private-access", "direction"),
            ),
            id="business-cannot-use-http-support",
        ),
    ],
)
def test_http_support_private_exception_is_limited_to_http_callers(
    tmp_path: Path, audience: ImportAudience
) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/api_support/__init__.py": "",
                "folio/api_support/_errors.py": "class ErrorResponse: pass\n",
                audience.source_file: "from folio.api_support._errors import ErrorResponse\n",
            },
        ),
        tach=TACH,
    )
    reasons = {
        "public-surfaces": "Foreign concept leaf/private module bypasses its public surface",
        "private-access": "Foreign owner accesses a private implementation",
        "direction": "Non-HTTP source imports shared HTTP support",
    }
    result = establish_ownership_tree(architecture)
    if audience.expected_rules:
        assert result == [
            Violation(
                rule=rule,
                src=audience.source_module,
                tgt="folio.api_support._errors",
                reason=f"{audience.source_module} -> folio.api_support._errors: {reasons[rule]}",
                file=audience.source_file,
                line=1,
            )
            for rule in audience.expected_rules
        ]
    else:
        extra = (OwnershipTree(owner="folio.api_support"),)
        if audience.additional_owner:
            extra += (OwnershipTree(owner=audience.additional_owner),)
        assert result == replace(
            FOLIO_OWNERSHIP_TREE,
            children=tuple(
                sorted(FOLIO_OWNERSHIP_TREE.children + extra, key=lambda child: child.owner)
            ),
        )


@pytest.mark.parametrize(
    "audience",
    [
        pytest.param(
            ImportAudience(
                source_file="folio/api.py", source_module="folio.api", additional_owner="folio.api"
            ),
            id="api-assembles-routes",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/cli.py",
                source_module="folio.cli",
                expected_rules=("public-surfaces", "direction"),
            ),
            id="cli-cannot-assemble-routes",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/deps.py",
                source_module="folio.loans.deps",
                expected_rules=("public-surfaces", "direction"),
            ),
            id="factory-cannot-assemble-routes",
        ),
        pytest.param(
            ImportAudience(
                source_file="folio/loans/queries.py",
                source_module="folio.loans.queries",
                expected_rules=("public-surfaces", "direction"),
            ),
            id="domain-cannot-assemble-routes",
        ),
    ],
)
def test_only_api_entry_assembles_catalog_routes(tmp_path: Path, audience: ImportAudience) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/api_routes.py": "router = object()\n",
                audience.source_file: "from folio.catalog.api_routes import router\n",
            },
        ),
        tach=TACH,
    )
    result = establish_ownership_tree(architecture)
    reasons = {
        "public-surfaces": "Foreign concept leaf/private module bypasses its public surface",
        "direction": "Only a declared API entry assembles capability HTTP surfaces",
    }
    if audience.expected_rules:
        assert result == [
            Violation(
                rule=rule,
                src=audience.source_module,
                tgt="folio.catalog.api_routes",
                reason=f"{audience.source_module} -> folio.catalog.api_routes: {reasons[rule]}",
                file=audience.source_file,
                line=1,
            )
            for rule in audience.expected_rules
        ]
    else:
        assert result == replace(
            FOLIO_OWNERSHIP_TREE,
            children=(OwnershipTree(owner="folio.api"),) + FOLIO_OWNERSHIP_TREE.children,
        )


# Reserved role names only grant permissions at their supported ownership locations.


@pytest.mark.parametrize(
    "source_module",
    [
        "folio.loans.api",
        "folio.loans.application",
        "folio.loans.foundation",
        "folio.loans.bootstrap",
        "folio.loans.scope",
    ],
)
def test_nested_role_names_do_not_grant_application_permissions(
    tmp_path: Path, source_module: str
) -> None:
    source_file = source_module.replace(".", "/") + ".py"
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/deps.py": "def get_books(): return ()\n",
                source_file: "from folio.catalog.deps import get_books\n",
            },
        ),
        tach=TACH,
    )
    assert (
        source_module not in architecture.entries | architecture.support | architecture.composition
    )
    assert owner_of(architecture, source_module) == "folio.loans"
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule=rule,
            src=source_module,
            tgt="folio.catalog.deps",
            reason=f"{source_module} -> folio.catalog.deps: {reason}",
            file=source_file,
            line=1,
        )
        for rule, reason in (
            ("public-surfaces", "Factory surface used by an unsupported audience"),
            ("direction", "Anchor depends on an operation or composition surface"),
            ("composition", "Business source or anchor imports composition/settings"),
        )
    ]


def test_deps_inside_a_private_branch_is_not_an_owner_factory(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(
            tmp_path,
            {
                "folio/catalog/deps.py": "def get_books(): return ()\n",
                "folio/loans/_commands/__init__.py": "",
                "folio/loans/_commands/deps.py": "from folio.catalog.deps import get_books\n",
            },
        ),
        tach=TACH,
    )
    assert owner_of(architecture, "folio.loans._commands.deps") == "folio.loans"
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule=rule,
            src="folio.loans._commands.deps",
            tgt="folio.catalog.deps",
            reason=f"folio.loans._commands.deps -> folio.catalog.deps: {reason}",
            file="folio/loans/_commands/deps.py",
            line=1,
        )
        for rule, reason in (
            ("public-surfaces", "Factory surface used by an unsupported audience"),
            ("composition", "Business source or anchor imports composition/settings"),
        )
    ]


# Incomplete or ambiguous source extraction never establishes a successful tree.


@dataclass(frozen=True)
class UnsupportedImport:
    source: str
    reason: str
    line: int


@pytest.mark.parametrize(
    "unsupported",
    [
        pytest.param(
            UnsupportedImport(
                source="from folio.catalog import *\n",
                reason="Wildcard import hides supported symbols",
                line=1,
            ),
            id="wildcard",
        ),
        pytest.param(
            UnsupportedImport(
                source="from ....catalog import BookId\n",
                reason="Unresolvable relative import",
                line=1,
            ),
            id="relative-import-beyond-root",
        ),
        pytest.param(
            UnsupportedImport(
                source="def books():\n    from folio.catalog import BookId\n",
                reason="Import is not at module scope",
                line=2,
            ),
            id="function-local-import",
        ),
        pytest.param(
            UnsupportedImport(
                source="class BookSearch:\n    from folio.catalog import BookId\n",
                reason="Import is not at module scope",
                line=2,
            ),
            id="class-local-import",
        ),
        pytest.param(
            UnsupportedImport(
                source="if True:\n    from folio.catalog import BookId\n",
                reason="Import is not at module scope",
                line=2,
            ),
            id="conditional-import",
        ),
        pytest.param(
            UnsupportedImport(
                source=(
                    "try:\n    from folio.catalog import BookId\nexcept ImportError:\n    pass\n"
                ),
                reason="Import is not at module scope",
                line=2,
            ),
            id="try-import",
        ),
        pytest.param(
            UnsupportedImport(
                source=(
                    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
                    "    from folio.catalog import BookId\n"
                ),
                reason="Import is not at module scope",
                line=3,
            ),
            id="type-checking-import",
        ),
    ],
)
def test_unsupported_import_forms_return_extraction_violations(
    tmp_path: Path, unsupported: UnsupportedImport
) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/loans/history/catalog.py": unsupported.source}), tach=TACH
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="explicit-imports",
            src="folio.loans.history.catalog",
            tgt="folio.loans.history.catalog",
            reason=unsupported.reason,
            file="folio/loans/history/catalog.py",
            line=unsupported.line,
        )
    ]


def test_missing_package_initializer_returns_a_layout_violation(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/loans/renewals/renewal.py": "class Renewal: pass\n"}),
        tach=TACH,
    )
    assert establish_ownership_tree(architecture) == [
        Violation(
            rule="python-layout",
            src="folio.loans.renewals",
            tgt="folio.loans.renewals",
            reason="Package directory lacks __init__.py",
            line=1,
        )
    ]


def test_source_parse_failure_returns_a_located_violation(tmp_path: Path) -> None:
    architecture = extract(
        folio_tree(tmp_path, {"folio/loans/history/broken.py": "def broken(\n"}), tach=TACH
    )
    result = establish_ownership_tree(architecture)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].rule == "ownership"
    assert result[0].src == result[0].tgt == "folio.loans.history.broken"
    assert result[0].file == "folio/loans/history/broken.py"
    assert result[0].line == 1
    assert result[0].reason.startswith("Cannot parse source:")


def test_source_file_symlink_returns_an_ownership_violation(tmp_path: Path) -> None:
    root = folio_tree(tmp_path)
    (root / "folio/loans/history/catalog.py").symlink_to(root / "folio/catalog/__init__.py")
    assert establish_ownership_tree(extract(root, tach=TACH)) == [
        Violation(
            rule="ownership",
            src="folio.loans.history.catalog",
            tgt="folio.loans.history.catalog",
            reason="Source symlinks are outside this auditable profile",
            file="folio/loans/history/catalog.py",
            line=1,
        )
    ]


def test_source_directory_symlink_cannot_hide_an_owner(tmp_path: Path) -> None:
    root = folio_tree(tmp_path)
    (root / "folio/loans/hidden_catalog").symlink_to(
        root / "folio/catalog", target_is_directory=True
    )
    assert establish_ownership_tree(extract(root, tach=TACH)) == [
        Violation(
            rule="ownership",
            src="folio.loans.hidden_catalog",
            tgt="folio.loans.hidden_catalog",
            reason="Source directory symlinks are outside this auditable profile",
            file="folio/loans/hidden_catalog",
            line=1,
        )
    ]


@dataclass(frozen=True)
class InvalidTachResponse:
    output: str
    expected_error: str
    returncode: int = 0


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            InvalidTachResponse(output="not JSON", expected_error="Tach map returned invalid JSON"),
            id="malformed-json",
        ),
        pytest.param(
            InvalidTachResponse(
                output="[]", expected_error="Tach map returned an invalid file dependency graph"
            ),
            id="array-instead-of-map",
        ),
        pytest.param(
            InvalidTachResponse(
                output="null", expected_error="Tach map returned an invalid file dependency graph"
            ),
            id="null-graph",
        ),
        pytest.param(
            InvalidTachResponse(
                output='{"folio/api.py": "folio/catalog/__init__.py"}',
                expected_error="Tach map returned an invalid file dependency graph",
            ),
            id="target-is-not-a-list",
        ),
        pytest.param(
            InvalidTachResponse(
                output='{"folio/api.py": [42]}',
                expected_error="Tach map returned an invalid file dependency graph",
            ),
            id="target-is-not-a-path",
        ),
        pytest.param(
            InvalidTachResponse(
                output="map unavailable",
                expected_error="Tach map failed: map unavailable",
                returncode=1,
            ),
            id="tool-failure",
        ),
    ],
)
def test_invalid_tach_output_cannot_return_a_successful_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: InvalidTachResponse,
) -> None:
    def run_tach(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=response.returncode, stdout=response.output, stderr=""
        )

    monkeypatch.setattr("bsa_linter.extract.subprocess.run", run_tach)
    root = folio_tree(tmp_path)
    with pytest.raises(ValueError, match=response.expected_error):
        extract(root, tach=TACH)
    with pytest.raises(SystemExit) as failure:
        cli_main(["--root", str(root), "--ownership-tree", "--json"])
    assert failure.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert response.expected_error in captured.err


def test_unbounded_folio_runs_despite_its_architecture_violations() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "folio.cli"],
        cwd=UNBOUNDED_FOLIO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout == "Ada borrowed Pride and Prejudice\nActive loans: 1\n"
    assert completed.stderr == ""


def test_unbounded_folio_returns_and_prints_located_violations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = establish_ownership_tree(extract(UNBOUNDED_FOLIO, tach=TACH))
    assert isinstance(result, list)
    assert Counter(violation.rule for violation in result) == {
        "python-layout": 1,
        "ownership": 1,
        "public-surfaces": 11,
        "private-access": 5,
        "direction": 4,
        "composition": 2,
        "owner-dependency-cycle": 1,
    }
    assert (
        Violation(
            rule="direction",
            src="folio.foundation",
            tgt="folio.loans",
            reason=(
                "folio.foundation -> folio.loans: Support source depends on a business capability"
            ),
            file="folio/foundation.py",
            line=1,
        )
        in result
    )
    assert (
        Violation(
            rule="private-access",
            src="folio.loans.service",
            tgt="folio.loans._commands.borrow",
            reason=(
                "folio.loans.service -> folio.loans._commands.borrow: "
                "Operations are private to commands.py, deps.py, and their own command branch"
            ),
            file="folio/loans/service.py",
            line=5,
        )
        in result
    )
    assert (
        Violation(
            rule="owner-dependency-cycle",
            src="folio.catalog",
            tgt="folio.catalog",
            reason="folio.catalog -> folio.loans -> folio.catalog",
            file="folio/catalog/__init__.py",
            line=1,
        )
        in result
    )
    for violation in result:
        assert violation.file is not None
        assert violation.line is not None
        source_lines = (UNBOUNDED_FOLIO / violation.file).read_text().splitlines()
        assert 1 <= violation.line <= len(source_lines)

    arguments = ["--root", str(UNBOUNDED_FOLIO), "--ownership-tree"]
    assert cli_main([*arguments, "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "pass": False,
        "violations": [violation.to_dict() for violation in result],
    }

    assert cli_main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "BSA profile failed with 25 violation(s)." in captured.out
    assert "Ownership tree establishment:" not in captured.out
    for violation in result:
        assert (
            f"{violation.file}:{violation.line}: {violation.rule}: {violation.reason}"
            in captured.out
        )


# Application assembly is an entry role, with ordinary boundary checks intact.
@pytest.mark.parametrize("wiring", ["scope", "bootstrap"])
def test_application_wires_multiple_factories_and_shared_composition(
    tmp_path: Path, wiring: str
) -> None:
    root = folio_tree(
        tmp_path,
        {
            "folio/catalog/deps.py": "def get_books(): return ()\n",
            "folio/loans/deps.py": (
                f"from folio.{wiring} import scope\ndef get_loans(): return scope\n"
            ),
            f"folio/{wiring}.py": "scope = object()\n",
            "folio/application.py": (
                "from folio.catalog.deps import get_books\n"
                "from folio.loans.deps import get_loans\n"
                f"from folio.{wiring} import scope\n"
                "def run(): return get_books(), get_loans(), scope\n"
            ),
        },
    )
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert result == replace(
        FOLIO_OWNERSHIP_TREE,
        children=tuple(
            sorted(
                (
                    OwnershipTree(owner="folio.application"),
                    FOLIO_OWNERSHIP_TREE.children[0],
                    OwnershipTree(owner=f"folio.{wiring}"),
                    FOLIO_OWNERSHIP_TREE.children[1],
                ),
                key=lambda child: child.owner,
            )
        ),
    )


@pytest.mark.parametrize("wiring", ["scope", "bootstrap"])
@pytest.mark.parametrize("source", ["folio/loans/queries.py", "folio/foundation.py"])
def test_business_and_support_cannot_use_application_composition(
    tmp_path: Path, source: str, wiring: str
) -> None:
    root = folio_tree(
        tmp_path,
        {
            f"folio/{wiring}.py": "scope = object()\n",
            source: f"from folio.{wiring} import scope\n",
        },
    )
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert isinstance(result, list)
    assert (
        Violation(
            rule="composition",
            src=source.removesuffix(".py").replace("/", "."),
            tgt=f"folio.{wiring}",
            reason=(
                f"{source.removesuffix('.py').replace('/', '.')} -> folio.{wiring}: "
                "Business source or anchor imports composition/settings"
            ),
            file=source,
            line=1,
        )
        in result
    )


@pytest.mark.parametrize("target", ["folio.catalog._stock", "folio.catalog.api_routes"])
def test_application_entry_cannot_bypass_private_or_http_surfaces(
    tmp_path: Path, target: str
) -> None:
    root = folio_tree(
        tmp_path,
        {
            "folio/catalog/_stock.py": "books = ()\n",
            "folio/catalog/api_routes.py": "books = ()\n",
            "folio/application.py": f"from {target} import books\n",
        },
    )
    result = establish_ownership_tree(extract(root, tach=TACH))
    assert isinstance(result, list)
    assert {finding.rule for finding in result} == (
        {"public-surfaces", "private-access"}
        if target.endswith("._stock")
        else {"public-surfaces", "direction"}
    )
    assert all(finding.file == "folio/application.py" and finding.line == 1 for finding in result)


@pytest.mark.parametrize(
    ("source_file", "source_module", "replacement"),
    [
        ("folio/_ui.py", "folio._ui", "api_support"),
        ("folio/_ui/__init__.py", "folio._ui", "api_support"),
        ("folio/http_support.py", "folio.http_support", "api_support"),
        ("folio/http_support/__init__.py", "folio.http_support", "api_support"),
        (
            "folio/composition.py",
            "folio.composition",
            "scope for resource definitions/binding and bootstrap for setup/teardown",
        ),
        (
            "folio/composition/__init__.py",
            "folio.composition",
            "scope for resource definitions/binding and bootstrap for setup/teardown",
        ),
        ("folio/catalog/http_routes.py", "folio.catalog.http_routes", "api_routes"),
        ("folio/catalog/routes.py", "folio.catalog.routes", "api_routes"),
        ("folio/catalog/routes/__init__.py", "folio.catalog.routes", "api_routes"),
        (
            "folio/loans/borrowing/http_routes.py",
            "folio.loans.borrowing.http_routes",
            "api_routes",
        ),
        ("folio/loans/borrowing/routes.py", "folio.loans.borrowing.routes", "api_routes"),
    ],
)
def test_alternate_role_names_return_actionable_layout_violations(
    tmp_path: Path, source_file: str, source_module: str, replacement: str
) -> None:
    architecture = extract(folio_tree(tmp_path, {source_file: ""}), tach=TACH)
    assert source_module not in (
        architecture.http_support | architecture.composition | architecture.routes
    )
    result = establish_ownership_tree(architecture)
    assert isinstance(result, list)
    assert [violation for violation in result if violation.rule == "python-layout"] == [
        Violation(
            rule="python-layout",
            src=source_module,
            tgt=source_module,
            reason=f"Unsupported role name {source_module.rsplit('.', 1)[-1]}; use {replacement}",
            file=source_file,
            line=1,
        )
    ]


@pytest.mark.parametrize(
    "name", ["scope", "bootstrap", "composition", "api_support", "http_support"]
)
def test_technical_role_names_inside_catalog_remain_ordinary_business_modules(
    tmp_path: Path, name: str
) -> None:
    architecture = extract(folio_tree(tmp_path, {f"folio/catalog/{name}.py": ""}), tach=TACH)
    assert f"folio.catalog.{name}" not in architecture.composition | architecture.http_support
    assert establish_ownership_tree(architecture) == FOLIO_OWNERSHIP_TREE
