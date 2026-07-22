import json
from pathlib import Path

from kylinbootlab.report import readiness_seconds, seconds, write_baseline_report
from kylinbootlab.store import RunStore
from tests.helpers import RUN_ID, CaptureFixture, create_probe_bundle


def test_seconds_formats_none_as_not_reported() -> None:
    assert seconds(None) == "not reported"


def test_seconds_formats_nanoseconds() -> None:
    assert seconds(1_500_000_000) == "1.500 s"


def test_report_writes_metrics_and_html_deterministically(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.ingest(create_probe_bundle(tmp_path / "source"))

    first = write_baseline_report(store, RUN_ID)
    first_json = first.metrics_json.read_bytes()
    first_html = first.html.read_bytes()
    second = write_baseline_report(store, RUN_ID)

    metrics = json.loads(first.metrics_json.read_text(encoding="utf-8"))
    assert metrics["boot"]["os_total_ns"] == 3_000_000_000
    assert metrics["units"][0]["unit"] == "NetworkManager.service"
    assert "KylinBootLab Baseline" in first.html.read_text(encoding="utf-8")
    assert second.metrics_json.read_bytes() == first_json
    assert second.html.read_bytes() == first_html


FIXTURE_EVENTS = Path("tests/fixtures/readiness-events-v1.jsonl").read_text(encoding="utf-8")


def _readiness_capture(stdout: str) -> CaptureFixture:
    return {
        "command": ["cat", "/var/lib/kylinbootlab/observe/current.jsonl"],
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
    }


def test_readiness_seconds_formats_none_as_not_measured() -> None:
    assert readiness_seconds(None) == "not measured"
    assert readiness_seconds(18_100_000_000) == "18.100 s"


def test_report_includes_complete_readiness_timeline(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.ingest(
        create_probe_bundle(
            tmp_path / "source",
            optional_captures={"readiness-events": _readiness_capture(FIXTURE_EVENTS)},
        )
    )

    paths = write_baseline_report(store, RUN_ID)

    metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    assert metrics["readiness"]["status"] == "complete"
    assert metrics["readiness"]["mode"] == "benchmark"
    assert metrics["readiness"]["login_ready_ns"] == 8_500_000_000
    assert metrics["readiness"]["usable_ns"] == 18_100_000_000
    html = paths.html.read_text(encoding="utf-8")
    assert "User-perceived readiness" in html
    assert "18.100 s" in html  # Tusable
    assert "11.500 s" in html  # Tsession


def test_report_marks_absent_readiness(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.ingest(create_probe_bundle(tmp_path / "source"))

    paths = write_baseline_report(store, RUN_ID)

    metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    assert metrics["readiness"]["status"] == "absent"
    assert "observer not deployed" in paths.html.read_text(encoding="utf-8")


def test_report_renders_incomplete_readiness_as_not_measured(tmp_path: Path) -> None:
    # Events through session_opened only — no usable, no timeout marker yet.
    truncated = "\n".join(FIXTURE_EVENTS.splitlines()[:8]) + "\n"
    store = RunStore(tmp_path / "runs")
    store.ingest(
        create_probe_bundle(
            tmp_path / "source",
            optional_captures={"readiness-events": _readiness_capture(truncated)},
        )
    )

    paths = write_baseline_report(store, RUN_ID)

    metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    assert metrics["readiness"]["status"] == "incomplete"
    assert metrics["readiness"]["usable_ns"] is None
    html = paths.html.read_text(encoding="utf-8")
    assert "not measured" in html  # usable + sentinel cards
    assert "11.500 s" in html  # session still shown
