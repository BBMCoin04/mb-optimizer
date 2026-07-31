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
        timeout_seconds=1800,
    ):
        self.__class__.calls += 1
        if self.calls == 1:
            rows = [
                f"104.16.0.{index},4,4,0.00,{40 + index},{30 - index},HKG"
                for index in range(1, 13)
            ]
        else:
            ips = Path(ip_file).read_text(encoding="utf-8").splitlines()
            rows = [
                f"{ip},4,4,0.00,{45 + index},{25 - index},HKG"
                for index, ip in enumerate(ips)
            ]
        Path(output_file).write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")

    def stop(self):
        return None


def test_optimization_runs_broad_scan_and_three_retests(
    tmp_path: Path, monkeypatch
) -> None:
    FakeRunner.calls = 0
    monkeypatch.setattr("mb_optimizer.optimizer.CfstRunner", FakeRunner)
    statuses: list[str] = []
    service = OptimizationService(
        engine=FakeEngine(tmp_path),
        status=lambda message, _progress: statuses.append(message),
    )

    results = service.optimize(OptimizationOptions(candidate_count=5, retest_rounds=3))

    assert FakeRunner.calls == 4
    assert len(results) == 5
    assert results[0].successful_rounds == 3
    assert statuses[-1] == "优选完成"
