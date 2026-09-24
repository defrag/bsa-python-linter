"""CLI presents rule findings with source locations."""

import json
import subprocess
import sys
from pathlib import Path

from .support import tree


def test_cli_json_and_location(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app/api.py": "from app.one.item import Item\n"})
    result = subprocess.run(
        [sys.executable, "-m", "bsa_linter.cli", "--root", str(root), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    finding = next(v for v in payload["violations"] if v["rule"] == "public-surfaces")
    assert finding["file"] == "app/api.py"
    assert finding["line"] == 1
