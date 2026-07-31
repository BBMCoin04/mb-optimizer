import pytest

from mb_optimizer import endpoints


def test_resolve_uses_fallback_when_preferred_fails(monkeypatch) -> None:
    attempted: list[str] = []

    def probe(url: str) -> None:
        attempted.append(url)
        if url == "https://broken.example/file":
            raise RuntimeError("HTTP 403")

    monkeypatch.setattr(endpoints, "probe_test_url", probe)

    selected = endpoints.resolve_test_url(
        "https://broken.example/file",
        ["https://working.example/file"],
    )

    assert selected == "https://working.example/file"
    assert attempted == ["https://broken.example/file", "https://working.example/file"]


def test_resolve_reports_all_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        endpoints,
        "probe_test_url",
        lambda _url: (_ for _ in ()).throw(RuntimeError("HTTP 403")),
    )

    with pytest.raises(RuntimeError, match="没有可用的测速地址"):
        endpoints.resolve_test_url("https://broken.example/file", [])
