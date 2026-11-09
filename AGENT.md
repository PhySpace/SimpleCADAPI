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

## How to commit: one decision per commit, with the reasons (the owner's rule, 2026-11-10)

Why this rule exists: a change that reverses an earlier design (for example "a Part holds exactly one solid") is
made of many small edits across layers. Someone who takes over later sees the edits, not the conversation that
caused them. The commit history is where that conversation has to survive, so that handing over and tracing back
are possible without asking anyone.

1. **One commit per decision, split as finely as is sensible.** A decision is a choice that could have gone the
   other way (a rule, a format, an API removal, a place where a feature lives). Edits that only follow from a
   decision (tests, docs, comments, dead code) are their own commits, each stating which decision they follow.
   Do not mix two decisions in one commit; do not split one decision so far that no commit holds its reason.
2. **Every message states the chain of the decision and WHY, and the why carries the core of the discussion**
   between the owner and the assistant that led to it: the need that started it, the owner's judgement, the
   analysis that was agreed, and what was rejected. Write it as what was said, not as a summary of the diff. The
   reader must be able to see why the decision exists from the message alone.
3. **Message layout** (subject line, then paragraphs; the subject says the decision, not only the edit):
   - `DECISION:` what is decided, in one or two sentences.
   - `WHY` (name the discussion and its date; point to the decision record): the need, the judgement, the
     analysis, and facts found by checking (with where and how they were checked).
   - `ALTERNATIVE CONSIDERED AND REJECTED:` when there was one, and why.
   - `WHAT CHANGES:` the files / behaviour, only as far as the reason needs; and what is kept on purpose.
   - `Checked:` what was run and what it showed, including what was not verified.
   - Last line: `Co-Authored-By: ...` as the session's attribution reminder says.
4. **A decision that outlives one commit gets a decision record** in `design-docs/<name>.md` (the whole
   discussion, the audit table, the rules after the decision, the list of commits). The first commit of the
   series carries the full account; later commits carry the short form and name that commit or the record.
   `design-docs/` is git-ignored: add a new file with `git add -f`. If an older design document is replaced, mark
   it superseded at its top and keep its body.
5. **Refer to other commits by subject line, not by hash.** Hashes change when history is rewritten (rewording a
   message with `filter-branch` changed every hash of the series once); a subject survives. A hash is acceptable
   only for a commit that is already published or will not be rewritten.
6. **Say the true thing.** If a message claims a check passed or a set of files is equal, run the check first; if
   a claim turns out wrong, `git commit --amend` while the commit is still the newest and unpublished.
7. **Mechanics that worked here**: write the message to a file with the file tool and use `git commit -F file`
   (long heredocs with quotes broke in this shell); stage by explicit paths, never `git add -A` (the untracked
   `STILL` file is not ours); work on a branch, not on `master`; do not push or merge unless asked.
