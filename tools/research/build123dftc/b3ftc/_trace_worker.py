"""Private process boundary. Model output goes to the parent's log, not JSON."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b3ftc.tracer import trace_file


if __name__ == "__main__":
    source, output = map(Path, sys.argv[1:])
    payload = trace_file(source)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
