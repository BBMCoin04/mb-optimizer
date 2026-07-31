from mb_optimizer.models import CfstResult
from mb_optimizer.ranking import aggregate_results


def result(
    ip: str, *, loss: float, latency: float, speed: float, region: str = "HKG"
) -> CfstResult:
    return CfstResult(ip, 4, 4, loss, latency, speed, region)


def test_ranking_prefers_reliability_then_speed() -> None:
    runs = [
        [
            result("fast", loss=0, latency=55, speed=30),
            result("stable", loss=0, latency=48, speed=20),
        ],
        [result("stable", loss=0, latency=50, speed=21)],
        [
            result("fast", loss=0, latency=52, speed=31),
            result("stable", loss=0, latency=49, speed=19),
        ],
    ]

    ranked = aggregate_results(runs, ["fast", "stable"])

    assert [item.ip for item in ranked] == ["stable", "fast"]
    assert ranked[0].success_rate == 1
    assert ranked[0].median_speed_mb_s == 20
    assert ranked[0].latency_jitter_ms == 1


def test_rejects_candidate_failing_majority_of_rounds() -> None:
    runs = [
        [
            result("good", loss=0, latency=40, speed=10),
            result("bad", loss=0, latency=30, speed=50),
        ],
        [result("good", loss=0, latency=41, speed=11)],
        [result("good", loss=0, latency=42, speed=9)],
    ]

    ranked = aggregate_results(runs, ["bad", "good"])

    assert [item.ip for item in ranked] == ["good"]
