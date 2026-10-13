# BSA architecture linter

This package owns the Python source graph, Tach adapter, BSA rule evaluation,
role inference, CLI, and regression tests. It is domain agnostic
and must not import samples or evaluation implementations. Tests may inspect a
sample as a fixture. Keep project names and application-only conventions in
the application's `tach.toml` and local checks.

Tach supplies file dependencies. AST inspection adds imported symbols, source
locations and extraction issues. Ownership tree establishment
preserves parent-child containment and checks separate dependency graphs by owner.
Collapse every local import to its top-level source and target owners; do not
read application `tach.toml` declarations to infer observed dependencies. Repeat the dependency check between
direct child boundaries at every depth, collapsing their descendants in that scope.
Support roles apply to their subtrees. Nested support packages remain distinct
owners and receive internal dependency-cycle checks; support never depends on
business owners. Top-level observed business dependencies exclude support.
Keep forbidden dependencies in the observed dependency data. Establishment returns
an `OwnershipTree` on success or all `Violation` values on failure. Dependency
arrows represent imports, not containment. Keep the Folio ownership tree fixture,
expected results, and its scenarios together in one self-contained test file.
Never ignore extraction issues to obtain a passing result. Preserve the nearest
capability or child boundary as direct owner. Keep project-specific
Tach dependency and visibility rules and convention tests in their owning projects.
Keep the architecture data and linting rules together in `architecture.py`;
`lint_architecture` returns `WellFormed` or a list of `Violation` values.
Technical-bucket and separated in-memory implementation names are shared BSA
rules; keep them here, not in a sample's convention checker.
These are module-layout rules. Do not infer implementation roles or constructor
restrictions from class-name prefixes.

Recognize application-root `scope.py` (or a `scope` package) as composition for
resource definitions and binding, and `bootstrap` for setup and teardown.
Shared API support is `api_support`; capability HTTP surfaces are `api_routes.py`.
Do not grant technical roles to alternate names. Report unsupported names at
their role locations as layout violations, with the current names in diagnostics.
The same names below business owners do not grant application-level permissions.
Keep runtime setup/teardown behavior outside this source/import linter.

Private underscore branches retain the nearest owner's identity. Same-owner
implementation/composition can access private descendants and siblings; preserve
cycle checks and role restrictions on anchors, routes and factories. Stop at each
child boundary. Foreign access to private source or symbols is forbidden even
for HTTP callers of shared support. Public support surfaces keep their audiences.

Run `uv sync --frozen` and `make check` here. `make check` includes passing
Folio and Meridian integration runs.
