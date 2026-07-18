$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Checked { uv run python scripts/export_schema.py --check }
Invoke-Checked { uv run ruff format --check . }
Invoke-Checked { uv run ruff check . }
Invoke-Checked { uv run mypy src tests }
Invoke-Checked { uv run pytest --cov=kylinbootlab --cov-report=term-missing }
Invoke-Checked { cargo fmt --all -- --check }
Invoke-Checked { cargo clippy --workspace --all-targets -- -D warnings }
Invoke-Checked { cargo test --workspace }
Invoke-Checked { git diff --check }
