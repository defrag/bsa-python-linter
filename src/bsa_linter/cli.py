"""Agent-facing architecture linter command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bsa_linter.architecture import OwnershipTree, establish_ownership_tree
from bsa_linter.extract import extract


def print_ownership_tree(tree: OwnershipTree, indent: str = "") -> None:
    print(f"{indent}{tree.owner}")
    for source, target in sorted(tree.dependencies):
        print(f"{indent}  imports: {source} -> {target}")
    for child in tree.children:
        print_ownership_tree(child, indent + "  ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a Python application against the BSA profile"
    )
    parser.add_argument("--root", type=Path, required=True, help="Python application root")
    parser.add_argument("--json", action="store_true", help="Machine-readable findings")
    parser.add_argument(
        "--ownership-tree",
        action="store_true",
        help="Show ownership tree establishment with dependencies between children at every depth",
    )
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f"application root is not a directory: {args.root}")
    tach = Path(sys.executable).with_name("tach")
    try:
        architecture = extract(args.root, tach=str(tach))
        result = establish_ownership_tree(architecture)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"bsa-lint: {exc}\n")
    findings = [] if isinstance(result, OwnershipTree) else result
    if args.json:
        payload: dict[str, object] = {
            "pass": not findings,
            "violations": [v.to_dict() for v in findings],
        }
        if args.ownership_tree and isinstance(result, OwnershipTree):
            payload["ownership_tree"] = result.to_dict()
        print(json.dumps(payload, indent=2))
        return int(bool(findings))
    if args.ownership_tree and isinstance(result, OwnershipTree):
        print("Ownership tree establishment:")
        print_ownership_tree(result)
    if findings:
        print(
            f"BSA profile failed with {len(findings)} violation(s). "
            "Review each finding against the project's architecture."
        )
        for finding in findings:
            location = finding.file or finding.src
            if finding.line:
                location += f":{finding.line}"
            print(f"{location}: {finding.rule}: {finding.reason}")
    else:
        print("OK")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
