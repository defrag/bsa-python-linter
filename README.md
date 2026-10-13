# BSA Python architecture linter

The shared Python linter checks source organization, ownership, and allowed
imports. It infers roles from the source layout, combines Tach's file dependency
map with Python AST inspection, and checks the resulting graph without importing
or executing the application. Its rules contain no sample-specific business names.

This document describes the **implemented checks**. The
[Python guide](../samples/bsa-python/AGENTS.md) also contains design and runtime
requirements that this linter does not enforce; see [Limits](#limits).

## Run it

From this package directory:

```sh
uv sync --frozen
uv run --frozen bsa-lint --root ../samples/bsa-python
uv run --frozen bsa-lint --root ../samples/meridian-python
uv run --frozen bsa-lint --root /path/to/application --json
uv run --frozen bsa-lint --root /path/to/application --ownership-tree
uv run --frozen bsa-lint --root /path/to/application --ownership-tree --json
```

`--root` is the source directory containing the application package and `tests/`,
not the application package itself. For example, point it at the directory
containing `folio/__init__.py`. There must be exactly one application root package
and at least one business capability package. A flat collection of files, or an
application with no capability boundaries, cannot obtain a vacuous pass.

| Exit | Meaning |
| --- | --- |
| `0` | The ownership tree and imports conform to this profile. Text output ends with `OK`. |
| `1` | Violations were found. Text output includes locations, rule names, and reasons. |
| `2` | The invocation or extraction failed, for example an invalid root, ambiguous application namespace, or failed Tach command. |

JSON output contains `pass` and `violations`. Each violation has `rule`, `src`,
`tgt`, `reason`, `file`, and `line`. `--ownership-tree --json` additionally includes
`ownership_tree` on success. A failed tree is never presented as established.
Tool errors use stderr rather than a successful JSON report. One import can
violate several independent rules and therefore produce several findings.

## How source roles are inferred

Roles come from paths, not class names, `__all__`, or a role configuration in
`pyproject.toml`. Optional roles do not require creating otherwise unnecessary
files. In the following examples, `folio` is an illustrative application name.

| Location | Inferred role and responsibility |
| --- | --- |
| `folio/__init__.py` | Application namespace. It cannot import its own descendants to aggregate the application. |
| `folio/catalog/__init__.py` | Business boundary and public vocabulary root. It selects concepts owned by that boundary. |
| `folio/catalog/book.py` | Direct concept module, called an **anchor** by the checker. It stays independent of operations, composition, and child boundaries. |
| `folio/catalog/editions/__init__.py` | A child business boundary. Its parent does not own its implementation. |
| `folio/catalog/_commands/register.py` | Private implementation belonging to `catalog`; underscore branches do not establish new owners. |
| `folio/catalog/commands.py` | Public operation surface. The guide uses it for command values. |
| `folio/catalog/deps.py` | The direct owner's factory surface. It may assemble that owner's implementation and consume supported foreign factories. |
| `folio/catalog/queries.py` | Ordinary non-anchor implementation. It is not a public cross-owner surface. |
| `folio/catalog/api_routes.py` | Capability HTTP surface. Only the application API entry may import it. |
| `folio/api.py` | API entry; may assemble capability HTTP surfaces. |
| `folio/cli.py`, `worker.py`, `main.py`, `application.py` | Other application entries; may assemble public factories, but do not gain HTTP permissions. |
| `folio/scope.py`, `folio/bootstrap.py` | Application composition: resource definitions/binding and setup/teardown respectively. Packages with these names also carry the role through their subtrees. |
| `folio/foundation`, `shared`, `settings`, `errors`, `database` | Independent support, as files or packages immediately below the application root. `settings` additionally has a restricted import audience. |
| `folio/api_support` | Shared HTTP support, as a file or package immediately below the application root. |
| `tests/` | Test entry modules. They may use supported production surfaces and collaborate with test helpers. Production cannot import them. |

An anchor is a business boundary root or a public module directly inside that
boundary, excluding `commands`, `deps`, `queries`, and the recognized HTTP route
surface. This is a source-location rule; the checker does not inspect whether a
class is an entity, repository, command, or handler to assign the role.

The nearest recognized package or support/composition boundary is the direct
owner. Private underscore branches preserve that owner even when they contain
`__init__.py` files and nested directories. Public child packages create new
owners. Entries and test modules are treated as their own entry owners.

Application roles apply only at their designated locations. For example,
`folio/catalog/scope.py` is an ordinary business module, and
`folio/catalog/_commands/deps.py` is not `catalog`'s factory. Renaming a file to a
technical role inside another branch cannot grant it extra permissions.

### Value objects and errors stay with their concepts

There is no `values` support role. `BookId` and `Title` belong with `Book` in
`catalog/book.py`; `LoanId` and `Borrower` belong with `Loan` in `loans/loan.py`.
Generic `values.py`, `values/`, and `*_values.py` containers are rejected as
technical buckets, including below shared support.

An optional root `errors.py` does not collect all application errors. Keep
`BookNotFound` and `BookExists` with the book concept, and `LoanNotFound` and
`BookOnLoan` with the loan concept. Export these through the owning capability's
root when consumers need them. Shared support can define a base exception and
generic categories such as invalid input, missing resource, or conflict. It must
not maintain a catalog of every capability's error codes. HTTP adapters translate
errors to status codes and wire responses.

The checker enforces support independence and source ownership, but cannot infer
that a literal error-code list is secretly business vocabulary. The
[Folio example](../samples/bsa-python/folio/catalog/book.py) and design review cover
that semantic distinction; a passing import graph alone does not establish it.

## Rule reference

Every connection must satisfy all applicable rules. “Allowed” below means the
illustrated import is permitted, provided the rest of the layout, direction, and
cycle checks also pass. The snippets are alternatives, not a complete application.

### `python-layout`: packages and concept-oriented names

Directories containing Python source must have `__init__.py`, including private
branches. Production source cannot split concepts into technical buckets. The
current bucket names are:

```text
model models repositories services contracts types values schemas domain entities
dto capabilities assembly stores
```

The check applies to each dotted path segment: an exact bucket name, a name
ending in `_<bucket>`, or a name starting with `in_memory_` is rejected. Thus
`models.py`, `book_dto.py`, `_stores/`, and `in_memory_books.py` fail. A concept
module such as `book.py` may contain its value types, repository contract, and
implementation together. A class named `InMemoryBooks` is not itself a violation.
Test modules are exempt from these naming rules. The exact shared HTTP module
`folio/api_support/api_models.py` is also exempt; this is not a general exemption
for every module under HTTP support.

These obsolete role names are rejected at their role locations:

| Rejected location/name | Current name |
| --- | --- |
| Application-root `_ui` or `http_support` | `api_support` |
| Application-root `composition` | `scope` for binding; `bootstrap` for setup/teardown |
| Business boundary's `routes` or `http_routes` | `api_routes` |

### `ownership`: every module belongs somewhere

The application must have a namespace and owned capabilities. Ordinary business
files cannot sit directly under the application namespace: they belong inside a
capability. Root-level entries, recognized support/composition, and the root
factory location are handled by their respective roles.

Production source cannot import `tests`, even through an entry or composition
module. Tests do not gain access to production implementation merely because they
are tests. Unreadable or syntactically invalid source and source symlinks also
produce ownership findings; see [Source extraction](#source-extraction).

### `public-surfaces`: cross-owner imports use supported surfaces

For a foreign owner, the supported target locations are its root, `commands`,
and `deps`, subject to their audiences. API entries additionally use capability
`api_routes`. A concept leaf such as `catalog.book` is implementation relative
to foreign owners, even if its classes have public names. `queries.py` is not an
additional public surface.

```python
# folio/lending/loan.py
from folio.catalog import BookId  # allowed: foreign public vocabulary
from folio.catalog.book import BookId  # forbidden: bypasses catalog's root

# folio/catalog/deps.py
from folio.catalog.book import Books  # allowed: own concept implementation

# folio/lending/deps.py
from folio.catalog.deps import get_books  # allowed: factory to factory
```

Foreign owners include parents and children, not only siblings. A child can use
its parent's public vocabulary, but cannot bypass it to reach the parent's
concept file or private implementation. Parent factories likewise cannot reach
into a child's private files.

API entries and capability routes may import public modules within shared
`api_support`, such as `api_support.api_models`. This exception does not permit
private modules or private symbols. Other callers, including tests, still use
that support owner's public surfaces.

### `private-access`: privacy follows ownership

A foreign owner cannot import a module through an underscore path segment or an
underscore-prefixed symbol from a local module. Renaming the imported symbol does
not make it public. This applies to business owners, support, parents, children,
entries, and tests.

```python
# folio/lending/_commands/borrow.py
from folio.catalog._storage import cache  # forbidden: foreign private module
from folio.catalog import _cache as cache  # forbidden: foreign private symbol

# folio/catalog/deps.py
from folio.catalog._commands.register import RegisterHandler  # allowed: own code
```

Same-owner implementation can collaborate across private descendants and sibling
branches, provided imports remain acyclic and satisfy role restrictions. There
is a stricter rule for `_commands`: the owner's roots, anchors, and HTTP routes
cannot import it directly. Its own `commands`, `deps`, and non-anchor
implementation can. Routes use the public command and factory surfaces instead.
Test helpers may import one another's private test implementation; that exception
does not extend to private production source.

**This import permission does not enforce the guide's ban on handler reuse.**
The checker can allow an acyclic same-owner `_commands` import without knowing
whether it imports a command value or another handler. See [Limits](#limits).

### `direction`: roots, anchors, support, and entries

The checker rejects these import directions independently of public/private access:

| Source | Forbidden target or direction |
| --- | --- |
| Application root | Its own descendants; the root remains a namespace. |
| Business boundary root | Any different local owner; a root selects its own concept vocabulary rather than forwarding another owner's exports. |
| Parent anchor | A child boundary, even through that child's public root. |
| Any anchor | `commands`, `deps`, or a capability HTTP route surface. |
| Independent support, including nested support | A business owner or application composition. |
| Application `scope`, including its subtree | Business owners, factory surfaces, or `bootstrap`; resource definitions/binding stay independent of business initialization. |
| Shared HTTP support | A business owner. |
| Non-HTTP source | Shared HTTP support. |
| Business implementation | An entry adapter. |
| Production entry | Another entry adapter. |
| Composition or shared HTTP support | Any entry adapter; entries assemble these helpers, not the reverse. |
| Any caller except the application API entry | A capability's `api_routes`. This includes tests importing the route module directly. |

A concept module can use another owner's public vocabulary when it does not
violate the parent/child rule. The boundary root itself cannot aggregate that
foreign vocabulary:

```python
# folio/lending/loan.py
from folio.catalog import BookId  # allowed: lending concept uses catalog vocabulary

# folio/lending/__init__.py
from .loan import Loan  # allowed: selects its own concept
from folio.catalog import BookId  # forbidden: root forwards a foreign owner
from .history import LoanEvent  # forbidden when history is a child boundary
```

A child may depend on its parent's public concept anchor through the parent root;
the parent anchor stays independent of its children. Support remains independent
of business even when the proposed target is a public root. Dependencies between
support owners still use public surfaces and remain acyclic.

### `composition`: wiring and transport have restricted audiences

Factory, settings, and application-composition imports are permitted for edge
modules and direct-owner factories. Edge modules are application entries, tests,
capability HTTP routes, shared HTTP support, and application composition. Other
rules still apply: for example, shared HTTP support cannot use a business factory
because it cannot depend on business owners.

Ordinary business implementation, queries, and anchors cannot import `deps`,
application `settings`, `scope`, or `bootstrap`, including from their own owner
where applicable. Being inside `_commands` does not grant factory permissions.
Modules inside a settings package may import its own implementation; ordinary
ownership, public-surface, private-access, and cycle checks still apply there.

```python
# folio/lending/deps.py
from folio.scope import current_scope  # allowed: factory reads application binding
from folio.catalog.deps import get_books  # allowed: supported foreign factory

# folio/lending/_commands/borrow.py
from folio.lending.deps import get_loans  # forbidden: business imports wiring
from folio.catalog.deps import Books  # forbidden even when used only as a type
from folio.settings import Settings  # forbidden: business imports settings
```

Imports from `fastapi`, `flask`, and `starlette` (including submodules) are allowed
only for HTTP callers: the API entry, capability HTTP routes, shared HTTP support,
and tests. CLI/worker entries, factories, application composition, ordinary
support, and business modules cannot import those frameworks.

The linter checks these imports, not what constructors or factories do. It does
not prove that a factory is synchronous, parameterless, free of I/O, or returns
an appropriate type.

### `cycles` and `owner-dependency-cycle`: check both graphs

`cycles` rejects cycles between source modules, including private branches and
support modules. `owner-dependency-cycle` additionally rejects cycles between
sibling owners at every depth of the ownership tree.

For example, these two imports can form an owner cycle without a file cycle:

```text
folio.lending.loan    -> folio.catalog
folio.catalog.search -> folio.lending

collapsed owners: folio.lending -> folio.catalog -> folio.lending
```

Imports collapse to the direct child boundary visible in each scope. Dependencies
between descendants of `folio.lending.borrowing` and `folio.lending.history` become
an edge between those children of `folio.lending`. The same check applies within
nested support packages. Top-level business dependency graphs exclude support,
composition, and entries; those modules still participate in the file graph.

Duplicate edges and same-owner edges collapse away in owner graphs. Edges describe
direct observed imports, not their transitive closure. Forbidden imports remain
in the graphs: reporting another violation does not hide a dependency or cycle.

### `explicit-imports`: dependencies must be statically visible

Absolute and resolvable relative imports are supported, as are explicit aliases.
All imports must be directly at module scope. Wildcards and imports inside
functions, classes, `try` blocks, or conditionals (including `if TYPE_CHECKING`)
produce findings. An import used only for an annotation still has to obey the
same ownership and audience rules.

```python
from folio.catalog import BookId as CatalogBookId  # supported explicit alias

from folio.catalog import *  # forbidden: symbols are hidden


def load_books():
    from folio.catalog import BookId  # forbidden: import is not at module scope
```

The extractor also rejects references to `importlib.*`, `sys.modules`, `sys.path`,
and the dynamic mechanisms `__import__`, `exec`, and `eval`, including their
`builtins` forms. Taking a reference to a loader is enough to produce a finding;
it need not be called. Qualified references and simple assignment aliases are
tracked, so `import folio.catalog as catalog; catalog._cache` cannot bypass
private-symbol checks. Unresolvable relative imports also produce findings.

## Source extraction

The extractor scans `.py` files below `--root`, including tests. It skips paths
containing `.venv`, `.git`, `__pycache__`, `.pytest_cache`, `.ruff_cache`,
`.uv-cache`, or `.lake`. Python source files and source-directory symlinks are
rejected, including directory symlinks that would otherwise hide a source tree.
Source read/parse failures are retained as findings rather than ignored.

Tach supplies file dependencies; the AST supplies explicit imports, referenced
symbols, aliases, and source locations. A Tach-only local edge needs supporting
AST import evidence, so a literal module name in a source-checking tool does not
become an invented dependency. Tach failures or malformed dependency-map output
cannot produce a passing result. The linter writes no graph or temporary policy
file into the checked application.

The shared engine infers ownership from source, not from the application's Tach
boundary declarations. `tach check` and `tach check-external` are separate checks
for project-declared direction, visibility, and external dependencies. Running
`bsa-lint` does not replace them.

## Ownership tree and Python API

Containment and imports are separate relationships: `children` identifies owned
boundaries; `dependencies` identifies imports between siblings at that scope.
For example:

```text
Ownership tree establishment:
folio
  imports: folio.lending -> folio.catalog
  folio.catalog
  folio.lending
    imports: folio.lending.borrowing -> folio.lending.history
    folio.lending.borrowing
    folio.lending.history
OK
```

Owners and dependencies are sorted for stable output. The
[ownership tree tests](tests/test_ownership_tree_establishment.py) contain a larger
self-contained Folio fixture with expected trees, nested business/support owners,
allowed and forbidden imports, extraction failures, and text/JSON assertions.
That fixture is separate from the runnable samples.

The API is defined in [architecture.py](src/bsa_linter/architecture.py) and
[extract.py](src/bsa_linter/extract.py):

```python
from pathlib import Path

from bsa_linter.architecture import OwnershipTree, establish_ownership_tree
from bsa_linter.extract import extract

architecture = extract(Path("/path/to/application"))  # tach must be on PATH
result = establish_ownership_tree(architecture)
if isinstance(result, OwnershipTree):
    print(result.to_dict())
else:
    for violation in result:
        print(violation.to_dict())
```

`extract(root, tach=...)` returns an `Architecture`; `tach` can select an executable.
`lint_architecture(architecture)` returns `WellFormed | list[Violation]`.
`establish_ownership_tree(architecture)` runs the same checks and returns
`OwnershipTree | list[Violation]`. Extraction issues prevent either success result.
`tree.to_dict()` serializes each node's `owner`, `children`, and `dependencies`.

`architecture.owner_dependencies` exposes top-level business dependencies.
`architecture.dependency_graphs_by_owner` exposes sibling dependencies at each
scope, including scopes without cross-owner imports and the application root.
These observed relationships remain inspectable when the architecture has
violations.

## Limits

A passing result means the observed source structure fits this profile. It does
not establish that business boundaries are appropriate or that the program works.
In particular, the current linter does not enforce:

| Requirement | Where it needs verification |
| --- | --- |
| No handler calls, constructs, or injects another handler, including callbacks/wrappers | The guide and design review, or an explicit project check. Forbidden imports catch some cases; same-owner imports and runtime call relationships are not a general handler-reuse check. |
| Domain results retain `LoanId`, `BookId`, or other declared value objects instead of primitives | The guide, type declarations, Pyright, and domain tests. The import graph cannot choose field types. |
| `commands.py` exports only command values; `deps.py` exposes only intended factories/types | Surface review and project checks. The linter recognizes locations and privacy, not the semantic kind of every exported object. |
| Repository/resource construction happens only at the intended seam | Project-specific source checks and review. Class-name prefixes do not determine implementation roles or constructor restrictions. |
| Factories have the required signature; scopes bind correctly; resources close; operations are transactional | Type, lifecycle, and behavior tests. |
| Test adapters convert losslessly and contain no business decisions | Acceptance tests, mutation tests, and review. |
| A new one-way dependency is intended, or a third-party dependency is allowed | Project `tach.toml` contracts and architecture checks. An acyclic observed connection is not an approved product dependency. |
| Imported modules/symbols exist, exports resolve at runtime, and annotations are valid | Pyright and runtime import/startup tests. This is not a complete Python name resolver. |

Alias tracking is deliberately limited to static references and simple assignments;
it is not whole-program data-flow analysis or a security sandbox. The supported
import profile rejects known dynamic mechanisms instead of executing code to
resolve them. Other transport libraries are not automatically covered by the
explicit FastAPI/Flask/Starlette restriction.

## Development and verification

```sh
uv sync --frozen
make check          # strict Pyright, Ruff, regression tests, and both sample graphs
make check-mutations # disable each rule in a disposable copy; its test must fail
make check-package  # build/install the wheel in a temporary external consumer
```

Development uses the parent tooling workspace's `../uv.lock` and `../.venv`.
The package retains its own dependencies and Python 3.12–3.13 support. Distribution
checks under [tests/packaging](tests/packaging/) install only the wheel and declared
dependencies, exercise the installed command, and reject a private import. They
require registry access and run separately from ordinary checks.

Focused regression tests cover [layout](tests/test_layout.py),
[ownership](tests/test_ownership.py), [surfaces](tests/test_surfaces.py),
[private access](tests/test_private_access.py), [direction](tests/test_direction.py),
[composition](tests/test_composition.py), [cycles](tests/test_cycles.py), and
[extraction](tests/test_extraction.py). Role inference is in
[roles.py](src/bsa_linter/roles.py), and command output is in
[cli.py](src/bsa_linter/cli.py).

[Break-and-repair tests](tests/test_rule_regressions.py) start with a conforming
source tree, introduce a fault for each diagnostic category, assert the same
findings from both checking APIs and the JSON CLI, then restore the source and
require a passing tree. A combined case repairs multiple independent faults one
at a time, checking that remaining violations cannot disappear prematurely.

[Boundary refactor examples](tests/test_boundary_refactors.py) compare flat
modules, private folders, and public child boundaries. They check selective
re-exports, illegal imports behind re-export chains, missing package initializers,
and cycles after moving files into folders. Private folders keep their owner's
identity; public children introduce separate owners. Disjoint file imports can
therefore form a cycle between child owners even without a file cycle, while
acyclic collaboration inside one owner's private branches remains allowed.

`make check-mutations` runs a separate
[mutation check](tests/mutations/check_rules.py). It first verifies the original
tests, then disables each of the nine diagnostic categories in a temporary source
copy. Each corresponding regression must fail with an assertion; collection or
execution errors do not count as detection. The repository's checker is never
modified. This verifies resistance to those specific rule removals, not exhaustive
coverage of every possible implementation bug or architecture.

Project-specific contracts stay with their application. Run `make check` in each
sample for its local rules; Meridian also has its own
[source conventions](../samples/meridian-python/tests/conventions.py). The shared
linter's integration checks inspect both samples without importing their
implementations into the checker engine.
