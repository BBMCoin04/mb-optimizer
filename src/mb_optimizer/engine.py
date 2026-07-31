from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .paths import app_data_dir

ENGINE_VERSION = "v2.3.5"
ENGINE_URL = "https://github.com/XIU2/CloudflareSpeedTest/releases/download/v2.3.5/cfst_windows_amd64.zip"
ENGINE_ZIP_SHA256 = "67d06a0c68b7fd6998d5e6abea1dbf850cac2c19c5d8c5980aa32fc7aba1ff5f"

DownloadProgress = Callable[[int, int], None]


class EngineManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir() / "engine"
        self.executable = self.root / "cfst.exe"
        self.ipv4_file = self.root / "ip.txt"
        self.ipv6_file = self.root / "ipv6.txt"
        self.marker = self.root / "engine.json"

    def ensure_installed(self, progress: DownloadProgress | None = None) -> Path:
        if os.name != "nt":
            raise RuntimeError("CFST 引擎当前仅支持 Windows x64")
        if self._installation_valid():
            return self.executable

        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="mb-cfst-") as temp_dir:
            archive = Path(temp_dir) / "cfst.zip"
            self._download(archive, progress)
            actual_hash = _sha256(archive)
            if actual_hash.lower() != ENGINE_ZIP_SHA256:
                raise RuntimeError("CFST 下载文件校验失败，已拒绝执行")
            self._extract(archive)
        return self.executable

    def default_ip_file(self, ipv6: bool) -> Path:
        path = self.ipv6_file if ipv6 else self.ipv4_file
        if not path.is_file():
            raise RuntimeError("CFST 默认 IP 文件缺失")
        return path

    def _installation_valid(self) -> bool:
        try:
            data = json.loads(self.marker.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False
        if data.get("version") != ENGINE_VERSION or not self.executable.is_file():
            return False
        if not self.ipv4_file.is_file() or not self.ipv6_file.is_file():
            return False
        return _sha256(self.executable) == data.get("executable_sha256")

    def _download(self, target: Path, progress: DownloadProgress | None) -> None:
        request = urllib.request.Request(
            ENGINE_URL,
            headers={"User-Agent": "MB-CF-Optimizer/0.1"},
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
            raise RuntimeError(f"CFST 下载失败：{exc}") from exc

    def _extract(self, archive: Path) -> None:
        wanted = {"cfst.exe", "ip.txt", "ipv6.txt"}
        staged: dict[str, Path] = {}
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                name = PurePosixPath(member.filename).name
                if name not in wanted:
                    continue
                destination = self.root / f".{name}.new"
                with bundle.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                staged[name] = destination
        missing = wanted - staged.keys()
        if missing:
            raise RuntimeError(f"CFST 压缩包缺少文件：{', '.join(sorted(missing))}")

        for name, staged_path in staged.items():
            os.replace(staged_path, self.root / name)
        marker_data = {
            "version": ENGINE_VERSION,
            "archive_sha256": ENGINE_ZIP_SHA256,
            "executable_sha256": _sha256(self.executable),
        }
        self.marker.write_text(json.dumps(marker_data, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
