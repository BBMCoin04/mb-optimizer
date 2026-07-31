import json
import zipfile
from pathlib import Path

from mb_optimizer.engine import ENGINE_VERSION, EngineManager, _sha256


def test_extracts_only_required_engine_files(tmp_path: Path) -> None:
    archive = tmp_path / "engine.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("folder/cfst.exe", b"exe")
        bundle.writestr("ip.txt", "1.1.1.0/24\n")
        bundle.writestr("ipv6.txt", "2606:4700::/32\n")
        bundle.writestr("untrusted.cmd", "ignored")

    manager = EngineManager(tmp_path / "engine")
    manager.root.mkdir()
    manager._extract(archive)

    assert manager.executable.read_bytes() == b"exe"
    assert not (manager.root / "untrusted.cmd").exists()
    marker = json.loads(manager.marker.read_text(encoding="utf-8"))
    assert marker["version"] == ENGINE_VERSION
    assert marker["executable_sha256"] == _sha256(manager.executable)
