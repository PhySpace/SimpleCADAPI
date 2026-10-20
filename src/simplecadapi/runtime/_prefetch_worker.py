"""A worker process of :mod:`.prefetch`: runs the notebooks it is sent.

Jobs and answers are length-prefixed pickles on stdin and the original stdout;
file descriptor 1 itself is pointed at the null device, so whatever a notebook
prints (from Python or from C) cannot get in the way of the protocol.
"""

from __future__ import annotations

import os
import pickle
import struct
import sys
from pathlib import Path


def main() -> int:
    reply = os.fdopen(os.dup(1), "wb")
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    jobs = sys.stdin.buffer
    from simplecadapi.runtime.runner import run_notebook

    while True:
        header = jobs.read(8)
        if len(header) < 8:
            return 0
        path, child_id, overrides = pickle.loads(jobs.read(struct.unpack(">Q", header)[0]))
        try:
            run_notebook(Path(path), id=child_id, overrides=overrides)
            answer: tuple[str, str] = ("ok", "")
        except BaseException as error:  # noqa: BLE001 - reported, the parent runs it for itself
            answer = ("error", f"{type(error).__name__}: {error}"[-2000:])
        data = pickle.dumps(answer)
        reply.write(struct.pack(">Q", len(data)) + data)
        reply.flush()


if __name__ == "__main__":
    sys.exit(main())
