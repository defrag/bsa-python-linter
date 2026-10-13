"""Verify each rule's regression test fails when that rule is disabled in a disposable copy."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]
SELECTOR = "tests/test_rule_regressions.py::test_break_and_repair_reports_the_specific_rule"
MUTATIONS = (
    ("python-layout", "technical_naming_violations", "[]"),
    ("ownership", "ownership_violations", "[]"),
    ("public-surfaces", "surface_violation", "None"),
    ("private-access", "private_access_violation", "None"),
    ("direction", "direction_violation", "None"),
    ("composition", "composition_import_violation", "None"),
    ("cycles", "cycle_violations", "[]"),
    ("owner-dependency-cycle", "owner_dependency_cycle_violations", "[]"),
    ("explicit-imports", "", ""),
)
HARNESS = """
import sys
from pathlib import Path
import bsa_linter.architecture as architecture
import pytest
assert Path(architecture.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
raise SystemExit(pytest.main([sys.argv[2], '-q', '--tb=short']))
"""


def disable_rule(source: str, function: str, result: str) -> str:
    if not function:
        # Keep extraction intact but drop its findings before establishing the tree.
        assert source.count("list(architecture.issues)") == 1
        return source.replace("list(architecture.issues)", "[]")
    definition = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == function
    )
    assert definition.end_lineno is not None
    lines = source.splitlines(keepends=True)
    return "".join(
        lines[: definition.body[0].lineno - 1]
        + [f"    return {result}\n"]
        + lines[definition.end_lineno :]
    )


def run_tests(source_root: Path, selector: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    return subprocess.run(
        [sys.executable, "-c", HARNESS, str(source_root), selector],
        cwd=PACKAGE,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bsa-rule-mutations-") as directory:
        source_root = Path(directory) / "src"
        shutil.copytree(PACKAGE / "src", source_root, ignore=shutil.ignore_patterns("__pycache__"))
        target = source_root / "bsa_linter/architecture.py"
        original = target.read_text()
        baseline = run_tests(source_root, SELECTOR)
        if baseline.returncode:
            print("Baseline failed; no mutation results are valid.")
            print(baseline.stdout, baseline.stderr)
            return 1
        print("Baseline: all rule break/repair tests pass.", flush=True)
        failures: list[str] = []
        for rule, function, result in MUTATIONS:
            target.write_text(disable_rule(original, function, result))
            # Do not let equal-size edits or filesystem timestamp resolution reuse bytecode.
            shutil.rmtree(target.parent / "__pycache__", ignore_errors=True)
            trial = run_tests(source_root, f"{SELECTOR}[{rule}]")
            detected = (
                trial.returncode == 1
                and f"FAILED {SELECTOR}[{rule}]" in trial.stdout
                and "AssertionError" in trial.stdout
            )
            if detected:
                print(f"Detected disabled rule: {rule}", flush=True)
            else:
                failures.append(rule)
                print(f"Undetected mutation or test error: {rule}")
                print(trial.stdout, trial.stderr)
        print(f"Detected {len(MUTATIONS) - len(failures)}/{len(MUTATIONS)} rule mutations.")
        return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
