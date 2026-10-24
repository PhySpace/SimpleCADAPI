#!/bin/sh
# usage: tools/graph_parity/run.sh <native build dir> [outroot] [scenario ...]
# Records the corpus on both backends and prints the comparison.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=${1:?native build dir}
ROOT=${2:-/tmp/graph_parity}
shift 2 2>/dev/null || shift $#
SDK=${SCA_SDK:-/Users/lildino/Project/ocws/SimpleCADAPI-native}
PY=$SDK/.venv/bin/python
rm -rf "$ROOT/ocp" "$ROOT/native"
(cd /tmp && SCA_BACKEND=ocp $PY "$HERE/record.py" "$ROOT/ocp" "$@")
(cd /tmp && SCA_BACKEND=native SCA_NO_PACK=1 PYTHONPATH=$BUILD/python $PY "$HERE/record.py" "$ROOT/native" "$@")
$PY "$HERE/compare.py" "$ROOT/ocp" "$ROOT/native"
