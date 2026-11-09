# First of all, you should follow the phylosophy below whatever you are going to do:

## Completeness Principle — Boil the Lake
AI-assisted coding makes the macrginal cost of completeness near-zero. When you present options:

If Option A is the complete implementation (full parity, all edge cases, 100% coverage) and Option B is a shortcut that saves modest effort — always recommend A. The delta between 80 lines and 150 lines is meaningless with Codex. "Good enough" is the wrong instinct when "complete" costs minutes more.
Lake vs. ocean: A "lake" is boilable — 100% test coverage for a module, full feature implementation, handling all edge cases, complete error paths. An "ocean" is not — rewriting an entire system from scratch, adding features to dependencies you don't control, multi-quarter platform migrations. Recommend boiling lakes. Flag oceans as out of scope.
When estimating effort, always show both scales: human team time and Codex time. The compression ratio varies by task type — use this reference:
Task type	Human team	Codex	Compression
Boilerplate / scaffolding	2 days	15 min	~100x
Test writing	1 day	15 min	~50x
Feature implementation	1 week	30 min	~30x
Bug fix + regression test	4 hours	15 min	~20x
Architecture / design	2 days	4 hours	~5x
Research / exploration	1 day	3 hours	~3x
This principle applies to test coverage, error handling, documentation, edge cases, and feature completeness. Don't skip the last 10% to "save time" — with AI, that 10% costs seconds.
Anti-patterns — DON'T do this:

BAD: "Choose B — it covers 90% of the value with less code." (If A is only 70 lines more, choose A.)
BAD: "We can skip edge case handling to save time." (Edge case handling costs minutes with Codex.)
BAD: "Let's defer test coverage to a follow-up PR." (Tests are the cheapest lake to boil.)
BAD: Quoting only human-team effort: "This would take 2 weeks." (Say: "2 weeks human / ~1 hour Codex.")


# Second: Only do necessary action, rather than do much is better.

# Third: Never use complex English Terms in chinese, you should say normal chinese.

# Before editing or adding code, plan for module splitting rather than putting code in one file which is not human readable.

# If you have any experience during working, you can write it down here, with detailed reasons.

## Experience: rebuilding the C++ module on this Windows machine (2026-11-10)

Why this is written down: changing anything under `src/cpp` needs a rebuilt `_native` module, and the obvious command
failed three times before it worked. Each failure had a cause that is not visible from the error text.

- Use the project's own path, `uv pip install --python .venv/Scripts/python.exe -e . --no-deps -v`. It reuses
  `src/cpp/build/wheel/<tag>/` (incremental when the compiler flags did not change). Plain `ninja _native` in that
  directory fails: its CMakeCache points into a temporary isolated build environment (ninja, pybind11, python) that was
  deleted when the last build ended, so CMake cannot regenerate.
- A bare run picks the NMake generator (no `nmake` here) and then a stale OpenCASCADE from `%TEMP%\occt-build-*`. Pass
  the MinGW toolchain and the real OCCT explicitly, in the same shell:
  `CMAKE_GENERATOR=Ninja CC=<scoop gcc>/gcc.exe CXX=<scoop gcc>/g++.exe
  CMAKE_ARGS="-DCMAKE_MAKE_PROGRAM=<scoop shims>/ninja.exe -DSCAD_OCCT_PREFIX=C:/occt -DOpenCASCADE_DIR=C:/occt/lib/cmake/opencascade"`.
  (The first full rebuild after the environment changed took about 4 minutes; the next, after one binding file, 1m16s.)
- The build ends with "failed to remove ... Scripts/sca.exe" when an editor (`sca edit`) is running: that is only the
  install step. The compiled module is already at `src/cpp/build/wheel/<tag>/bindings/python/_native.<tag>.pyd`.
  The installed copy in `.venv/lib/site-packages/simplecadapi/_cpp/` is locked by the running processes (copy fails with
  "Device or resource busy") but Windows lets you RENAME a loaded DLL: rename the old `.pyd` aside, copy the new one in.
  New processes load the new module, running editors keep the old one. Do not kill the user's editor to install.
- The built web UI (`src/simplecadapi/editor/webui/`) is git-ignored: after changing `editor-web/src`, rebuild it with
  `editor-web/node_modules/.bin/vite.exe build`, and typecheck with `node editor-web/node_modules/typescript/bin/tsc
  --noEmit -p editor-web/tsconfig.json` (`npx tsc` downloads an unrelated package named tsc).
- `design-docs/` is git-ignored but some files in it are tracked: a new file there needs `git add -f`.
- `docstrings.json` is read back over the docstring in the Python source at import time, so a docstring edit is
  invisible in `help()` until `_glue/docstrings.json` is updated too (edit the one line, do not re-dump the file).
