import io
import os

from simplecadapi._internal.os_compat import harden_console_streams, with_binary_flag
from simplecadapi.build.dependencies import read_stable_file


def test_with_binary_flag_or_in_the_attribute_when_present(monkeypatch):
    fake = 1 << 28
    monkeypatch.setattr(os, "O_BINARY", fake, raising=False)
    assert with_binary_flag(os.O_RDONLY) == os.O_RDONLY | fake


def test_with_binary_flag_passes_through_when_attribute_missing(monkeypatch):
    monkeypatch.delattr(os, "O_BINARY", raising=False)
    assert with_binary_flag(os.O_RDONLY) == os.O_RDONLY


def _spy_binary_open(monkeypatch):
    fake = 1 << 28
    real_open = os.open
    seen = []

    def spy(path, flags, *args, **kwargs):
        seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    monkeypatch.setattr(os, "O_BINARY", fake, raising=False)
    return seen, fake


def test_read_stable_file_opens_in_binary_mode(tmp_path, monkeypatch):
    seen, fake = _spy_binary_open(monkeypatch)
    target = tmp_path / "builder.py"
    target.write_bytes(b"x = 1\r\ny = 2\r\n")

    payload = read_stable_file(
        target, max_bytes=1024, error_path="/file_input/path"
    )

    assert payload == b"x = 1\r\ny = 2\r\n"
    assert seen and seen[0] & fake


def test_stable_source_bytes_opens_in_binary_mode(tmp_path, monkeypatch):
    from simplecadapi.artifacts.feature_graph import _stable_source_bytes

    seen, fake = _spy_binary_open(monkeypatch)
    target = tmp_path / "source.py"
    target.write_bytes(b"a = 1\n")

    payload = _stable_source_bytes(target, max_bytes=1024, error_path="/source")

    assert payload == b"a = 1\n"
    assert seen and seen[0] & fake


def test_harden_console_streams_escapes_unencodable_diagnostics():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="\n")

    harden_console_streams((stream,))

    stream.write("警告: wire fault\n")
    stream.flush()
    assert raw.getvalue() == b"\\u8b66\\u544a: wire fault\n"


def test_harden_console_streams_keeps_utf_streams_untouched():
    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")

    harden_console_streams((stream,))

    assert stream.errors == "strict"


def test_harden_console_streams_tolerates_plain_and_closed_streams():
    harden_console_streams((object(),))
    closed = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    closed.close()
    harden_console_streams((closed,))
