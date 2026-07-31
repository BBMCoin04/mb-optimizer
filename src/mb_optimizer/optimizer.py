from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from .engine import EngineManager
from .models import AggregatedResult, CfstResult, OptimizationOptions
from .parser import parse_cfst_csv
from .ranking import aggregate_results
from .runner import CfstCancelled, CfstRunner

StatusCallback = Callable[[str, int], None]
LogCallback = Callable[[str], None]


class OptimizationService:
    def __init__(
        self,
        engine: EngineManager | None = None,
        status: StatusCallback | None = None,
        log: LogCallback | None = None,
    ) -> None:
        self.engine = engine or EngineManager()
        self.status = status or (lambda _message, _progress: None)
        self.log = log or (lambda _message: None)
        self.stop_event = threading.Event()
        self._runner: CfstRunner | None = None

    def optimize(self, options: OptimizationOptions) -> list[AggregatedResult]:
        options.validate()
        self.stop_event.clear()
        self.status("准备测速引擎", 2)

        def download_progress(downloaded: int, total: int) -> None:
            if self.stop_event.is_set():
                raise CfstCancelled("测速已停止")
            percentage = int(downloaded * 100 / total) if total else 0
            self.status(f"下载测速引擎 {percentage}%", min(15, 2 + percentage // 8))

        executable = self.engine.ensure_installed(download_progress)
        if self.stop_event.is_set():
            raise CfstCancelled("测速已停止")
        self._runner = CfstRunner(executable, self.log)
        source = options.custom_ip_file or self.engine.default_ip_file(options.ipv6)

        with tempfile.TemporaryDirectory(prefix="mb-optimize-") as temp_dir:
            workdir = Path(temp_dir)
            self.status("第一轮广泛筛选", 18)
            broad_output = workdir / "broad.csv"
            self._runner.run(
                source,
                broad_output,
                options,
                options.broad_download_count,
                self.stop_event,
            )
            broad = self._usable(parse_cfst_csv(broad_output))
            if not broad:
                raise RuntimeError("没有找到满足条件的 IP，请放宽延迟或丢包限制")

            candidates = sorted(
                broad,
                key=lambda item: (-item.speed_mb_s, item.loss_rate, item.latency_ms),
            )[: options.candidate_count]
            candidate_file = workdir / "candidates.txt"
            candidate_file.write_text(
                "\n".join(item.ip for item in candidates) + "\n",
                encoding="utf-8",
            )

            runs: list[list[CfstResult]] = []
            for index in range(options.retest_rounds):
                progress = 25 + int(index * 65 / options.retest_rounds)
                self.status(f"稳定性复测 {index + 1}/{options.retest_rounds}", progress)
                output = workdir / f"retest-{index + 1}.csv"
                self._runner.run(
                    candidate_file,
                    output,
                    options,
                    len(candidates),
                    self.stop_event,
                )
                runs.append(self._usable(parse_cfst_csv(output)))

            self.status("汇总稳定性结果", 94)
            results = aggregate_results(runs, [item.ip for item in candidates])
            if not results:
                raise RuntimeError("候选 IP 未通过稳定性复测，请稍后重试")
            self.status("优选完成", 100)
            return results

    def stop(self) -> None:
        self.stop_event.set()
        if self._runner:
            self._runner.stop()

    @staticmethod
    def _usable(results: list[CfstResult]) -> list[CfstResult]:
        return [item for item in results if item.received > 0 and item.speed_mb_s > 0]
