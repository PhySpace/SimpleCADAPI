#!/usr/bin/env bash
# Generate the type stubs of the compiled module `simplecadapi._cpp._native` with pybind11-stubgen.
#
#   tools/gen_stubs.sh            write the stubs to src/simplecadapi/_cpp/ (commit the result)
#   tools/gen_stubs.sh --check    regenerate into a temp dir and fail if the checked-in stubs differ
#
# Needs the module built and importable (editable install / `uv sync`) and `pip install pybind11-stubgen==2.5.5`
# (2.5.5 is the last 2.x release; 3.0.0 also exists on PyPI but changes the output format).
# PYTHON overrides the interpreter (default: python3); STUBGEN the command (default: <PYTHON> -m pybind11_stubgen).
set -euo pipefail
repo="$(cd "$(dirname "$0")/../../.." && pwd)"
dest="$repo/src/simplecadapi/_cpp"
py="${PYTHON:-python3}"
mode="write"
[ "${1:-}" = "--check" ] && mode="check"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# shellcheck disable=SC2086  # PYTHON / STUBGEN may carry arguments (e.g. "uv run python")
${STUBGEN:-$py -m pybind11_stubgen} simplecadapi._cpp._native --output-dir "$tmp" --ignore-all-errors

# The stubgen output tree is <tmp>/simplecadapi/_cpp/_native.pyi or <tmp>/simplecadapi/_cpp/_native/__init__.pyi.
src="$tmp/simplecadapi/_cpp"
if [ ! -e "$src/_native.pyi" ] && [ ! -d "$src/_native" ]; then
  echo "gen_stubs: pybind11-stubgen produced nothing under $src" >&2
  exit 2
fi

# pybind11-stubgen writes the re-export imports in set order, which differs from run to run: sort every run of
# consecutive import lines so that the output is reproducible (and the --check below means something).
"$py" - "$src" <<'PY'
import pathlib, sys

for path in pathlib.Path(sys.argv[1]).rglob("*.pyi"):
    lines, out, run = path.read_text().split("\n"), [], []
    for line in lines + [""]:
        if line.startswith(("from ", "import ")):
            run.append(line)
            continue
        out.extend(sorted(run))
        run = []
        out.append(line)
    path.write_text("\n".join(out[:-1]))
PY

if [ "$mode" = "check" ]; then
  status=0
  if [ -e "$src/_native.pyi" ]; then
    diff -u "$dest/_native.pyi" "$src/_native.pyi" || status=1
  else
    diff -ru "$dest/_native" "$src/_native" || status=1
  fi
  [ "$status" = 0 ] || echo "gen_stubs: stubs are stale; run src/cpp/tools/gen_stubs.sh and commit" >&2
  exit $status
fi

rm -rf "$dest/_native" "$dest/_native.pyi"
if [ -e "$src/_native.pyi" ]; then cp "$src/_native.pyi" "$dest/"; else cp -R "$src/_native" "$dest/"; fi
echo "wrote stubs to $dest"
