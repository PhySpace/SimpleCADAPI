"""Adding, editing and removing GUI-made features in the open notebook, with undo.

:mod:`.features` turns values into cells; this module finds where they go, writes them through the editor's own cell
commands (so the page shows them live, the file has one writer, and an agent editing the same notebook is never
overwritten: every edit carries the code it was made from), and keeps what is needed to undo.

A feature is two cells: ``# ---- params: <slug> ----`` (its numbers) and ``# ---- feature: <slug> (<role>) ----``.  The
product cell (the one that builds the ``Part`` from a body) is pointed at the new body when the feature consumed the body it
was reading; otherwise it is left alone and the state says which body it reads.
"""

from __future__ import annotations

import ast
import re
import threading
from typing import Any, Mapping

from ..runtime.workspace import features_in_cell
from . import features as F
from . import sketch_doc

_PARAMS_HEADER = re.compile(r"^#\s*-{3,}\s*params\b[^\n]*", re.MULTILINE)
_PARAMS_FOR = re.compile(r"^#\s*-{3,}\s*params:\s*(?P<slug>[a-z][a-z0-9_]*)\s*-{3,}\s*$")
_PRODUCT_BODY = re.compile(r"(\bbody\s*=\s*)([A-Za-z_][A-Za-z0-9_]*)")
_ROLES_WITH_BODIES = {"build", "add", "subtract", "modifier"}


class GuiError(Exception):
    """A GUI command that cannot be done; ``conflict`` marks one that lost to a concurrent edit."""

    def __init__(self, message: str, *, conflict: bool = False):
        super().__init__(message)
        self.conflict = conflict


def _names(code: str) -> tuple[list[str], set[str]]:
    """(public names the cell defines at its top level, in order; every name it reads)."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return [], set()
    defined: list[str] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            for name in ast.walk(target):
                if isinstance(name, ast.Name) and not name.id.startswith("_") and name.id not in defined:
                    defined.append(name.id)
    loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return defined, loaded


class FeatureService:
    """The GUI-feature view and commands of one :class:`~simplecadapi.editor.server.WorkspaceState`."""

    def __init__(self, state: Any):
        self.state = state
        self._lock = threading.RLock()
        self._undo: list[list[dict]] = []
        self._redo: list[list[dict]] = []
        self._notebook: Any = None

    # -- reading ----------------------------------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Features, bodies, the product, and the defaults a form should open with."""
        cells = list(self.state.cells)
        features: list[dict[str, Any]] = []
        bodies: dict[str, str] = {}
        consumed: set[str] = set()
        order: list[str] = []
        taken: set[str] = set()
        product: dict[str, Any] | None = None
        params_cells: dict[str, str] = {}
        for index, cell in enumerate(cells):
            code = str(cell.get("code", ""))
            defined, loaded = _names(code)
            taken.update(defined)
            first = code.strip().splitlines()[0] if code.strip() else ""
            match = _PARAMS_FOR.match(first)
            if match:
                params_cells[match.group("slug")] = cell["id"]
                continue
            heads = features_in_cell(code, cell.get("key", ""))
            if not heads:
                if ("Part(" in code or "make_part_rpart(" in code) and _PRODUCT_BODY.search(code):
                    product = {"cell": cell["id"], "body": _PRODUCT_BODY.search(code).group(2)}  # type: ignore[union-attr]
                continue
            head = heads[0]
            gui = F.parse_gui(code)
            consumed.update(loaded & set(bodies))
            produces = F.BY_ID[gui["spec"]].produces if gui else "solid"
            made = defined if head.role in _ROLES_WITH_BODIES else []
            for name in made:
                bodies[name] = produces
                order.append(name)
            features.append(
                {
                    "cell": cell["id"],
                    "index": index + 1,
                    "slug": head.slug,
                    "role": head.role,
                    "gui": {"spec": gui["spec"], "values": gui.get("values", {}), "picked": gui.get("picked", {})} if gui else None,
                    "makes": made,
                    "reads": sorted(loaded & set(bodies) - set(made)),
                    "status": cell.get("status"),
                    "errors": cell.get("errors") or [],
                }
            )
        for feature in features:
            feature["params_cell"] = params_cells.get(feature["slug"])
        solids = [name for name in order if bodies[name] != "face"]
        faces = [name for name in order if bodies[name] == "face"]
        open_bodies = [name for name in solids if name not in consumed]
        profiles = []
        for feature in features:
            gui = feature["gui"]
            if gui and gui["spec"] == "sketch" and feature["makes"]:
                plane = (gui["values"].get("sketch") or {}).get("plane", "XY")
                profiles.append({"name": feature["makes"][0], "plane": plane, "normal": sketch_doc.PLANE_NORMALS.get(plane, "+z")})
        return {
            "features": features,
            "bodies": [{"name": name, "produces": bodies[name]} for name in order],
            "open": open_bodies,
            "tip": open_bodies[-1] if open_bodies else None,
            "profiles": profiles,
            "product": product,
            "defaults": self._defaults(open_bodies, faces),
            "taken": sorted(taken),
            "undo": len(self._undo),
            "redo": len(self._redo),
        }

    @staticmethod
    def _defaults(open_bodies: list[str], faces: list[str]) -> dict[str, dict[str, str]]:
        last = open_bodies[-1] if open_bodies else None
        before = open_bodies[-2] if len(open_bodies) > 1 else last
        profile = faces[-1] if faces else None
        out: dict[str, dict[str, str]] = {}
        for spec in F.SPECS:
            chosen: dict[str, str] = {}
            for slot in spec.slots:
                if slot.kind == "body" and last is not None:
                    chosen[slot.name] = before if slot.name == "base" else last
                elif slot.kind == "profile" and profile is not None:
                    chosen[slot.name] = profile
            out[spec.id] = chosen
        return out

    # -- commands -----------------------------------------------------------------------------------------------------
    def add(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sync()
            snap = self.snapshot()
            spec_id = str(request.get("spec", ""))
            if spec_id not in F.BY_ID:
                raise GuiError(f"unknown operation {spec_id!r}")
            taken = set(snap["taken"])
            slug = F.check_slug(str(request["name"]), taken) if request.get("name") else F.default_slug(spec_id, taken)
            bodies = {b["name"]: b["produces"] for b in snap["bodies"]}
            values = self._with_defaults(spec_id, dict(request.get("values") or {}), snap)
            rendered = self._render(spec_id, slug, values, bodies, request.get("selections"), snap)
            self._check_param_names(rendered, taken)
            steps: list[dict] = []
            cells = self.state.cells
            params_anchor = self._params_anchor(cells)
            feature_anchor = request.get("after") or self._feature_anchor(snap, cells)
            if rendered.params:
                steps.append(self._create(params_anchor, "\n".join(rendered.params), run=False))
                if feature_anchor == params_anchor:  # the params cell sits where the feature goes: keep params first
                    feature_anchor = steps[-1]["id"]
            made = self._create(feature_anchor, rendered.feature, run=True)
            steps.append(made)
            steps.extend(self._repoint_product(snap, rendered))
            steps.extend(self._first_product(snap, rendered, made["id"], taken))
            self._record(steps)
            return self._result(made["id"], steps, slug)

    def edit(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sync()
            snap = self.snapshot()
            feature = self._feature(snap, request.get("cell"))
            if not feature["gui"]:
                raise GuiError("this feature was written as code; edit it in the notebook")
            cell = self._cell(feature["cell"])
            spec_id = feature["gui"]["spec"]
            spec = F.BY_ID[spec_id]
            values = {**feature["gui"]["values"], **dict(request.get("values") or {})}
            bodies = {b["name"]: b["produces"] for b in snap["bodies"] if b["name"] != feature["slug"]}
            keep = {slot.name: F.extract_recipe(cell["code"], slot.name) for slot in spec.slots if slot.kind == "select"}
            rendered = self._render(spec_id, feature["slug"], values, bodies, request.get("selections"), snap, keep={k: v for k, v in keep.items() if v})
            steps: list[dict] = []
            if feature["params_cell"]:
                old = self._cell(feature["params_cell"])["code"]
                new = "\n".join(rendered.params)
                if rendered.params and new.strip() != old.strip():
                    steps.append(self._edit(feature["params_cell"], old, new, run=False))
            elif rendered.params:
                steps.append(self._create(self._params_anchor(self.state.cells), "\n".join(rendered.params), run=False))
            steps.append(self._edit(feature["cell"], cell["code"], rendered.feature, run=True))
            self._record(steps)
            return self._result(feature["cell"], steps, feature["slug"])

    def delete(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sync()
            snap = self.snapshot()
            feature = self._feature(snap, request.get("cell"))
            users = [f["slug"] for f in snap["features"] if f["cell"] != feature["cell"] and set(f["reads"]) & set(feature["makes"])]
            if users:
                raise GuiError(f"{', '.join(users)} still use {feature['slug']}; remove those first")
            steps: list[dict] = []
            product = snap["product"]
            if product and product["body"] in feature["makes"]:
                fallback = feature["reads"][0] if feature["reads"] else None
                if fallback is None:
                    raise GuiError(f"the product is built from {feature['slug']}; point it at another body first")
                steps.append(self._point_product(product, fallback))
            for cell_id in (feature["cell"], feature["params_cell"]):
                if cell_id:
                    steps.append(self._remove(cell_id))
            self._record(steps)
            return self._result(None, steps, feature["slug"])

    def use_as_product(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sync()
            snap = self.snapshot()
            name = str(request.get("body", ""))
            if name not in {b["name"] for b in snap["bodies"]}:
                raise GuiError(f"{name!r} is not a body in this notebook")
            if not snap["product"]:
                raise GuiError("this notebook has no product cell that builds a Part from a body")
            steps = [self._point_product(snap["product"], name)]
            self._record(steps)
            return self._result(snap["product"]["cell"], steps, name)

    def undo(self) -> dict[str, Any]:
        with self._lock:
            self._sync()
            if not self._undo:
                raise GuiError("nothing to undo")
            steps = self._undo.pop()
            for step in reversed(steps):
                self._apply(step, forward=False)
            self._redo.append(steps)
            return self._result(None, [], "undo")

    def redo(self) -> dict[str, Any]:
        with self._lock:
            self._sync()
            if not self._redo:
                raise GuiError("nothing to redo")
            steps = self._redo.pop()
            for step in steps:
                self._apply(step, forward=True)
            self._undo.append(steps)
            return self._result(None, [], "redo")

    # -- internals ------------------------------------------------------------------------------------------------------
    def _sync(self) -> None:
        """History belongs to one open notebook."""
        current = getattr(self.state, "notebook", None)
        if current != self._notebook:
            self._notebook = current
            self._undo, self._redo = [], []

    def _record(self, steps: list[dict]) -> None:
        if steps:
            self._undo.append(steps)
            self._redo.clear()
            del self._undo[:-50]

    def _cell(self, ref: Any) -> dict:
        for cell in self.state.cells:
            if cell["id"] == ref:
                return cell
        raise GuiError(f"the cell {ref!r} is gone; reload the feature list")

    @staticmethod
    def _feature(snap: Mapping[str, Any], ref: Any) -> dict[str, Any]:
        for feature in snap["features"]:
            if ref in (feature["cell"], feature["slug"]):
                return feature
        raise GuiError(f"no feature {ref!r}")

    @staticmethod
    def _with_defaults(spec_id: str, values: dict[str, Any], snap: Mapping[str, Any]) -> dict[str, Any]:
        for name, body in (snap["defaults"].get(spec_id) or {}).items():
            values.setdefault(name, body)
        return values

    def _render(self, spec_id, slug, values, bodies, selections, snap, keep=None) -> F.Rendered:
        known = {f["slug"] for f in snap["features"]}
        picked = {k: list(v) for k, v in dict(selections or {}).items() if isinstance(v, (list, tuple))}
        try:
            return F.render_feature(spec_id, slug, values, bodies=bodies, selections=picked, known_slugs=known, keep_recipes=keep)
        except F.FeatureError as exc:
            raise GuiError(str(exc)) from exc

    @staticmethod
    def _check_param_names(rendered: F.Rendered, taken: set[str]) -> None:
        for line in rendered.params:
            match = re.match(r"([A-Z][A-Z0-9_]*) = ", line)
            if match and match.group(1) in taken:
                raise GuiError(f"the name {match.group(1)} is already used in this notebook")

    @staticmethod
    def _params_anchor(cells: list[dict]) -> str:
        anchor = "start"
        for cell in cells:
            if _PARAMS_HEADER.match(str(cell.get("code", "")).strip()):
                anchor = cell["id"]
        return anchor

    @staticmethod
    def _feature_anchor(snap: Mapping[str, Any], cells: list[dict]) -> str:
        """After the last feature cell (never 'end': the selection cell must stay last)."""
        if snap["features"]:
            return snap["features"][-1]["cell"]
        return FeatureService._params_anchor(cells)

    def _command(self, op: str, body: dict) -> dict:
        report = self.state.cell_command(op, body)
        if "error" in report:
            message = str(report["error"])
            raise GuiError(message, conflict=message.startswith("conflict"))
        return report

    def _create(self, anchor: str, code: str, *, run: bool) -> dict:
        report = self._command("insert", {"after": anchor, "code": code, "run": run})
        index = (report.get("touched") or [None])[0]
        cell = next((c for c in report["cells"] if c["index"] == index), None)
        if cell is None:
            raise GuiError("the kernel did not create the cell")
        return {"kind": "created", "id": cell["id"], "after": anchor, "code": code}

    def _edit(self, cell_id: str, old: str, new: str, *, run: bool) -> dict:
        self._command("edit", {"cell": cell_id, "code": new, "base": old, "run": run})
        return {"kind": "edited", "id": cell_id, "old": old, "new": new}

    def _remove(self, cell_id: str, expect: str | None = None) -> dict:
        """Delete a cell; with *expect*, only if it still holds the code the GUI wrote (else it was edited since)."""
        cells = self.state.cells
        position = next((i for i, c in enumerate(cells) if c["id"] == cell_id), None)
        if position is None:
            raise GuiError("the cell is gone", conflict=True)
        code = cells[position]["code"]
        if expect is not None and code.strip() != expect.strip():
            raise GuiError(f"conflict: the cell {cell_id} was edited since", conflict=True)
        before = cells[position - 1]["id"] if position else "start"
        self._command("delete", {"cell": cell_id})
        return {"kind": "deleted", "id": cell_id, "after": before, "code": code}

    def _point_product(self, product: Mapping[str, Any], body: str) -> dict:
        cell = self._cell(product["cell"])
        new = _PRODUCT_BODY.sub(lambda m: f"{m.group(1)}{body}", cell["code"], count=1)
        return self._edit(product["cell"], cell["code"], new, run=True)

    def _repoint_product(self, snap: Mapping[str, Any], rendered: F.Rendered) -> list[dict]:
        product = snap["product"]
        if product and product["body"] in rendered.reads and rendered.produces == "solid":
            return [self._point_product(product, rendered.slug)]
        return []

    def _first_product(self, snap: Mapping[str, Any], rendered: F.Rendered, after: str, taken: set[str]) -> list[dict]:
        """A notebook with no product yet gets one, built from its first body (a blank notebook starts without cells)."""
        if snap["product"] is not None or rendered.produces != "solid" or any("Part(" in str(c.get("code", "")) for c in self.state.cells):
            return []
        stem = re.sub(r"\W", "_", getattr(self.state.notebook, "stem", "part") or "part").strip("_").lower() or "part"
        variable = stem if stem not in taken and stem not in F._RESERVED and not stem[0].isdigit() else f"{stem}_part"
        return [self._create(after, f"{variable} = scad.Part(part_id=scad.notebook_id(), body={rendered.slug})", run=True)]

    def _apply(self, step: dict, *, forward: bool) -> None:
        kind = step["kind"]
        make, drop = (forward and kind == "created") or (not forward and kind == "deleted"), (forward and kind == "deleted") or (not forward and kind == "created")
        try:
            if make:
                created = self._create(step["after"] if self._exists(step["after"]) else "end", step["code"], run=True)
                step["id"] = created["id"]
            elif drop:
                self._remove(step["id"], expect=step["code"])
            else:  # edited
                old, new = (step["old"], step["new"]) if forward else (step["new"], step["old"])
                self._edit(step["id"], old, new, run=True)
        except GuiError as exc:
            raise GuiError(f"cannot {'redo' if forward else 'undo'}: the notebook changed since ({exc})", conflict=exc.conflict) from exc

    def _exists(self, ref: str) -> bool:
        return ref in ("start", "end") or any(c["id"] == ref for c in self.state.cells)

    def _result(self, cell_id: str | None, steps: list[dict], name: str) -> dict[str, Any]:
        report = self.state.cells_report(refresh=False)
        cell = next((c for c in report["cells"] if c["id"] == cell_id), None) if cell_id else None
        return {
            "ok": True,
            "name": name,
            "cell": {k: cell[k] for k in ("id", "index", "status", "errors", "output", "console") if k in cell} if cell else None,
            "state": self.snapshot(),
        }


__all__ = ["FeatureService", "GuiError"]
