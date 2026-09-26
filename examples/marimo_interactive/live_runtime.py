"""Live modeling runtime for growing-model notebooks.

Register once in a setup cell:

    LIVE = live_runtime.register(out_dir=Path(__file__).parent / "out")

Every modeling step cell then reads as pure intent:

    body_hub = LIVE.step("2-hub", lambda: scad.union_rsolid(body_disc, make_cyl(...)))

The runtime owns everything the user should not have to see:
- one persistent GraphSession — shapes chain across cells without
  graph-ownership conflicts, and per-cell ContextVar activation is handled
  internally (marimo cells may run in distinct contexts);
- feature-graph freeze + durable .scadpkg compile (opt-in via
  ``LIVE.publish_package_on_step`` / ``LIVE.export_package(body)``);
- tessellation and the direct geometry channel (``sca-live-geometry-1``)
  consumed by the Studio viewport — no container, no BREP, no GLB.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import simplecadapi as scad
from simplecadapi._internal.mesh import DEFAULT_ANGULAR_TOLERANCE, DEFAULT_LINEAR_TOLERANCE
from simplecadapi.artifacts.feature_graph import capture_feature_graph
from simplecadapi.build.part_builder import _part_definition, generator_profile
from simplecadapi.product.part import Part
from simplecadapi.product.packages import build_product_package, encode_product_package
from simplecadapi.scene.render_mesh import build_edge_mesh, build_render_mesh

LIVE_SCHEMA = "sca-live-geometry-1"

_CURRENT: "LiveRuntime | None" = None

# Solid operators that participate in the recorded graph. Each is wrapped so
# the persistent session is active for the duration of the call — this is what
# lets step cells stay pure modeling code (no `with recording():`).
_PATCHABLE_OPERATORS = (
    "make_cylinder_rsolid",
    "make_box_rsolid",
    "make_sweep_rsolid",
    "make_loft_rsolid",
    "make_revolve_rsolid",
    "make_extrude_rsolid",
    "make_spline_rsolid",
    "union_rsolid",
    "subtract_rsolid",
    "cut_rsolid",
    "intersect_rsolid",
    "fillet_rsolid",
    "chamfer_rsolid",
    "mirror_rsolid",
    "linear_pattern_rsolid",
    "radial_pattern_rsolid",
)


@dataclass(frozen=True, slots=True)
class LastStep:
    """Everything the notebook's own views need about the latest step."""

    step: str
    mesh: object
    volume: float
    faces: int


class LiveRuntime:
    def __init__(
        self,
        out_dir: str | Path,
        *,
        graph_id: str = "growing",
        revision: str = "0.1.0",
        live_name: str = "growing.live.json",
        package_name: str = "growing.scadpkg",
        edge_linear_tolerance: float = 0.2,
        edge_angular_tolerance: float = 0.2,
    ) -> None:
        self.out_dir = Path(out_dir).expanduser().resolve()
        self.graph_id = graph_id
        self.revision = revision
        self.live_path = self.out_dir / live_name
        self.package_path = self.out_dir / package_name
        self.edge_linear_tolerance = edge_linear_tolerance
        self.edge_angular_tolerance = edge_angular_tolerance
        self.session = scad.GraphSession(graph_id=graph_id)
        self.publish_package_on_step = False
        self.last: LastStep | None = None
        self.last_body = None
        self._published_node_count = 0
        self._graph_lock = threading.RLock()
        self._flush_timer: threading.Timer | None = None
        self.flush_delay_seconds = 1.5
        self._patch_operators()

    # -- transparent recording ---------------------------------------------------

    def _patch_operators(self) -> None:
        """Wrap the solid operators so every scad call auto-activates the
        persistent session. Users never write recording boilerplate."""
        import functools

        for name in _PATCHABLE_OPERATORS:
            fn = getattr(scad, name, None)
            if fn is None or getattr(fn, "_live_runtime_wrapped", False):
                continue

            @functools.wraps(fn)
            def wrapper(*args, __fn=fn, **kwargs):
                runtime = _CURRENT
                if runtime is None:
                    return __fn(*args, **kwargs)
                with runtime._graph_lock:
                    activated = scad.get_active_session() is not runtime.session
                    if activated:
                        runtime.session.start()
                    try:
                        result = __fn(*args, **kwargs)
                    finally:
                        if activated:
                            runtime.session.stop()
                    if isinstance(result, scad.Solid):
                        runtime.last_body = result
                    runtime._schedule_flush()
                return result

            wrapper._live_runtime_wrapped = True
            setattr(scad, name, wrapper)

    # -- transparent recording -----------------------------------------------------

    def _schedule_flush(self) -> None:
        """Debounced auto-publish: N seconds after the LAST scad call, ship the
        current session state to the Studio viewport once. A burst of ops
        (slider cascade, multi-line step cell) collapses into a single flush."""
        if self._flush_timer is not None:
            self._flush_timer.cancel()
        self._flush_timer = threading.Timer(self.flush_delay_seconds, self._flush_live)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _flush_live(self) -> None:
        with self._graph_lock:
            if self.last_body is None:
                return
            count = len(self.session.graph.topological_order())
            if count <= self._published_node_count:
                return
            self._publish(f"auto/{count}", self.last_body)

    # -- registration-time helpers -------------------------------------------

    @contextmanager
    def recording(self):
        """Explicit wrapper for cells that mix several ops — LIVE.step already
        wraps its own."""
        activated = scad.get_active_session() is not self.session
        if activated:
            self.session.start()
        try:
            yield
        finally:
            if activated:
                self.session.stop()

    def reset(self) -> None:
        """Remove the published live file; the viewport goes empty."""
        self.live_path.unlink(missing_ok=True)

    # -- the one-call step -----------------------------------------------------

    def step(self, name: str, recipe: Callable[[], scad.Solid]) -> scad.Solid:
        """Explicit step: run the recipe inside the persistent session and
        publish. Prefer the automatic cell hooks — this exists for scripts."""
        with self.recording():
            body = recipe()
            part = Part(self.graph_id, body)
            self.session.clear_results()
            self.session.capture_result(value=part)
            feature_graph = capture_feature_graph(
                session=self.session,
                owner_definition_kind="single_solid",
                owner_definition_id=self.session.graph.graph_id,
                owner_revision=self.revision,
                project_root=self.out_dir,
            )
            if self.publish_package_on_step:
                self._write_package(part, feature_graph)
        self.last_body = body
        self._publish(name, body)
        return body

    # -- channels ---------------------------------------------------------------

    def _publish(self, name: str, body) -> None:
        with self._graph_lock:
            self._publish_locked(name, body)

    def _publish_locked(self, name: str, body) -> None:
        face_ids = [f"face:{i}" for i, _ in enumerate(body._iter_faces())]
        edge_ids = [f"edge:{i}" for i, _ in enumerate(body._iter_edges())]
        mesh = build_render_mesh(
            body,
            face_entity_ids=face_ids,
            linear_tolerance=DEFAULT_LINEAR_TOLERANCE,
            angular_tolerance=DEFAULT_ANGULAR_TOLERANCE,
        )
        edge_mesh = build_edge_mesh(
            body,
            edge_entity_ids=edge_ids,
            linear_tolerance=self.edge_linear_tolerance,
            angular_tolerance=self.edge_angular_tolerance,
        )
        self.last = LastStep(step=name, mesh=mesh, volume=body.get_volume(), faces=len(face_ids))

        def cad(point):
            """glTF space (m, +Y up) -> CAD space (mm, +Z up)."""
            return [point[0] * 1000.0, -point[2] * 1000.0, point[1] * 1000.0]

        segments: list[float] = []
        indices = edge_mesh.indices
        for a, b in zip(indices[0::2], indices[1::2]):
            segments.extend(cad(edge_mesh.positions[a]))
            segments.extend(cad(edge_mesh.positions[b]))
        payload = {
            "schema": LIVE_SCHEMA,
            "step": name,
            "positions": [cad(p) for p in mesh.positions],
            "normals": [[n[0], -n[2], n[1]] for n in mesh.normals],
            "indices": list(mesh.indices),
            "edge_positions": segments,
            "face_groups": [
                {"entity_id": g.entity_id, "first": g.first_index, "count": g.index_count}
                for g in mesh.groups
            ],
            "stats": {"volume": self.last.volume, "faces": len(face_ids)},
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.live_path.with_name(self.live_path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.live_path)  # atomic: the viewport never reads a torn file
        self._published_node_count = len(self.session.graph.topological_order())

    def export_package(self, body=None) -> Path:
        """Compile the durable .scadpkg from the session graph (opt-in)."""
        with self._graph_lock:
            return self._export_package_locked(body)

    def _export_package_locked(self, body=None) -> Path:
        body = body if body is not None else self.last_body
        if body is None:
            raise RuntimeError("no step has published yet")
        activated = scad.get_active_session() is not self.session
        if activated:
            self.session.start()
        try:
            part = Part(self.graph_id, body)
            self.session.clear_results()
            self.session.capture_result(value=part)
            feature_graph = capture_feature_graph(
                session=self.session,
                owner_definition_kind="single_solid",
                owner_definition_id=self.session.graph.graph_id,
                owner_revision=self.revision,
                project_root=self.out_dir,
            )
            definition = _part_definition(
                part=part,
                feature_graph=feature_graph,
                revision=self.revision,
                tolerance_profile="simplecad-default",
                file_inputs=(),
                generator=generator_profile(),
            )
            self.out_dir.mkdir(parents=True, exist_ok=True)
            payload_bytes = encode_product_package(build_product_package(definition))
            tmp = self.package_path.with_name(self.package_path.name + ".tmp")
            tmp.write_bytes(payload_bytes)
            os.replace(tmp, self.package_path)
            return self.package_path
        finally:
            if activated:
                self.session.stop()

    def _write_package(self, part, feature_graph) -> None:
        definition = _part_definition(
            part=part,
            feature_graph=feature_graph,
            revision=self.revision,
            tolerance_profile="simplecad-default",
            file_inputs=(),
            generator=generator_profile(),
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        payload_bytes = encode_product_package(build_product_package(definition))
        tmp = self.package_path.with_name(self.package_path.name + ".tmp")
        tmp.write_bytes(payload_bytes)
        os.replace(tmp, self.package_path)


def register(out_dir: str | Path, **kwargs) -> LiveRuntime:
    """Create (and thereby register) the notebook's live runtime.

    Idempotent: re-running the setup cell (or re-registering after the
    operator patches are installed) returns the same instance — the patched
    operators keep a reference to the module-level singleton, so they always
    drive the runtime that is actually registered.
    """
    global _CURRENT
    if _CURRENT is None:
        _CURRENT = LiveRuntime(out_dir, **kwargs)
    return _CURRENT
