"""Read evaluated SimpleCADAPI parameters and explicit drawing intent from a part notebook."""

import ast
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory


def overrides_from_args(entries):
    overrides = {}
    for entry in entries:
        name, sep, value = entry.partition("=")
        if not sep or not name.isidentifier() or name in overrides:
            raise ValueError(f"Expected a unique --set NAME=VALUE: {entry!r}")
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = value
        if not isinstance(parsed, (int, float, bool, str)) or (
            isinstance(parsed, float) and not math.isfinite(parsed)
        ):
            raise ValueError(
                f"{name}: a finite numeric, boolean or string override is required"
            )
        overrides[name] = parsed
    return overrides


def parameter_value(value, unit, name):
    from simplecadapi.params.expr import Var, get_unit

    if isinstance(value, Var) and value.unit is not None:
        return (
            float(value),
            value.unit.symbol,
            (value.dimension.length == 1 and value.dimension.angle == 0),
        )
    if isinstance(value, Var):
        if unit is None:
            return float(value), None, False
        value = float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return (
            value if isinstance(value, (bool, str, int, float)) else None,
            unit,
            False,
        )
    resolved = get_unit(unit) if unit else None
    if resolved is not None and (
        resolved.dimension.length,
        resolved.dimension.angle,
    ) != (1, 0):
        return value, unit, False
    return (
        (resolved.to_canonical(value) if resolved is not None else float(value)),
        unit or "mm",
        True,
    )


def prepare_notebook(path, step, overrides):
    from simplecadapi import Part
    from simplecadapi.kernel.ocp_export import export_step_shapes
    from simplecadapi.params.expr import Var
    from simplecadapi.runtime import run_notebook
    from simplecadapi.runtime.params import list_parameters

    if step.suffix.lower() != ".step" or step.resolve() == path.resolve():
        raise ValueError("Notebook STEP snapshot must be a distinct .step path")
    run = run_notebook(path, overrides=overrides, cache=False)
    if not isinstance(run.product, Part):
        raise ValueError("Notebook drawing requires a single SimpleCADAPI Part")
    declared = {spec.name: spec for spec in list_parameters(path)}
    intent = run.values.get("DRAWING_INTENT", {})
    if not isinstance(intent, dict) or intent.keys() - {"dimensions", "datums"}:
        raise ValueError("DRAWING_INTENT accepts dimensions and datums lists")
    rows, datums = intent.get("dimensions", []), intent.get("datums", [])
    if not isinstance(rows, (list, tuple)) or not isinstance(datums, (list, tuple)):
        raise ValueError("DRAWING_INTENT dimensions and datums must be lists")
    ledger = {}
    for name, spec in declared.items():
        value, unit, length = parameter_value(run.values.get(name), spec.unit, name)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{name}: the evaluated parameter must be finite")
        field = "evaluated_mm" if length else "evaluated"
        ledger[name] = dict(
            name=name,
            group=spec.group,
            unit=unit,
            status="unbound" if length else "non_length",
        )
        ledger[name][field] = value
    dims = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each design-intent dimension must be a dictionary")
        values = row.copy()
        name = values.pop("parameter", None)
        if not isinstance(name, str) or name not in run.values:
            raise ValueError(f"Unknown notebook parameter {name!r}")
        if "value" in values:
            raise ValueError(
                f"{name}: the dimension expectation comes from the notebook parameter"
            )
        factor = values.pop("factor", 1)
        if (
            isinstance(factor, bool)
            or not isinstance(factor, (int, float))
            or not math.isfinite(factor)
            or factor <= 0
        ):
            raise ValueError(f"{name}: factor must be a positive finite number")
        unit_hint = values.pop("unit", None) or (
            declared[name].unit if name in declared else None
        )
        expected, unit, length = parameter_value(run.values[name], unit_hint, name)
        if not length or not math.isfinite(expected * factor):
            raise ValueError(
                f"{name}: a model length is required for a linear, diameter or radius dimension"
            )
        values.setdefault("caption", name)
        values.setdefault("kind", "size")
        values["value"] = expected * factor
        values.setdefault(
            "dec", max(0, len(f"{values['value']:.6f}".rstrip("0").partition(".")[2]))
        )
        if values.pop("use_parameter_tolerance", False):
            var = run.values[name]
            if (
                not isinstance(var, Var)
                or var.canonical_tolerance is None
                or values.get("tol") is not None
            ):
                raise ValueError(
                    f"{name}: select either explicit tol or a tolerance declared on the evaluated Var"
                )
            limit = var.canonical_tolerance
            values["tol"] = [
                limit.upper_deviation * factor,
                limit.lower_deviation * factor,
            ]
        values["covers"] = list(dict.fromkeys([name, *values.get("covers", [])]))
        dims.append(values)
        item = ledger.setdefault(
            name, dict(name=name, group="", unit=unit, evaluated_mm=expected)
        )
        item.pop("evaluated", None)
        item.update(unit=unit, evaluated_mm=expected)
        item["status"] = "declared"
        item.setdefault("dimensions", []).append(
            dict(caption=values["caption"], expected_mm=values["value"], factor=factor)
        )

    step.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=step.parent) as temp:
        staged = Path(temp) / step.name
        export_step_shapes([run.product.body._native_wrapped], str(staged))
        staged.replace(step)
    return dict(
        dimensions=dims,
        datums=list(datums),
        parameters=list(ledger.values()),
        source=dict(
            notebook=str(path),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            overrides=overrides,
            product_id=run.config.id,
            content_hash=run.definition.content_hash,
        ),
    )
