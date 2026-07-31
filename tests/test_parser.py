from pathlib import Path

import pytest

from mb_optimizer.parser import parse_cfst_csv

CSV = """IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码
104.16.1.1,4,4,0.00,45.20,18.75,HKG
104.16.1.2,4,3,25%,61.50,8.20,NRT
"""


def test_parse_utf8_bom_csv(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    path.write_text(CSV, encoding="utf-8-sig")

    results = parse_cfst_csv(path)

    assert len(results) == 2
    assert results[0].ip == "104.16.1.1"
    assert results[0].latency_ms == 45.2
    assert results[0].speed_mb_s == 18.75
    assert results[1].loss_rate == 0.25


def test_parse_gb18030_csv(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    path.write_bytes(CSV.encode("gb18030"))

    assert parse_cfst_csv(path)[0].region == "HKG"


def test_reject_missing_required_column(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    path.write_text("IP 地址,平均延迟\n1.1.1.1,20\n", encoding="utf-8")

    with pytest.raises(ValueError, match="缺少必要列"):
        parse_cfst_csv(path)
