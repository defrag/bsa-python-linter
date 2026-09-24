.PHONY: check test lint sample

check: lint test sample

lint:
	uv run --frozen pyright
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .

test:
	uv run --frozen pytest

sample:
	uv run --frozen bsa-lint --root ../samples/bsa-python
	uv run --frozen bsa-lint --root ../samples/meridian-python
