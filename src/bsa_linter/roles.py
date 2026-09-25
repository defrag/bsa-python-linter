"""Infer BSA roles from the Python source tree."""

from __future__ import annotations

from bsa_linter.architecture import Architecture

ENTRY_NAMES = {"api", "cli", "worker", "main", "application"}
ROUTE_NAMES = {"api_routes", "http_routes", "routes"}
SUPPORT_NAMES = {"foundation", "shared", "settings", "errors", "values", "database"}
HTTP_SUPPORT_NAMES = {"api_support", "_ui", "http_support"}
COMPOSITION_NAMES = {"scope", "composition", "bootstrap"}


class SourceLayoutError(ValueError):
    """Candidate source cannot establish an application namespace."""


def infer_architecture(modules: set[str], packages: set[str]) -> Architecture:
    roots = {package for package in packages if "." not in package}
    if len(roots) != 1:
        raise SourceLayoutError("Source tree must contain exactly one application root package")
    namespace = roots.pop()
    support = {
        m
        for m in modules
        if m.rpartition(".")[0] == namespace and m.rsplit(".", 1)[-1] in SUPPORT_NAMES
    }
    http_support = {
        m
        for m in modules
        if m.rpartition(".")[0] == namespace and m.rsplit(".", 1)[-1] in HTTP_SUPPORT_NAMES
    }
    composition = {
        m
        for m in modules
        if m.rpartition(".")[0] == namespace and m.rsplit(".", 1)[-1] in COMPOSITION_NAMES
    }
    excluded = support | http_support | composition
    boundaries = {
        package
        for package in packages
        if package.startswith(f"{namespace}.")
        and not any(package == role or package.startswith(f"{role}.") for role in excluded)
    }
    entries = {f"{namespace}.{name}" for name in ENTRY_NAMES if f"{namespace}.{name}" in modules}
    api_entries = {f"{namespace}.api"} & entries
    routes = {
        module
        for module in modules
        if module.rsplit(".", 1)[-1] in ROUTE_NAMES and module.rpartition(".")[0] in boundaries
    }
    return Architecture(
        namespace=namespace,
        modules=frozenset(modules),
        packages=frozenset(packages),
        boundaries=frozenset(boundaries),
        entries=frozenset(entries),
        api_entries=frozenset(api_entries),
        routes=frozenset(routes),
        support=frozenset(support),
        http_support=frozenset(http_support),
        composition=frozenset(composition),
    )
