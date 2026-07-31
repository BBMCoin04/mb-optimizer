from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .models import OptimizationOptions

LogCallback = Callable[[str], None]


class CfstCancelled(RuntimeError):
    pass


class CfstRunner:
    def __init__(self, executable: Path, log: LogCallback | None = None) -> None:
        self.executable = executable
        self.log = log or (lambda _message: None)
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def run(
        self,
        ip_file: Path,
        output_file: Path,
        options: OptimizationOptions,
        download_count: int,
        stop_event: threading.Event,
        timeout_seconds: int = 1800,
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
            "-dn",
            str(download_count),
            "-dt",
            str(options.download_seconds),
            "-url",
            options.test_url,
        ]
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
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            **popen_options,
        )
        with self._lock:
            self._process = process

        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line.rstrip())
            lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        started = time.monotonic()
        recent: list[str] = []
        try:
            while True:
                if stop_event.is_set():
                    self.stop()
                    raise CfstCancelled("测速已停止")
                if time.monotonic() - started > timeout_seconds:
                    self.stop()
                    raise RuntimeError("CFST 运行超时")
                try:
                    line = lines.get(timeout=0.15)
                    if line is not None and line:
                        recent.append(line)
                        recent = recent[-8:]
                        self.log(line)
                except queue.Empty:
                    pass
                if process.poll() is not None:
                    break
            if process.returncode != 0:
                details = "\n".join(recent[-3:])
                raise RuntimeError(
                    f"CFST 运行失败（退出码 {process.returncode}）\n{details}"
                )
        finally:
            with self._lock:
                self._process = None

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
