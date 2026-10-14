"""Concept behavior has a public type; composition constructs it separately.

The checker verifies import structure, not the meaning of arbitrary callables.
Keep the passing semantic counterexample explicit so it cannot be mistaken for
general enforcement of the guide's ban on handler forwarding.
"""

import sys
from pathlib import Path

import pytest

from bsa_linter.architecture import OwnershipTree, establish_ownership_tree
from bsa_linter.extract import extract

TACH = str(Path(sys.executable).with_name("tach"))
LIBRARY = {
    "workshop/__init__.py": "",
    "workshop/pricing/__init__.py": "from .price import DiscountPolicy\n",
    "workshop/pricing/price.py": (
        "class DiscountPolicy:\n"
        "    def quote(self, quantity: int) -> int:\n"
        "        return quantity * (8 if quantity >= 10 else 10)\n"
    ),
    "workshop/orders/__init__.py": "from .order import Order\n",
    "workshop/orders/order.py": (
        "from workshop.pricing import DiscountPolicy\n"
        "class Order:\n"
        "    def total(self, policy: DiscountPolicy, quantity: int) -> int:\n"
        "        return policy.quote(quantity)\n"
    ),
}
APPLICATION = {
    "workshop/pricing/deps.py": (
        "from .price import DiscountPolicy\n"
        "def get_policy() -> DiscountPolicy:\n"
        "    return DiscountPolicy()\n"
    ),
    "workshop/pricing/_commands/__init__.py": "",
    "workshop/pricing/_commands/quote.py": (
        "from workshop.pricing.price import DiscountPolicy\n"
        "class QuoteHandler:\n"
        "    def __init__(self, policy: DiscountPolicy) -> None:\n"
        "        self.policy = policy\n"
        "    def handle(self, quantity: int) -> int:\n"
        "        return self.policy.quote(quantity)\n"
    ),
    "workshop/orders/_commands/__init__.py": "",
    "workshop/orders/_commands/place.py": (
        "from workshop.pricing import DiscountPolicy\n"
        "class PlaceHandler:\n"
        "    def __init__(self, policy: DiscountPolicy) -> None:\n"
        "        self.policy = policy\n"
        "    def handle(self, quantity: int) -> int:\n"
        "        return self.policy.quote(quantity)\n"
    ),
    "workshop/orders/deps.py": (
        "from workshop.pricing.deps import get_policy\n"
        "from ._commands.place import PlaceHandler\n"
        "def get_place() -> PlaceHandler:\n"
        "    return PlaceHandler(get_policy())\n"
    ),
}


def write_sources(root: Path, sources: dict[str, str]) -> None:
    for name, content in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def check(root: Path):
    return establish_ownership_tree(extract(root, tach=TACH))


@pytest.mark.parametrize("application", [False, True], ids=["plain-library", "with-factories"])
def test_shared_concept_behavior_uses_root_type_and_separate_construction(
    tmp_path: Path, application: bool
) -> None:
    write_sources(tmp_path, LIBRARY | (APPLICATION if application else {}))
    architecture = extract(tmp_path, tach=TACH)
    assert not architecture.entries
    assert not architecture.support
    assert not architecture.composition
    assert not any(name.startswith("tests.") for name in architecture.modules)
    result = establish_ownership_tree(architecture)
    assert isinstance(result, OwnershipTree)
    assert result.dependencies == {("workshop.orders", "workshop.pricing")}
    assert {node.owner for node in result.children} == {"workshop.orders", "workshop.pricing"}


@pytest.mark.parametrize(
    ("replacement", "rules"),
    [
        (
            "from workshop.pricing.deps import DiscountPolicy",
            {"composition", "public-surfaces"},
        ),
        ("from workshop.pricing.price import DiscountPolicy", {"public-surfaces"}),
        (
            "from workshop.pricing._commands.quote import QuoteHandler as DiscountPolicy",
            {"private-access", "public-surfaces"},
        ),
    ],
    ids=["factory-surface-type", "foreign-concept-leaf", "aliased-foreign-handler"],
)
def test_business_consumer_cannot_bypass_the_concept_root(
    tmp_path: Path, replacement: str, rules: set[str]
) -> None:
    sources = LIBRARY | APPLICATION
    write_sources(tmp_path, sources)
    baseline = check(tmp_path)
    assert isinstance(baseline, OwnershipTree)
    name = "workshop/orders/_commands/place.py"
    (tmp_path / name).write_text(
        sources[name].replace("from workshop.pricing import DiscountPolicy", replacement)
    )
    result = check(tmp_path)
    assert isinstance(result, list)
    assert {finding.rule for finding in result} == rules
    (tmp_path / name).write_text(sources[name])
    assert check(tmp_path) == baseline


@pytest.mark.parametrize("wrapper", [False, True], ids=["root-alias", "concept-forwarder"])
def test_root_alias_or_concept_wrapper_cannot_launder_a_private_handler(
    tmp_path: Path, wrapper: bool
) -> None:
    sources = LIBRARY | APPLICATION
    write_sources(tmp_path, sources)
    baseline = check(tmp_path)
    assert isinstance(baseline, OwnershipTree)
    if wrapper:
        name = "workshop/pricing/price.py"
        broken = (
            "from ._commands.quote import QuoteHandler\n"
            "class DiscountPolicy:\n"
            "    def __init__(self, handler: QuoteHandler) -> None:\n"
            "        self.handler = handler\n"
            "    def quote(self, quantity: int) -> int:\n"
            "        return self.handler.handle(quantity)\n"
        )
    else:
        name = "workshop/pricing/__init__.py"
        broken = "from ._commands.quote import QuoteHandler as DiscountPolicy\n"
    (tmp_path / name).write_text(broken)
    result = check(tmp_path)
    assert isinstance(result, list)
    assert "private-access" in {finding.rule for finding in result}
    (tmp_path / name).write_text(sources[name])
    assert check(tmp_path) == baseline


def test_same_owner_callback_forwarding_requires_semantic_review(tmp_path: Path) -> None:
    write_sources(
        tmp_path,
        LIBRARY
        | APPLICATION
        | {
            "workshop/pricing/_commands/forward.py": (
                "from collections.abc import Callable\n"
                "class ForwardHandler:\n"
                "    def __init__(self, invoke: Callable[[int], int]) -> None:\n"
                "        self.invoke = invoke\n"
                "    def handle(self, quantity: int) -> int:\n"
                "        return self.invoke(quantity)\n"
            ),
            "workshop/pricing/deps.py": APPLICATION["workshop/pricing/deps.py"]
            + (
                "from ._commands.quote import QuoteHandler\n"
                "from ._commands.forward import ForwardHandler\n"
                "def get_forward() -> ForwardHandler:\n"
                "    return ForwardHandler(QuoteHandler(get_policy()).handle)\n"
            ),
        },
    )
    # The guide forbids this runtime delegation. Its imports are all permitted;
    # a passing structural graph must not be reported as semantic compliance.
    assert isinstance(check(tmp_path), OwnershipTree)
