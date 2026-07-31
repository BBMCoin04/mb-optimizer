from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from statistics import median

from .endpoints import resolve_test_url
from .engine import EngineManager
from .ip_source import OfficialIPSource, sample_candidates
from .models import AggregatedResult, CfstResult, OptimizationOptions
from .parser import parse_cfst_csv
from .ranking import aggregate_results
from .runner import CfstCancelled, CfstRunner, ProgressCallback

StatusCallback = Callable[[str, int], None]
LogCallback = Callable[[str], None]


class OptimizationService:
    def __init__(
        self,
        engine: EngineManager | None = None,
        ip_source: OfficialIPSource | None = None,
        status: StatusCallback | None = None,
        log: LogCallback | None = None,
    ) -> None:
        self.engine = engine or EngineManager()
        self.ip_source = ip_source or OfficialIPSource()
        self.status = status or (lambda _message, _progress: None)
        self.log = log or (lambda _message: None)
        self.stop_event = threading.Event()
        self._runner: CfstRunner | None = None

    def optimize(self, options: OptimizationOptions) -> list[AggregatedResult]:
        options.validate()
        self.stop_event.clear()
        self.status("准备测速引擎", 2)

        def download_progress(downloaded: int, total: int) -> None:
            self._check_cancelled()
            percentage = int(downloaded * 100 / total) if total else 0
            self.status(f"下载测速引擎 {percentage}%", min(9, 2 + percentage // 15))

        executable = self.engine.ensure_installed(download_progress)
        self._check_cancelled()
        self._runner = CfstRunner(executable, self.log)

        self.status("验证测速地址", 10)
        selected_url = resolve_test_url(
            options.test_url,
            status=lambda message: self.status(message, 10),
        )
        if selected_url != options.test_url:
            self.log(f"已切换备用测速地址：{selected_url}")
        options = replace(options, test_url=selected_url)
        self._check_cancelled()

        fallback = self.engine.default_ip_file(options.ipv6)
        if options.custom_ip_file:
            source = options.custom_ip_file
            self.status("读取自定义候选 IP", 12)
        else:
            source = self.ip_source.get(
                options.ipv6,
                fallback,
                status=lambda message: self.status(message, 12),
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
            self.log(f"本轮抽取 {len(candidates)} 个候选 IP")

            self.status("第一轮延迟广筛", 15)
            broad_output = workdir / "broad.csv"
            self._runner.run(
                broad_file,
                broad_output,
                options,
                0,
                self.stop_event,
                disable_download=True,
                progress=self._phase_progress("第一轮延迟广筛", 15, 48),
            )
            broad = self._latency_usable(parse_cfst_csv(broad_output))
            if not broad:
                raise RuntimeError("没有找到可直连的 IP，请检查代理设置或放宽筛选条件")
            if len(broad) >= 5 and median(item.latency_ms for item in broad) < 5:
                self.log("警告：延迟中位数低于 5 ms，测速流量可能被透明代理接管")

            speed_candidates = sorted(
                broad,
                key=lambda item: (item.loss_rate, item.latency_ms),
            )[: options.speed_candidate_count]
            speed_file = workdir / "speed-candidates.txt"
            self._write_ips(speed_file, [item.ip for item in speed_candidates])

            self.status("短名单下载测速", 50)
            speed_output = workdir / "speed.csv"
            self._runner.run(
                speed_file,
                speed_output,
                options,
                len(speed_candidates),
                self.stop_event,
                progress=self._phase_progress("短名单测速", 50, 70, split_stages=True),
            )
            first_speed_run = self._speed_usable(parse_cfst_csv(speed_output))
            if not first_speed_run:
                raise RuntimeError(
                    "候选 IP 下载速度均为零，请更换测速地址或检查直连网络"
                )

            finalists = sorted(
                first_speed_run,
                key=lambda item: (-item.speed_mb_s, item.loss_rate, item.latency_ms),
            )[: options.final_candidate_count]
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
                self.status(message, start)
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
                )
                runs.append(self._speed_usable(parse_cfst_csv(output)))

            self.status("汇总稳定性结果", 95)
            results = aggregate_results(runs, finalist_ips)
            if not results:
                raise RuntimeError("候选 IP 未通过稳定性复测，请稍后重试")
            self.status("优选完成", 100)
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
            if total <= 0:
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

    @staticmethod
    def _write_ips(path: Path, ips: list[str]) -> None:
        path.write_text("\n".join(ips) + "\n", encoding="utf-8")

    @staticmethod
    def _latency_usable(results: list[CfstResult]) -> list[CfstResult]:
        return [item for item in results if item.received > 0]

    @staticmethod
    def _speed_usable(results: list[CfstResult]) -> list[CfstResult]:
        return [item for item in results if item.received > 0 and item.speed_mb_s > 0]
