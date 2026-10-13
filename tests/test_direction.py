"""Entry, HTTP support, and anchor direction checks."""

from pathlib import Path

import pytest

from bsa_linter.extract import extract

from .support import TACH, findings, tree, violations


def test_anchor_cannot_import_another_capability(tmp_path: Path) -> None:
    root = tree(
        tmp_path, {"app/one/__init__.py": "from .item import Item\nfrom app.two import Rel\n"}
    )
    assert "direction" in findings(root)


def test_support_cannot_import_business_capability(tmp_path: Path) -> None:
    assert "direction" in findings(tree(tmp_path, {"app/shared.py": "from app.one import Item\n"}))


def test_only_api_assembles_api_routes(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/api.py": "from app.one.api_routes import router\n",
            "app/cli.py": "from app.one.api_routes import router\n",
            "app/one/api_routes.py": "router = object()\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert not [v for v in reported if v.src == "app.api"]
    assert any(v.rule == "direction" and v.src == "app.cli" for v in reported)


def test_api_routes_can_use_shared_api_models(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/api_support/__init__.py": "",
            "app/api_support/api_models.py": "class Error: pass\n",
            "app/one/api_routes.py": "from app.api_support.api_models import Error\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert not [
        v
        for v in reported
        if v.src == "app.one.api_routes" and v.tgt == "app.api_support.api_models"
    ]
    assert not [v for v in reported if v.src == "app.api_support.api_models"]


def test_business_code_cannot_use_shared_api_models(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/api_support/__init__.py": "",
            "app/api_support/api_models.py": "class Error: pass\n",
            "app/one/item.py": "from app.api_support.api_models import Error\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert any(
        v.rule == "direction" and v.src == "app.one.item" and v.tgt == "app.api_support.api_models"
        for v in reported
    )


@pytest.mark.parametrize("source", ["app/scope.py", "app/scope/binding.py"])
@pytest.mark.parametrize(
    "target", ["app.one", "app.one.deps", "app.foundation.deps", "app.bootstrap"]
)
def test_scope_cannot_acquire_bootstrap_or_business_responsibilities(
    tmp_path: Path, source: str, target: str
) -> None:
    sources = {
        "app/foundation/__init__.py": "resource = object()\n",
        "app/foundation/deps.py": "def get_resource(): return object()\n",
        "app/bootstrap.py": "",
        source: "from app.foundation import resource\n",
    }
    if source.endswith("binding.py"):
        sources["app/scope/__init__.py"] = "from .binding import resource\n"
    root = tree(tmp_path, sources)
    assert violations(extract(root, tach=TACH)) == []
    (root / source).write_text(f"import {target}\n")
    reported = violations(extract(root, tach=TACH))
    assert [(v.rule, v.file, v.tgt, v.reason) for v in reported] == [
        (
            "direction",
            source,
            target,
            f"{source.removesuffix('.py').replace('/', '.')} -> {target}: "
            "Application scope depends on business, factories, or bootstrap",
        )
    ]


@pytest.mark.parametrize("source", ["app/scope.py", "app/bootstrap.py", "app/api_support.py"])
@pytest.mark.parametrize("entry", ["app.api", "app.cli"])
def test_composition_and_http_support_cannot_import_entries(
    tmp_path: Path, source: str, entry: str
) -> None:
    root = tree(tmp_path, {"app/cli.py": "", source: ""})
    assert violations(extract(root, tach=TACH)) == []
    (root / source).write_text(f"import {entry}\n")
    reported = violations(extract(root, tach=TACH))
    assert [(v.rule, v.file, v.tgt) for v in reported] == [("direction", source, entry)]
    assert "Non-entry source imports an entry adapter" in reported[0].reason


def test_bootstrap_can_initialize_capabilities_after_binding_resources(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/scope.py": "resource = object()\n",
            "app/bootstrap.py": (
                "from app.scope import resource\n"
                "from app.one.deps import get_items\n"
                "from app.two.deps import get_items as get_other_items\n"
            ),
        },
    )
    assert violations(extract(root, tach=TACH)) == []
