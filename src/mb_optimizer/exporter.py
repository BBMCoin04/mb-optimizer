from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .models import AggregatedResult


CSV_HEADER = [
    "推荐",
    "IP",
    "地区",
    "成功率",
    "丢包率",
    "速度(MB/s)",
    "延迟(ms)",
    "波动(ms)",
    "网络模式",
    "测速地址",
]


def timestamped_result_path(
    directory: Path,
    now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"MB-CF-Optimizer-{timestamp}.csv"
    suffix = 1
    while candidate.exists():
        candidate = directory / f"MB-CF-Optimizer-{timestamp}-{suffix}.csv"
        suffix += 1
    return candidate


def write_results_csv(
    path: Path,
    results: Sequence[AggregatedResult],
    network_mode: str = "用户确认直连",
    test_url: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(CSV_HEADER)
            for index, result in enumerate(results):
                recommendation = (
                    "首选" if index == 0 else f"备用 {index}" if index <= 2 else ""
                )
                writer.writerow(
                    [
                        recommendation,
                        result.ip,
                        result.region,
                        f"{result.success_rate:.0%}",
                        f"{result.median_loss_rate:.0%}",
                        f"{result.median_speed_mb_s:.2f}",
                        f"{result.median_latency_ms:.1f}",
                        f"{result.latency_jitter_ms:.1f}",
                        network_mode,
                        test_url,
                    ]
                )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
