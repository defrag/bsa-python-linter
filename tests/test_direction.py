"""Entry, HTTP support, and anchor direction checks."""

from pathlib import Path

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
