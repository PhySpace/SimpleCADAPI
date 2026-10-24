"""Record the corpus on one backend.

    SCA_BACKEND=ocp|native [PYTHONPATH=<build>/python] python record.py OUTDIR [scenario ...]

Writes, per scenario, `<name>.model.json` (export_model_json of the session), and the
three translator outputs `<name>.freecad.py`, `<name>.fusion360.py`, `<name>.solidworks.py`
(or `<name>.<target>.error` with the exception).  A scenario that raises writes `<name>.error`.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _translate(kind: str, payload: dict) -> str:
    if kind == "freecad":
        from simplecadapi.translator.freecad_translator.translator import _FreeCADCompiler

        return _FreeCADCompiler().translate_model_payload_to_script(payload)
    if kind == "fusion360":
        from simplecadapi.translator.fusion360_translator.compiler import Fusion360ScriptTranslator

        return Fusion360ScriptTranslator().translate_model_payload_to_script(payload)
    from simplecadapi.translator.solidworks_translator.translator import _SolidWorksCompiler

    return _SolidWorksCompiler().translate_model_payload_to_script(payload, graph=payload["graph"])


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    import simplecadapi as s
    import simplecadapi.ql as ql
    from simplecadapi import GraphSession, export_model_json, import_model_json
    from scenarios import SCENARIOS

    names = sys.argv[2:] or list(SCENARIOS)
    for name in names:
        try:
            with GraphSession() as session:
                SCENARIOS[name](s, ql)
                text = export_model_json(session)
            (out / f"{name}.model.json").write_text(text)
        except Exception as exc:  # noqa: BLE001
            (out / f"{name}.error").write_text(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")
            continue
        for kind in ("freecad", "fusion360", "solidworks"):
            try:
                (out / f"{name}.{kind}.py").write_text(_translate(kind, import_model_json(text)))
            except Exception as exc:  # noqa: BLE001
                (out / f"{name}.{kind}.error").write_text(f"{type(exc).__name__}: {str(exc)[:600]}")
    print("backend", os.environ.get("SCA_BACKEND", "ocp"), "recorded", len(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
