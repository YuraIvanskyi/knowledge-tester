from io import StringIO
from unittest import mock

from apps.core.management.commands.serve import Command, static_root_is_empty


def test_static_root_is_empty(tmp_path):
    assert static_root_is_empty(tmp_path / "missing")
    assert static_root_is_empty(tmp_path)
    (tmp_path / "x.css").write_text("a")
    assert not static_root_is_empty(tmp_path)


def test_urls_for_wildcard_host_lists_lan_then_localhost():
    with mock.patch(
        "apps.core.management.commands.serve.lan_ipv4_addresses", return_value=["192.168.1.5"]
    ):
        assert Command._urls("0.0.0.0", 8000) == [
            "http://192.168.1.5:8000",
            "http://localhost:8000",
        ]


def test_urls_for_explicit_host():
    assert Command._urls("127.0.0.1", 9000) == ["http://127.0.0.1:9000"]


def test_terminal_qr_is_printed():
    out = StringIO()
    command = Command(stdout=out)
    with mock.patch("sys.stdout", out):
        command._print_qr("http://192.168.1.5:8000")
    text = out.getvalue()
    assert "http://192.168.1.5:8000" in text
    assert len(text.splitlines()) > 10
