import ipaddress
import random
from pathlib import Path

from mb_optimizer.ip_source import OfficialIPSource, sample_candidates


def test_sample_candidates_writes_bounded_exact_ips(tmp_path: Path) -> None:
    source = tmp_path / "ranges.txt"
    source.write_text("104.16.0.0/16\n172.64.0.0/16\n", encoding="utf-8")
    destination = tmp_path / "candidates.txt"

    values = sample_candidates(
        source,
        destination,
        ipv6=False,
        count=100,
        rng=random.Random(7),
    )

    assert len(values) == 100
    assert len(set(values)) == 100
    assert all(ipaddress.ip_address(value).version == 4 for value in values)
    assert destination.read_text(encoding="utf-8").splitlines() == values


def test_source_uses_bundled_fallback_when_refresh_fails(
    tmp_path: Path, monkeypatch
) -> None:
    fallback = tmp_path / "fallback.txt"
    fallback.write_text("104.16.0.0/13\n", encoding="utf-8")
    source = OfficialIPSource(tmp_path / "cache")
    monkeypatch.setattr(
        source,
        "_download",
        lambda _ipv6: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    statuses: list[str] = []

    selected = source.get(False, fallback, statuses.append)

    assert selected == fallback
    assert statuses[-1] == "官方 IP 更新失败，使用内置备用列表"
