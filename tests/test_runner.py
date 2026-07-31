import os
import threading
import time
from pathlib import Path

import pytest

from mb_optimizer.models import OptimizationOptions
from mb_optimizer.runner import CfstCancelled, CfstRunner, parse_progress_line


def test_parse_latency_progress_with_available_count() -> None:
    parsed = parse_progress_line("123 / 800 [----------------] 可用: 42")

    assert parsed == ("延迟测速", 123, 800, 42)


def test_parse_download_progress() -> None:
    assert parse_progress_line("3 / 10 [----------------]") == (
        "下载测速",
        3,
        10,
        None,
    )


def test_forces_latency_stage_for_initial_progress_frame() -> None:
    assert parse_progress_line("0 / 800 [----------------]", "延迟测速") == (
        "延迟测速",
        0,
        800,
        None,
    )


def test_rejects_non_progress_console_line() -> None:
    assert parse_progress_line("开始延迟测速") is None


def test_csv_ready_process_is_terminated_after_grace(tmp_path: Path) -> None:
    executable = _fake_cfst(tmp_path, writes_csv=True)
    output = tmp_path / "result.csv"
    runner = CfstRunner(executable)

    report = runner.run(
        tmp_path / "ips.txt",
        output,
        OptimizationOptions(),
        download_count=0,
        stop_event=threading.Event(),
        disable_download=True,
        phase_name="延迟广筛",
        csv_exit_grace_seconds=0.1,
        debug=True,
        min_speed_mb_s=0.01,
    )

    args = output.with_suffix(".args").read_text(encoding="utf-8").splitlines()
    assert "-debug" in args
    assert args[args.index("-sl") + 1] == "0.01"
    assert report.csv_ready is True
    assert report.forced_after_csv is True
    assert report.elapsed_seconds < 2
    with pytest.raises(ProcessLookupError):
        os.kill(report.pid, 0)


def test_initial_download_run_progress_stays_in_latency_stage(tmp_path: Path) -> None:
    executable = _fake_cfst(tmp_path, writes_csv=True)
    output = tmp_path / "result.csv"
    progress_events = []
    logs: list[str] = []
    runner = CfstRunner(
        executable,
        logs.append,
        log_started_at=time.monotonic() - 65,
    )

    runner.run(
        tmp_path / "ips.txt",
        output,
        OptimizationOptions(),
        download_count=3,
        stop_event=threading.Event(),
        progress=lambda *event: progress_events.append(event),
        csv_exit_grace_seconds=0.1,
    )

    assert progress_events[0][0] == "延迟测速"
    assert logs[0].startswith("[01:")


def test_stop_event_terminates_process_without_csv(tmp_path: Path) -> None:
    executable = _fake_cfst(tmp_path, writes_csv=False)
    stop_event = threading.Event()
    runner = CfstRunner(executable)

    def stop_soon() -> None:
        time.sleep(0.15)
        stop_event.set()

    threading.Thread(target=stop_soon, daemon=True).start()
    with pytest.raises(CfstCancelled, match="测速已停止"):
        runner.run(
            tmp_path / "ips.txt",
            tmp_path / "result.csv",
            OptimizationOptions(),
            download_count=0,
            stop_event=stop_event,
            disable_download=True,
        )


def _fake_cfst(tmp_path: Path, writes_csv: bool) -> Path:
    executable = tmp_path / ("fake-cfst-with-csv" if writes_csv else "fake-cfst")
    write_block = """
output.write_text(
    "IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s)\\n"
    "104.16.0.1,4,4,0,30,0\\n",
    encoding="utf-8",
)
print("0 / 10", flush=True)
print("完整测速结果已写入 result.csv", flush=True)
""" if writes_csv else ""
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "import time\n"
        "args = sys.argv[1:]\n"
        "output = pathlib.Path(args[args.index('-o') + 1])\n"
        "output.with_suffix('.args').write_text('\\n'.join(args), encoding='utf-8')\n"
        f"{write_block}\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable
