# Release the Python linter

Develop in the source monorepo. Export only `src/python/architecture-linter` to
`defrag/bsa-python-linter`; keep the public repository a one-way release mirror.
Do not export the website, eval artifacts, or customer kit.

1. Update the package version and release notes. Refresh the standalone lockfile
   from a copy outside the monorepo, and refresh the parent workspace lockfile if
   package metadata or dependencies require it.
2. Run `make check check-mutations check-package` in the package, and `make sample`
   in the monorepo. Test an exported checkout independently on Python 3.12 and 3.13.
3. Commit the package changes. From the monorepo root, split and inspect the
   exported file tree and history before pushing:

   ```sh
   git subtree split --prefix=src/python/architecture-linter -b codex/python-linter-export
   git push https://github.com/defrag/bsa-python-linter.git codex/python-linter-export:main
   ```

   Use a fresh local export branch name for subsequent splits. Do not force-push
   divergent public history. Keep subtree options consistent between releases.
4. Tag the exported commit `v<package-version>` in the public repository, wait for
   its verification workflow, and create a GitHub release with the wheel and source
   archive. Build distributions with `uv build --no-sources`.
5. Configure PyPI Trusted Publishing once, then dispatch `publish.yml` on the
   public repository with that exact tag. Verify installation from PyPI in a fresh
   environment before announcing registry availability or pinning the kit to it.

## PyPI setup

For a new project, add a pending Trusted Publisher in the owning PyPI account:

- Project: `bsa-architecture-linter`
- GitHub owner: `defrag`
- Repository: `bsa-python-linter`
- Workflow: `publish.yml`
- Environment: `pypi`

Create the matching GitHub environment. The workflow obtains short-lived upload
credentials; no PyPI API token is stored in this repository. A pending publisher
does not reserve the package name until the first successful upload.

Official references: [PyPI setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [uv publishing](https://docs.astral.sh/uv/guides/publish/).
