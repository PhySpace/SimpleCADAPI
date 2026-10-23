"""Execute build123d and capture the actual solid construction graph.

Instrumentation sits at the topology API: Builder, algebra and direct topology
calls consequently share one history. Sketches are transcribed as analytic/NURBS
profiles at feature boundaries. Tracing executes Python; only trusted models
should be supplied. Patches are scoped and restored even on execution failure.
"""
from __future__ import annotations

from contextlib import contextmanager
import functools
import hashlib
import inspect
from pathlib import Path
import sys
import threading
import traceback
from typing import Any

from . import geometry
from .schema import SCHEMA_VERSION, empty_trace

schema_version = SCHEMA_VERSION
_LOCK = threading.RLock()


class Recorder:
    def __init__(self):
        self.trace = empty_trace()
        self.depth = 0
        self.refs: dict[int, str] = {}
        self.components: dict[int, tuple[str, int, Any]] = {}
        self.ref_solids: dict[str, list[Any]] = {}
        self.patches: list[tuple[Any, str, Any, bool]] = []
        self.retained: list[Any] = []
        self.serial = 0

    @staticmethod
    def key(shape):
        return hash(shape.wrapped)

    @staticmethod
    def is_solid(shape):
        return hasattr(shape, "solids") and bool(shape.solids())

    def register(self, shape, ref):
        if shape is None:
            return
        if isinstance(shape, (list, tuple)):
            solids = [s for item in shape if item is not None for s in item.solids()]
            if len(solids) == 1:
                self.register(solids[0], ref)
            else:
                for index, solid in enumerate(solids):
                    self.components[self.key(solid)] = (ref, index, solid)
                    self.retained.append(solid.wrapped)
                for item in shape:
                    if item is not None and len(item.solids()) == 1:
                        single = item.solids()[0]
                        if self.key(single) in self.components:
                            self.components[self.key(item)] = self.components[self.key(single)]
            return
        if not hasattr(shape, "wrapped") or shape.wrapped is None:
            return
        self.refs[self.key(shape)] = ref
        self.retained.append(shape.wrapped)
        solids = shape.solids()
        if len(solids) == 1:
            self.refs[self.key(solids[0])] = ref
            self.retained.append(solids[0].wrapped)
        elif len(solids) > 1:
            for index, solid in enumerate(solids):
                self.components[self.key(solid)] = (ref, index, solid)
                self.retained.append(solid.wrapped)

    def emit(self, op, inputs, parameters, result, source, **extra):
        import build123d as b
        from simplecadapi._cpp.occt.TopLoc import TopLoc_Location
        results = result if isinstance(result, (list, tuple)) else [result]
        solids = [s for obj in results if obj is not None for s in obj.solids()]
        if len(solids) > 1:
            extra["result_components"] = [geometry.metrics(s) for s in solids]
        if op == "union" and len(solids) > 1:
            groups = []
            self.depth += 1
            try:
                for output in solids:
                    group = []
                    output_box = geometry.metrics(output)["bbox"]
                    for input_ref in inputs:
                        for operand in self.ref_solids.get(input_ref, []):
                            box = geometry.metrics(operand)["bbox"]
                            if any(box[i] < output_box[i] - 1e-5 or box[i+3] > output_box[i+3] + 1e-5 for i in range(3)):
                                continue
                            common = operand.intersect(output)
                            overlap = geometry.metrics(common)["volume"] if common is not None else 0.
                            operand_volume = geometry.metrics(operand)["volume"]
                            if abs(overlap - operand_volume) <= max(1e-6, abs(operand_volume) * 1e-7):
                                group.extend(self.reference(operand))
                    groups.append(list(dict.fromkeys(group)))
            finally:
                self.depth -= 1
            extra["result_groups"] = groups
        self.serial += 1
        ref = f"s{self.serial}"
        step = {"id": ref, "op": op, "inputs": list(dict.fromkeys(inputs)),
                "parameters": parameters, "source": source,
                "result": geometry.metrics(result), **extra}
        self.trace["steps"].append(step)
        self.register(result, ref)
        self.ref_solids[ref] = [b.Solid(s.wrapped.Moved(TopLoc_Location())) for s in solids]
        return ref

    def unsupported(self, message, shape=None, source="unknown"):
        entry = {"source": source, "reason": message}
        if entry not in self.trace["unsupported"]:
            self.trace["unsupported"].append(entry)
        if shape is not None:
            return self.emit("unsupported", [], {"reason": message}, shape, source)
        return None

    def reference(self, shape):
        if shape is None:
            return []
        if isinstance(shape, (list, tuple)):
            return [r for item in shape for r in self.reference(item)]
        if hasattr(shape, "part") and not hasattr(shape, "wrapped"):
            return self.reference(shape.part)
        if not hasattr(shape, "wrapped") or shape.wrapped is None or not self.is_solid(shape):
            return []
        key = self.key(shape)
        if key in self.refs:
            return [self.refs[key]]
        if key in self.components:
            parent, index, solid = self.components[key]
            return [self.emit("component", [parent], {"index": index, "fingerprint": geometry.metrics(solid)}, solid, "Shape.solids")]
        solids = shape.solids()
        known = [self.refs.get(self.key(s)) for s in solids]
        if all(known):
            if len(set(known)) == 1:
                self.register(shape, known[0])
                return [known[0]]
            return [self.emit("compound", known, {}, shape, "Compound")]
        if all(self.key(s) in self.refs or self.key(s) in self.components for s in solids):
            children = [ref for solid in solids for ref in self.reference(solid)]
            return [self.emit("compound", children, {}, shape, "Compound")]
        ref = self.unsupported(f"Untraced solid construction: {type(shape).__name__}", shape)
        return [ref]

    def patch(self, owner, name, replacement):
        own_attribute = name in owner.__dict__
        original = inspect.getattr_static(owner, name)
        self.patches.append((owner, name, original, own_attribute))
        setattr(owner, name, replacement)

    def bind(self, fn, args, kwargs):
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)

    def wrap(self, owner, name, op, *, factory=False):
        fn = getattr(owner, name)
        descriptor = inspect.getattr_static(owner, name)

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if self.depth:
                return fn(*args, **kwargs)
            receiver = None if factory else args[0]
            if receiver is not None and not self.is_solid(receiver):
                return fn(*args, **kwargs)
            params = self.bind(fn, args, kwargs)
            params.pop("self", None)
            # Materialize iterables once: feature generators must still execute normally.
            for field in ("objs", "profiles", "edge_list", "faces", "openings", "inner_wires"):
                value = params.get(field)
                if value is not None and not isinstance(value, (list, tuple)) and not hasattr(value, "wrapped"):
                    params[field] = list(value)
            # Rebind the materialized values to preserve the original call contract.
            bound = inspect.signature(fn).bind(*args, **kwargs)
            for field, value in params.items():
                if field in bound.arguments:
                    bound.arguments[field] = value
            inputs = self.reference(receiver) if receiver is not None else []
            extra = {}
            encoded = {}
            try:
                for field, value in params.items():
                    if field in {"obj", "profile", "section", "surface"} and op in {"extrude", "extrude_taper", "extrude_until", "revolve", "sweep", "extrude_twist", "thicken"}:
                        extra["profile"] = geometry.profile(value)
                    elif field in {"objs", "profiles"} and op in {"loft", "sweep_multi"}:
                        extra["profiles"] = [geometry.profile(v) for v in value]
                    elif field == "path" and op in {"sweep", "sweep_multi"}:
                        extra["path"] = geometry.path(value)
                    elif field in {"edge_list", "faces", "openings"}:
                        extra["selection"] = [geometry.fingerprint(v, receiver) for v in value or []]
                        if receiver is not None and len(receiver.solids()) > 1:
                            kind = "edge" if field == "edge_list" else "face"
                            extra["component_selections"] = [
                                [geometry.fingerprint(v, solid) for v in value or []
                                 if any(child.wrapped.IsSame(v.wrapped) for child in
                                        (solid.edges() if kind == "edge" else solid.faces()))]
                                for solid in receiver.solids()]
                    elif field in {"to_fuse", "to_cut", "to_intersect", "target"}:
                        inputs.extend(self.reference(value))
                    elif field == "inner_wires":
                        # build123d uses explicit holes only for Wire sections.
                        # A Face already owns the loops actually consumed by the feature.
                        import build123d as b
                        section = params.get("section")
                        extra["inner_wires"] = ([] if isinstance(section, b.Face) else
                                                [geometry.wire(v) for v in value or []])
                    else:
                        encoded[field] = geometry.serialize(value)
            except Exception as exc:
                extra["geometry_error"] = str(exc)
                self.unsupported(f"Cannot transcribe {name} inputs: {exc}", source=f"{owner.__name__}.{name}")
            if op == "chamfer" and params.get("length2") is not None and params["length2"] != params["length"]:
                # The native kernel assigns distance1 relative to an adjacent
                # face, even when no reference face is supplied by the caller.
                import build123d as b
                from build123d.topology.three_d import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher
                from simplecadapi._cpp.occt.TopExp import TopExp
                from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE, TopAbs_FACE
                adjacency = IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher()
                TopExp.MapShapesAndAncestors_s(receiver.wrapped, TopAbs_EDGE, TopAbs_FACE, adjacency)
                directions = []
                for selected in params["edge_list"]:
                    explicit = params.get("face")
                    reference = explicit if explicit is not None else next(face for face in receiver.faces() if face.wrapped.IsSame(adjacency.FindFromKey(selected.wrapped).First()))
                    direction = geometry.vector(reference.normal_at(selected.position_at(.5)))
                    directions.append(direction)
                encoded["reference_directions"] = directions
                if directions and all(sum((a-b)**2 for a,b in zip(directions[0], item)) < 1e-12 for item in directions):
                    encoded["reference_direction"] = directions[0]
            if op == "transform":
                encoded["method"] = name
                if name == "scale" and params.get("about") is None:
                    encoded["about"] = geometry.vector(receiver.location.position)
                if name == "transformed":
                    from simplecadapi._cpp.occt.gp import gp_Trsf, gp_Ax1, gp_Pnt, gp_Dir, gp_Vec
                    import math
                    rotation = params["rotate"]
                    if hasattr(rotation, "X"):
                        rotation = geometry.vector(rotation)
                    rotations = []
                    for i, angle in enumerate(rotation):
                        trsf = gp_Trsf()
                        axis = [0., 0., 0.]
                        axis[i] = 1.
                        trsf.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(*axis)), math.radians(angle))
                        rotations.append(trsf)
                    translation = gp_Trsf()
                    offset = params["offset"]
                    translation.SetTranslation(gp_Vec(*(geometry.vector(offset) if hasattr(offset, "X") else offset)))
                    transformation = translation * rotations[0] * rotations[1] * rotations[2]
                    encoded["matrix"] = [[float(transformation.Value(i, j)) for j in range(1, 5)] for i in range(1, 4)] + [[0., 0., 0., 1.]]
                if name in {"locate", "located"}:
                    # Absolute location requires replacing the current shape location.
                    import build123d as b
                    loc = params["loc"]
                    encoded["matrix"] = geometry.location_matrix(loc * receiver.location.inverse())
                elif name in {"move", "moved"}:
                    loc = params["loc"]
                    encoded["matrix"] = geometry.location_matrix(getattr(loc, "location", loc))
            self.depth += 1
            try:
                result = fn(*bound.args, **bound.kwargs)
            finally:
                self.depth -= 1
            if result is not None and (self.is_solid(result) if not isinstance(result, (list, tuple)) else any(self.is_solid(v) for v in result if v is not None)):
                if op == "split" and isinstance(result, tuple) and len(result) == 2:
                    for value, keep in zip(result, ["TOP", "BOTTOM"]):
                        if value is not None:
                            self.emit(op, inputs, {**encoded, "keep": keep}, value, f"{owner.__name__}.{name}", **extra)
                else:
                    self.emit(op, inputs, encoded, result, f"{owner.__name__}.{name}", **extra)
            return result

        if isinstance(descriptor, classmethod):
            # `fn` is already bound to the class; discard the newly supplied cls.
            @functools.wraps(fn)
            def class_wrapped(cls, *args, **kwargs):
                return wrapped(*args, **kwargs)
            self.patch(owner, name, classmethod(class_wrapped))
        elif isinstance(descriptor, staticmethod):
            self.patch(owner, name, staticmethod(wrapped))
        else:
            self.patch(owner, name, wrapped)

    def install(self):
        import build123d as b
        # Compound algebra and Builder insertion can call the kernel boolean
        # boundary directly, without Shape.fuse/cut/intersect.
        original_boolean = b.Shape._bool_op

        @functools.wraps(original_boolean)
        def boolean(shape, args, tools, operation):
            if self.depth:
                return original_boolean(shape, args, tools, operation)
            args, tools = list(args), list(tools)
            from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common
            op = next((name for cls, name in ((BRepAlgoAPI_Fuse, "union"),
                       (BRepAlgoAPI_Cut, "cut"), (BRepAlgoAPI_Common, "intersect"))
                       if isinstance(operation, cls)), None)
            if op is None or not args or any(not self.is_solid(s) for s in [*args, *tools]):
                return original_boolean(shape, args, tools, operation)
            # Each side is a set of bodies, not a chain of intersections.
            inputs = self.reference(b.Compound(args))
            if tools:
                inputs.extend(self.reference(b.Compound(tools)))
            self.depth += 1
            try:
                result = original_boolean(shape, args, tools, operation)
            finally:
                self.depth -= 1
            if result is not None and self.is_solid(result):
                self.emit(op, inputs, {}, result, "Shape._bool_op")
            return result

        self.patch(b.Shape, "_bool_op", boolean)
        original_solid_init = b.Solid.__init__

        @functools.wraps(original_solid_init)
        def solid_init(solid, obj=None, *args, **kwargs):
            if self.depth or not isinstance(obj, b.Shell):
                return original_solid_init(solid, obj, *args, **kwargs)
            extra = {}
            try:
                extra["profiles"] = [geometry.profile(face) for face in obj.faces()]
            except Exception as exc:
                extra["geometry_error"] = str(exc)
                self.unsupported(f"Cannot transcribe Solid(Shell) inputs: {exc}", source="Solid.__init__")
            self.depth += 1
            try:
                original_solid_init(solid, obj, *args, **kwargs)
            finally:
                self.depth -= 1
            if self.is_solid(solid):
                self.emit("sew_solid", [], {}, solid, "Solid.__init__", **extra)

        self.patch(b.Solid, "__init__", solid_init)
        factories = {"make_box": "box", "make_cylinder": "cylinder", "make_cone": "cone",
                     "make_sphere": "sphere", "make_torus": "torus", "make_wedge": "wedge",
                     "extrude": "extrude", "extrude_taper": "extrude_taper", "extrude_until": "extrude_until",
                     "extrude_linear_with_rotation": "extrude_twist", "revolve": "revolve",
                     "make_loft": "loft", "sweep": "sweep", "sweep_multi": "sweep_multi", "thicken": "thicken"}
        for name, op in factories.items():
            if hasattr(b.Solid, name):
                self.wrap(b.Solid, name, op, factory=True)
        for name, op in {"fuse": "union", "cut": "cut", "intersect": "intersect", "split": "split"}.items():
            self.wrap(b.Shape, name, op)
        for name, op in {"fillet": "fillet", "chamfer": "chamfer", "offset_3d": "offset", "hollow": "shell", "draft": "draft"}.items():
            owner = next((c for c in b.Solid.__mro__ if name in c.__dict__), None)
            if owner is not None:
                self.wrap(owner, name, op)
        for name in ("moved", "move", "located", "locate", "translate", "rotate", "mirror", "scale", "transformed", "transform_shape", "transform_geometry"):
            self.wrap(b.Shape, name, "transform")
        original_clean = b.Shape.clean
        original_copy = b.Shape.__deepcopy__

        @functools.wraps(original_copy)
        def deepcopy(shape, memo):
            refs = self.reference(shape) if not self.depth and self.is_solid(shape) else []
            self.depth += 1
            try:
                result = original_copy(shape, memo)
            finally:
                self.depth -= 1
            if refs:
                self.register(result, refs[0])
            return result
        self.patch(b.Shape, "__deepcopy__", deepcopy)
        original_location = inspect.getattr_static(b.Shape, "location")

        def set_location(shape, loc):
            if self.depth or not self.is_solid(shape):
                original_location.fset(shape, loc)
                return
            inputs = self.reference(shape)
            matrix = geometry.location_matrix(loc * shape.location.inverse())
            self.depth += 1
            try:
                original_location.fset(shape, loc)
            finally:
                self.depth -= 1
            self.emit("transform", inputs, {"method": "locate", "matrix": matrix}, shape, "Shape.location")
        self.patch(b.Shape, "location", property(original_location.fget, set_location, original_location.fdel, original_location.__doc__))

        @functools.wraps(original_clean)
        def clean(shape):
            refs = self.reference(shape) if not self.depth and self.is_solid(shape) else []
            self.depth += 1
            try:
                result = original_clean(shape)
            finally:
                self.depth -= 1
            if refs:
                self.register(result, refs[0])
            return result
        self.patch(b.Shape, "clean", clean)

    def restore(self):
        for owner, name, original, own_attribute in reversed(self.patches):
            if own_attribute:
                setattr(owner, name, original)
            else:
                delattr(owner, name)
        self.patches.clear()


def _find_result(namespace):
    from build123d import BuildPart, Shape
    for name in ("result", "part", "model", "solid", "body"):
        if name not in namespace:
            continue
        value = namespace[name]
        if isinstance(value, BuildPart):
            return value.part
        # An explicit output is authoritative, including an empty or invalid one.
        return value
    for value in reversed(list(namespace.values())):
        if isinstance(value, BuildPart) and value.part is not None:
            return value.part
        if isinstance(value, Shape) and value.solids():
            return value
    return None


def trace_source(source: str, filename: str = "<build123d-model>") -> dict[str, Any]:
    """Execute a trusted program and return a portable feature graph."""
    with _LOCK:
        recorder = Recorder()
        namespace = {"__name__": "__build123d_trace__", "__file__": filename}
        old_path = list(sys.path)
        sys.path.insert(0, str(Path(filename).resolve().parent))
        try:
            recorder.install()
            try:
                exec(compile(source, filename, "exec"), namespace)
            except Exception:
                recorder.trace["b3d_status"] = "error"
                recorder.trace["error"] = traceback.format_exc()
            result = _find_result(namespace)
            values = result if isinstance(result, (list, tuple)) else [result]
            from build123d import Shape
            if (not values or any(v is not None and not isinstance(v, Shape) for v in values)
                    or not any(v is not None and recorder.is_solid(v) for v in values)):
                recorder.trace["b3d_status"] = "error"
                recorder.trace["error"] += "\nNo solid result found in model namespace"
            else:
                recorder.trace["result_refs"] = recorder.reference(result)
                summary = geometry.metrics(result)
                recorder.trace.update(b3d_volume=summary["volume"], b3d_bbox=summary["bbox"], solid_count=summary["solid_count"])
                recorder.trace["b3d_default_volume"] = summary.get("default_volume", summary["volume"])
                recorder.trace["b3d_volume_gk"] = summary["volume"]
                recorder.trace["b3d_valid"] = all(v.is_valid for v in values if v is not None)
                recorder.trace["b3d_area"] = summary["area"]
        finally:
            recorder.restore()
            sys.path[:] = old_path
        recorder.trace["source_file"] = filename
        recorder.trace["source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        import build123d
        recorder.trace["build123d_version"] = getattr(build123d, "__version__", "unknown")
        return recorder.trace


def trace_file(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return trace_source(path.read_text(encoding="utf-8"), str(path))
