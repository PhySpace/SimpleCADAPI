#!/usr/bin/env bash
# `tools/check_format.sh` lists the files clang-format would change (exit 1 if any); `tools/check_format.sh --fix` rewrites them.
# Version: clang-format 18 (pip install clang-format==18.1.8).
set -euo pipefail
cd "$(dirname "$0")/.."
CF="${CLANG_FORMAT:-clang-format}"
files=$(find src include bindings tests/cpp -type f \( -name '*.cpp' -o -name '*.hpp' -o -name '*.h' \))
if [ "${1:-}" = "--fix" ]; then
  echo "$files" | xargs "$CF" -i
else
  bad=0
  for f in $files; do
    if ! "$CF" --dry-run --Werror "$f" >/dev/null 2>&1; then echo "needs formatting: $f"; bad=1; fi
  done
  exit $bad
fi
