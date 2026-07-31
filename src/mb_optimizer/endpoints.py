from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable

MIRROR_TEST_URL = (
    "https://cloudflaremirrors.com/archlinux/iso/latest/archlinux-x86_64.iso"
)
CLOUDFLARE_SPEED_URL = "https://speed.cloudflare.com/__down?bytes=250000000"
COMMUNITY_7RS_URL = "https://w.7rs.net/speedtest/300MiB.test"
COMMUNITY_CFSPEED_URL = "https://cfspeed.520131420.xyz/300mb.bin"
DEFAULT_TEST_URL = MIRROR_TEST_URL
FALLBACK_TEST_URLS = (MIRROR_TEST_URL, CLOUDFLARE_SPEED_URL)
TEST_URL_PRESETS = (
    ("Cloudflare 镜像（实测可用）", MIRROR_TEST_URL),
    ("Cloudflare 官方测速", CLOUDFLARE_SPEED_URL),
    ("社区公益测速 7RS", COMMUNITY_7RS_URL),
    ("社区公益测速 CFSpeed", COMMUNITY_CFSPEED_URL),
)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)

StatusCallback = Callable[[str], None]


def test_url_candidates(
    preferred: str,
    fallbacks: Iterable[str] = FALLBACK_TEST_URLS,
) -> list[str]:
    return list(dict.fromkeys([preferred, *fallbacks]))


def probe_test_url(url: str, timeout: int = 15) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "*/*",
            "Connection": "close",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP {status}")
            if not response.read(64 * 1024):
                raise RuntimeError("响应内容为空")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(_network_error_message(exc.reason)) from exc
    except TimeoutError as exc:
        raise RuntimeError("连接超时") from exc
    except ssl.SSLError as exc:
        raise RuntimeError(f"TLS 连接失败：{exc}") from exc
    except OSError as exc:
        raise RuntimeError(_network_error_message(exc)) from exc


def resolve_test_url(
    preferred: str,
    fallbacks: Iterable[str] = FALLBACK_TEST_URLS,
    status: StatusCallback | None = None,
) -> str:
    report = status or (lambda _message: None)
    urls = test_url_candidates(preferred, fallbacks)
    failures: list[str] = []
    for index, url in enumerate(urls):
        report("验证测速地址" if index == 0 else "尝试备用测速地址")
        try:
            probe_test_url(url)
            report(f"测速地址可用：{url}")
            return url
        except RuntimeError as exc:
            reason = str(exc)
            failures.append(f"{url}: {reason}")
            report(f"测速地址不可用：{reason}")
    details = "\n".join(failures)
    raise RuntimeError(f"没有可用的测速地址：\n{details}")


def _network_error_message(reason: object) -> str:
    if isinstance(reason, (socket.gaierror,)):
        return f"DNS 解析失败：{reason}"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "连接超时"
    if isinstance(reason, ssl.SSLError):
        return f"TLS 连接失败：{reason}"
    text = str(reason)
    lowered = text.lower()
    if "name or service not known" in lowered or "getaddrinfo failed" in lowered:
        return f"DNS 解析失败：{text}"
    return f"连接失败：{text}"
