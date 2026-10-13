"""Use Tach for file dependencies and Python AST for policy-specific details."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

from bsa_linter.architecture import (
    Architecture,
    ImportEdge,
    Violation,
    is_test,
)
from bsa_linter.roles import infer_architecture

EXCLUDE = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".uv-cache", ".lake"}
DYNAMIC = {"__import__", "exec", "eval", "builtins.__import__", "builtins.exec", "builtins.eval"}


class IssueReporter(Protocol):
    def __call__(self, rule: str, module: str, reason: str, line: int = 1) -> None: ...


def module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _tach_map(root: Path, tach: str) -> dict[str, list[str]]:
    result = subprocess.run(
        [tach, "map", "--output", "-"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise ValueError(f"Tach map failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        raw_graph: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Tach map returned invalid JSON: {exc}") from exc
    if not isinstance(raw_graph, dict):
        raise ValueError("Tach map returned an invalid file dependency graph")
    graph: dict[str, list[str]] = {}
    for source, targets in cast(dict[object, object], raw_graph).items():
        if not isinstance(source, str) or not isinstance(targets, list):
            raise ValueError("Tach map returned an invalid file dependency graph")
        validated: list[str] = []
        for target in cast(list[object], targets):
            if not isinstance(target, str):
                raise ValueError("Tach map returned an invalid file dependency graph")
            validated.append(target)
        graph[source] = validated
    return graph


def _imports_for_tree(
    module: str, path: Path, tree: ast.Module, modules: set[str], issue: IssueReporter
) -> list[ImportEdge]:
    found: list[ImportEdge] = []
    top_imports = {id(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if id(node) not in top_imports:
            issue("explicit-imports", module, "Import is not at module scope", node.lineno)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(ImportEdge(module, alias.name, file=str(path), line=node.lineno))
                bindings[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        else:
            try:
                target = (
                    importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                    if node.level
                    else node.module or ""
                )
            except (ValueError, ImportError):
                issue("explicit-imports", module, "Unresolvable relative import", node.lineno)
                continue
            for alias in node.names:
                if alias.name == "*":
                    issue(
                        "explicit-imports",
                        module,
                        "Wildcard import hides supported symbols",
                        node.lineno,
                    )
                    continue
                candidate = f"{target}.{alias.name}"
                found.append(
                    ImportEdge(
                        module,
                        candidate if candidate in modules else target,
                        alias.name,
                        str(path),
                        node.lineno,
                    )
                )
                bindings[alias.asname or alias.name] = candidate

    class References(ast.NodeVisitor):
        """Resolve direct references and simple aliases without executing source."""

        def __init__(self) -> None:
            self.bindings: dict[str, str | None] = dict(bindings)
            self.local_modules = sorted(modules, key=len, reverse=True)

        def expand(self, node: ast.AST) -> str | None:
            name = attribute_name(node)
            if not name:
                return None
            first, _, tail = name.partition(".")
            resolved = self.bindings.get(first, first)
            return resolved + (f".{tail}" if tail else "") if resolved is not None else None

        def record(self, node: ast.AST, *, dependency: bool = True) -> None:
            expanded = self.expand(node)
            if not expanded:
                return
            if (
                expanded.startswith(("importlib.", "sys.modules", "sys.path"))
                or expanded in DYNAMIC
            ):
                issue(
                    "explicit-imports",
                    module,
                    f"Unsupported dynamic dependency mechanism: {expanded}",
                    getattr(node, "lineno", 1),
                )
            if not dependency:
                return
            for target in self.local_modules:
                if target != module and expanded.startswith(f"{target}."):
                    symbol = expanded[len(target) + 1 :].partition(".")[0]
                    found.append(
                        ImportEdge(module, target, symbol, str(path), getattr(node, "lineno", 1))
                    )
                    break

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load):
                # Taking a reference to a dynamic loader already makes it unauditable,
                # including when the reference is later stored in a container or passed on.
                self.record(node, dependency=False)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            self.record(node)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            self.record(node.func)
            self.generic_visit(node)

        def bind(self, target: ast.AST, value: ast.AST | None) -> None:
            if isinstance(target, ast.Name):
                expanded = self.expand(value) if value is not None else None
                if expanded:
                    self.bindings[target.id] = expanded
                else:
                    self.bindings[target.id] = None
            else:
                self.visit(target)

        def visit_Assign(self, node: ast.Assign) -> None:
            self.visit(node.value)
            for target in node.targets:
                self.bind(target, node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)
            self.bind(node.target, node.value)

        def shadow_arguments(self, args: ast.arguments) -> None:
            arguments = args.posonlyargs + args.args + args.kwonlyargs
            if args.vararg:
                arguments.append(args.vararg)
            if args.kwarg:
                arguments.append(args.kwarg)
            for argument in arguments:
                self.bindings[argument.arg] = None

        def function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            self.visit(node.args)
            if node.returns is not None:
                self.visit(node.returns)
            outer = self.bindings
            self.bindings = dict(outer)
            self.shadow_arguments(node.args)
            for statement in node.body:
                self.visit(statement)
            self.bindings = outer
            self.bindings[node.name] = None

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.function(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            self.visit(node.args)
            outer = self.bindings
            self.bindings = dict(outer)
            self.shadow_arguments(node.args)
            self.visit(node.body)
            self.bindings = outer

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for expression in [*node.bases, *node.decorator_list, *node.keywords]:
                self.visit(expression)
            outer = self.bindings
            self.bindings = dict(outer)
            for statement in node.body:
                self.visit(statement)
            self.bindings = outer
            self.bindings[node.name] = None

    References().visit(tree)
    return found


def extract(root: Path, *, tach: str = "tach") -> Architecture:
    root = root.resolve()
    paths: dict[str, Path] = {}
    trees: dict[str, ast.Module] = {}
    issues: list[Violation] = []

    def issue(rule: str, module: str, reason: str, line: int = 1) -> None:
        finding = Violation(
            rule, module, module, reason, str(paths[module]) if module in paths else "", line
        )
        if finding not in issues:
            issues.append(finding)

    # rglob does not descend into directory symlinks. Reject them explicitly so
    # an entire hidden source owner cannot disappear from an otherwise valid tree.
    for directory in sorted(root.rglob("*")):
        relative = directory.relative_to(root)
        if any(part in EXCLUDE for part in relative.parts):
            continue
        if directory.is_symlink() and directory.is_dir():
            module = ".".join(relative.parts)
            issues.append(
                Violation(
                    "ownership",
                    module,
                    module,
                    "Source directory symlinks are outside this auditable profile",
                    str(relative),
                    1,
                )
            )

    for file in sorted(root.rglob("*.py")):
        relative = file.relative_to(root)
        if any(part in EXCLUDE for part in relative.parts):
            continue
        module = module_name(relative)
        paths[module] = relative
        if file.is_symlink():
            issue("ownership", module, "Source symlinks are outside this auditable profile")
            continue
        try:
            trees[module] = ast.parse(file.read_text(), filename=str(relative))
        except (OSError, SyntaxError, UnicodeError) as exc:
            issue("ownership", module, f"Cannot parse source: {exc}")
    modules = set(trees)
    packages = {
        module
        for module, path in paths.items()
        if module in modules
        and path.name == "__init__.py"
        and not is_test(module)
        and not any(part.startswith("_") for part in module.split("."))
    }
    architecture = infer_architecture(modules, packages)
    for directory in {
        parent for path in paths.values() for parent in path.parents if parent != Path(".")
    }:
        if directory / "__init__.py" not in paths.values() and not (
            directory == Path("tests") and (root / directory / "__init__.py").is_file()
        ):
            issue(
                "python-layout",
                str(directory).replace("/", "."),
                "Package directory lacks __init__.py",
            )
    candidates: list[ImportEdge] = []
    for module, tree in trees.items():
        path = paths[module]
        candidates.extend(_imports_for_tree(module, path, tree, modules, issue))
    tach_graph = _tach_map(root, tach)
    file_to_module = {str(path): module for module, path in paths.items() if module in modules}
    dependencies = {
        (file_to_module[src], file_to_module[tgt])
        for src, tgts in tach_graph.items()
        for tgt in tgts
        if src in file_to_module and tgt in file_to_module
    }
    # Tach sometimes treats an imported class as a path or stops at an alias's
    # package. The AST supplies precise imports; a Tach-only edge needs an AST
    # import of the same module or one of its ancestors. This prevents literal
    # module names in source-checking tools from becoming synthetic imports.
    imports = list(candidates)
    seen = {(edge.src, edge.tgt, edge.symbol, edge.line) for edge in imports}
    for src, tgt in sorted(dependencies):
        if not any(edge.src == src and edge.tgt == tgt for edge in imports):
            evidence = next(
                (
                    edge
                    for edge in candidates
                    if edge.src == src and (edge.tgt == tgt or tgt.startswith(f"{edge.tgt}."))
                ),
                None,
            )
            if evidence is None:
                continue
            edge = ImportEdge(src, tgt, file=evidence.file, line=evidence.line)
            key = (edge.src, edge.tgt, edge.symbol, edge.line)
            if key not in seen:
                imports.append(edge)
                seen.add(key)
    return replace(
        architecture,
        files={m: str(p) for m, p in paths.items() if m in modules},
        imports=tuple(dict.fromkeys(imports)),
        issues=tuple(issues),
    )
