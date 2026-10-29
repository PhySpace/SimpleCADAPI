#!/usr/bin/env python3
"""List every site in src/ that constructs an OCCT boolean/fillet/offset builder in a function that never mentions
`occt_guard` (the wrapper of include/scad/core/error.hpp that turns Standard_Failure into scad::KernelError).

    python3 tools/check_occt_guard.py [--root src/cpp] [--strict]

Heuristic, not exact: the "function" is the outermost non-namespace, non-type brace block around the site, and the
site passes if that block mentions occt_guard / rethrow_occt_failure.  A function that is only ever called from inside
an occt_guard lambda says so with a comment `// occt_guard: the caller <name> runs this inside occt_guard` (above or
in the function); without it, it is reported.  Exit status is 0
unless --strict is given and violations exist.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BUILDER = re.compile(
    r"\b(BRepAlgoAPI_(?:Fuse|Cut|Common|Section)|BRepFilletAPI_\w+|BRepOffsetAPI_\w+)\b")
# `Type name(`, `Type name{`, `Type name;`, `Type(` (temporary), `make_unique<Type>` / `new Type`.
CONSTRUCT = re.compile(
    r"(?:\bnew\s+|make_(?:unique|shared)\s*<\s*)?\b(?:BRepAlgoAPI_(?:Fuse|Cut|Common|Section)|BRepFilletAPI_\w+|"
    r"BRepOffsetAPI_\w+)\b(?:\s*>)?\s*(?:\w+\s*[({;=]|[({])")
GUARD = re.compile(r"\b(occt_guard|operator_scope|rethrow_occt_failure)\b")  # operator_scope = guarded + occt_guard
# A helper that is only ever called from inside a guard says so, once, above (or in) the function; the audit takes
# the claim at its word, and a reviewer can check the one caller it names.
CALLER_GUARDS = re.compile(r"occt_guard:\s*the caller\b")
SKIP_DIRS = {"build", "third_party", "occt_dev"}


def strip(text: str) -> str:
    """Blank out comments, string and char literals, keeping offsets and newlines."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            j += 1
        else:
            i += 1
            continue
        for k in range(i, min(j, n)):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def function_spans(code: str):
    """(start, end) of every outermost function-like block (not namespace / type scope)."""
    spans, stack = [], []
    for m in re.finditer(r"[{}]", code):
        if m.group() == "{":
            head = code[max(0, m.start() - 400):m.start()]
            head = head[head.rfind(";") + 1:] if ";" in head else head
            head = head[head.rfind("}") + 1:] if "}" in head else head
            if re.search(r"\bnamespace\b[^()]*$", head) or re.search(r"\bextern\s*$", head):  # extern "C" is blanked
                kind = "ns"
            elif re.search(r"\b(class|struct|union|enum)\b[^()]*$", head):
                kind = "type"
            else:
                kind = "fn"
            stack.append((kind, m.start()))
        elif stack:
            kind, start = stack.pop()
            if kind == "fn" and not any(k == "fn" for k, _ in stack):
                spans.append((start, m.start()))
    return spans


def scan(path: Path):
    raw = path.read_text(errors="replace")
    code = strip(raw)
    spans = function_spans(code)
    hits = []
    for m in CONSTRUCT.finditer(code):
        line_start = code.rfind("\n", 0, m.start()) + 1
        line = code[line_start:code.find("\n", m.start())]
        if line.lstrip().startswith("#"):
            continue
        # a reference/pointer declaration or parameter is not a construction
        after = code[m.start():m.end()]
        if re.search(r"[&*]\s*\w*\s*[,)]", after):
            continue
        span = next(((s, e) for s, e in spans if s <= m.start() <= e), None)
        if span is None:
            continue  # declaration at class/namespace scope (member), not a call site
        claim = raw[max(0, span[0] - 400):span[1]]
        if not GUARD.search(code[span[0]:span[1]]) and not CALLER_GUARDS.search(claim):
            hits.append((raw.count("\n", 0, m.start()) + 1, BUILDER.search(after).group(1)))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    root = Path(args.root)
    total = 0
    for path in sorted((root / "src").rglob("*")):
        if path.suffix not in {".cpp", ".hpp", ".h"} or SKIP_DIRS & set(path.parts):
            continue
        if path.name == "occt_guard.cpp":
            continue
        for line, builder in scan(path):
            print(f"{path.relative_to(root)}:{line}: {builder} constructed in a function without occt_guard")
            total += 1
    print(f"{total} unguarded builder construction(s)")
    return 1 if (args.strict and total) else 0


if __name__ == "__main__":
    sys.exit(main())
