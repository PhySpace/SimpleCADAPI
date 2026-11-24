"""Apply the audited OCCT patch set without modifying an unrelated source tree.

Only files with locked before/after SHA256 values are accepted. Patch application
is exact (no fuzz or offset guessing), idempotent, and needs no external git.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PATCH_DIR = Path(__file__).resolve().parents[1] / "patches" / "occt"
TOOLKIT_FILE = PATCH_DIR.parents[1] / 'cmake' / 'ScadOcct.cmake'


def toolkits() -> list[str]:
    body = TOOLKIT_FILE.read_text().split('set(SCAD_OCCT_TOOLKITS', 1)[1].split(')', 1)[0]
    return re.sub(r'#[^\n]*', '', body).split()


def recipe() -> str:
    h = hashlib.sha256()
    sources = [Path(__file__), Path(__file__).with_name('build_occt.py'), TOOLKIT_FILE,
               PATCH_DIR / 'manifest.json', *sorted(PATCH_DIR.glob('*.patch')), *sorted((PATCH_DIR / 'overlay').glob('*.*'))]
    for path in sources:
        h.update(path.name.encode() + b'\0' + path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return h.hexdigest()


def append_line(path: Path, line: str) -> None:
    text = path.read_text(encoding='utf8')
    if line not in text:
        path.write_text(text.rstrip('\n') + '\n' + line + '\n', encoding='utf8')


def install_overlay(source: Path) -> None:
    apply(source)
    for path in sorted((PATCH_DIR / 'overlay').glob('*.*')):
        package = source / 'src' / path.name.split('_')[0]
        (package / path.name).write_bytes(path.read_bytes())
        append_line(package / 'FILES', path.name)
    append_line(source / 'src/TKFillet/EXTERNLIB', 'TKPrim')
    append_line(source / 'adm/cmake/occt_toolkit.cmake', '''if(WIN32 AND NOT BUILD_SHARED_LIBS)
  target_compile_definitions(${PROJECT_NAME} INTERFACE OCCT_STATIC_BUILD OCCT_NO_PLUGINS _USE_MATH_DEFINES)
endif()''')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest() -> dict:
    return json.loads((PATCH_DIR / "manifest.json").read_text(encoding="utf8"))


def identity() -> dict:
    data = manifest()
    return {"tag": data["tag"], "commit": data["commit"], "patchset": data["patchset"],
            "manifest_sha256": digest((PATCH_DIR / "manifest.json").read_bytes()),
            "patches": [{"file": name, "sha256": digest((PATCH_DIR / name).read_bytes())}
                        for name in data["patches"]]}


def apply(source: Path) -> dict:
    lock = manifest()
    source = source.resolve()
    states = {}
    for name, hashes in lock["files"].items():
        filename = source / name
        raw = filename.read_bytes().replace(b"\r\n", b"\n")
        checksum = digest(raw)
        if checksum not in (hashes["before"], hashes["after"]):
            raise RuntimeError(f"OCCT source differs from locked {lock['tag']}: {filename} ({checksum})")
        states[name] = checksum == hashes["after"]
    outputs = {}
    for patch_name in lock["patches"]:
        lines = (PATCH_DIR / patch_name).read_text(encoding="utf8").splitlines(keepends=True)
        i = 0
        while i < len(lines):
            if not lines[i].startswith("--- a/"):
                i += 1
                continue
            name = lines[i][6:].strip()
            i += 2  # +++ b/path
            if name not in states:
                raise RuntimeError(f"Patch changes an unlocked file: {name}")
            original = (source / name).read_text(encoding="utf8").splitlines(keepends=True)
            output = []
            cursor = 0
            while i < len(lines) and lines[i].startswith("@@"):
                header = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", lines[i])
                if header is None:
                    raise RuntimeError(f"Invalid hunk in {patch_name}")
                start = int(header[1]) - 1
                output.extend(original[cursor:start])
                cursor = start
                i += 1
                while i < len(lines) and lines[i][:1] in (" ", "+", "-") and not lines[i].startswith("--- a/"):
                    line = lines[i]
                    if line[0] in (" ", "-"):
                        if not states[name] and (cursor >= len(original) or original[cursor] != line[1:]):
                            raise RuntimeError(f"Patch context mismatch: {name}:{cursor+1}")
                        cursor += 1
                    if line[0] in (" ", "+"):
                        output.append(line[1:])
                    i += 1
            if not states[name]:
                output.extend(original[cursor:])
                raw = "".join(output).encode("utf8")
                if digest(raw) != lock["files"][name]["after"]:
                    raise RuntimeError(f"Patched output differs from locked digest: {name}")
                outputs[source / name] = raw
    # Validate all hunks before mutating any source.
    for filename, raw in outputs.items():
        filename.write_bytes(raw)
    return identity()
