"""Composition imports and transport checks."""

from pathlib import Path

import pytest

from bsa_linter.extract import extract

from .support import TACH, VALID, findings, tree, violations


def test_business_module_cannot_import_factory(tmp_path: Path) -> None:
    root = tree(
        tmp_path, {"app/one/item.py": VALID["app/one/item.py"] + "from .deps import get_items\n"}
    )
    assert "composition" in findings(root)


def test_business_module_cannot_import_transport(tmp_path: Path) -> None:
    assert "composition" in findings(
        tree(tmp_path, {"app/one/item.py": "from fastapi import FastAPI\n"})
    )


@pytest.mark.parametrize(
    "framework",
    ["fastapi", "fastapi.responses", "flask", "flask.views", "starlette", "starlette.responses"],
)
def test_transport_audiences_include_submodules(tmp_path: Path, framework: str) -> None:
    allowed = {
        "app/api.py",
        "app/one/api_routes.py",
        "app/api_support/__init__.py",
        "app/api_support/errors.py",
        "tests/test_http.py",
    }
    forbidden = {
        "app/cli.py",
        "app/worker.py",
        "app/main.py",
        "app/application.py",
        "app/scope.py",
        "app/bootstrap.py",
        "app/foundation/__init__.py",
        "app/foundation/clock.py",
        "app/one/deps.py",
        "app/one/item.py",
        "app/one/queries.py",
        "app/one/_commands/add.py",
    }
    sources = {"app/one/_commands/__init__.py": ""}
    for path in allowed | forbidden:
        sources[path] = f"import {framework}\n" + VALID.get(path, "")
    reported = violations(extract(tree(tmp_path, sources), tach=TACH))
    assert {(v.file, v.rule, v.tgt, v.line) for v in reported} == {
        (path, "composition", framework, 1) for path in forbidden
    }
    assert all("Non-HTTP source imports a transport framework" in v.reason for v in reported)


@pytest.mark.parametrize("settings_package", [False, True], ids=["file", "package"])
def test_settings_audience_with_allowed_and_forbidden_callers(
    tmp_path: Path, settings_package: bool
) -> None:
    target = "app.settings.environment" if settings_package else "app.settings"
    sources = {"app/settings/__init__.py": ""} if settings_package else {}
    sources[target.replace(".", "/") + ".py"] = "setting = 'test'\n"
    allowed = {
        "app/api.py",
        "app/cli.py",
        "app/application.py",
        "app/scope.py",
        "app/bootstrap.py",
        "app/one/deps.py",
        "app/one/api_routes.py",
        "tests/test_settings.py",
    }
    forbidden = {
        "app/one/item.py",
        "app/one/queries.py",
        "app/one/_commands/add.py",
        "app/foundation.py",
    }
    # A settings package exposes its values through its root, just like other owners.
    if settings_package:
        sources["app/settings/__init__.py"] = "from .environment import setting\n"
    sources["app/one/_commands/__init__.py"] = ""
    for path in allowed | forbidden:
        sources[path] = "from app.settings import setting\n" + VALID.get(path, "")
    reported = violations(extract(tree(tmp_path, sources), tach=TACH))
    assert {(v.file, v.rule, v.tgt, v.line) for v in reported} == {
        (path, "composition", "app.settings", 1) for path in forbidden
    }


@pytest.mark.parametrize("target", ["app.scope", "app.bootstrap", "app.one.deps"])
def test_settings_internal_import_permission_does_not_grant_composition_access(
    tmp_path: Path, target: str
) -> None:
    root = tree(
        tmp_path,
        {
            "app/scope.py": "value = 1\n",
            "app/bootstrap.py": "value = 1\n",
            "app/settings/__init__.py": "from .environment import value\n",
            "app/settings/environment.py": "value = 1\n",
        },
    )
    assert violations(extract(root, tach=TACH)) == []
    path = root / "app/settings/environment.py"
    path.write_text(f"import {target}\nvalue = 1\n")
    reported = violations(extract(root, tach=TACH))
    assert any(v.rule == "composition" and v.tgt == target for v in reported)
    assert all(v.src == "app.settings.environment" for v in reported)
