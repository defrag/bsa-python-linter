"""Shared Python layout and naming checks."""

from pathlib import Path

import pytest

from bsa_linter.extract import extract

from .support import TACH, tree, violations


@pytest.mark.parametrize(
    "path",
    [
        "app/one/models.py",
        "app/one/book_models.py",
        "app/one/dto.py",
        "app/one/book_dto.py",
        "app/one/capabilities/__init__.py",
        "app/one/assembly.py",
        "app/one/_stores/__init__.py",
        "app/one/in_memory_items.py",
    ],
)
def test_technical_names_are_violations(tmp_path: Path, path: str) -> None:
    architecture = extract(tree(tmp_path, {path: ""}), tach=TACH)
    module = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    assert any(
        finding.rule == "python-layout" and finding.src == module
        for finding in violations(architecture)
    )


@pytest.mark.parametrize(
    "bucket",
    [
        "model",
        "models",
        "repositories",
        "services",
        "contracts",
        "types",
        "values",
        "schemas",
        "domain",
        "entities",
        "dto",
        "capabilities",
        "assembly",
        "stores",
    ],
)
def test_bucket_suffix_is_rejected_but_word_prefix_is_allowed(tmp_path: Path, bucket: str) -> None:
    root = tree(tmp_path, {f"app/one/{bucket}_catalog.py": "class InMemoryCatalog: pass\n"})
    assert violations(extract(root, tach=TACH)) == []
    source = root / "app/one" / f"{bucket}_catalog.py"
    renamed = source.with_name(f"catalog_{bucket}.py")
    source.rename(renamed)
    reported = violations(extract(root, tach=TACH))
    assert [(v.rule, v.file, v.line) for v in reported] == [
        ("python-layout", f"app/one/catalog_{bucket}.py", 1)
    ]


@pytest.mark.parametrize(
    ("path", "forbidden"),
    [
        ("app/api_support/api_models.py", False),
        ("app/api_support/models.py", True),
        ("app/api_support/nested/api_models.py", True),
        ("app/one/api_models.py", True),
        ("tests/models.py", False),
    ],
)
def test_naming_exceptions_do_not_spread_to_other_locations(
    tmp_path: Path, path: str, forbidden: bool
) -> None:
    root = tree(
        tmp_path,
        {
            "app/api_support/__init__.py": "",
            "app/api_support/nested/__init__.py": "",
            path: "class Response: pass\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert [(v.rule, v.file) for v in reported] == ([("python-layout", path)] if forbidden else [])


@pytest.mark.parametrize(
    "path",
    [
        "app/values.py",
        "app/values/__init__.py",
        "app/one/values.py",
        "app/one/_values.py",
        "app/one/item_values.py",
        "app/foundation/values.py",
        "app/foundation/values/__init__.py",
    ],
)
def test_values_bucket_has_no_support_exemption(tmp_path: Path, path: str) -> None:
    root = tree(
        tmp_path,
        {
            "app/foundation/__init__.py": "",
            "app/one/item.py": (
                "from dataclasses import dataclass\n"
                "@dataclass(frozen=True)\nclass ItemId:\n    value: str\n"
                "class Item: pass\n"
            ),
        },
    )
    assert violations(extract(root, tach=TACH)) == []
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("class ItemId: pass\n")
    architecture = extract(root, tach=TACH)
    assert "app.values" not in architecture.support
    reported = violations(architecture)
    assert any(v.rule == "python-layout" and v.file == path for v in reported)
