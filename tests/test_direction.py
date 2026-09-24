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


def test_only_api_assembles_http_routes(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/api.py": "from app.one.http_routes import router\n",
            "app/cli.py": "from app.one.http_routes import router\n",
            "app/one/http_routes.py": "router = object()\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert not [v for v in reported if v.src == "app.api"]
    assert any(v.rule == "direction" and v.src == "app.cli" for v in reported)


@pytest.mark.parametrize("route_name", ["api_routes", "http_routes", "routes"])
def test_http_routes_can_use_shared_api_models(tmp_path: Path, route_name: str) -> None:
    root = tree(
        tmp_path,
        {
            "app/_ui/__init__.py": "",
            "app/_ui/api_models.py": "class Error: pass\n",
            f"app/one/{route_name}.py": "from app._ui.api_models import Error\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert not [
        v for v in reported if v.src == f"app.one.{route_name}" and v.tgt == "app._ui.api_models"
    ]
    assert not [v for v in reported if v.src == "app._ui.api_models"]


def test_business_code_cannot_use_shared_api_models(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app/_ui/__init__.py": "",
            "app/_ui/api_models.py": "class Error: pass\n",
            "app/one/item.py": "from app._ui.api_models import Error\n",
        },
    )
    reported = violations(extract(root, tach=TACH))
    assert any(
        v.rule == "direction" and v.src == "app.one.item" and v.tgt == "app._ui.api_models"
        for v in reported
    )
