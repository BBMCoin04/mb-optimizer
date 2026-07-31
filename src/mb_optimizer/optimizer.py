from __future__ import annotations

import queue
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from pathlib import Path
from statistics import median

from .endpoints import DEFAULT_TEST_URL, probe_test_url, test_url_candidates
from .engine import EngineManager
from .ip_source import OfficialIPSource, sample_candidates
from .models import AggregatedResult, CfstResult, OptimizationOptions
from .parser import parse_cfst_csv
from .ranking import aggregate_results
from .runner import CfstCancelled, CfstRunner, ProgressCallback

StatusCallback = Callable[[str, int], None]
LogCallback = Callable[[str], None]
EndpointCallback = Callable[[str], None]


class OptimizationService:
    def __init__(
        self,
        engine: EngineManager | None = None,
        ip_source: OfficialIPSource | None = None,
        status: StatusCallback | None = None,
        log: LogCallback | None = None,
        endpoint_selected: EndpointCallback | None = None,
    ) -> None:
        self.engine = engine or EngineManager()
        self.ip_source = ip_source or OfficialIPSource()
        self.status = status or (lambda _message, _progress: None)
        self.log = log or (lambda _message: None)
        self.endpoint_selected = endpoint_selected or (lambda _url: None)
        self.stop_event = threading.Event()
        self._runner: CfstRunner | None = None
        self._started_at = 0.0

    def optimize(self, options: OptimizationOptions) -> list[AggregatedResult]:
        options.validate()
        self.stop_event.clear()
        self._started_at = time.monotonic()
        self.status("准备测速引擎", -1)
        self._event("INFO", "开始优选任务")

        def download_progress(downloaded: int, total: int) -> None:
            self._check_cancelled()
            percentage = int(downloaded * 100 / total) if total else 0
            self.status(f"下载测速引擎 {percentage}%", min(9, 2 + percentage // 15))

        executable = self.engine.ensure_installed(download_progress)
        self._check_cancelled()
        self._runner = CfstRunner(
            executable,
            self.log,
            log_started_at=self._started_at,
        )

        test_urls = test_url_candidates(options.test_url)
        self.status("预检首选测速地址", -1)
        try:
            self._run_cancellable(
                lambda: probe_test_url(options.test_url, timeout=5)
            )
            self._event("INFO", f"普通预检通过：{options.test_url}")
        except RuntimeError as exc:
            known_urls = test_url_candidates(DEFAULT_TEST_URL)
            test_urls = list(dict.fromkeys([*known_urls, *test_urls]))
            self._event(
                "WARN",
                f"普通预检未通过（{exc}），优先实测已知地址；自定义地址移到最后",
            )
        self._check_cancelled()

        fallback = self.engine.default_ip_file(options.ipv6)
        if options.custom_ip_file:
            source = options.custom_ip_file
            self.status("读取自定义候选 IP", 12)
            self._event("INFO", f"使用自定义候选文件：{source}")
        else:
            self.status("获取 Cloudflare 官方 IP 段", -1)
            source = self._run_cancellable(
                lambda: self.ip_source.get(
                    options.ipv6,
                    fallback,
                    status=lambda message: self._network_status(message, 12),
                )
            )
        self._check_cancelled()

        with tempfile.TemporaryDirectory(prefix="mb-optimize-") as temp_dir:
            workdir = Path(temp_dir)
            broad_file = workdir / "broad-candidates.txt"
            candidates = sample_candidates(
                source,
                broad_file,
                options.ipv6,
                options.broad_candidate_count,
            )
            self._event("INFO", f"本轮抽取 {len(candidates)} 个候选 IP")

            self.status("第一轮延迟广筛 · CFST 正在运行", -1)
            broad_output = workdir / "broad.csv"
            self._runner.run(
                broad_file,
                broad_output,
                options,
                0,
                self.stop_event,
                disable_download=True,
                progress=self._phase_progress("第一轮延迟广筛", 15, 48),
                phase_name="第一轮延迟广筛",
                progress_stage="延迟测速",
            )
            self.status("解析延迟广筛结果", 49)
            broad = self._latency_usable(parse_cfst_csv(broad_output))
            self._event("INFO", f"[第一轮延迟广筛] 状态 parsed，可用 {len(broad)} 个")
            if not broad:
                raise RuntimeError("没有找到可直连的 IP，请检查代理设置或放宽筛选条件")
            if len(broad) >= 5 and median(item.latency_ms for item in broad) < 5:
                self._event("WARN", "延迟中位数低于 5 ms，测速流量可能被透明代理接管")
            self._event("INFO", "[第一轮延迟广筛] 状态 finished")

            speed_candidates = sorted(
                broad,
                key=lambda item: (item.loss_rate, item.latency_ms),
            )[: options.speed_candidate_count]
            speed_file = workdir / "speed-candidates.txt"
            self._write_ips(speed_file, [item.ip for item in speed_candidates])

            first_speed_run: list[CfstResult] = []
            selected_url = ""
            for url_index, test_url in enumerate(test_urls, start=1):
                self._check_cancelled()
                attempt_options = replace(options, test_url=test_url)
                phase_name = f"下载地址实测 {url_index}/{len(test_urls)}"
                self.status(f"{phase_name} · CFST 正在运行", -1)
                speed_output = workdir / f"speed-{url_index}.csv"
                self._event("INFO", f"[{phase_name}] 尝试地址：{test_url}")
                self._runner.run(
                    speed_file,
                    speed_output,
                    attempt_options,
                    min(options.download_target_count, len(speed_candidates)),
                    self.stop_event,
                    progress=self._phase_progress(
                        phase_name, 50, 70, split_stages=True
                    ),
                    phase_name=phase_name,
                    debug=True,
                    min_speed_mb_s=0.01,
                )
                first_speed_run = self._speed_usable(parse_cfst_csv(speed_output))
                self._event(
                    "INFO",
                    f"[{phase_name}] 状态 parsed，可用 {len(first_speed_run)} 个",
                )
                if first_speed_run:
                    selected_url = test_url
                    options = attempt_options
                    self._event("INFO", f"下载测速地址已确认：{selected_url}")
                    self.endpoint_selected(selected_url)
                    self._event("INFO", f"[{phase_name}] 状态 finished")
                    break
                self._event(
                    "WARN",
                    f"[{phase_name}] 下载速度均为零，自动尝试下一个地址",
                )

            if not first_speed_run:
                attempted = "\n".join(f"- {url}" for url in test_urls)
                raise RuntimeError(
                    "所有测速地址经 CFST 实测后下载速度均为零。\n"
                    f"已尝试：\n{attempted}\n"
                    "请查看日志中的 [调试] 错误，或填写其他 Cloudflare 大文件地址。"
                )

            finalists = _select_finalists(
                first_speed_run,
                options.final_candidate_count,
            )
            finalist_ips = [item.ip for item in finalists]
            finalist_file = workdir / "finalists.txt"
            self._write_ips(finalist_file, finalist_ips)
            runs: list[list[CfstResult]] = [
                [item for item in first_speed_run if item.ip in finalist_ips]
            ]

            for index in range(options.retest_rounds):
                start = 72 + int(index * 20 / options.retest_rounds)
                end = 72 + int((index + 1) * 20 / options.retest_rounds)
                message = f"稳定性复测 {index + 1}/{options.retest_rounds}"
                self.status(f"{message} · CFST 正在运行", -1)
                output = workdir / f"retest-{index + 1}.csv"
                self._runner.run(
                    finalist_file,
                    output,
                    options,
                    len(finalists),
                    self.stop_event,
                    progress=self._phase_progress(
                        message, start, end, split_stages=True
                    ),
                    phase_name=message,
                )
                retest_results = self._speed_usable(parse_cfst_csv(output))
                self._event(
                    "INFO",
                    f"[{message}] 状态 parsed，可用 {len(retest_results)} 个",
                )
                runs.append(retest_results)
                self._event("INFO", f"[{message}] 状态 finished")

            self.status("汇总稳定性结果", 95)
            results = aggregate_results(runs, finalist_ips)
            if not results:
                raise RuntimeError("候选 IP 未通过稳定性复测，请稍后重试")
            self.status("优选完成", 100)
            self._event("INFO", f"优选完成，推荐候选 {len(results)} 个")
            return results

    def stop(self) -> None:
        self.stop_event.set()
        if self._runner:
            self._runner.stop()

    def _check_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise CfstCancelled("测速已停止")

    def _phase_progress(
        self,
        phase: str,
        start: int,
        end: int,
        split_stages: bool = False,
    ) -> ProgressCallback:
        def report(stage: str, current: int, total: int, available: int | None) -> None:
            if total <= 0 or current <= 0:
                return
            ratio = current / total
            if split_stages:
                middle = start + max(2, (end - start) // 5)
                progress = (
                    start + int((middle - start) * ratio)
                    if stage == "延迟测速"
                    else middle + int((end - middle) * ratio)
                )
            else:
                progress = start + int((end - start) * ratio)
            suffix = f" · 可用 {available}" if available is not None else ""
            self.status(f"{phase} · {stage} {current}/{total}{suffix}", progress)

        return report

    def _network_status(self, message: str, progress: int) -> None:
        if self.stop_event.is_set():
            return
        self.status(message, progress)
        level = "WARN" if "失败" in message or "不可用" in message else "INFO"
        self._event(level, message)

    def _run_cancellable(self, operation: Callable[[], Any]) -> Any:
        results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def execute() -> None:
            try:
                results.put((True, operation()))
            except Exception as exc:  # propagate the original operation failure
                results.put((False, exc))

        worker = threading.Thread(target=execute, daemon=True)
        worker.start()
        while worker.is_alive():
            self._check_cancelled()
            worker.join(0.08)
        succeeded, value = results.get_nowait()
        if succeeded:
            return value
        raise value

    def _event(self, level: str, message: str) -> None:
        elapsed = int(time.monotonic() - self._started_at) if self._started_at else 0
        self.log(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] [{level}] {message}")

    @staticmethod
    def _write_ips(path: Path, ips: list[str]) -> None:
        path.write_text("\n".join(ips) + "\n", encoding="utf-8")

    @staticmethod
    def _latency_usable(results: list[CfstResult]) -> list[CfstResult]:
        return [item for item in results if item.received > 0]

    @staticmethod
    def _speed_usable(results: list[CfstResult]) -> list[CfstResult]:
        return [item for item in results if item.received > 0 and item.speed_mb_s > 0]


def _select_finalists(
    results: list[CfstResult],
    count: int,
) -> list[CfstResult]:
    fastest = sorted(
        results,
        key=lambda item: (-item.speed_mb_s, item.loss_rate, item.latency_ms),
    )
    if count <= 1:
        return fastest[:count]

    selected = fastest[: max(1, count - 1)]
    selected_ips = {item.ip for item in selected}
    for item in sorted(results, key=lambda value: (value.loss_rate, value.latency_ms)):
        if item.ip not in selected_ips:
            selected.append(item)
            selected_ips.add(item.ip)
            break
    for item in fastest:
        if len(selected) >= count:
            break
        if item.ip not in selected_ips:
            selected.append(item)
            selected_ips.add(item.ip)
    return selected[:count]
