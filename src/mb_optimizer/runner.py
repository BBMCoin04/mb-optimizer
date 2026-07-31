from __future__ import annotations

import codecs
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .models import OptimizationOptions

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[str, int, int, int | None], None]
_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+).*?(?:可用:\s*(\d+))?\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class CfstCancelled(RuntimeError):
    pass


class CfstRunner:
    def __init__(self, executable: Path, log: LogCallback | None = None) -> None:
        self.executable = executable
        self.log = log or (lambda _message: None)
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def run(
        self,
        ip_file: Path,
        output_file: Path,
        options: OptimizationOptions,
        download_count: int,
        stop_event: threading.Event,
        timeout_seconds: int = 900,
        disable_download: bool = False,
        progress: ProgressCallback | None = None,
    ) -> None:
        command = [
            str(self.executable),
            "-f",
            str(ip_file),
            "-o",
            str(output_file),
            "-tp",
            str(options.port),
            "-t",
            str(options.ping_count),
            "-n",
            str(options.threads),
            "-tl",
            str(options.max_latency_ms),
            "-tlr",
            str(options.max_loss_rate),
        ]
        if disable_download:
            command.append("-dd")
        else:
            command.extend(
                [
                    "-dn",
                    str(download_count),
                    "-dt",
                    str(options.download_seconds),
                    "-url",
                    options.test_url,
                ]
            )

        creationflags = 0
        popen_options: dict[str, object] = {}
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_options["start_new_session"] = True

        self.log("启动 CFST 测速")
        process = subprocess.Popen(
            command,
            cwd=output_file.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            **popen_options,
        )
        with self._lock:
            self._process = process

        messages: queue.Queue[str] = queue.Queue()
        reader_done = threading.Event()

        def read_output() -> None:
            assert process.stdout is not None
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            buffer = ""
            last_reported: dict[str, int] = {}

            def handle(raw: str) -> None:
                line = _ANSI_RE.sub("", raw).strip()
                if not line:
                    return
                parsed = parse_progress_line(line)
                if not parsed:
                    messages.put(line)
                    return
                stage, current, total, available = parsed
                percent = int(current * 100 / total) if total else 0
                if percent > last_reported.get(stage, -1) or current == total:
                    last_reported[stage] = percent
                    if progress:
                        progress(stage, current, total, available)
                    if percent % 10 == 0 or current == total:
                        suffix = f"，可用 {available}" if available is not None else ""
                        messages.put(f"{stage} {current}/{total}{suffix}")

            while chunk := process.stdout.read1(4096):
                text = decoder.decode(chunk)
                for character in text:
                    if character in "\r\n":
                        handle(buffer)
                        buffer = ""
                    else:
                        buffer += character
            buffer += decoder.decode(b"", final=True)
            handle(buffer)
            reader_done.set()

        threading.Thread(target=read_output, daemon=True).start()
        started = time.monotonic()
        recent: list[str] = []
        try:
            while process.poll() is None:
                if stop_event.is_set():
                    self.stop()
                    raise CfstCancelled("测速已停止")
                if time.monotonic() - started > timeout_seconds:
                    self.stop()
                    raise RuntimeError("CFST 运行超时")
                self._drain_messages(messages, recent)
                time.sleep(0.08)
            reader_done.wait(1)
            self._drain_messages(messages, recent)
            if process.returncode != 0:
                details = "\n".join(recent[-3:])
                raise RuntimeError(
                    f"CFST 运行失败（退出码 {process.returncode}）\n{details}"
                )
        finally:
            with self._lock:
                self._process = None

    def _drain_messages(self, messages: queue.Queue[str], recent: list[str]) -> None:
        while True:
            try:
                line = messages.get_nowait()
            except queue.Empty:
                return
            recent.append(line)
            del recent[:-8]
            self.log(line)

    def stop(self) -> None:
        with self._lock:
            process = self._process
        if not process or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)


def parse_progress_line(line: str) -> tuple[str, int, int, int | None] | None:
    match = _PROGRESS_RE.search(line)
    if not match:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    if total <= 0 or current > total:
        return None
    available = int(match.group(3)) if match.group(3) is not None else None
    stage = "延迟测速" if available is not None else "下载测速"
    return stage, current, total, available
