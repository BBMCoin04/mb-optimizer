from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    test_url: str = "https://cf.xiu2.xyz/url"
    custom_ip_file: Path | None = None
    candidate_count: int = 10
    retest_rounds: int = 3
    broad_download_count: int = 20
    threads: int = 200
    ping_count: int = 4
    max_latency_ms: int = 300
    max_loss_rate: float = 0.2
    download_seconds: int = 5

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("端口必须在 1 到 65535 之间")
        if not self.test_url.startswith(("https://", "http://")):
            raise ValueError("测速地址必须以 http:// 或 https:// 开头")
        if self.custom_ip_file and not self.custom_ip_file.is_file():
            raise ValueError("自定义 IP 文件不存在")
        if self.candidate_count < 3:
            raise ValueError("复测候选数量不能少于 3")
        if self.retest_rounds < 2:
            raise ValueError("复测轮数不能少于 2")
