import threading
import time
from pathlib import Path

import pytest

from mb_optimizer.models import OptimizationOptions
from mb_optimizer.optimizer import OptimizationService, _select_finalists
from mb_optimizer.runner import CfstCancelled

HEADER = "IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码\n"


def test_standard_options_use_practical_filters() -> None:
    options = OptimizationOptions()

    assert options.max_latency_ms == 300
    assert options.max_loss_rate == 0.25
    assert options.broad_candidate_count == 800


class FakeEngine:
    def __init__(self, root: Path) -> None:
        self.executable = root / "cfst.exe"
        self.ip_file = root / "ip.txt"
        self.executable.write_bytes(b"")
        self.ip_file.write_text("104.16.0.0/24\n", encoding="utf-8")

    def ensure_installed(self, progress=None):
        return self.executable

    def default_ip_file(self, ipv6: bool):
        return self.ip_file


class FakeRunner:
    calls = 0
    zero_speed_urls: set[str] = set()

    def __init__(self, executable: Path, log=None, **_kwargs) -> None:
        self.log = log or (lambda _message: None)

    def run(
        self,
        ip_file,
        output_file,
        options,
        download_count,
        stop_event,
        timeout_seconds=900,
        disable_download=False,
        progress=None,
        **_kwargs,
    ):
        self.__class__.calls += 1
        ips = Path(ip_file).read_text(encoding="utf-8").splitlines()
        if disable_download:
            rows = [
                f"{ip},4,4,0.00,{40 + index / 10:.1f},0.00,HKG"
                for index, ip in enumerate(ips)
            ]
            if progress:
                progress("延迟测速", len(ips), len(ips), len(ips))
        else:
            speed = 0 if options.test_url in self.__class__.zero_speed_urls else 25
            rows = [
                f"{ip},4,4,0.00,{45 + index},{max(0, speed - index)},HKG"
                for index, ip in enumerate(ips)
            ]
            if progress:
                progress("下载测速", len(ips), len(ips), None)
        Path(output_file).write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")

    def stop(self):
        return None


def test_finalists_include_a_low_latency_candidate() -> None:
    results = [
        _result("far-1", speed=30, latency=200),
        _result("far-2", speed=29, latency=210),
        _result("far-3", speed=28, latency=220),
        _result("near", speed=25, latency=50),
    ]

    selected = _select_finalists(results, 3)

    assert [item.ip for item in selected] == ["far-1", "far-2", "near"]


def test_optimization_uses_latency_scan_shortlist_and_retests(
    tmp_path: Path, monkeypatch
) -> None:
    FakeRunner.calls = 0
    FakeRunner.zero_speed_urls = set()
    monkeypatch.setattr("mb_optimizer.optimizer.CfstRunner", FakeRunner)
    monkeypatch.setattr("mb_optimizer.optimizer.probe_test_url", lambda *_args, **_kwargs: None)
    statuses: list[str] = []
    selected_urls: list[str] = []
    engine = FakeEngine(tmp_path)
    service = OptimizationService(
        engine=engine,
        status=lambda message, _progress: statuses.append(message),
        endpoint_selected=selected_urls.append,
    )
    options = OptimizationOptions(
        custom_ip_file=engine.ip_file,
        broad_candidate_count=100,
        speed_candidate_count=5,
        final_candidate_count=3,
        retest_rounds=2,
    )

    results = service.optimize(options)

    assert FakeRunner.calls == 4
    assert len(results) == 3
    assert results[0].successful_rounds == 3
    assert statuses[-1] == "优选完成"
    assert selected_urls == [options.test_url]
    assert not any("第一轮延迟广筛 · 下载测速" in item for item in statuses)


def test_optimization_retries_url_when_cfst_speed_is_zero(
    tmp_path: Path, monkeypatch
) -> None:
    failed_url = "https://broken.example/file"
    FakeRunner.calls = 0
    FakeRunner.zero_speed_urls = {failed_url}
    monkeypatch.setattr("mb_optimizer.optimizer.CfstRunner", FakeRunner)
    monkeypatch.setattr(
        "mb_optimizer.optimizer.probe_test_url", lambda *_args, **_kwargs: None
    )
    logs: list[str] = []
    engine = FakeEngine(tmp_path)
    service = OptimizationService(engine=engine, log=logs.append)
    options = OptimizationOptions(
        test_url=failed_url,
        custom_ip_file=engine.ip_file,
        broad_candidate_count=100,
        speed_candidate_count=5,
        final_candidate_count=3,
        retest_rounds=2,
    )

    results = service.optimize(options)

    assert len(results) == 3
    assert FakeRunner.calls == 5
    assert any("下载速度均为零，自动尝试下一个地址" in line for line in logs)
    assert any("下载测速地址已确认" in line for line in logs)


def test_failed_preflight_prioritizes_known_working_urls(
    tmp_path: Path, monkeypatch
) -> None:
    custom_url = "https://broken.example/file"
    FakeRunner.calls = 0
    FakeRunner.zero_speed_urls = set()
    monkeypatch.setattr("mb_optimizer.optimizer.CfstRunner", FakeRunner)
    monkeypatch.setattr(
        "mb_optimizer.optimizer.probe_test_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 403")),
    )
    logs: list[str] = []
    engine = FakeEngine(tmp_path)
    service = OptimizationService(engine=engine, log=logs.append)
    options = OptimizationOptions(
        test_url=custom_url,
        custom_ip_file=engine.ip_file,
        broad_candidate_count=100,
        speed_candidate_count=5,
        final_candidate_count=3,
        retest_rounds=2,
    )

    results = service.optimize(options)

    assert len(results) == 3
    assert FakeRunner.calls == 4
    assert any("自定义地址移到最后" in line for line in logs)


def _result(ip: str, speed: float, latency: float):
    from mb_optimizer.models import CfstResult

    return CfstResult(
        ip=ip,
        sent=4,
        received=4,
        loss_rate=0,
        latency_ms=latency,
        speed_mb_s=speed,
    )


def test_network_preparation_can_be_cancelled_promptly() -> None:
    service = OptimizationService()

    def cancel_soon() -> None:
        time.sleep(0.1)
        service.stop()

    threading.Thread(target=cancel_soon, daemon=True).start()
    started = time.monotonic()
    with pytest.raises(CfstCancelled):
        service._run_cancellable(lambda: time.sleep(10))

    assert time.monotonic() - started < 1
