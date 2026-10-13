UV ?= uv
export UV

.PHONY: check test lint sample check-package

check: lint test sample

lint:
	$(UV) run --frozen pyright
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .

test:
	$(UV) run --frozen pytest

sample:
	$(UV) run --frozen bsa-lint --root ../samples/bsa-python
	$(UV) run --frozen bsa-lint --root ../samples/meridian-python

check-package:
	$(UV) run --frozen python tests/packaging/check_package.py
