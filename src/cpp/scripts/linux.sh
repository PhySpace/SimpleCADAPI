#!/usr/bin/env bash
# Build and run areas on Linux (the OrbStack Ubuntu VM is x86_64; GCC + libstdc++ assertions
# catch out-of-range reads and missing includes that macOS tolerates).
#
#   scripts/linux.sh <area> [<area> ...]     e.g. scripts/linux.sh reactive io
#
# Uses build/linux-<first area>; never share a build dir with the macOS tree.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: $0 <area>..." >&2; exit 2; }
root="$(cd "$(dirname "$0")/.." && pwd)"
dir="build/linux-$1"
targets=()
for area in "$@"; do targets+=("test_$area"); done

remote="cd '$root' && cmake -S . -B $dir -G Ninja -DCMAKE_BUILD_TYPE=Debug -DSCAD_BUILD_PYTHON=OFF \
-DCMAKE_CXX_COMPILER_LAUNCHER=ccache >/dev/null && \
{ ninja -C $dir -k 0 ${targets[*]} 2>&1 | grep -E 'error|FAILED|warning:' | sed 's|$root/||' | cut -c1-240 | head -30 || true; } ; \
for t in ${targets[*]}; do echo \"== \$t\"; ./$dir/tests/cpp/\$t 2>&1 | tail -6; done"
exec orb -m ubuntu bash -lc "$remote"
