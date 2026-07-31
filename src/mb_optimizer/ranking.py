from __future__ import annotations

from collections import defaultdict
from statistics import median

from .models import AggregatedResult, CfstResult


def aggregate_results(
    runs: list[list[CfstResult]],
    expected_ips: list[str],
) -> list[AggregatedResult]:
    if not runs:
        return []

    by_ip: dict[str, list[CfstResult]] = defaultdict(list)
    for run in runs:
        seen: set[str] = set()
        for result in run:
            if result.ip in seen or result.speed_mb_s <= 0:
                continue
            seen.add(result.ip)
            by_ip[result.ip].append(result)

    aggregates: list[AggregatedResult] = []
    minimum_successes = max(2, (len(runs) + 1) // 2)
    for ip in expected_ips:
        samples = by_ip.get(ip, [])
        if len(samples) < minimum_successes:
            continue
        latencies = [item.latency_ms for item in samples]
        median_latency = median(latencies)
        aggregates.append(
            AggregatedResult(
                ip=ip,
                region=next(
                    (item.region for item in samples if item.region != "N/A"), "N/A"
                ),
                expected_rounds=len(runs),
                successful_rounds=len(samples),
                median_loss_rate=median(item.loss_rate for item in samples),
                median_latency_ms=median_latency,
                median_speed_mb_s=median(item.speed_mb_s for item in samples),
                latency_jitter_ms=median(
                    abs(value - median_latency) for value in latencies
                ),
            )
        )
    return sorted(aggregates, key=lambda item: item.rank_key)
