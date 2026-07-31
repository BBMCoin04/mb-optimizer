from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import CfstResult

_ALIASES = {
    "ip": ("IP 地址", "IP地址", "IP Address", "IP"),
    "sent": ("已发送", "Sent"),
    "received": ("已接收", "Received"),
    "loss": ("丢包率", "Loss Rate", "Packet Loss"),
    "latency": ("平均延迟", "Average Latency", "Latency"),
    "speed": ("下载速度(MB/s)", "下载速度", "Download Speed (MB/s)", "Download Speed"),
    "region": ("地区码", "Region", "Data Center"),
}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别 CSV 编码：{path.name}")


def _header_map(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("测速结果没有表头")
    normalized = {name.strip(): name for name in fieldnames if name}
    mapped: dict[str, str] = {}
    for key, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapped[key] = normalized[alias]
                break
    required = {"ip", "sent", "received", "loss", "latency", "speed"}
    missing = sorted(required - mapped.keys())
    if missing:
        raise ValueError(f"测速结果缺少必要列：{', '.join(missing)}")
    return mapped


def _number(value: str | None, label: str) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", value or "")
    if not match:
        raise ValueError(f"{label}不是有效数字：{value!r}")
    return float(match.group())


def _loss_rate(value: str | None) -> float:
    number = _number(value, "丢包率")
    if value and "%" in value:
        return number / 100
    return number


def parse_cfst_csv(path: Path) -> list[CfstResult]:
    if not path.is_file():
        raise ValueError("CFST 未生成结果文件")

    text = _read_text(path)
    reader = csv.DictReader(text.splitlines())
    fields = _header_map(reader.fieldnames)
    results: list[CfstResult] = []
    for index, row in enumerate(reader, start=2):
        if not any(row.values()):
            continue
        try:
            ip = (row.get(fields["ip"]) or "").strip()
            if not ip:
                continue
            results.append(
                CfstResult(
                    ip=ip,
                    sent=int(_number(row.get(fields["sent"]), "已发送")),
                    received=int(_number(row.get(fields["received"]), "已接收")),
                    loss_rate=_loss_rate(row.get(fields["loss"])),
                    latency_ms=_number(row.get(fields["latency"]), "平均延迟"),
                    speed_mb_s=_number(row.get(fields["speed"]), "下载速度"),
                    region=(row.get(fields.get("region", "")) or "N/A").strip()
                    or "N/A",
                )
            )
        except ValueError as exc:
            raise ValueError(f"结果文件第 {index} 行解析失败：{exc}") from exc
    return results
