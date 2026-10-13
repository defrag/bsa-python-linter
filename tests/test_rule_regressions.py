"""Break and repair one valid application through both public checking APIs and the CLI."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from bsa_linter.architecture import (
    OwnershipTree,
    Violation,
    WellFormed,
    establish_ownership_tree,
    lint_architecture,
)
from bsa_linter.cli import main
from bsa_linter.extract import extract

from .support import TACH, tree


@dataclass(frozen=True)
class Break:
    rule: str
    file: str
    source: str


BREAKS = (
    Break("python-layout", "app/one/models.py", "value = 1\n"),
    Break("ownership", "app/loose.py", "value = 1\n"),
    Break("public-surfaces", "app/two/queries.py", "from app.one.item import Item\n"),
    Break("private-access", "app/api.py", "from app.one import _secret\n"),
    Break("direction", "app/shared.py", "from app.one import Item\n"),
    Break("composition", "app/one/queries.py", "from fastapi import FastAPI\n"),
    Break("explicit-imports", "app/two/read.py", "from app.one import *\n"),
    Break("cycles", "app/one/link_b.py", "from .link_a import value\n"),
    Break("owner-dependency-cycle", "app/one/_work/run.py", "from app.two import Rel\n"),
)


def baseline(root: Path) -> Path:
    return tree(
        root,
        {
            "app/one/__init__.py": "from .item import Item\n_secret = object()\n",
            "app/one/link_a.py": "from .link_b import value\n",
            "app/one/link_b.py": "value = 1\n",
            "app/one/_work/__init__.py": "",
            "app/one/_work/run.py": "",
            "app/shared.py": "",
        },
    )


def check_clean(root: Path) -> None:
    architecture = extract(root, tach=TACH)
    assert isinstance(lint_architecture(architecture), WellFormed)
    assert isinstance(establish_ownership_tree(architecture), OwnershipTree)


@pytest.mark.parametrize("broken", BREAKS, ids=lambda broken: broken.rule)
def test_break_and_repair_reports_the_specific_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], broken: Break
) -> None:
    root = baseline(tmp_path)
    check_clean(root)
    path = root / broken.file
    original = path.read_text() if path.exists() else None
    path.write_text(broken.source)
    architecture = extract(root, tach=TACH)
    findings = lint_architecture(architecture)
    assert isinstance(findings, list)
    assert {v.rule for v in findings} == {broken.rule}
    assert establish_ownership_tree(architecture) == findings
    for finding in findings:
        assert finding.file and finding.line > 0
        assert finding.reason
        assert (root / finding.file).is_file()
        assert finding.line <= len((root / finding.file).read_text().splitlines())
    assert main(["--root", str(root), "--ownership-tree", "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == {
        "pass": False,
        "violations": [v.to_dict() for v in findings],
    }
    if original is None:
        path.unlink()
    else:
        path.write_text(original)
    check_clean(root)
    assert main(["--root", str(root), "--ownership-tree", "--json"]) == 0
    repaired = json.loads(capsys.readouterr().out)
    assert repaired["pass"] is True and repaired["violations"] == []
    assert repaired["ownership_tree"]["owner"] == "app"


def test_partial_repairs_do_not_hide_remaining_faults(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    check_clean(root)
    originals: dict[Path, str | None] = {}
    for broken in BREAKS:
        path = root / broken.file
        originals[path] = path.read_text() if path.exists() else None
        path.write_text(broken.source)
    remaining = {broken.rule for broken in BREAKS}
    for repaired in BREAKS:
        architecture = extract(root, tach=TACH)
        findings = establish_ownership_tree(architecture)
        assert isinstance(findings, list)
        assert all(isinstance(finding, Violation) for finding in findings)
        assert {finding.rule for finding in findings} == remaining
        assert lint_architecture(architecture) == findings
        path = root / repaired.file
        original = originals[path]
        if original is None:
            path.unlink()
        else:
            path.write_text(original)
        remaining.remove(repaired.rule)
    check_clean(root)
