"""Stage 4: count actual traced operations and report conversion gaps."""
import argparse
from collections import Counter
import json
from pathlib import Path


def profile_traces(paths):
    operations, sources, unsupported = Counter(), Counter(), Counter()
    rows = []
    for path in paths:
        trace = json.loads(Path(path).read_text(encoding="utf-8"))
        for step in trace.get("steps", []):
            operations[step["op"]] += 1
            sources[step.get("source", step["op"])] += 1
        for note in trace.get("unsupported", []):
            unsupported[note.get("reason", str(note)) if isinstance(note, dict) else str(note)] += 1
        rows.append({"stem": trace.get("stem", Path(path).name.removesuffix(".trace.json")),
                     "status": trace.get("b3d_status"), "steps": len(trace.get("steps", [])),
                     "unsupported": len(trace.get("unsupported", []))})
    return {"model_count": len(rows), "operations": dict(operations.most_common()),
            "source_methods": dict(sources.most_common()), "unsupported": dict(unsupported.most_common()), "rows": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces-dir", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    paths = sorted(Path(args.traces_dir).glob("*.trace.json"))
    if not paths:
        parser.error("no traces found")
    report = profile_traces(paths)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
