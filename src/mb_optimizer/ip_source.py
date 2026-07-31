from __future__ import annotations

import ipaddress
import os
import random
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .paths import app_data_dir

OFFICIAL_IPV4_URL = "https://www.cloudflare.com/ips-v4/"
OFFICIAL_IPV6_URL = "https://www.cloudflare.com/ips-v6/"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

StatusCallback = Callable[[str], None]


class OfficialIPSource:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir() / "ip-lists"

    def get(
        self,
        ipv6: bool,
        fallback: Path,
        status: StatusCallback | None = None,
    ) -> Path:
        report = status or (lambda _message: None)
        cache = self.root / ("cloudflare-v6.txt" if ipv6 else "cloudflare-v4.txt")
        snapshots = [
            cache.with_name(f"{cache.stem}-previous-{index}{cache.suffix}")
            for index in (1, 2)
        ]
        if self._fresh(cache, ipv6):
            report(f"使用已缓存的官方 IP 段（{self._cache_age(cache)}）")
            return cache

        report("更新 Cloudflare 官方 IP 段")
        try:
            networks = self._download(ipv6)
            self._install_cache(cache, snapshots, networks, ipv6)
            report(f"官方 IP 更新完成（{len(networks)} 个网段）")
            return cache
        except RuntimeError as exc:
            reason = str(exc)
            if self._valid_file(cache, ipv6):
                report(f"官方 IP 更新失败，使用旧缓存：{reason}")
                return cache
            for index, snapshot in enumerate(snapshots, start=1):
                if self._valid_file(snapshot, ipv6):
                    report(f"当前缓存无效，使用历史快照 {index}：{reason}")
                    return snapshot
            if self._valid_file(fallback, ipv6):
                report(f"官方 IP 更新失败，使用内置备用列表：{reason}")
                return fallback
            raise RuntimeError("无法获取 Cloudflare IP 段，且没有可用缓存") from None

    def _install_cache(
        self,
        cache: Path,
        snapshots: list[Path],
        networks: list[str],
        ipv6: bool,
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self._valid_file(snapshots[0], ipv6):
            temporary_snapshot = snapshots[1].with_suffix(".tmp")
            shutil.copy2(snapshots[0], temporary_snapshot)
            os.replace(temporary_snapshot, snapshots[1])
        if self._valid_file(cache, ipv6):
            temporary_snapshot = snapshots[0].with_suffix(".tmp")
            shutil.copy2(cache, temporary_snapshot)
            os.replace(temporary_snapshot, snapshots[0])
        temporary = cache.with_suffix(".tmp")
        temporary.write_text("\n".join(networks) + "\n", encoding="utf-8")
        os.replace(temporary, cache)

    @staticmethod
    def _cache_age(path: Path) -> str:
        age_seconds = max(0, int(time.time() - path.stat().st_mtime))
        if age_seconds < 3600:
            return f"{max(1, age_seconds // 60)} 分钟前更新"
        return f"{age_seconds // 3600} 小时前更新"

    @staticmethod
    def _fresh(path: Path, ipv6: bool) -> bool:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return False
        return age <= CACHE_MAX_AGE_SECONDS and OfficialIPSource._valid_file(path, ipv6)

    @staticmethod
    def _valid_file(path: Path, ipv6: bool) -> bool:
        try:
            _parse_networks(path.read_text(encoding="utf-8"), ipv6)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _download(ipv6: bool) -> list[str]:
        url = OFFICIAL_IPV6_URL if ipv6 else OFFICIAL_IPV4_URL
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"MB-CF-Optimizer/{__version__}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if getattr(response, "status", 200) != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                body = response.read(1024 * 1024 + 1)
        except (OSError, urllib.error.HTTPError) as exc:
            raise RuntimeError(f"官方 IP 下载失败：{exc}") from exc
        if len(body) > 1024 * 1024:
            raise RuntimeError("官方 IP 响应异常过大")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("官方 IP 响应编码无效") from exc
        networks = [str(network) for network in _parse_networks(text, ipv6)]
        if len(networks) < 5:
            raise RuntimeError("官方 IP 响应中的网段数量异常")
        return networks


def sample_candidates(
    source: Path,
    destination: Path,
    ipv6: bool,
    count: int,
    rng: random.Random | random.SystemRandom | None = None,
) -> list[str]:
    networks = _parse_networks(source.read_text(encoding="utf-8"), ipv6)
    generator = rng or random.SystemRandom()
    capacity = min(
        count, sum(min(network.num_addresses, count) for network in networks)
    )
    if capacity < 3:
        raise RuntimeError("候选 IP 数量不能少于 3")
    target_count = int(capacity)
    candidates: set[str] = set()

    for network in networks:
        if len(candidates) >= target_count:
            break
        candidates.add(str(_random_address(network, generator)))

    attempts = 0
    max_attempts = target_count * 20
    while len(candidates) < target_count and attempts < max_attempts:
        network = generator.choice(networks)
        candidates.add(str(_random_address(network, generator)))
        attempts += 1
    if len(candidates) < target_count:
        raise RuntimeError("候选 IP 段不足，无法生成测速列表")

    values = list(candidates)
    generator.shuffle(values)
    destination.write_text("\n".join(values) + "\n", encoding="utf-8")
    return values


def _parse_networks(
    text: str, ipv6: bool
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    expected_version = 6 if ipv6 else 4
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            network = ipaddress.ip_network(line, strict=False)
        except ValueError as exc:
            raise ValueError(f"无效 IP 网段：{line}") from exc
        if network.version != expected_version:
            raise ValueError(f"IP 版本不匹配：{line}")
        networks.append(network)
    if not networks:
        raise ValueError("IP 列表为空")
    return networks


def _random_address(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
    rng: random.Random | random.SystemRandom,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if network.version == 4 and network.num_addresses > 2:
        offset = rng.randrange(1, network.num_addresses - 1)
    else:
        offset = rng.randrange(network.num_addresses)
    return network.network_address + offset
