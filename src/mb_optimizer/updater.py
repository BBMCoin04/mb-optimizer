from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .paths import app_data_dir

REPOSITORY = "BBMCoin04/mb-optimizer"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
EXPECTED_ASSET = "MB-CF-Optimizer-windows-x64.exe"
CHECKSUM_ASSET = f"{EXPECTED_ASSET}.sha256"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    release_url: str
    notes: str
    asset_url: str | None
    checksum_url: str | None


class UpdateClient:
    def check(self) -> UpdateInfo | None:
        request = urllib.request.Request(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"MB-CF-Optimizer/{__version__}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"检查更新失败：HTTP {exc.code}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"检查更新失败：{exc}") from exc

        tag = str(payload.get("tag_name", "")).lstrip("v")
        if not tag or _version_key(tag) <= _version_key(__version__):
            return None
        assets = {
            asset.get("name"): asset.get("browser_download_url")
            for asset in payload.get("assets", [])
        }
        return UpdateInfo(
            version=tag,
            release_url=str(
                payload.get("html_url") or f"https://github.com/{REPOSITORY}/releases"
            ),
            notes=str(payload.get("body") or "").strip(),
            asset_url=assets.get(EXPECTED_ASSET),
            checksum_url=assets.get(CHECKSUM_ASSET),
        )

    def install(
        self,
        info: UpdateInfo,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        if os.name != "nt" or not getattr(sys, "frozen", False):
            webbrowser.open(info.release_url)
            raise RuntimeError("源码运行模式不能自动替换程序，已打开发布页面")
        if not info.asset_url or not info.checksum_url:
            webbrowser.open(info.release_url)
            raise RuntimeError("发布版本缺少程序或校验文件，已打开发布页面")

        update_dir = app_data_dir() / "updates"
        update_dir.mkdir(parents=True, exist_ok=True)
        downloaded = update_dir / f"MB-CF-Optimizer-{info.version}.exe"
        checksum_file = update_dir / f"MB-CF-Optimizer-{info.version}.sha256"
        _download(info.asset_url, downloaded, progress)
        _download(info.checksum_url, checksum_file, None)

        expected = checksum_file.read_text(encoding="utf-8").strip().split()[0].lower()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected)
            or _sha256(downloaded) != expected
        ):
            downloaded.unlink(missing_ok=True)
            raise RuntimeError("更新包 SHA-256 校验失败，已取消更新")

        current = Path(sys.executable).resolve()
        script = update_dir / "apply-update.cmd"
        script.write_text(
            _update_script(os.getpid(), downloaded, current), encoding="ascii"
        )
        flags = (
            subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        return script


def _download(
    url: str, target: Path, progress: Callable[[int, int], None] | None
) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"MB-CF-Optimizer/{__version__}"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=30) as response,
            target.open("wb") as output,
        ):
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            while chunk := response.read(1024 * 256):
                output.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"更新包下载失败：{exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _version_key(version: str) -> tuple[int, ...]:
    values = [int(value) for value in re.findall(r"\d+", version)]
    return tuple((values + [0, 0, 0])[:3])


def _update_script(pid: int, downloaded: Path, current: Path) -> str:
    return (
        "@echo off\n"
        "setlocal\n"
        ":wait\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\n'
        "if not errorlevel 1 (\n"
        "  timeout /t 1 /nobreak >NUL\n"
        "  goto wait\n"
        ")\n"
        f'copy /Y "{downloaded}" "{current}" >NUL\n'
        "if errorlevel 1 exit /b 1\n"
        f'start "" "{current}"\n'
        f'del /Q "{downloaded}"\n'
        'del /Q "%~f0"\n'
    )
