from datetime import datetime
from pathlib import Path

from mb_optimizer.exporter import timestamped_result_path, write_results_csv
from mb_optimizer.models import AggregatedResult


def test_export_writes_excel_compatible_csv_atomically(tmp_path: Path) -> None:
    result = AggregatedResult(
        ip="104.16.0.1",
        region="HKG",
        expected_rounds=3,
        successful_rounds=3,
        median_loss_rate=0,
        median_latency_ms=42.5,
        median_speed_mb_s=18.25,
        latency_jitter_ms=1.2,
    )
    destination = tmp_path / "result.csv"

    write_results_csv(
        destination,
        [result],
        test_url="https://example.com/download",
    )

    raw = destination.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "首选,104.16.0.1,HKG,100%" in text
    assert "用户确认直连" in text
    assert "https://example.com/download" in text
    assert not (tmp_path / ".result.csv.tmp").exists()


def test_timestamped_path_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    now = datetime(2026, 8, 1, 0, 15, 0)
    first = tmp_path / "MB-CF-Optimizer-20260801-001500.csv"
    first.write_text("existing", encoding="utf-8")

    selected = timestamped_result_path(tmp_path, now)

    assert selected.name == "MB-CF-Optimizer-20260801-001500-1.csv"
