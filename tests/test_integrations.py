"""The shared profile accepts both independent runnable samples."""

from bsa_linter.architecture import WellFormed, lint_architecture
from bsa_linter.extract import extract

from .support import FOLIO, MERIDIAN, TACH


def test_folio_imports_form_business_edge() -> None:
    graph = extract(FOLIO, tach=TACH)
    assert graph.owner_dependencies == {("folio.loans", "folio.catalog")}
    assert isinstance(lint_architecture(graph), WellFormed)


def test_meridian_imports_form_business_edge() -> None:
    graph = extract(MERIDIAN, tach=TACH)
    assert graph.owner_dependencies == {("meridian.shipping", "meridian.fleet")}
    assert isinstance(lint_architecture(graph), WellFormed)
