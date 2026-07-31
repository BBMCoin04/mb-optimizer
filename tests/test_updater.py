from pathlib import PureWindowsPath

from mb_optimizer.updater import _update_script, _version_key


def test_version_key_normalizes_tags() -> None:
    assert _version_key("v1.4") == (1, 4, 0)
    assert _version_key("1.4.2") > _version_key("1.4.1")


def test_update_script_waits_replaces_and_restarts() -> None:
    script = _update_script(
        1234,
        PureWindowsPath("C:/Temp/new.exe"),
        PureWindowsPath("D:/Apps/MB-CF-Optimizer.exe"),
    )

    assert 'tasklist /FI "PID eq 1234"' in script
    assert 'copy /Y "C:\\Temp\\new.exe" "D:\\Apps\\MB-CF-Optimizer.exe"' in script
    assert 'start "" "D:\\Apps\\MB-CF-Optimizer.exe"' in script
