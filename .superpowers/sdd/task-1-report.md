# Task 1 Report: Bootstrap the Monorepo and Python CLI

## Status: DONE_WITH_CONCERNS

## Steps Completed

### Step 1: Install toolchains

- `uv` was already installed via winget at `C:\Users\Ruijie\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe` (v0.11.28)
- `rustup` was installed via the official rustup-init.sh script with toolchain 1.85.1 and components clippy+rustfmt
- Python 3.12.13 installed via `uv python install 3.12`

### Step 2: Config files created

- `.gitignore` -- Python/Rust build artifacts, venv, cache dirs
- `.gitattributes` -- line-ending normalization (LF for code, CRLF for .ps1)
- `.editorconfig` -- UTF-8, LF, 4-space indent (2-space for JSON/TOML/YAML)
- `.cargo/config.toml` -- target-dir = `.cargo-target`
- `rust-toolchain.toml` -- channel 1.85.1, clippy+rustfmt, minimal profile
- `pyproject.toml` -- hatchling build, typer/pydantic/jinja2/jsonschema deps, ruff/mypy/pytest dev deps
- `README.md` -- project overview

### Step 3: Python environment resolved

`uv sync --all-groups --python 3.12` resolved 32 packages, created `.venv`, and wrote `uv.lock`.

### Step 4: Failing test verified

`tests/test_cli.py` with `test_version_command_prints_package_version` was created. Running it before implementation produced `ModuleNotFoundError: No module named 'kylinbootlab'` as expected.

### Step 5: Minimal package and CLI implemented

- `src/kylinbootlab/__init__.py` -- `__version__ = "0.1.0"`
- `src/kylinbootlab/cli.py` -- Typer app with `version` command

### Step 6: Tests and CLI verified

- `uv run pytest tests/test_cli.py -v` -- **1 passed**
- `uv run kbl version` -- prints `0.1.0`

### Step 7: Static checks

- `uv run ruff check .` -- All checks passed (after auto-fix of import ordering)
- `uv run mypy src tests` -- Success: no issues found in 3 source files

### Step 8: Committed

```
415b018 chore: bootstrap KylinBootLab workspace
```

## Deviation from Plan

**cli.py requires an explicit `@app.callback()` to work with Typer 0.26.8.**

The task brief specified:

```python
app = typer.Typer(no_args_is_help=True)

@app.command()
def version() -> None:
    ...
```

However, Typer 0.26.8 (resolved by `uv sync`) changed behavior: when an app has exactly one command and no explicit callback, the single command is treated as the top-level app entry point rather than as a named subcommand. This caused `kbl version` to fail with "Got unexpected extra argument(s) (version)".

**Fix applied:** Added an explicit `@app.callback()` decorator on a `main()` function. This makes the `version` function behave as a proper subcommand. The fix adds 4 lines:

```python
@app.callback()
def main() -> None:
    """KylinBootLab controller CLI."""
```

Without this fix, the CLI is non-functional. The deviation is unavoidable with the resolved dependency versions (typer==0.26.8). If the constraint were tightened to `typer>=0.15,<0.26`, the original code would work.

## Test Summary

1 test passed (`test_version_command_prints_package_version`). Ruff and mypy pass clean.

## Code Review Fix: Restore `.worktrees/` to `.gitignore`

**Issue:** The `.gitignore` created in Step 2 replaced the old gitignore entirely with spec-mandated entries but omitted `.worktrees/`. This meant git worktree directories (including `.claude/worktrees/`) were no longer ignored and could be accidentally staged or committed.

**Fix:** Added `.worktrees/` at the top of `.gitignore`.

**Test Results:** `uv run pytest tests/test_cli.py -v` -- 1 passed (no regressions).

**Commit:** `a125faacfa6ff34552248bcfe34c5c6f137eea45`

## Final Review Fixes: Cross-filesystem move, SSH error masking, connect timeout

### Issue 1: `os.replace` not cross-filesystem atomic (`store.py`)

**Problem:** `os.replace(incoming, destination)` raises `OSError` (EXDEV) when `incoming` and `destination` are on different filesystems. A user can override `--incoming-root` independently of `--data-root`.

**Fix:** Replaced `os.replace(...)` with `shutil.move(str(incoming), str(destination))`. `shutil` was already imported. `shutil.move` handles cross-filesystem moves by falling back to copy+delete.

### Issue 2: SSH snapshot failure masked as "scp failed" (`remote.py`)

**Problem:** If `kbl-capture-run` fails before creating the output directory, SCP has nothing to copy. SCP fails, and the user sees "scp failed: No such file" instead of the actual snapshot error.

**Fix:** Before raising the SCP error, check if the snapshot also failed. If so, include the snapshot exit code and stderr in the SCP failure message:
```
scp failed (snapshot exited <N>): <scp-stderr>
snapshot stderr: <snapshot-stderr>
```

### Issue 3: No SSH connect timeout could hang indefinitely (`remote.py`)

**Problem:** SSH and SCP commands use `BatchMode=yes` but no `ConnectTimeout`. If the target is unreachable, `subprocess.run` blocks for minutes.

**Fix:** Added `-o ConnectTimeout=15` to both `ssh_snapshot_command` and `scp_command` after the `BatchMode=yes` lines. Updated the command-builder unit test to match.

### Test Results

`uv run pytest tests/test_store.py tests/test_remote.py -v` -- 10 passed (no regressions).

### Commit

(See current HEAD.)
