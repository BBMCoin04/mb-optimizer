from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable, Iterable

from . import __version__

MIRROR_TEST_URL = (
    "https://cloudflaremirrors.com/archlinux/iso/latest/archlinux-x86_64.iso"
)
CLOUDFLARE_SPEED_URL = "https://speed.cloudflare.com/__down?bytes=250000000"
DEFAULT_TEST_URL = MIRROR_TEST_URL
FALLBACK_TEST_URLS = (MIRROR_TEST_URL, CLOUDFLARE_SPEED_URL)
TEST_URL_PRESETS = (
    ("Cloudflare 镜像（推荐）", MIRROR_TEST_URL),
    ("Cloudflare 官方测速", CLOUDFLARE_SPEED_URL),
)

StatusCallback = Callable[[str], None]


def probe_test_url(url: str, timeout: int = 15) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"MB-CF-Optimizer/{__version__}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            if not response.read(64 * 1024):
                raise RuntimeError("响应内容为空")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc


def resolve_test_url(
    preferred: str,
    fallbacks: Iterable[str] = FALLBACK_TEST_URLS,
    status: StatusCallback | None = None,
) -> str:
    report = status or (lambda _message: None)
    urls = list(dict.fromkeys([preferred, *fallbacks]))
    failures: list[str] = []
    for index, url in enumerate(urls):
        report("验证测速地址" if index == 0 else "尝试备用测速地址")
        try:
            probe_test_url(url)
            return url
        except RuntimeError as exc:
            failures.append(f"{url}: {exc}")
    details = "\n".join(failures)
    raise RuntimeError(f"没有可用的测速地址：\n{details}")
