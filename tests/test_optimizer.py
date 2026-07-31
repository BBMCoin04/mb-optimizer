from pathlib import Path

from mb_optimizer.models import OptimizationOptions
from mb_optimizer.optimizer import OptimizationService

HEADER = "IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码\n"


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

    def __init__(self, executable: Path, log=None) -> None:
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
            rows = [
                f"{ip},4,4,0.00,{45 + index},{25 - index},HKG"
                for index, ip in enumerate(ips)
            ]
            if progress:
                progress("下载测速", len(ips), len(ips), None)
        Path(output_file).write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")

    def stop(self):
        return None


def test_optimization_uses_latency_scan_shortlist_and_retests(
    tmp_path: Path, monkeypatch
) -> None:
    FakeRunner.calls = 0
    monkeypatch.setattr("mb_optimizer.optimizer.CfstRunner", FakeRunner)
    monkeypatch.setattr(
        "mb_optimizer.optimizer.resolve_test_url", lambda preferred, status: preferred
    )
    statuses: list[str] = []
    engine = FakeEngine(tmp_path)
    service = OptimizationService(
        engine=engine,
        status=lambda message, _progress: statuses.append(message),
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
