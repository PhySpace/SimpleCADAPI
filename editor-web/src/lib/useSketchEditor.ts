import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  LatestSolver,
  addArc,
  addSpline,
  addCircle,
  addConstraint,
  addLine,
  applicableConstraints,
  applySolved,
  blamedConstraints,
  choiceFromDoc,
  choiceToIndices,
  circleRadius,
  constraintTargets,
  dimensionValue,
  dragDoc,
  dragPoints,
  ensurePoint,
  entityMap,
  fetchSolve,
  findLoops,
  gridStep,
  entityHit,
  hitTest,
  isDimensional,
  isFixed,
  loopAt,
  measure,
  parseDimension,
  pickLoop,
  reconcileChoice,
  removeItems,
  seedDelta,
  setConstruction,
  snap,
  solvedPoints,
  statusBadge,
  writable,
  type Choice,
  type ConstraintKind,
  type Hit,
  type SConstraint,
  type SketchDoc,
  type SolveResult,
  type Spot,
} from "@/lib/sketch";
import {
  applyEdit,
  cornerAt,
  cornerOfLines,
  cornerRequest,
  defaultCornerValue,
  describeEdit,
  extendRequest,
  fetchSketchOp,
  nearerEnd,
  parseCornerValue,
  projectRequest,
  projectedCount,
  pushHistory,
  remapChoice,
  trimRequest,
  type Corner,
  type CornerOp,
  type EditRequest,
  type End,
} from "@/lib/sketch-edit";
import { typedFields, typedTarget, type TypedDims } from "@/lib/sketch-typed";

/** How near the pointer (screen pixels) must be to a point or a curve to snap to it or pick it. */
const PICK_PX = 16;
const DRAW_TOOLS = new Set(["point", "line", "circle", "arc", "spline"]);
const FIRST = "\u0000first"; // a spline's closing click: "the first control point"

export type Tool = "select" | "point" | "line" | "circle" | "arc" | "spline" | "delete" | "trim" | "extend" | "fillet" | "chamfer";
/** The corner value box (fillet radius / chamfer distance) open at a corner. */
export type CornerBox = { op: CornerOp; corner: Corner; text: string; bad: boolean };
/** What the last SDK edit (trim, extend) said: its notes, or the error (which names ids). Shown in the status area. */
export type EditNote = { tone: "ok" | "fail"; text: string };
const EDIT_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["trim", "extend", "fillet", "chamfer"]);
export type Draft = { tool: "line"; from: Spot } | { tool: "circle"; center: Spot } | { tool: "arc"; center: Spot; start?: Spot } | { tool: "spline"; points: Spot[] } | null;
export type Drag = { ids: string[]; origin: Record<string, [number, number]>; start: [number, number]; positions: Record<string, [number, number]>; releasing?: boolean };
export type ValueBox = { kind: ConstraintKind; targets: string[]; constraintId?: string; text: string; bad: boolean };

/** One pointer event in the sketch's terms: its screen position (px, local to the overlay), the plane position under
 * it (null when the ray misses the plane), the pixels per mm there, and the modifier keys. */
export type PointerInfo = { sx: number; sy: number; world: [number, number] | null; scale: number; shift: boolean; alt: boolean };

export type KeyOutcome = "handled" | "leave" | "ignored";

/** The state and the behaviour of the sketch editor, apart from where it is drawn: the document with its undo history,
 * the live solve, loops and the chosen profile, the tools and their drafts, drag with a temporary fix, the value box.
 * The overlay feeds it pointer events already mapped into the plane. */
export function useSketchEditor(initial: SketchDoc, modelPoints: readonly [number, number][] = [], projectFrom: readonly string[] = []) {
  const [doc, setDoc] = useState<SketchDoc>(initial);
  const [tool, setTool] = useState<Tool>("select");
  const [selection, setSelection] = useState<string[]>([]);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number; pointId?: string } | null>(null);
  const [hover, setHover] = useState<Hit | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [box, setBox] = useState<ValueBox | null>(null);
  const [solve, setSolve] = useState<{ result: SolveResult; for: SketchDoc } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [auto, setAuto] = useState(true);
  const [snapOn, setSnapOn] = useState(true);
  const [construction, setConstructionMode] = useState(false);
  const [choice, setChoice] = useState<Choice>({ outer: null, inner: [], chosen: false });
  const [edits, setEdits] = useState(0);
  const [editNote, setEditNote] = useState<EditNote | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [flash, setFlash] = useState<ReadonlySet<string>>(new Set());
  const [hoverEnd, setHoverEnd] = useState<End | null>(null);
  const [cornerHover, setCornerHover] = useState<Corner | null>(null);
  const [pendingLine, setPendingLine] = useState<string | null>(null);
  const [cornerBox, setCornerBox] = useState<CornerBox | null>(null);
  const [projectOpen, setProjectOpen] = useState(false);
  const flashTimer = useRef<number | null>(null);

  const docRef = useRef(doc);
  docRef.current = doc;
  const draftRef = useRef<Draft>(null);
  draftRef.current = draft;
  const history = useRef<SketchDoc[]>([]);
  const future = useRef<SketchDoc[]>([]);
  const press = useRef<{ hit: Hit; sx: number; sy: number; world: [number, number]; shift: boolean; wasSelected: boolean } | null>(null);
  const choiceReady = useRef(initial.points.length === 0);

  // -- document changes (history) --------------------------------------------------------------------------------------
  const commit = useCallback((next: SketchDoc, record = true) => {
    if (record) {
      history.current = pushHistory(history.current, docRef.current);
      future.current = [];
      setEdits(history.current.length);
    }
    docRef.current = next;
    setDoc(next);
  }, []);
  const undo = useCallback(() => {
    const previous = history.current.pop();
    if (!previous) return;
    future.current.push(docRef.current);
    docRef.current = previous;
    setDoc(previous);
    setEdits(history.current.length);
    setSelection([]);
    setDraft(null);
    setEditNote(null); // the note told about an edit that is now undone
    setCornerBox(null);
    setPendingLine(null);
  }, []);
  const redo = useCallback(() => {
    const next = future.current.pop();
    if (!next) return;
    history.current.push(docRef.current);
    docRef.current = next;
    setDoc(next);
    setEdits(history.current.length);
    setEditNote(null);
  }, []);

  // -- live solve ----------------------------------------------------------------------------------------------------------
  const solver = useMemo(
    () =>
      new LatestSolver(async (d) => {
        try {
          const result = await fetchSolve(d);
          setError(null);
          return result;
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
          return null;
        }
      }),
    [],
  );
  const effective = useMemo(() => (drag ? dragDoc(doc, drag.positions) : doc), [doc, drag]);
  useEffect(() => {
    let live = true;
    void solver.request(effective).then((result) => {
      if (live && result) setSolve({ result, for: effective });
    });
    return () => {
      live = false;
    };
  }, [effective, solver]);
  const result = solve?.result ?? null;

  // Write the solved coordinates back into the seeds (never while dragging, never for a conflicting sketch).
  useEffect(() => {
    if (drag || !solve || solve.for !== docRef.current || !writable(solve.result)) return;
    if (seedDelta(docRef.current, solve.result) > 1e-6) commit(applySolved(docRef.current, solve.result), false);
  }, [solve, drag, commit]);

  const pts = useMemo(() => solvedPoints(doc, result), [doc, result]);
  const loops = useMemo(() => findLoops(doc, result), [doc, result]);
  const loopKey = loops.map((l) => `${l.key}:${l.index}`).join("|");
  const loopsRef = useRef(loops);
  loopsRef.current = loops;
  const resultRef = useRef(result);
  resultRef.current = result;
  const choiceRef = useRef(choice);
  choiceRef.current = choice;
  const ptsRef = useRef(pts);
  ptsRef.current = pts;

  // The chosen outer profile and holes follow the loops' identity; the document keeps the server's indices.
  useEffect(() => {
    if (drag || !result) return;
    if (!choiceReady.current) {
      choiceReady.current = true;
      setChoice(reconcileChoice(choiceFromDoc(docRef.current, loops), loops));
      return;
    }
    setChoice((current) => reconcileChoice(current, loops));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loopKey, result === null]);
  useEffect(() => {
    if (drag || !result) return;
    const outer = loops.find((l) => l.key === choice.outer);
    const { profile, inner } = choiceToIndices(choice, loops);
    const d = docRef.current;
    if (d.profile !== profile || d.inner.length !== inner.length || d.inner.some((v, i) => v !== inner[i])) commit({ ...d, profile, inner }, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choice, loopKey, drag, doc.profile, doc.inner]);

  // -- snapping -----------------------------------------------------------------------------------------------------------------
  /** Where curves of the sketch cross and no point is yet (the SDK's answer for the last solve): shown, and snapped to. */
  const crossings = useMemo(() => (result?.crossings ?? []).map((c) => c.at), [result]);
  const snapTargets = useMemo(() => {
    const all = new Map(pts);
    modelPoints.forEach((p, i) => all.set(`m:${i}`, p));
    crossings.forEach((p, i) => all.set(`x:${i}`, p));
    return all;
  }, [pts, modelPoints, crossings]);

  const spotAt = useCallback(
    (world: [number, number], info: Pick<PointerInfo, "scale" | "alt">): Spot => {
      const s = snap(world, snapTargets, { grid: snapOn && !info.alt ? gridStep(info.scale) : null, tol: PICK_PX / info.scale });
      return { x: s.x, y: s.y, pointId: s.pointId?.startsWith("m:") || s.pointId?.startsWith("x:") ? undefined : s.pointId };
    },
    [snapTargets, snapOn],
  );

  // -- constraints, value box -------------------------------------------------------------------------------------------------
  const openBox = useCallback(
    (kind: ConstraintKind, targets: string[], constraint?: SConstraint) => {
      const current = constraint ? dimensionValue(constraint, docRef.current, result) : measure(kind, targets, docRef.current, result);
      setBox({ kind, targets, constraintId: constraint?.id, text: current === null ? "" : String(Math.round(current * 100) / 100), bad: false });
    },
    [result],
  );

  const applyConstraint = useCallback(
    (kind: ConstraintKind) => {
      const list = constraintTargets(kind, selection, docRef.current);
      if (!list.length) return;
      if (isDimensional(kind)) {
        openBox(kind, list[0]);
        return;
      }
      let next = docRef.current;
      for (const targets of list) next = addConstraint(next, { kind, targets });
      commit(next);
    },
    [selection, commit, openBox],
  );

  const submitBox = useCallback(() => {
    if (!box) return;
    const value = parseDimension(box.text, box.kind);
    if (value === null) {
      setBox({ ...box, bad: true });
      return;
    }
    const d = docRef.current;
    if (box.constraintId) commit({ ...d, constraints: d.constraints.map((c) => (c.id === box.constraintId ? { ...c, value, driving: true } : c)) });
    else commit(addConstraint(d, { kind: box.kind, targets: box.targets, value, driving: true }));
    setBox(null);
  }, [box, commit]);

  const deleteSelection = useCallback(() => {
    if (!selection.length) return;
    commit(removeItems(docRef.current, selection));
    setSelection([]);
    setHover(null);
  }, [selection, commit]);

  const toggleConstruction = useCallback(() => {
    const entities = selection.filter((id) => entityMap(docRef.current).has(id));
    if (entities.length) {
      const all = entities.every((id) => entityMap(docRef.current).get(id)?.construction);
      commit(setConstruction(docRef.current, entities, !all));
    } else setConstructionMode((on) => !on);
  }, [selection, commit]);

  const chooseTool = useCallback((next: Tool) => {
    // The SDK edits are not offered in the middle of a draft (finish or cancel it first).
    if (EDIT_TOOLS.has(next) && draftRef.current) {
      setEditNote({ tone: "fail", text: `${next} is not available while a draft is in progress: finish it or press Esc first` });
      return;
    }
    setEditNote(null);
    setHoverEnd(null);
    setCornerHover(null);
    setPendingLine(null);
    setCornerBox(null);
    setProjectOpen(false);
    setTool(next);
    setDraft(null);
    if (next !== "select") setSelection([]);
  }, []);

  // -- SDK edits (trim, extend) -----------------------------------------------------------------------------------------------
  /** Send one edit to the server (which runs the SDK function) and adopt the document it returns: undoable as one step,
   * re-solved by the live solve, the created entities flashed.  A failure is shown, never swallowed. */
  const runEdit = useCallback(
    async (request: EditRequest) => {
      setEditBusy(true);
      setEditNote(null);
      try {
        const response = await fetchSketchOp(request);
        const { doc: next, flash: created } = applyEdit(response);
        // The server resets the profile and the holes: the chosen loops are carried over to the loops that replace them and
        // the live solve writes the indices back.
        setChoice(remapChoice(loopsRef.current, choiceRef.current, findLoops(next, resultRef.current)));
        commit(next);
        setSelection([]);
        setHover(null);
        setHoverEnd(null);
        setCornerHover(null);
        setPendingLine(null);
        setCornerBox(null);
        setProjectOpen(false);
        const from = request.op === "project" ? String((request.args as { from_sketch: string }).from_sketch) : "";
        setEditNote({ tone: "ok", text: describeEdit(request.op, response, request.op === "project" ? { ...projectedCount(next, created), from } : undefined) });
        if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
        setFlash(new Set(created));
        flashTimer.current = window.setTimeout(() => {
          flashTimer.current = null;
          setFlash(new Set());
        }, 1400);
      } catch (e) {
        setEditNote({ tone: "fail", text: `${request.op}: ${e instanceof Error ? e.message : String(e)}` });
        setCornerBox(null);
        setPendingLine(null);
      } finally {
        setEditBusy(false);
      }
    },
    [commit],
  );
  useEffect(() => () => void (flashTimer.current !== null && window.clearTimeout(flashTimer.current)), []);

  /** Open the value box of a corner (fillet radius / chamfer distance) with the offered default. */
  const openCorner = useCallback((op: CornerOp, corner: Corner) => {
    const value = defaultCornerValue(docRef.current, ptsRef.current, corner);
    setCornerHover(null);
    setPendingLine(null);
    setCornerBox({ op, corner, text: value > 0 ? String(value) : "", bad: false });
  }, []);
  const submitCorner = useCallback(() => {
    if (!cornerBox || editBusy) return;
    const value = parseCornerValue(cornerBox.text);
    if (value === null) {
      setCornerBox({ ...cornerBox, bad: true });
      return;
    }
    const request = cornerRequest(cornerBox.op, docRef.current, cornerBox.corner, value);
    setCornerBox(null);
    void runEdit(request);
  }, [cornerBox, editBusy, runEdit]);

  /** The project popover: refuses with a word when the notebook has no other sketch. */
  const openProject = useCallback(() => {
    if (draftRef.current) {
      setEditNote({ tone: "fail", text: "project is not available while a draft is in progress: finish it or press Esc first" });
      return;
    }
    if (projectFrom.length === 0) {
      setEditNote({ tone: "fail", text: "project: there is no other sketch in this notebook to project from; finish and add another sketch first" });
      return;
    }
    setEditNote(null);
    setProjectOpen((open) => !open);
  }, [projectFrom.length]);
  const projectSketch = useCallback((slug: string) => void runEdit(projectRequest(docRef.current, slug)), [runEdit]);

  // -- placing: a click of a drawing tool, or the same click given as typed numbers --------------------------------------------------
  /** Put the next point of the active drawing tool at `spot`; `dims` are typed dimensions kept as driving constraints. */
  const place = (spot: Spot, dims: TypedDims = {}): void => {
    const d = docRef.current;
    const opts = { auto, construction };
    const keep = (doc: SketchDoc, id: string): SketchDoc => {
      let next = doc;
      if (dims.length !== undefined) next = addConstraint(next, { kind: "length", targets: [id], value: dims.length, driving: true });
      if (dims.radius !== undefined) next = addConstraint(next, { kind: "radius", targets: [id], value: dims.radius, driving: true });
      return next;
    };
    if (tool === "point") {
      if (!spot.pointId) commit(ensurePoint(d, spot).doc);
      return;
    }
    if (tool === "line") {
      if (!draft) {
        setDraft({ tool: "line", from: spot });
        return;
      }
      if (draft.tool !== "line") return;
      const start = ensurePoint(d, draft.from);
      const made = addLine(start.doc, start.id, spot, opts);
      if (!made) return;
      commit(keep(made.doc, made.lineId));
      setDraft(made.reused ? null : { tool: "line", from: { x: 0, y: 0, pointId: made.endId } });
      return;
    }
    if (tool === "circle") {
      if (!draft) {
        setDraft({ tool: "circle", center: spot });
        return;
      }
      if (draft.tool !== "circle") return;
      const made = addCircle(d, draft.center, spot, opts);
      if (made) {
        commit(keep(made.doc, made.id));
        setDraft(null);
      }
      return;
    }
    if (tool === "spline") {
      const points = draft?.tool === "spline" ? draft.points : [];
      const near = (a: Spot) => (a.pointId !== undefined && a.pointId === spot.pointId) || Math.hypot(a.x - spot.x, a.y - spot.y) <= pickTolerance.current;
      if (points.length >= 3 && near(points[0])) {
        // back on the first control point: a closed spline (it starts and ends on one point)
        const first = points[0];
        finishSpline([...points, first.pointId ? first : { ...first, pointId: FIRST }]);
        return;
      }
      if (points.length >= 2 && near(points[points.length - 1])) {
        finishSpline(points); // the last point clicked again (a double click): done
        return;
      }
      setDraft({ tool: "spline", points: [...points, spot] });
      return;
    }
    if (tool === "arc") {
      if (!draft) {
        setDraft({ tool: "arc", center: spot });
        return;
      }
      if (draft.tool !== "arc") return;
      if (!draft.start) {
        setDraft({ ...draft, start: spot });
        if (dims.radius !== undefined) arcRadius.current = dims.radius;
        return;
      }
      const made = addArc(d, draft.center, draft.start, spot, opts);
      if (made) {
        const radius = arcRadius.current;
        arcRadius.current = undefined;
        commit(radius === undefined ? made.doc : addConstraint(made.doc, { kind: "radius", targets: [made.id], value: radius, driving: true }));
        setDraft(null);
      }
    }
  };
  /** Make the B-spline of the clicked control points (Enter, or a click back on the first point closes it). */
  const finishSpline = (points: Spot[]): void => {
    setDraft(null);
    // a closing click names the first spot with FIRST: it becomes that spot's point once the first point exists
    let doc = docRef.current;
    const first = ensurePoint(doc, points[0]);
    doc = first.doc;
    const spots = points.map((spot, i) => (i === 0 ? { ...spot, pointId: first.id } : spot.pointId === FIRST ? { ...spot, pointId: first.id } : spot));
    const made = addSpline(doc, spots, { auto, construction });
    if (made) commit(made.doc);
  };
  /** Snap distance of the last press (sketch units): how near a click must be to a draft's point to mean it. */
  const pickTolerance = useRef(0);
  /** The radius typed for the arc being drawn (its start), kept until the arc is made. */
  const arcRadius = useRef<number | undefined>(undefined);

  /** The typed-entry box: open while a drawing tool waits for its next point and a number was typed (or Tab pressed). */
  const [entry, setEntry] = useState<{ text: Record<string, string>; focus: number; error: string | null } | null>(null);
  const entryFields = typedFields(tool, draft);
  useEffect(() => setEntry(null), [tool]);
  const openEntry = (first?: string) => {
    const fields = typedFields(tool, draftRef.current);
    if (!fields) return false;
    setEntry({ text: first === undefined ? {} : { [fields[0].name]: first }, focus: 0, error: null });
    return true;
  };
  const submitEntry = () => {
    if (!entry) return;
    const pointsNow = pts;
    const at = (spot: Spot): [number, number] => (spot.pointId ? (pointsNow.get(spot.pointId) ?? [spot.x, spot.y]) : [spot.x, spot.y]);
    const target = typedTarget(tool, draftRef.current, entry.text, at);
    if ("error" in target) {
      setEntry({ ...entry, error: target.error });
      return;
    }
    place(target.spot, target.dims);
    setEntry(null);
  };

  // -- pointer ------------------------------------------------------------------------------------------------------------------
  /** A left-button press. "press" asks the caller to capture the pointer (a selection that may become a drag). */
  const pointerDown = (info: PointerInfo, shiftKey = info.shift): "press" | "handled" => {
    const world = info.world;
    if (!world) return "handled";
    const d = docRef.current;
    const opts = { auto, construction };
    const tol = PICK_PX / info.scale;
    pickTolerance.current = tol;
    if (tool === "trim" || tool === "extend") {
      if (editBusy) return "handled";
      const hit = entityHit(d, result, world, tol);
      if (!hit) return "handled";
      if (tool === "trim") void runEdit(trimRequest(d, hit.id, world));
      else {
        const request = extendRequest(d, pts, hit.id, world);
        if (request) void runEdit(request);
        else setEditNote({ tone: "fail", text: `extend: ${hit.id} has no end to extend (a circle is closed); pick a line or an arc` });
      }
      return "handled";
    }
    if (tool === "fillet" || tool === "chamfer") {
      if (editBusy || cornerBox) return "handled";
      const op: CornerOp = tool === "fillet" ? "fillet_corner" : "chamfer_corner";
      const hit = hitTest(d, result, world, tol);
      if (!hit) return "handled";
      if (hit.kind === "point") {
        const corner = cornerAt(d, hit.id);
        if (corner) openCorner(op, corner);
        else setEditNote({ tone: "fail", text: `${tool}: ${hit.id} is not a corner (a corner is a point shared by exactly two lines)` });
        return "handled";
      }
      const line = d.entities.find((e) => e.id === hit.id);
      if (!line || line.kind !== "line") {
        setEditNote({ tone: "fail", text: `${tool}: ${hit.id} is not a line; click a corner point or two lines in turn` });
        return "handled";
      }
      setEditNote(null);
      if (!pendingLine || pendingLine === hit.id) {
        setPendingLine(hit.id);
        return "handled";
      }
      const corner = cornerOfLines(d, pendingLine, hit.id);
      if (corner) openCorner(op, corner);
      else {
        setEditNote({ tone: "fail", text: `${tool}: ${pendingLine} and ${hit.id} do not meet at a corner of exactly two lines` });
        setPendingLine(hit.id);
      }
      return "handled";
    }
    if (tool === "select" || tool === "delete") {
      const hit = hitTest(d, result, world, tol);
      if (tool === "delete") {
        if (hit) {
          commit(removeItems(d, [hit.id]));
          setHover(null);
        }
        return "handled";
      }
      if (hit) {
        const wasSelected = selection.includes(hit.id);
        if (shiftKey) setSelection((s) => (s.includes(hit.id) ? s.filter((id) => id !== hit.id) : [...s, hit.id]));
        else if (!wasSelected) setSelection([hit.id]);
        press.current = { hit, sx: info.sx, sy: info.sy, world, shift: shiftKey, wasSelected };
        return "press";
      }
      const loop = loopAt(loops, world);
      if (loop) {
        setChoice((c) => pickLoop(c, loop.key, shiftKey));
        if (!shiftKey) setSelection([]);
        return "handled";
      }
      if (!shiftKey) setSelection([]);
      return "handled";
    }
    place(spotAt(world, info));
    return "handled";
  };

  const pointerMove = (info: PointerInfo) => {
    const world = info.world;
    if (!world) {
      setHover(null);
      return;
    }
    const tol = PICK_PX / info.scale;
    if (press.current && !drag) {
      const p = press.current;
      if (Math.hypot(info.sx - p.sx, info.sy - p.sy) > 4 && !p.shift) {
        const d = docRef.current;
        const ids = dragPoints(d, p.hit.id);
        if (ids.length && !ids.some((id) => isFixed(d, id))) {
          const origin: Record<string, [number, number]> = {};
          for (const id of ids) origin[id] = pts.get(id) ?? [0, 0];
          setDrag({ ids, origin, start: p.world, positions: origin });
        }
      }
    }
    if (drag && !drag.releasing) {
      const positions: Record<string, [number, number]> = {};
      if (drag.ids.length === 1) {
        const s = snap(world, snapTargets, { grid: snapOn && !info.alt ? gridStep(info.scale) : null, tol: snapOn ? tol : 0, skip: new Set(drag.ids) });
        positions[drag.ids[0]] = [s.x, s.y];
      } else {
        const dx = world[0] - drag.start[0];
        const dy = world[1] - drag.start[1];
        for (const id of drag.ids) positions[id] = [drag.origin[id][0] + dx, drag.origin[id][1] + dy];
      }
      setDrag({ ...drag, positions });
      return;
    }
    if (tool === "select") {
      setHover(hitTest(docRef.current, result, world, tol));
      setCursor({ x: world[0], y: world[1] });
    } else if (tool === "fillet" || tool === "chamfer") {
      const hit = cornerBox ? null : hitTest(docRef.current, result, world, tol);
      setHover(hit);
      if (hit?.kind === "point") setCornerHover(cornerAt(docRef.current, hit.id));
      else if (hit && pendingLine && hit.id !== pendingLine) setCornerHover(cornerOfLines(docRef.current, pendingLine, hit.id));
      else setCornerHover(null);
      setCursor({ x: world[0], y: world[1] });
    } else if (tool === "trim" || tool === "extend") {
      const hit = entityHit(docRef.current, result, world, tol);
      setHover(hit);
      setHoverEnd(hit && tool === "extend" ? nearerEnd(docRef.current, pts, hit.id, world) : null);
      setCursor({ x: world[0], y: world[1] });
    } else {
      const s = spotAt(world, info);
      setCursor({ x: s.x, y: s.y, pointId: s.pointId });
    }
  };

  const pointerUp = async () => {
    const p = press.current;
    press.current = null;
    if (drag && !drag.releasing) {
      // Final solve with the temporary fixes, then drop them and keep the solved coordinates.
      setDrag({ ...drag, releasing: true });
      const final = await solver.request(dragDoc(docRef.current, drag.positions));
      if (final && writable(final)) commit(applySolved(docRef.current, final));
      setDrag(null);
      return;
    }
    if (p && !p.shift && p.wasSelected && selection.length > 1) setSelection([p.hit.id]);
  };

  const pointerLeave = () => {
    setHover(null);
    if (!draft) setCursor(null);
  };

  // -- keyboard ----------------------------------------------------------------------------------------------------------------
  /** Keys of the sketch: tool letters, X, Delete, Cmd/Ctrl+Z, Escape.  "leave" asks the caller to leave sketch mode. */
  const key = (event: KeyboardEvent): KeyOutcome => {
    const tag = (event.target as HTMLElement | null)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return "ignored";
    const k = event.key.toLowerCase();
    if (event.metaKey || event.ctrlKey) {
      if (k !== "z") return "ignored";
      if (event.shiftKey) redo();
      else undo();
      return "handled";
    }
    if (event.altKey) return "ignored";
    if (entry) return "ignored"; // the box has the keyboard
    if ((/^[0-9.\-=]$/.test(event.key) || event.key === "Tab") && DRAW_TOOLS.has(tool) && openEntry(event.key === "Tab" ? undefined : event.key)) return "handled";
    const shortcuts: Record<string, Tool> = { v: "select", p: "point", l: "line", c: "circle", a: "arc", b: "spline", d: "delete", t: "trim", e: "extend", r: "fillet", h: "chamfer" };
    if (k === "enter" && draft?.tool === "spline") {
      if (draft.points.length >= 2) finishSpline(draft.points);
      return "handled";
    }
    if (shortcuts[k]) chooseTool(shortcuts[k]);
    else if (k === "j") openProject();
    else if (k === "x") toggleConstruction();
    else if (k === "delete" || k === "backspace") deleteSelection();
    else if (k === "escape") {
      if (entry) setEntry(null);
      else if (box) setBox(null);
      else if (cornerBox) setCornerBox(null);
      else if (projectOpen) setProjectOpen(false);
      else if (pendingLine) setPendingLine(null);
      else if (draft) setDraft(null);
      else if (tool !== "select") setTool("select");
      else if (selection.length) setSelection([]);
      else return "leave";
    } else return "ignored";
    return "handled";
  };

  // -- derived display ------------------------------------------------------------------------------------------------------------------
  const applicable = useMemo(() => new Set(applicableConstraints(selection, doc)), [selection, doc]);
  const blamed = useMemo(() => blamedConstraints(result), [result]);
  const failing = useMemo(() => {
    const ids = new Set<string>();
    for (const c of doc.constraints) if (blamed.has(c.id)) for (const t of c.targets) ids.add(t.split(".")[0]);
    return ids;
  }, [doc.constraints, blamed]);
  const highlighted = useMemo(() => {
    const c = doc.constraints.find((k) => k.id === highlight);
    return new Set(c ? c.targets.map((t) => t.split(".")[0]) : []);
  }, [doc.constraints, highlight]);
  const fixedPoints = useMemo(() => new Set(doc.constraints.filter((c) => c.kind === "fix").map((c) => c.targets[0].split(".")[0])), [doc.constraints]);
  /** The solve answers the document as it is now (profiles and indices are the SDK's for exactly this sketch). */
  const fresh = solve !== null && solve.for === effective;
  const solved = result?.status === "solved";
  const badge = statusBadge(result, error);
  const diagnostics = (result?.diagnostics ?? []).filter((d) => d.code !== "underconstrained");
  const outer = loops.find((l) => l.key === choice.outer);

  /** The bounding box of the sketch (points and the extent of circles and arcs), or null when it is empty. */
  const extents = useCallback((): { min: [number, number]; max: [number, number] } | null => {
    const list: [number, number][] = [...pts.values()];
    for (const e of docRef.current.entities)
      if (e.kind !== "line") {
        const c = pts.get(e.center ?? "");
        if (c) {
          const r = circleRadius(docRef.current, e, pts, result);
          list.push([c[0] - r, c[1] - r], [c[0] + r, c[1] + r]);
        }
      }
    if (!list.length) return null;
    return { min: [Math.min(...list.map((p) => p[0])), Math.min(...list.map((p) => p[1]))], max: [Math.max(...list.map((p) => p[0])), Math.max(...list.map((p) => p[1]))] };
  }, [pts, result]);

  const typed = DRAW_TOOLS.has(tool) ? " Or type numbers (Tab between fields, Enter places)." : "";
  const hint =
    (tool === "select"
      ? "Click or shift-click to select; drag a point or a line to move it; click inside a loop for the profile, shift-click for a hole."
      : tool === "line"
        ? draft ? "Click the next point; clicking an existing point ends the chain; Esc ends." : "Click the first point."
        : tool === "circle"
          ? draft ? "Click a point on the circle." : "Click the centre."
          : tool === "spline"
            ? draft ? "Click the next control point. Finish: Enter, or click the last point again (double-click); click the first point to close it. Esc drops it." : "Click the first control point."
          : tool === "arc"
            ? draft ? (draft.tool === "arc" && draft.start ? "Click the end (counter-clockwise from start)." : "Click the start point (sets the radius).") : "Click the centre."
            : tool === "delete"
              ? "Click an item to delete it."
              : tool === "fillet" || tool === "chamfer"
                ? pendingLine
                  ? `Click the second line of the corner (${pendingLine} is picked).`
                  : `Click a corner (a point shared by two lines) or two lines in turn, then type the ${tool === "fillet" ? "radius" : "distance"}: Enter commits, Esc cancels.`
              : tool === "trim"
                ? "Click the part of a line, arc or circle to cut away; the SDK decides the piece between its neighbours."
                : tool === "extend"
                  ? "Click a line near the end to extend; it grows to the next entity."
                  : "Click to place a point.") + typed;

  return {
    cornerHover, pendingLine, cornerBox, setCornerBox, submitCorner, projectOpen, setProjectOpen, openProject, projectSketch, projectFrom,
    doc, commit, undo, redo, edits, editNote, editBusy, flash, hoverEnd, runEdit, tool, chooseTool, selection, highlight, setHighlight, draft, cursor, hover, drag, box, setBox, result, error, auto, setAuto, snapOn,
    setSnapOn, construction, choice, pts, loops, applicable, blamed, fresh, crossings, finishSplineDraft: () => draft?.tool === "spline" && draft.points.length >= 2 && finishSpline(draft.points), entry, setEntry, entryFields, submitEntry, failing, highlighted, fixedPoints, solved, badge, diagnostics, outer, hint, extents,
    openBox, applyConstraint, submitBox, deleteSelection, toggleConstruction, pointerDown, pointerMove, pointerUp, pointerLeave, key,
  };
}

export type SketchEditor = ReturnType<typeof useSketchEditor>;
