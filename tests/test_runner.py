from mb_optimizer.runner import parse_progress_line


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


def test_rejects_non_progress_console_line() -> None:
    assert parse_progress_line("开始延迟测速") is None
