import json
from pathlib import Path

from kylinbootlab.report import seconds, write_baseline_report
from kylinbootlab.store import RunStore
from tests.helpers import RUN_ID, create_probe_bundle


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
