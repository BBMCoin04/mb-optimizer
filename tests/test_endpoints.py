import socket
import urllib.error

import pytest

from mb_optimizer import endpoints


def test_community_presets_are_opt_in_only() -> None:
    preset_urls = [url for _label, url in endpoints.TEST_URL_PRESETS]

    assert endpoints.COMMUNITY_7RS_URL in preset_urls
    assert endpoints.COMMUNITY_CFSPEED_URL in preset_urls
    assert endpoints.COMMUNITY_7RS_URL not in endpoints.FALLBACK_TEST_URLS
    assert endpoints.COMMUNITY_CFSPEED_URL not in endpoints.FALLBACK_TEST_URLS


def test_candidate_urls_keep_preferred_and_remove_duplicates() -> None:
    assert endpoints.test_url_candidates(
        "https://custom.example/file",
        ["https://fallback.example/file", "https://custom.example/file"],
    ) == ["https://custom.example/file", "https://fallback.example/file"]


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


def test_probe_uses_browser_user_agent_and_reads_only_probe_chunk(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int) -> bytes:
            captured["size"] = size
            return b"data"

    def open_request(request, timeout):
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(endpoints.urllib.request, "urlopen", open_request)

    endpoints.probe_test_url("https://example.com/file", timeout=3)

    assert captured["user_agent"] == endpoints.BROWSER_USER_AGENT
    assert captured["size"] == 64 * 1024
    assert captured["timeout"] == 3


def test_probe_reports_dns_failure(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(socket.gaierror(-2, "Name not known"))

    monkeypatch.setattr(endpoints.urllib.request, "urlopen", fail)

    with pytest.raises(RuntimeError, match="DNS 解析失败"):
        endpoints.probe_test_url("https://missing.example/file")
