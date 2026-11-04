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
from pathlib import Path
from typing import Any, Mapping

from ..runtime.config import read_notebook_config
from ..runtime.workspace import features_in_cell
from . import assembly_doc
from . import features as F
from . import sketch_doc

_PARAMS_HEADER = re.compile(r"^#\s*-{3,}\s*params\b[^\n]*", re.MULTILINE)
_PARAMS_FOR = re.compile(r"^#\s*-{3,}\s*params:\s*(?P<slug>[a-z][a-z0-9_]*)\s*-{3,}\s*$")
_PRODUCT_BODY = re.compile(r"(\bbody\s*=\s*)([A-Za-z_][A-Za-z0-9_]*)")
_ROLES_WITH_BODIES = {"build", "add", "subtract", "modifier", "intersect"}


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
        self._sync()
        cells = list(self.state.cells)
        features: list[dict[str, Any]] = []
        bodies: dict[str, str] = {}
        consumed: set[str] = set()
        order: list[str] = []
        taken: set[str] = set()
        product: dict[str, Any] | None = None
        params_cells: dict[str, str] = {}
        assembly_slugs: set[str] = set()
        workplanes: list[dict[str, Any]] = []
        for cell in cells:
            gui = F.parse_gui(str(cell.get("code", "")))
            heads = features_in_cell(str(cell.get("code", "")), "")
            if gui and gui["spec"] == "assembly" and heads:
                assembly_slugs.add(heads[0].slug)
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
            if head.role != "datum":  # a workplane on a body's face is not built from the body: the body stays open
                consumed.update(loaded & set(bodies))
            produces = F.BY_ID[gui["spec"]].produces if gui else "solid"
            if gui and gui["spec"] == "sketch":  # a sketch makes a face or a wire, as its document says
                produces = sketch_doc.output_of(gui.get("values", {}).get("sketch") or {})
            part_of = head.slug[: -len("_parts")] if head.slug.endswith("_parts") and head.slug[: -len("_parts")] in assembly_slugs else None
            made = defined if head.role in _ROLES_WITH_BODIES and not part_of else []
            for name in made:
                bodies[name] = produces
                order.append(name)
            if head.role == "datum" and produces == "workplane":
                made = sorted(defined)
                workplanes.extend({"name": name, "cell": cell["id"], "slug": head.slug} for name in made)
            features.append(
                {
                    "cell": cell["id"],
                    "index": index + 1,
                    "slug": head.slug,
                    "role": head.role,
                    "gui": {"spec": gui["spec"], "values": gui.get("values", {}), "picked": gui.get("picked", {})} if gui else None,
                    "makes": made,
                    "part_of": part_of,
                    "reads": sorted(loaded & (set(bodies) | {w["name"] for w in workplanes}) - set(made)),
                    "status": cell.get("status"),
                    "errors": cell.get("errors") or [],
                }
            )
        for feature in features:
            feature["params_cell"] = params_cells.get(feature["slug"])
        solids = [name for name in order if bodies[name] in ("solid", "solids")]
        faces = [name for name in order if bodies[name] == "face"]
        open_bodies = [name for name in solids if name not in consumed]
        profiles = []
        for feature in features:
            gui = feature["gui"]
            if gui and gui["spec"] == "sketch" and feature["makes"] and sketch_doc.output_of(gui["values"].get("sketch") or {}) == "face":
                plane = (gui["values"].get("sketch") or {}).get("plane", "XY")
                profiles.append(
                    {
                        "name": feature["makes"][0],
                        "plane": plane,
                        "plane_label": plane if isinstance(plane, str) else (sketch_doc.plane_workplane(plane) or "face"),
                        "normal": sketch_doc.PLANE_NORMALS.get(plane, "normal") if isinstance(plane, str) else "normal",
                        "normal_vec": sketch_doc.plane_normal(plane),
                    }
                )
        if product is None and open_bodies and self._implicit_part():
            # no cell builds the Part: the runtime makes it from the open bodies (several are the bodies of one Part)
            product = {"cell": None, "body": open_bodies[-1], "bodies": list(open_bodies), "implicit": True}
        return {
            "features": features,
            "bodies": [{"name": name, "produces": bodies[name]} for name in order],
            "open": open_bodies,
            "tip": open_bodies[-1] if open_bodies else None,
            "profiles": profiles,
            "workplanes": workplanes,
            "assembly": next(
                (
                    {"cell": f["cell"], "slug": f["slug"], "doc": (f["gui"]["values"] or {}).get("assembly")}
                    for f in features
                    if f["gui"] and f["gui"]["spec"] == "assembly"
                ),
                None,
            ),
            "product": product,
            "connectors": self._connectors(cells, product),
            "defaults": self._defaults(open_bodies, faces, [(name, bodies[name]) for name in order]),
            "taken": sorted(taken),
            "undo": len(self._undo),
            "redo": len(self._redo),
        }

    @staticmethod
    def _connectors(cells: list[dict], product: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        if not product:
            return []
        code = next((str(c.get("code", "")) for c in cells if c["id"] == product["cell"]), "")
        return assembly_doc.parse_connectors(code)

    @staticmethod
    def _defaults(open_bodies: list[str], faces: list[str], made: list[tuple[str, str]] = ()) -> dict[str, dict[str, Any]]:
        last = open_bodies[-1] if open_bodies else None
        before = open_bodies[-2] if len(open_bodies) > 1 else last
        profile = faces[-1] if faces else None
        out: dict[str, dict[str, Any]] = {}
        for spec in F.BY_ID.all():
            chosen: dict[str, Any] = {}
            for slot in spec.slots:
                if slot.kind == "value" and not slot.many:  # the last value of a kind that fits (the open body for a solid)
                    fits = [name for name, kind in made if kind in (slot.accepts or ())]
                    pick = last if "solid" in (slot.accepts or ()) and last is not None else (fits[-1] if fits else None)
                    if pick is not None:
                        chosen[slot.name] = pick
                elif slot.kind == "body" and last is not None:
                    chosen[slot.name] = before if slot.name == "base" else last
                elif slot.name == "operation" and spec.combinable:
                    chosen["operation"] = "join" if last is not None else "new"  # a part holds one solid: meet it, do not leave a second
                elif slot.kind == "profile" and profile is not None:
                    chosen[slot.name] = profile
            out[spec.id] = chosen
        return out

    def sketch_document(self, ref: str) -> dict[str, Any] | None:
        """The document of the sketch feature named *ref* (slug or cell), or ``None``."""
        for feature in self.snapshot()["features"]:
            gui = feature["gui"]
            if ref in (feature["slug"], feature["cell"]) and gui and gui["spec"] == "sketch":
                return gui["values"].get("sketch")
        return None

    # -- commands -----------------------------------------------------------------------------------------------------
    def add(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sync()
            snap = self.snapshot()
            spec_id = str(request.get("spec", ""))
            if spec_id not in F.BY_ID:
                raise GuiError(f"unknown operation {spec_id!r}")
            taken = set(snap["taken"])
            try:
                slug = F.check_slug(str(request["name"]), taken) if request.get("name") else F.default_slug(spec_id, taken)
            except F.FeatureError as exc:
                raise GuiError(str(exc)) from exc
            bodies = {b["name"]: b["produces"] for b in snap["bodies"]}
            values = self._with_defaults(spec_id, dict(request.get("values") or {}), snap)
            rendered = self._render(spec_id, slug, values, bodies, request.get("selections"), snap)
            self._check_param_names(rendered, taken)
            steps: list[dict] = []
            cells = self.state.cells
            params_anchor = self._params_anchor(cells)
            feature_anchor = request.get("after") or self._feature_anchor(snap, cells)
            if rendered.params:
                # run now: the feature cell below reads these names, and a cell never run defines nothing (NameError)
                steps.append(self._create(params_anchor, "\n".join(rendered.params), run=True))
                if feature_anchor == params_anchor:  # the params cell sits where the feature goes: keep params first
                    feature_anchor = steps[-1]["id"]
            for code in rendered.before:
                before = self._create(feature_anchor, code, run=True)
                steps.append(before)
                feature_anchor = before["id"]
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
            deferred: dict | None = None
            if feature["params_cell"]:
                old = self._cell(feature["params_cell"])["code"]
                new = "\n".join(rendered.params)
                if rendered.params and new.strip() != old.strip():
                    # a name the new feature cell reads must exist first; a name it no longer reads goes after it, else the old
                    # cell would read a name that is gone for a moment
                    added = set(_names(new)[0]) - set(_names(old)[0])
                    if added or not _names(old)[0]:
                        steps.append(self._edit(feature["params_cell"], old, new, run=False))
                    else:
                        deferred = {"cell": feature["params_cell"], "old": old, "new": new}
            elif rendered.params:
                steps.append(self._create(self._params_anchor(self.state.cells), "\n".join(rendered.params), run=False))
            for code in rendered.before:
                parts = next((f for f in snap["features"] if f["part_of"] == feature["slug"]), None)
                if parts is not None:
                    old = self._cell(parts["cell"])["code"]
                    if old.strip() != code.strip():
                        steps.append(self._edit(parts["cell"], old, code, run=False))
            steps.append(self._edit(feature["cell"], cell["code"], rendered.feature, run=True))
            if deferred is not None:
                steps.append(self._edit(deferred["cell"], deferred["old"], deferred["new"], run=True))
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
            if product and product["cell"] and product["body"] in feature["makes"]:
                fallback = feature["reads"][0] if feature["reads"] else None
                if fallback is None:
                    raise GuiError(f"the product is built from {feature['slug']}; point it at another body first")
                steps.append(self._point_product(product, fallback))
            companions = [f["cell"] for f in snap["features"] if f["part_of"] == feature["slug"]]
            for cell_id in (feature["cell"], *companions, feature["params_cell"]):
                if cell_id:
                    steps.append(self._remove(cell_id))
            self._record(steps)
            return self._result(None, steps, feature["slug"])

    def set_connectors(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Replace the connectors of the part the product cell builds (the list is the whole truth, kept in a ``# gui:`` line)."""
        with self._lock:
            self._sync()
            snap = self.snapshot()
            product = snap["product"]
            if not product:
                raise GuiError("this notebook has no product cell that builds a Part from a body")
            try:
                items = assembly_doc.validate_connectors(request.get("connectors") or [])
            except assembly_doc.AssemblyError as exc:
                raise GuiError(str(exc)) from exc
            if not product["cell"]:  # the Part is implicit: connectors are its arguments, so it gets a cell now
                made = self._product_cell(snap, product["body"])
                variable = made["variable"]
                first = f"{variable} = scad.make_part_rpart(part_id=scad.notebook_id(), body={product['body']})"
                steps = [self._create(made["after"], "\n".join(assembly_doc.render_connectors(first, variable, items)), run=True)]
                self._record(steps)
                return self._result(steps[0]["id"], steps, "connectors")
            cell = self._cell(product["cell"])
            first = next((ln for ln in cell["code"].splitlines() if "Part(" in ln or "make_part_rpart(" in ln), None)
            if first is None:
                raise GuiError("the product cell does not build a Part in one line; edit it as code")
            variable = first.split("=", 1)[0].strip()
            first = first.replace("scad.Part(", "scad.make_part_rpart(")  # connectors need a recorded Part
            new = "\n".join(assembly_doc.render_connectors(first, variable, items))
            steps = [self._edit(product["cell"], cell["code"], new, run=True)] if new.strip() != cell["code"].strip() else []
            self._record(steps)
            return self._result(product["cell"], steps, "connectors")

    def use_as_product(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sync()
            snap = self.snapshot()
            name = str(request.get("body", ""))
            if name not in {b["name"] for b in snap["bodies"]}:
                raise GuiError(f"{name!r} is not a body in this notebook")
            if not snap["product"]:
                raise GuiError("this notebook has no product cell that builds a Part from a body")
            if not snap["product"]["cell"]:
                made = self._product_cell(snap, name)
                steps = [self._create(made["after"], f"{made['variable']} = scad.make_part_rpart(part_id=scad.notebook_id(), body={name})", run=True)]
                self._record(steps)
                return self._result(steps[0]["id"], steps, name)
            steps = [self._point_product(snap["product"], name)]
            self._record(steps)
            return self._result(snap["product"]["cell"], steps, name)

    def ref_status(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """How the references of a feature resolve now: per selection slot, ``Resolution.describe()`` of each.

        ``badge`` is the feature's worst: ``ok`` (green), ``merged`` (green, with a note), ``split`` (amber: choose a
        piece), ``lost`` (red: accept a look-alike or pick again); ``None`` when the feature has no references.
        """
        with self._lock:
            self._sync()
            snap = self.snapshot()
            feature = self._feature(snap, request.get("cell"))
            body, slots = self._references(feature)
            report: dict[str, list[dict[str, Any]]] = {}
            for slot, refs in slots.items():
                report[slot] = list(self._kernel_call("reference_status", body, [r.to_dict() for r in refs]))  # type: ignore[arg-type]
            order = {"ok": 0, "merged": 1, "split": 2, "lost": 3}
            worst = None
            for rows in report.values():
                for row in rows:
                    status = "ok" if row.get("chosen") is not None else str(row.get("status"))
                    if worst is None or order.get(status, 3) > order.get(worst, 3):
                        worst = status
            return {"ok": True, "cell": feature["cell"], "body": body, "slots": report, "badge": worst}

    def ref_repair(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Write the person's choice into one reference: ``{cell, slot, index, choice}``.

        *choice* indexes the candidates :meth:`ref_status` listed for that reference: a piece of a split (``piece=``) or
        a look-alike of a lost reference (a new reference made there, in the kernel).  The cell's code is rewritten.
        """
        with self._lock:
            self._sync()
            snap = self.snapshot()
            feature = self._feature(snap, request.get("cell"))
            body, slots = self._references(feature)
            slot = str(request.get("slot", ""))
            refs = list(slots.get(slot) or [])
            try:
                index, choice = int(request.get("index", 0)), int(request["choice"])
            except (KeyError, TypeError, ValueError) as exc:
                raise GuiError("index and choice: whole numbers") from exc
            if not 0 <= index < len(refs):
                raise GuiError(f"{slot!r} has no reference {index}")
            chosen = self._kernel_call("reference_choose", body, refs[index].to_dict(), choice)
            refs[index] = F._ref.ElementRef.from_dict(chosen["record"])  # type: ignore[index]
            cell = self._cell(feature["cell"])
            steps = [self._edit(feature["cell"], cell["code"], F.replace_refs(cell["code"], slot, refs), run=True)]
            self._record(steps)
            return self._result(feature["cell"], steps, feature["slug"])

    def _references(self, feature: Mapping[str, Any]) -> tuple[str, dict[str, list[Any]]]:
        """(the body the feature's selections resolve in, the references of each selection slot)."""
        gui = feature.get("gui")
        if not gui:
            raise GuiError("this feature was written as code; its references are in the notebook")
        spec = F.BY_ID[gui["spec"]]
        values = gui.get("values") or {}
        body = next((v for v in (values.get(spec.body_slot), values.get("body")) if isinstance(v, str)), "")
        code = self._cell(feature["cell"])["code"]
        slots = {slot.name: F.extract_refs(code, slot.name) for slot in spec.slots if slot.kind == "select"}
        return body, {name: refs for name, refs in slots.items() if refs}

    def _kernel_call(self, function: str, *args: Any) -> Any:
        kernel = getattr(self.state, "kernel", None)
        if kernel is None:
            raise GuiError("the notebook's kernel is not running")
        try:
            return kernel.references(function, *args)
        except Exception as exc:  # noqa: BLE001 - the kernel's words are the message
            raise GuiError(str(exc)) from exc

    def _name_picks(self, picked: dict[str, list]) -> dict[str, list]:
        """Each picked entity with its stable reference (``ref``: a record), named in the kernel from the value it
        was drawn from.  An entity the kernel cannot name keeps no ``ref`` (its slot falls back to the older recipe)."""
        ids = [str(item.get("entity_id")) for items in picked.values() for item in items if isinstance(item, Mapping) and item.get("entity_id")]
        kernel = getattr(self.state, "kernel", None)
        named: dict[str, Any] = {}
        if ids and kernel is not None:
            try:
                answers = kernel.references("entity_refs", ids)
            except Exception:  # noqa: BLE001 - no kernel answer: the older recipe
                answers = []
            named = {entity_id: answer.get("record") for entity_id, answer in zip(ids, answers or []) if isinstance(answer, Mapping)}
        out: dict[str, list] = {}
        for slot, items in picked.items():
            rows = []
            for item in items:
                row = {k: v for k, v in dict(item).items() if k != "ref"} if isinstance(item, Mapping) else item
                record = named.get(str(row.get("entity_id"))) if isinstance(row, dict) else None
                if record:
                    row["ref"] = record
                rows.append(row)
            out[slot] = rows
        return out

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
        picked = self._name_picks({k: list(v) for k, v in dict(selections or {}).items() if isinstance(v, (list, tuple))})
        notebook = getattr(self.state, "notebook", None)
        workspace = getattr(self.state, "workspace", None)
        env = {
            "name": getattr(notebook, "stem", slug),
            "notebook_dir": notebook.parent if notebook else None,
            "workspace": workspace,
            "profile_normals": {p["name"]: p["normal_vec"] for p in snap.get("profiles", [])},
        }
        if spec_id == "assembly" and workspace is not None:
            for component in ((values.get("assembly") or {}).get("components") or []):
                if not (Path(workspace) / str(component.get("part", ""))).is_file():
                    raise GuiError(f"{component.get('id')}: the notebook {component.get('part')!r} is not in the workspace")
        try:
            return F.render_feature(spec_id, slug, values, bodies=bodies, selections=picked, known_slugs=known, keep_recipes=keep, env=env)
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
            # a notebook that has only just opened may report the new cell a moment late: look for it by its code
            import time

            deadline = time.monotonic() + 5.0
            while cell is None and time.monotonic() < deadline:
                cell = next((c for c in self.state.cells if str(c.get("code", "")).strip() == code.strip()), None)
                if cell is None:
                    time.sleep(0.2)
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

    def _product_cell(self, snap: Mapping[str, Any], body: str) -> dict[str, str]:
        """Where an explicit product cell goes (after the last cell) and the name it binds (the notebook's stem, free)."""
        taken = set(snap["taken"])
        stem = re.sub(r"\W", "_", getattr(self.state.notebook, "stem", "part") or "part").strip("_").lower() or "part"
        variable = stem if stem not in taken and stem not in F._RESERVED and not stem[0].isdigit() else f"{stem}_part"
        cells = list(self.state.cells)
        return {"after": cells[-1]["id"] if cells else "end", "variable": variable}

    def _repoint_product(self, snap: Mapping[str, Any], rendered: F.Rendered) -> list[dict]:
        product = snap["product"]
        if product and product["cell"] and product["body"] in rendered.reads and rendered.produces == "solid":
            return [self._point_product(product, rendered.slug)]
        return []

    def _first_product(self, snap: Mapping[str, Any], rendered: F.Rendered, after: str, taken: set[str]) -> list[dict]:
        """A notebook with no product yet gets one, built from its first body (a blank notebook starts without cells)."""
        if snap["product"] is not None or rendered.produces != "solid" or any("Part(" in str(c.get("code", "")) for c in self.state.cells):
            return []
        if self._implicit_part():
            return []  # the header says part: the runtime builds the Part from the open body, no cell to keep in step
        stem = re.sub(r"\W", "_", getattr(self.state.notebook, "stem", "part") or "part").strip("_").lower() or "part"
        variable = stem if stem not in taken and stem not in F._RESERVED and not stem[0].isdigit() else f"{stem}_part"
        return [self._create(after, f"{variable} = scad.make_part_rpart(part_id=scad.notebook_id(), body={rendered.slug})", run=True)]

    def _implicit_part(self) -> bool:
        """Whether the open notebook's header declares ``kind = "part"`` (its product needs no cell)."""
        notebook = getattr(self.state, "notebook", None)
        try:
            config = read_notebook_config(notebook) if notebook is not None else None
        except Exception:  # noqa: BLE001 - a malformed header is reported elsewhere
            return False
        return config is not None and config.kind == "part"

    def _apply(self, step: dict, *, forward: bool) -> None:
        kind = step["kind"]
        make, drop = (forward and kind == "created") or (not forward and kind == "deleted"), (forward and kind == "deleted") or (not forward and kind == "created")
        try:
            if make:
                created = self._create(step["after"] if self._exists(step["after"]) else "end", step["code"], run=True)
                self._rename(step["id"], created["id"])  # the cell is a new one: every step that names it follows
            elif drop:
                self._remove(step["id"], expect=step["code"])
            else:  # edited
                old, new = (step["old"], step["new"]) if forward else (step["new"], step["old"])
                self._edit(step["id"], old, new, run=True)
        except GuiError as exc:
            raise GuiError(f"cannot {'redo' if forward else 'undo'}: the notebook changed since ({exc})", conflict=exc.conflict) from exc

    def _rename(self, old: str, new: str) -> None:
        for steps in (*self._undo, *self._redo):
            for step in steps:
                if step.get("id") == old:
                    step["id"] = new
                if step.get("after") == old:
                    step["after"] = new

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
