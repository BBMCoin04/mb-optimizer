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
from dataclasses import dataclass
from pathlib import Path

from .models import OptimizationOptions

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[str, int, int, int | None], None]
_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+).*?(?:可用:\s*(\d+))?\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class CfstCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CfstRunReport:
    phase: str
    pid: int
    returncode: int
    csv_ready: bool
    forced_after_csv: bool
    output_reader_finished: bool
    elapsed_seconds: float


class CfstRunner:
    def __init__(
        self,
        executable: Path,
        log: LogCallback | None = None,
        log_started_at: float | None = None,
    ) -> None:
        self.executable = executable
        self.log = log or (lambda _message: None)
        self._log_started_at = log_started_at
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
        phase_name: str = "CFST 测速",
        progress_stage: str | None = None,
        csv_exit_grace_seconds: float = 5.0,
        debug: bool = False,
        min_speed_mb_s: float | None = None,
    ) -> CfstRunReport:
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
            progress_stage = "延迟测速"
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
        if min_speed_mb_s is not None:
            command.extend(["-sl", str(min_speed_mb_s)])
        if debug:
            command.append("-debug")

        creationflags = 0
        popen_options: dict[str, object] = {}
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_options["start_new_session"] = True

        output_file.unlink(missing_ok=True)
        started = time.monotonic()
        self._event(started, "INFO", phase_name, "状态 starting")
        process = subprocess.Popen(
            command,
            cwd=output_file.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            **popen_options,
        )
        with self._lock:
            self._process = process
        self._event(started, "INFO", phase_name, f"状态 running，PID {process.pid}")

        messages: queue.Queue[str] = queue.Queue()
        reader_done = threading.Event()

        def read_output() -> None:
            assert process.stdout is not None
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            buffer = ""
            last_reported: dict[str, int] = {}
            current_stage = progress_stage or "延迟测速"

            def handle(raw: str) -> None:
                nonlocal current_stage
                line = _ANSI_RE.sub("", raw).strip()
                if not line:
                    return
                if "开始延迟测速" in line:
                    current_stage = "延迟测速"
                elif "开始下载测速" in line:
                    current_stage = "下载测速"
                parsed = parse_progress_line(line, current_stage)
                if not parsed:
                    if "完整测速结果已写入" in line:
                        messages.put("测速结果文件已生成")
                    else:
                        messages.put(line)
                    return
                stage, current, total, available = parsed
                if not disable_download and current == 0:
                    stage = "延迟测速"
                elif (
                    not disable_download
                    and current > 0
                    and total == download_count
                ):
                    stage = "下载测速"
                percent = int(current * 100 / total) if total else 0
                if percent > last_reported.get(stage, -1) or current == total:
                    last_reported[stage] = percent
                    if progress:
                        progress(stage, current, total, available)
                    if percent % 10 == 0 or current == total:
                        suffix = f"，可用 {available}" if available is not None else ""
                        messages.put(f"{stage} {current}/{total}{suffix}")

            try:
                while True:
                    chunk = process.stdout.read1(4096)
                    if not chunk:
                        break
                    text = decoder.decode(chunk)
                    for character in text:
                        if character in "\r\n":
                            handle(buffer)
                            buffer = ""
                        else:
                            buffer += character
                buffer += decoder.decode(b"", final=True)
                handle(buffer)
            except (OSError, ValueError):
                # The controller closes stdout when a reader does not finish promptly.
                pass
            finally:
                reader_done.set()

        reader_thread = threading.Thread(
            target=read_output,
            name=f"cfst-output-{process.pid}",
            daemon=True,
        )
        reader_thread.start()

        recent: list[str] = []
        csv_ready_at: float | None = None
        forced_after_csv = False
        cancelled = False
        last_heartbeat = started
        try:
            while True:
                now = time.monotonic()
                self._drain_messages(messages, recent, started, phase_name)

                if stop_event.is_set():
                    cancelled = True
                    self._event(started, "INFO", phase_name, "收到停止请求")
                    self._terminate_process(process)
                    raise CfstCancelled("测速已停止")

                current_size = self._file_size(output_file)
                if current_size > 0 and csv_ready_at is None:
                    csv_ready_at = now
                    self._event(started, "INFO", phase_name, "状态 csv_ready")

                returncode = process.poll()
                if returncode is not None:
                    break

                if (
                    csv_ready_at is not None
                    and now - csv_ready_at >= csv_exit_grace_seconds
                ):
                    forced_after_csv = True
                    self._event(
                        started,
                        "WARN",
                        phase_name,
                        "CSV 已生成但进程未退出，执行安全终止并继续解析",
                    )
                    self._terminate_process(process)
                    break

                if now - started > timeout_seconds:
                    self._event(started, "ERROR", phase_name, "阶段运行超时")
                    self._terminate_process(process)
                    raise RuntimeError(f"{phase_name}超时")
                if now - last_heartbeat >= 10:
                    self._event(started, "INFO", phase_name, "CFST 仍在运行")
                    last_heartbeat = now
                time.sleep(0.08)

            try:
                returncode = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._terminate_process(process)
                returncode = process.wait(timeout=2)
            self._event(
                started,
                "INFO",
                phase_name,
                f"状态 process_exited，退出码 {returncode}",
            )

            reader_thread.join(timeout=1)
            if reader_thread.is_alive() and process.stdout is not None:
                process.stdout.close()
                reader_thread.join(timeout=0.5)
            self._drain_messages(messages, recent, started, phase_name)
            output_reader_finished = reader_done.is_set()
            reader_level = "INFO" if output_reader_finished else "WARN"
            reader_message = "输出线程已结束" if output_reader_finished else "输出线程等待超时"
            self._event(started, reader_level, phase_name, reader_message)

            csv_ready = self._file_size(output_file) > 0
            if not csv_ready:
                details = "\n".join(recent[-3:])
                suffix = f"\n{details}" if details else ""
                raise RuntimeError(f"{phase_name}未生成结果文件{suffix}")
            if returncode != 0 and not forced_after_csv:
                details = "\n".join(recent[-3:])
                raise RuntimeError(f"{phase_name}失败（退出码 {returncode}）\n{details}")

            self._event(started, "INFO", phase_name, "输出已就绪，等待解析")
            return CfstRunReport(
                phase=phase_name,
                pid=process.pid,
                returncode=returncode,
                csv_ready=csv_ready,
                forced_after_csv=forced_after_csv,
                output_reader_finished=output_reader_finished,
                elapsed_seconds=time.monotonic() - started,
            )
        finally:
            if not cancelled and process.poll() is None:
                self._terminate_process(process)
            with self._lock:
                if self._process is process:
                    self._process = None

    def _drain_messages(
        self,
        messages: queue.Queue[str],
        recent: list[str],
        started: float,
        phase: str,
    ) -> None:
        while True:
            try:
                line = messages.get_nowait()
            except queue.Empty:
                return
            recent.append(line)
            del recent[:-8]
            self._event(started, "INFO", phase, line)

    def stop(self) -> None:
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            self._terminate_process(process)

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=2,
                )
            except subprocess.TimeoutExpired:
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def _event(self, started: float, level: str, phase: str, message: str) -> None:
        elapsed = int(time.monotonic() - (self._log_started_at or started))
        self.log(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] [{level}] [{phase}] {message}")


def parse_progress_line(
    line: str,
    forced_stage: str | None = None,
) -> tuple[str, int, int, int | None] | None:
    match = _PROGRESS_RE.search(line)
    if not match:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    if total <= 0 or current > total:
        return None
    available = int(match.group(3)) if match.group(3) is not None else None
    stage = forced_stage or ("延迟测速" if available is not None else "下载测速")
    return stage, current, total, available
