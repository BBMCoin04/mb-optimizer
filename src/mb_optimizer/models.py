from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .endpoints import DEFAULT_TEST_URL


@dataclass(frozen=True, slots=True)
class CfstResult:
    ip: str
    sent: int
    received: int
    loss_rate: float
    latency_ms: float
    speed_mb_s: float
    region: str = "N/A"


@dataclass(frozen=True, slots=True)
class AggregatedResult:
    ip: str
    region: str
    expected_rounds: int
    successful_rounds: int
    median_loss_rate: float
    median_latency_ms: float
    median_speed_mb_s: float
    latency_jitter_ms: float

    @property
    def success_rate(self) -> float:
        return self.successful_rounds / self.expected_rounds

    @property
    def rank_key(self) -> tuple[float, float, float, float, float, str]:
        return (
            -self.success_rate,
            self.median_loss_rate,
            -self.median_speed_mb_s,
            self.median_latency_ms,
            self.latency_jitter_ms,
            self.ip,
        )


@dataclass(frozen=True, slots=True)
class OptimizationOptions:
    ipv6: bool = False
    port: int = 443
    test_url: str = DEFAULT_TEST_URL
    custom_ip_file: Path | None = None
    broad_candidate_count: int = 800
    speed_candidate_count: int = 10
    final_candidate_count: int = 3
    retest_rounds: int = 2
    threads: int = 200
    ping_count: int = 4
    max_latency_ms: int = 1000
    max_loss_rate: float = 1.0
    download_seconds: int = 5

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("端口必须在 1 到 65535 之间")
        if not self.test_url.startswith(("https://", "http://")):
            raise ValueError("测速地址必须以 http:// 或 https:// 开头")
        if self.custom_ip_file and not self.custom_ip_file.is_file():
            raise ValueError("自定义 IP 文件不存在")
        if not 100 <= self.broad_candidate_count <= 5000:
            raise ValueError("广筛候选数量必须在 100 到 5000 之间")
        if not 3 <= self.speed_candidate_count <= 30:
            raise ValueError("测速候选数量必须在 3 到 30 之间")
        if not 1 <= self.final_candidate_count <= self.speed_candidate_count:
            raise ValueError("最终候选数量无效")
        if self.retest_rounds < 1:
            raise ValueError("复测轮数不能少于 1")
