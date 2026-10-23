"""The library carries no Chinese: every message, label, docstring and comment under ``src/`` is English.

(Examples, documentation and the research tools are outside the library; the third-party OCCT checkout that the C++
build may leave in ``src/cpp/.setup`` and the built web UI are not ours.)
"""

import re
from pathlib import Path

CJK = re.compile("[㐀-鿿豈-﫿　-〿＀-￯]")
SRC = Path(__file__).resolve().parents[1] / "src"
SKIP_DIRS = {"build", "__pycache__", "webui", "node_modules", ".setup"}
SUFFIXES = {".py", ".cpp", ".hpp", ".h", ".txt", ".toml", ".json", ".md", ".cmake", ".yml", ".yaml", ".sh"}


def test_no_chinese_text_in_the_library():
    found = []
    for path in SRC.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES and path.name != "CMakeLists.txt":
            continue
        if SKIP_DIRS & set(path.relative_to(SRC).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if CJK.search(line):
                found.append(f"{path.relative_to(SRC)}:{number}: {line.strip()[:80]}")
    assert not found, "Chinese text in the library:\n" + "\n".join(found[:40])
