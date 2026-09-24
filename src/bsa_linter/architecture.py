"""BSA architecture, violations, and well-formedness checks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ImportEdge:
    src: str
    tgt: str
    symbol: str | None = None
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Violation:
    rule: str
    src: str
    tgt: str
    reason: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True)
class Architecture:
    namespace: str
    modules: frozenset[str]
    packages: frozenset[str]
    boundaries: frozenset[str]
    entries: frozenset[str]
    api_entries: frozenset[str]
    routes: frozenset[str]
    support: frozenset[str]
    http_support: frozenset[str]
    composition: frozenset[str]
    files: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    imports: tuple[ImportEdge, ...] = ()
    issues: tuple[Violation, ...] = ()

    def file_of(self, module: str) -> str:
        return self.files.get(module, "")

    @property
    def owner_dependencies(self) -> frozenset[tuple[str, str]]:
        """Observed dependencies between the application's top-level business owners."""
        return owner_dependencies_from_imports(self)

    @property
    def dependency_graphs_by_owner(self) -> dict[str, frozenset[tuple[str, str]]]:
        """Dependencies between siblings at each level of the ownership tree."""
        scopes = {self.namespace} | {
            parent(package)
            for package in self.packages
            if package != self.namespace and under(self.namespace, package)
        }
        return {scope: owner_dependencies_from_imports(self, scope) for scope in sorted(scopes)}


@dataclass(frozen=True)
class WellFormed:
    architecture: Architecture


@dataclass(frozen=True)
class OwnershipTree:
    """Containment between owners, with separate dependencies between siblings."""

    owner: str
    children: tuple[OwnershipTree, ...] = ()
    dependencies: frozenset[tuple[str, str]] = frozenset()

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "children": [child.to_dict() for child in self.children],
            "dependencies": [
                {"src": source, "tgt": target} for source, target in sorted(self.dependencies)
            ],
        }


NOT_ANCHOR = {"commands", "deps", "queries"}
SURFACES = {"deps", "commands"}
TRANSPORT = {"fastapi", "flask", "starlette"}
TECHNICAL_BUCKETS = {
    "model",
    "models",
    "repositories",
    "services",
    "contracts",
    "types",
    "schemas",
    "domain",
    "entities",
    "dto",
    "capabilities",
    "assembly",
    "stores",
}


def under(parent: str, child: str) -> bool:
    return child == parent or child.startswith(f"{parent}.")


def under_any(parents: set[str] | frozenset[str], module: str) -> bool:
    return any(under(parent, module) for parent in parents)


def parent(module: str) -> str:
    return module.rpartition(".")[0]


def leaf(module: str) -> str:
    return module.rpartition(".")[2]


def is_test(module: str) -> bool:
    return under("tests", module)


def cycle_paths(edges: set[tuple[str, str]]) -> list[list[str]]:
    adjacent: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        adjacent[source].add(target)
    state: dict[str, int] = {}
    stack: list[str] = []
    found: list[list[str]] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in sorted(adjacent[node]):
            if state.get(target) == 1:
                found.append(stack[stack.index(target) :] + [target])
            elif state.get(target, 0) == 0:
                visit(target)
        stack.pop()
        state[node] = 2

    for node in sorted({x for edge in edges for x in edge}):
        if state.get(node, 0) == 0:
            visit(node)
    return found


def declared_owners(architecture: Architecture) -> set[str]:
    return (
        set(architecture.packages)
        | architecture.support
        | architecture.composition
        | architecture.http_support
    )


def entry_modules(architecture: Architecture) -> set[str]:
    return set(architecture.entries) | {m for m in architecture.modules if is_test(m)}


def owner_of(architecture: Architecture, module: str) -> str | None:
    if module in entry_modules(architecture):
        return module
    return max(
        (d for d in declared_owners(architecture) if under(d, module)), key=len, default=None
    )


def is_ui(architecture: Architecture, module: str) -> bool:
    return under_any(architecture.http_support, module)


def is_http(architecture: Architecture, module: str) -> bool:
    return (
        module in architecture.api_entries | architecture.routes
        or is_test(module)
        or is_ui(architecture, module)
    )


def is_edge(architecture: Architecture, module: str) -> bool:
    return (
        module in entry_modules(architecture)
        or is_http(architecture, module)
        or under_any(architecture.composition, module)
    )


def is_factory(architecture: Architecture, module: str) -> bool:
    owner = owner_of(architecture, module)
    return owner in declared_owners(architecture) and module == f"{owner}.deps"


def is_anchor(architecture: Architecture, module: str) -> bool:
    owner = owner_of(architecture, module)
    return (
        module in architecture.boundaries
        or owner in architecture.boundaries
        and parent(module) == owner
        and leaf(module) not in NOT_ANCHOR
        and module not in architecture.routes
    )


def business_owner(architecture: Architecture, owner: str | None) -> bool:
    return (
        owner is not None
        and owner in architecture.boundaries
        and not under_any(
            architecture.support | architecture.http_support | architecture.composition, owner
        )
    )


def boundary_in_scope(
    architecture: Architecture, module: str, scope: str | None = None
) -> str | None:
    """Resolve a module to the direct child boundary visible in this scope."""
    scope = architecture.namespace if scope is None else scope
    owner = owner_of(architecture, module)
    if owner is None or scope == architecture.namespace and not business_owner(architecture, owner):
        return None
    return min(
        (
            d
            for d in declared_owners(architecture)
            if parent(d) == scope
            and under(d, owner)
            and (scope != architecture.namespace or business_owner(architecture, d))
        ),
        key=len,
        default=None,
    )


def owner_dependencies_from_imports(
    architecture: Architecture, scope: str | None = None
) -> frozenset[tuple[str, str]]:
    """Collapse local imports to sibling boundaries; default to the application root.

    Descendants collapse to their direct child of scope. Imports involving the
    scope itself or an outside boundary remain subject to the import rules, but
    are not relationships between this scope's children.
    """
    return frozenset(
        (source, target)
        for edge in architecture.imports
        if edge.tgt in architecture.modules
        if (source := boundary_in_scope(architecture, edge.src, scope))
        and (target := boundary_in_scope(architecture, edge.tgt, scope))
        and source != target
    )


def private_exception(architecture: Architecture, source: str, target: str) -> bool:
    return (
        (is_test(source) and is_test(target))
        or (source in architecture.api_entries and is_ui(architecture, target))
        or (source in architecture.routes and is_ui(architecture, target))
    )


def public_surface(architecture: Architecture, source: str, target: str) -> bool:
    owner = owner_of(architecture, target)
    return owner is not None and (
        target == owner
        or target in {f"{owner}.{name}" for name in SURFACES}
        or (target in architecture.routes and source in architecture.api_entries)
        or (is_test(source) and is_test(target))
    )


def make_violation(
    architecture: Architecture,
    rule: str,
    source: str,
    target: str,
    reason: str,
    edge: ImportEdge | None = None,
) -> Violation:
    return Violation(
        rule,
        source,
        target,
        reason,
        edge.file or architecture.file_of(source) if edge else architecture.file_of(source),
        edge.line or 1 if edge else 1,
    )


def technical_naming_violations(architecture: Architecture) -> list[Violation]:
    findings: list[Violation] = []
    shared_api_models = {f"{root}.api_models" for root in architecture.http_support}
    for module in sorted(architecture.modules):
        if is_test(module) or module in shared_api_models:
            continue
        if any(
            part in TECHNICAL_BUCKETS
            or any(part.endswith(f"_{bucket}") for bucket in TECHNICAL_BUCKETS)
            or part.startswith("in_memory_")
            for part in module.split(".")
        ):
            findings.append(
                make_violation(
                    architecture,
                    "python-layout",
                    module,
                    module,
                    "Technical bucket or storage-specific module splits a concept",
                )
            )
    return findings


def ownership_violations(architecture: Architecture) -> list[Violation]:
    findings = [
        make_violation(
            architecture,
            "ownership",
            edge.src,
            edge.tgt,
            "Production source depends on test code",
            edge,
        )
        for edge in architecture.imports
        if not is_test(edge.src) and is_test(edge.tgt)
    ]
    if not architecture.namespace or not any(
        business_owner(architecture, b) for b in architecture.boundaries
    ):
        findings.append(
            Violation(
                "ownership",
                "application",
                "application",
                "No application namespace with owned capability packages; not a vacuous pass",
            )
        )
    declared_packages = (
        {architecture.namespace}
        | architecture.boundaries
        | architecture.support
        | architecture.http_support
        | architecture.composition
    )
    # A support role applies to its subtree, while each package remains its own
    # direct owner for public-surface, private-access, and dependency checks.
    declared_packages |= {
        package
        for package in architecture.packages
        if under_any(
            architecture.support | architecture.http_support | architecture.composition, package
        )
    }
    for package in sorted(architecture.packages - declared_packages):
        findings.append(
            make_violation(
                architecture,
                "ownership",
                package,
                package,
                "Package has no declared boundary or support role",
            )
        )
    for module in sorted(architecture.modules):
        if is_test(module):
            continue
        owner = owner_of(architecture, module)
        if owner is None:
            findings.append(
                make_violation(
                    architecture,
                    "ownership",
                    module,
                    module,
                    "Application module has no declared owner",
                )
            )
        elif (
            owner == architecture.namespace
            and module != owner
            and not is_edge(architecture, module)
            and not is_factory(architecture, module)
        ):
            findings.append(
                make_violation(
                    architecture,
                    "ownership",
                    module,
                    module,
                    "Company namespace permits only declared entry adapters and owned boundaries",
                )
            )
    return findings


def private_access_violation(architecture: Architecture, edge: ImportEdge) -> Violation | None:
    if edge.tgt not in architecture.modules:
        return None
    target_owner = owner_of(architecture, edge.tgt)
    source_owner = owner_of(architecture, edge.src)
    if target_owner is None or source_owner is None:
        return None
    private_commands = under(f"{target_owner}._commands", edge.tgt)
    allowed_commands = edge.src in {
        f"{target_owner}.commands",
        f"{target_owner}.deps",
    } or under(f"{target_owner}._commands", edge.src)
    if private_commands and not allowed_commands:
        return make_violation(
            architecture,
            "private-access",
            edge.src,
            edge.tgt,
            f"{edge.src} -> {edge.tgt}: Operations are private to "
            "commands.py, deps.py, and their own command branch",
            edge,
        )
    if (
        source_owner != target_owner
        and not private_exception(architecture, edge.src, edge.tgt)
        and (
            any(part.startswith("_") and part != "__init__" for part in edge.tgt.split("."))
            or bool(edge.symbol and edge.symbol.startswith("_"))
        )
    ):
        return make_violation(
            architecture,
            "private-access",
            edge.src,
            edge.tgt,
            f"{edge.src} -> {edge.tgt}: Foreign owner accesses a private implementation",
            edge,
        )
    return None


def surface_violation(architecture: Architecture, edge: ImportEdge) -> Violation | None:
    if edge.tgt not in architecture.modules:
        return None
    source_owner, target_owner = owner_of(architecture, edge.src), owner_of(architecture, edge.tgt)
    if (
        source_owner is None
        or target_owner is None
        or source_owner == target_owner
        or private_exception(architecture, edge.src, edge.tgt)
    ):
        return None
    if not public_surface(architecture, edge.src, edge.tgt):
        reason = "Foreign concept leaf/private module bypasses its public surface"
    elif (
        edge.tgt.endswith(".deps")
        and not is_edge(architecture, edge.src)
        and not is_factory(architecture, edge.src)
    ):
        reason = "Factory surface used by an unsupported audience"
    else:
        return None
    return make_violation(
        architecture,
        "public-surfaces",
        edge.src,
        edge.tgt,
        f"{edge.src} -> {edge.tgt}: {reason}",
        edge,
    )


def direction_violation(architecture: Architecture, edge: ImportEdge) -> Violation | None:
    source, target = edge.src, edge.tgt
    source_owner, target_owner = owner_of(architecture, source), owner_of(architecture, target)
    if under_any(TRANSPORT, target):
        return None
    reason = None
    if (
        target in architecture.routes
        and source not in architecture.api_entries
        and target in architecture.modules
    ):
        reason = "Only a declared API entry assembles capability HTTP surfaces"
    elif is_ui(architecture, target) and not is_http(architecture, source):
        reason = "Non-HTTP source imports shared HTTP support"
    elif is_ui(architecture, source) and business_owner(architecture, target_owner):
        reason = "Shared HTTP support depends on a business capability"
    elif under_any(architecture.support, source) and business_owner(architecture, target_owner):
        reason = "Support source depends on a business capability"
    elif under_any(architecture.support, source) and under_any(architecture.composition, target):
        reason = "Support source depends on application composition"
    elif (
        not is_edge(architecture, source)
        and target in entry_modules(architecture)
        and target in architecture.modules
    ):
        reason = "Domain source imports an entry adapter"
    elif (
        source in entry_modules(architecture)
        and target in entry_modules(architecture)
        and source != target
        and not is_test(source)
        and target in architecture.modules
    ):
        reason = "Entry adapters depend on one another"
    elif source == architecture.namespace and target.startswith(f"{source}."):
        reason = "Company root must remain a namespace"
    elif (
        is_anchor(architecture, source)
        and target_owner is not None
        and target_owner != source_owner
        and target.startswith(f"{source_owner}.")
    ):
        reason = "Parent anchor imports a child boundary"
    elif (
        is_anchor(architecture, source)
        and source_owner == source
        and target_owner is not None
        and target_owner != source_owner
    ):
        reason = "Boundary root must select its own concept vocabulary"
    elif is_anchor(architecture, source) and (
        target.endswith((".commands", ".deps")) or target in architecture.routes
    ):
        reason = "Anchor depends on an operation or composition surface"
    return (
        make_violation(
            architecture, "direction", source, target, f"{source} -> {target}: {reason}", edge
        )
        if reason
        else None
    )


def composition_import_violation(architecture: Architecture, edge: ImportEdge) -> Violation | None:
    source, target = edge.src, edge.tgt
    reason = None
    if under_any(TRANSPORT, target) and not is_http(architecture, source):
        reason = "Non-HTTP source imports a transport framework"
    elif (
        (
            target.endswith(".deps")
            or under(f"{architecture.namespace}.settings", target)
            or under_any(architecture.composition, target)
        )
        and not is_edge(architecture, source)
        and not is_factory(architecture, source)
    ):
        reason = "Business source or anchor imports composition/settings"
    return (
        make_violation(
            architecture, "composition", source, target, f"{source} -> {target}: {reason}", edge
        )
        if reason
        else None
    )


def cycle_violations(architecture: Architecture) -> list[Violation]:
    edges = {
        (edge.src, edge.tgt)
        for edge in architecture.imports
        if edge.tgt in architecture.modules and edge.src != edge.tgt
    }
    return [
        make_violation(architecture, "cycles", path[0], path[0], " -> ".join(path))
        for path in cycle_paths(edges)
    ]


def owner_dependency_cycle_violations(architecture: Architecture) -> list[Violation]:
    return [
        make_violation(architecture, "owner-dependency-cycle", path[0], path[0], " -> ".join(path))
        for edges in architecture.dependency_graphs_by_owner.values()
        for path in cycle_paths(set(edges))
    ]


def collect_violations(architecture: Architecture) -> list[Violation]:
    findings = (
        list(architecture.issues)
        + technical_naming_violations(architecture)
        + ownership_violations(architecture)
        + cycle_violations(architecture)
    )
    for edge in architecture.imports:
        for check in (
            surface_violation,
            private_access_violation,
            direction_violation,
            composition_import_violation,
        ):
            if finding := check(architecture, edge):
                findings.append(finding)
    findings.extend(owner_dependency_cycle_violations(architecture))
    return list(dict.fromkeys(findings))


def lint_architecture(architecture: Architecture) -> WellFormed | list[Violation]:
    findings = collect_violations(architecture)
    return findings if findings else WellFormed(architecture)


def establish_ownership_tree(architecture: Architecture) -> OwnershipTree | list[Violation]:
    """Return an assertable ownership tree, or every violation that prevents establishment."""
    findings = collect_violations(architecture)
    if findings:
        return findings
    owners = {
        owner
        for owner in declared_owners(architecture) | architecture.entries
        if under(architecture.namespace, owner)
    }
    children: dict[str, list[str]] = defaultdict(list)
    for owner in sorted(owners - {architecture.namespace}):
        direct_parent = max(
            (candidate for candidate in owners if candidate != owner and under(candidate, owner)),
            key=len,
        )
        children[direct_parent].append(owner)
    dependencies = architecture.dependency_graphs_by_owner

    def branch(owner: str) -> OwnershipTree:
        return OwnershipTree(
            owner=owner,
            children=tuple(branch(child) for child in children[owner]),
            dependencies=dependencies.get(owner, frozenset()),
        )

    return branch(architecture.namespace)
