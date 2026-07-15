from pathlib import Path

from typer.testing import CliRunner

from kylinbootlab.cli import app
from tests.helpers import RUN_ID, create_probe_bundle

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout == "0.1.0\n"


def test_ingest_and_report_commands(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    data_root = tmp_path / "runs"

    ingest_result = runner.invoke(
        app,
        ["ingest", str(bundle), "--data-root", str(data_root)],
    )
    report_result = runner.invoke(
        app,
        ["report", str(RUN_ID), "--data-root", str(data_root)],
    )

    assert ingest_result.exit_code == 0
    assert str(RUN_ID) in ingest_result.stdout
    assert report_result.exit_code == 0
    assert (data_root / str(RUN_ID) / "reports/baseline.html").is_file()
