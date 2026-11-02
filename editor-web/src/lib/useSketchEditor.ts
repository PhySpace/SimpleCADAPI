import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  LatestSolver,
  addArc,
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

export type Tool = "select" | "point" | "line" | "circle" | "arc" | "delete";
export type Draft = { tool: "line"; from: Spot } | { tool: "circle"; center: Spot } | { tool: "arc"; center: Spot; start?: Spot } | null;
export type Drag = { ids: string[]; origin: Record<string, [number, number]>; start: [number, number]; positions: Record<string, [number, number]>; releasing?: boolean };
export type ValueBox = { kind: ConstraintKind; targets: string[]; constraintId?: string; text: string; bad: boolean };

/** One pointer event in the sketch's terms: its screen position (px, local to the overlay), the plane position under
 * it (null when the ray misses the plane), the pixels per mm there, and the modifier keys. */
export type PointerInfo = { sx: number; sy: number; world: [number, number] | null; scale: number; shift: boolean; alt: boolean };

export type KeyOutcome = "handled" | "leave" | "ignored";

/** The state and the behaviour of the sketch editor, apart from where it is drawn: the document with its undo history,
 * the live solve, loops and the chosen profile, the tools and their drafts, drag with a temporary fix, the value box.
 * The overlay feeds it pointer events already mapped into the plane. */
export function useSketchEditor(initial: SketchDoc, modelPoints: readonly [number, number][] = []) {
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

  const docRef = useRef(doc);
  docRef.current = doc;
  const history = useRef<SketchDoc[]>([]);
  const future = useRef<SketchDoc[]>([]);
  const press = useRef<{ hit: Hit; sx: number; sy: number; world: [number, number]; shift: boolean; wasSelected: boolean } | null>(null);
  const choiceReady = useRef(initial.points.length === 0);

  // -- document changes (history) --------------------------------------------------------------------------------------
  const commit = useCallback((next: SketchDoc, record = true) => {
    if (record) {
      history.current = [...history.current.slice(-80), docRef.current];
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
  }, []);
  const redo = useCallback(() => {
    const next = future.current.pop();
    if (!next) return;
    history.current.push(docRef.current);
    docRef.current = next;
    setDoc(next);
    setEdits(history.current.length);
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
    if (choice.outer && outer && outer.index === null) return;
    const { profile, inner } = choiceToIndices(choice, loops);
    const d = docRef.current;
    if (d.profile !== profile || d.inner.length !== inner.length || d.inner.some((v, i) => v !== inner[i])) commit({ ...d, profile, inner }, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choice, loopKey, drag]);

  // -- snapping -----------------------------------------------------------------------------------------------------------------
  const snapTargets = useMemo(() => {
    const all = new Map(pts);
    modelPoints.forEach((p, i) => all.set(`m:${i}`, p));
    return all;
  }, [pts, modelPoints]);

  const spotAt = useCallback(
    (world: [number, number], info: Pick<PointerInfo, "scale" | "alt">): Spot => {
      const s = snap(world, snapTargets, { grid: snapOn && !info.alt ? gridStep(info.scale) : null, tol: 9 / info.scale });
      return { x: s.x, y: s.y, pointId: s.pointId?.startsWith("m:") ? undefined : s.pointId };
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
    setTool(next);
    setDraft(null);
    if (next !== "select") setSelection([]);
  }, []);

  // -- pointer ------------------------------------------------------------------------------------------------------------------
  /** A left-button press. "press" asks the caller to capture the pointer (a selection that may become a drag). */
  const pointerDown = (info: PointerInfo, shiftKey = info.shift): "press" | "handled" => {
    const world = info.world;
    if (!world) return "handled";
    const d = docRef.current;
    const opts = { auto, construction };
    const tol = 9 / info.scale;
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
    const spot = spotAt(world, info);
    if (tool === "point") {
      if (!spot.pointId) commit(ensurePoint(d, spot).doc);
      return "handled";
    }
    if (tool === "line") {
      if (!draft) {
        setDraft({ tool: "line", from: spot });
        return "handled";
      }
      if (draft.tool !== "line") return "handled";
      const start = ensurePoint(d, draft.from);
      const made = addLine(start.doc, start.id, spot, opts);
      if (!made) return "handled";
      commit(made.doc);
      setDraft(made.reused ? null : { tool: "line", from: { x: 0, y: 0, pointId: made.endId } });
      return "handled";
    }
    if (tool === "circle") {
      if (!draft) {
        setDraft({ tool: "circle", center: spot });
        return "handled";
      }
      if (draft.tool !== "circle") return "handled";
      const made = addCircle(d, draft.center, spot, opts);
      if (made) {
        commit(made.doc);
        setDraft(null);
      }
      return "handled";
    }
    if (tool === "arc") {
      if (!draft) {
        setDraft({ tool: "arc", center: spot });
        return "handled";
      }
      if (draft.tool !== "arc") return "handled";
      if (!draft.start) {
        setDraft({ ...draft, start: spot });
        return "handled";
      }
      const made = addArc(d, draft.center, draft.start, spot, opts);
      if (made) {
        commit(made.doc);
        setDraft(null);
      }
    }
    return "handled";
  };

  const pointerMove = (info: PointerInfo) => {
    const world = info.world;
    if (!world) {
      setHover(null);
      return;
    }
    const tol = 9 / info.scale;
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
    const shortcuts: Record<string, Tool> = { v: "select", p: "point", l: "line", c: "circle", a: "arc", d: "delete" };
    if (shortcuts[k]) chooseTool(shortcuts[k]);
    else if (k === "x") toggleConstruction();
    else if (k === "delete" || k === "backspace") deleteSelection();
    else if (k === "escape") {
      if (box) setBox(null);
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

  const hint =
    tool === "select"
      ? "Click or shift-click to select; drag a point or a line to move it; click inside a loop for the profile, shift-click for a hole."
      : tool === "line"
        ? draft ? "Click the next point; clicking an existing point ends the chain; Esc ends." : "Click the first point."
        : tool === "circle"
          ? draft ? "Click a point on the circle." : "Click the centre."
          : tool === "arc"
            ? draft ? (draft.tool === "arc" && draft.start ? "Click the end (counter-clockwise from start)." : "Click the start point (sets the radius).") : "Click the centre."
            : tool === "delete"
              ? "Click an item to delete it."
              : "Click to place a point.";

  return {
    doc, commit, undo, redo, edits, tool, chooseTool, selection, highlight, setHighlight, draft, cursor, hover, drag, box, setBox, result, error, auto, setAuto, snapOn,
    setSnapOn, construction, choice, pts, loops, applicable, blamed, failing, highlighted, fixedPoints, solved, badge, diagnostics, outer, hint, extents,
    openBox, applyConstraint, submitBox, deleteSelection, toggleConstruction, pointerDown, pointerMove, pointerUp, pointerLeave, key,
  };
}

export type SketchEditor = ReturnType<typeof useSketchEditor>;
