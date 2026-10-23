"""Diff two recorded corpora (record.py output) and print the per-operator table.

    python compare.py OCP_DIR NATIVE_DIR [--paths N] [--scenario NAME] [--show PATHPREFIX]

Only run-specific values are normalised: graph ids (graph_<8 hex>) and the random hex that
callsite / semantic ids derive from them.  Everything else is compared as recorded: keys, value
types (1 vs 1.0), list order, nesting.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

GRAPH_ID = re.compile(r"graph_[0-9a-f]{8}")
MISSING = object()


def norm_text(text: str) -> str:
    return GRAPH_ID.sub("graph_X", text)


def load(path: Path):
    return json.loads(norm_text(path.read_text()))


def flat(value, prefix=""):
    if isinstance(value, dict):
        if not value:
            yield prefix, ("empty", "{}")
        elif len(value) > 1:
            yield prefix + "/<key order>", ("order", ",".join(value))
        for key, item in value.items():
            yield from flat(item, f"{prefix}/{key}")
    elif isinstance(value, list):
        if not value:
            yield prefix, ("empty", "[]")
        for index, item in enumerate(value):
            yield from flat(item, f"{prefix}/{index}")
    else:
        yield prefix, (type(value).__name__, value)


def category(path: str) -> str:
    return re.sub(r"/\d+", "/#", path)


def diff_flat(a, b):
    """-> list of (kind, path, left, right); kind in only_ocp / only_native / value / type."""

    fa, fb = dict(flat(a)), dict(flat(b))
    out = []
    for path in fa.keys() | fb.keys():
        x, y = fa.get(path, MISSING), fb.get(path, MISSING)
        if x is MISSING and y[0] == "order":
            continue
        if y is MISSING and x[0] == "order":
            continue
        if x is MISSING:
            out.append(("only_native", path, None, y[1]))
        elif y is MISSING:
            out.append(("only_ocp", path, x[1], None))
        elif x[0] != y[0]:
            out.append(("type", path, f"{x[0]}:{x[1]}", f"{y[0]}:{y[1]}"))
        elif x[1] != y[1]:
            out.append(("order" if x[0] == "order" else "value", path, x[1], y[1]))
    return out


def node_op(payload, path):
    m = re.match(r"/graph/nodes/(\d+)/", path)
    if m:
        try:
            return payload["graph"]["nodes"][int(m.group(1))]["op"]
        except (KeyError, IndexError, TypeError):
            return "?"
    parts = path.split("/")
    return "<" + (parts[1] if len(parts) > 1 else "") + ">"


def main() -> int:
    args = sys.argv[1:]
    top = 12
    only = None
    show = None
    if "--paths" in args:
        i = args.index("--paths"); top = int(args[i + 1]); del args[i:i + 2]
    if "--scenario" in args:
        i = args.index("--scenario"); only = args[i + 1]; del args[i:i + 2]
    if "--show" in args:
        i = args.index("--show"); show = args[i + 1]; del args[i:i + 2]
    ocp, native = Path(args[0]), Path(args[1])
    names = sorted({p.name.split(".")[0] for p in ocp.iterdir()} | {p.name.split(".")[0] for p in native.iterdir()})
    if only:
        names = [only]

    per_op = collections.defaultdict(lambda: collections.Counter())
    cat_count = collections.Counter()
    scen_rows = []
    errors = []
    trans = collections.defaultdict(collections.Counter)
    for name in names:
        eo, en = (ocp / f"{name}.error").exists(), (native / f"{name}.error").exists()
        if eo or en:
            errors.append((name, "ocp" if eo else "", "native" if en else "",
                           (native / f"{name}.error").read_text().splitlines()[0][:110] if en else (ocp / f"{name}.error").read_text().splitlines()[0][:110]))
            if eo != en:
                continue
            continue
        a, b = load(ocp / f"{name}.model.json"), load(native / f"{name}.model.json")
        ops_a = [n["op"] for n in a["graph"]["nodes"]]
        ops_b = [n["op"] for n in b["graph"]["nodes"]]
        d = diff_flat(a, b)
        diff_nodes = set()
        for kind, path, l, r in d:
            op = node_op(a, path)
            per_op[op][kind if kind != 'order' else 'type'] += 1
            cat_count[(op, kind, category(path))] += 1
            m = re.match(r"/graph/nodes/(\d+)/", path)
            if m:
                diff_nodes.add(int(m.group(1)))
            if show and path.startswith(show):
                print(f"[{name}] {kind} {path}: {l!r} | {r!r}")
        for i, n in enumerate(a["graph"]["nodes"]):
            per_op[n["op"]]["nodes"] += 1
            if i in diff_nodes:
                per_op[n["op"]]["nodes_diff"] += 1
        scen_rows.append((name, len(a["graph"]["nodes"]), len(diff_nodes), len(d), ops_a == ops_b))
        for kind in ("freecad", "fusion360", "solidworks"):
            fa, fb = ocp / f"{name}.{kind}.py", native / f"{name}.{kind}.py"
            ea, eb = ocp / f"{name}.{kind}.error", native / f"{name}.{kind}.error"
            if fa.exists() and fb.exists():
                same = norm_text(fa.read_text()) == norm_text(fb.read_text())
                trans[kind]["identical" if same else "different"] += 1
            elif ea.exists() and eb.exists():
                same = norm_text(ea.read_text()) == norm_text(eb.read_text())
                trans[kind]["same_error" if same else "different_error"] += 1
            else:
                trans[kind]["one_side_error"] += 1

    print("== scenarios (nodes, nodes with diffs, leaf diffs, same op sequence)")
    for name, n, nd, ld, same in scen_rows:
        print(f"{name:34s} {n:4d} {nd:4d} {ld:6d} {'' if same else 'OPS DIFFER'}")
    print(f"\n== scenario errors ({len(errors)})")
    for e in errors:
        print("  ", e)
    print("\n== per operator (nodes, nodes differing, leaf: only_ocp / only_native / value / type)")
    tot = collections.Counter()
    for op, c in sorted(per_op.items(), key=lambda kv: -sum(kv[1][k] for k in ("only_ocp", "only_native", "value", "type"))):
        print(f"{op:40s} {c['nodes']:4d} {c['nodes_diff']:4d}   {c['only_ocp']:6d} {c['only_native']:6d} {c['value']:6d} {c['type']:6d}")
        tot.update(c)
    print(f"{'TOTAL':40s} {tot['nodes']:4d} {tot['nodes_diff']:4d}   {tot['only_ocp']:6d} {tot['only_native']:6d} {tot['value']:6d} {tot['type']:6d}")
    print("\n== translator outputs (scenario count)")
    for kind, c in trans.items():
        print(f"{kind:12s} {dict(c)}")
    print(f"\n== top diff categories (op, kind, path)")
    for (op, kind, cat), n in cat_count.most_common(top * 3):
        print(f"{n:6d} {op:34s} {kind:12s} {cat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
