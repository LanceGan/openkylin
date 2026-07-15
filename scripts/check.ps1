$ErrorActionPreference = "Stop"

uv run python scripts/export_schema.py --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=kylinbootlab --cov-report=term-missing
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
git diff --check
