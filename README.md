# BSA Python architecture linter

This is the shared BSA Python linter. It checks concept-oriented naming,
ownership tree establishment, public and private imports, composition, dependencies
between owners, and cycles. Technical buckets (`models.py`, `book_dto.py`, `_stores/`)
and separate `in_memory_*` modules are rejected here, with shared HTTP API
models allowed under HTTP support. Tach supplies the file dependency map;
Python AST inspection supplies symbols, source locations, and
unsupported syntax diagnostics.
The engine contains BSA Python conventions, but no Folio or Meridian names.
Class names do not determine implementation roles or constructor restrictions.
Composition checks enforce factory/settings import audiences and transport
boundaries. Repository and resource construction policies belong in explicit
project-specific checks.
Factory permissions apply to the direct owner's `deps.py`; a file named
`_commands/deps.py` does not become a factory. Extraction preserves imported
symbols through qualified references and simple assignment aliases. References
to dynamic loaders, non-module-scope imports, and source symlinks prevent
establishment, including directory symlinks that would otherwise hide source.

Private underscore branches retain their nearest boundary's ownership. Owner
implementation and composition may consume private descendants and collaborate
across private branches with acyclic imports. Access stops at the next boundary:
parent, sibling, descendant and external owners use supported surfaces. This
includes private shared HTTP support; HTTP callers use its public surface.
Role checks remain independent: anchors and routes cannot import `_commands`,
and private implementation cannot import factories. An import permission is
not permission to aggregate a child boundary's exports through a parent root.

```sh
uv sync --frozen
uv run --frozen bsa-lint --root ../samples/bsa-python
uv run --frozen bsa-lint --root ../samples/meridian-python
uv run --frozen bsa-lint --root /path/to/application --json
uv run --frozen bsa-lint --root /path/to/application --ownership-tree
uv run --frozen bsa-lint --root /path/to/application --ownership-tree --json
make check  # strict Pyright, Ruff, tests, Folio, and Meridian
make check-package  # build and install the distribution in a temporary external consumer
```

Development uses the tooling workspace's `../uv.lock` and `../.venv`. The package
retains its own dependency declarations and Python 3.12–3.13 support. Distribution
checks install only the wheel and its declared dependencies, exercise the installed
`bsa-lint` command and reject a private import. They require registry access.

The command prints `OK` and exits 0 on a conforming tree. It prints findings
and exits 1 on violations. Extraction or tool errors exit 2. Source parse and
unsupported-import issues are findings, so an incomplete graph cannot pass.
The Python API is in [`architecture.py`](src/bsa_linter/architecture.py):
`extract(root)` builds an `Architecture`, and `lint_architecture(architecture)`
returns either `WellFormed` or `list[Violation]`.

## Ownership tree establishment

The ownership tree describes containment: each boundary owns its direct children.
Source imports establish separate dependency relationships between those owners.
Ownership tree establishment checks those relationships at every depth while
preserving each module's nearest owner.

`establish_ownership_tree(architecture)` returns `OwnershipTree | list[Violation]`:
a valid result contains the application's owners as recursive `children`, with
separate `dependencies` between siblings. Entries, support, and composition retain
their own places in the application tree. Tests can compare the returned immutable
tree directly, or assert the exact violations when establishment fails.
`tree.to_dict()` supplies a serializable structure with `owner`, `children`, and
`dependencies` fields at each node.

`architecture.owner_dependencies` exposes dependencies between top-level business owners;
`architecture.dependency_graphs_by_owner` maps each scope with child boundaries to its
observed edges, including scopes with no cross-boundary imports. The application
root is always included. These observed relationships remain inspectable when
the source contains violations.

Shared support can be a file (`shared.py` or `foundation.py`) or a package.
Modules such as `foundation/clock.py` and `foundation/identifiers.py` share the
foundation owner. Nested packages such as `foundation/clock/` have their own
direct ownership boundaries while retaining the support role. Their dependency
cycles and private surfaces are checked recursively. Support imports remain
separate from the top-level business dependency graph, and support cannot depend
on business owners at any depth.

`--ownership-tree` prints the established tree and its dependencies, followed by
`OK`. With `--json`, it adds an `ownership_tree` object on success. On failure,
the command returns violations and omits the tree. Owners and dependencies are
sorted for stable output. Extraction issues prevent establishment.

The shared engine infers BSA roles from the source tree. It requires exactly
one application root package. Every local import is mapped to its source and
target top-level capability (for example, `folio.loans._commands.borrow_book` →
`folio.catalog` becomes `folio.loans` → `folio.catalog`). Duplicate and
within-capability imports collapse away at the application level. The same
check runs inside every boundary with children: imports between descendants of
`folio.loans.borrowing` and `folio.loans.history` become an edge between those two
children in the `folio.loans` dependency graph. Each graph must be acyclic, even when the
individual files have no import cycle. Imports crossing top-level capabilities
appear in the application graph, not as foreign nodes in a child's graph.
Imports involving the parent itself still receive the ordinary ownership,
surface, private-access, and direction checks. Forbidden imports remain graph
edges; a violation does not erase an observed relationship.

The self-contained [ownership tree tests](tests/test_ownership_tree_establishment.py)
include the Folio source fixture, full expected tree, named forbidden connections,
cycles at multiple depths, support layouts, and text/JSON assertions. The cases
also cover private-symbol aliases, factory audiences, command-branch
exceptions, entry and HTTP direction, role-name scope, and extraction failures.
Borrowing owns a `BorrowingRequest` anchor in `request.py`; eligibility and limits import it
through the borrowing root. The anchor stays independent of those children.
This illustrative extension
adds child owners to exercise nesting; it is separate from the runnable Folio sample.
For this fixture, `--ownership-tree` prints:

```text
Ownership tree establishment:
folio
  imports: folio.loans -> folio.catalog
  folio.catalog
    imports: folio.catalog.editions -> folio.catalog.titles
    folio.catalog.editions
    folio.catalog.titles
  folio.loans
    imports: folio.loans.borrowing -> folio.loans.history
    folio.loans.borrowing
      imports: folio.loans.borrowing.eligibility -> folio.loans.borrowing.limits
      folio.loans.borrowing.eligibility
      folio.loans.borrowing.limits
    folio.loans.history
OK
```

Tach's dependency map and AST imports are used during
the run; no graph or temporary policy file is written into the repository.

The observed graph describes the direction already present in code. It cannot
decide whether a new one-way capability dependency was intended. If a project
needs that restriction, keep an independent declared-direction check in its
own `tach.toml` contracts or architecture tests.

## Shared checks and project checks

Project-specific checks stay with the application. Folio and Meridian each
have their own `tach.toml` contracts and architecture tests; Meridian also
has [source conventions](../samples/meridian-python/tests/conventions.py).
Run `make check` in each application for those local rules. This linter's
`make check` runs its own tests and then checks both samples with the shared
engine. Neither layer imports an application's implementation.

The linters check source structure. They cannot decide whether the inferred
business boundaries are conceptually correct or guarantee runtime behavior.

## Source roles and application wiring

Roles are inferred from source locations; no `pyproject.toml` role configuration
or skip list is used. Root-level `application.py` is an entry alongside `api.py`,
`cli.py`, `worker.py`, and `main.py`. It can assemble multiple capabilities through
public `deps.py` surfaces. Shared resource definitions/binding belong in `scope`, with setup/teardown in
`bootstrap`. Capability HTTP surfaces use `api_routes.py`. Entries and factories may
use these modules, while business and support may not. Test-only adapters stay
under tests rather than becoming production application facades.
Only `api.py` assembles capability HTTP surfaces. Entries remain independent.

Independent support belongs in `foundation`, `shared`, `settings`, `errors`,
`values`, or `database`; shared API support belongs in `api_support`.
Technical role names are exact. Alternate names such as `_ui`, `http_support`,
and `composition` at the application root, or `http_routes.py`/`routes.py` at a
capability boundary, produce layout violations.
Support and composition names grant their roles only directly below the application package.
They do not exempt imports, private code, or cycles from checking. The application
package root remains a namespace. Optional roles do not require creating files.

Distribution integration tests live under `tests/packaging/`. Their small catalog
consumer is a synthetic fixture owned by the tests; it is not an application
dependency or part of the checker engine. They run separately because they build
and install artifacts with registry access.
