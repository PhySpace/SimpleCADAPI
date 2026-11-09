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
  type SketchOutput,
  type SolveResult,
  type Spot,
  wireProfiles,
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
  convertSplineRequest,
  insertAnchorRequest,
  removeAnchorRequest,
  type Corner,
  type CornerOp,
  type EditRequest,
  type End,
} from "@/lib/sketch-edit";
import { t } from "@/i18n";
import { typedFields, typedTarget, type TypedDims } from "@/lib/sketch-typed";
import { edgeSnap, type Segment } from "@/lib/sketch-face";
import { addPenSpline, anchorAction, anchorRoles, curveAt, handlePoints, isAnchorSpline, mirrorHandle, shownHandles, smoothAnchors, type AnchorAction } from "@/lib/sketch-anchors";

/** How near the pointer (screen pixels) must be to a point or a curve to snap to it or pick it. */
const PICK_PX = 16;
const DRAW_TOOLS = new Set(["point", "line", "circle", "arc", "spline"]);
/** The drawing tools whose click on the curve of a B-spline in anchor form adds an anchor there and uses it (a point on the
 * curve, a line's end on it, a pen path through it). */
const ON_CURVE_TOOLS = new Set(["point", "line", "spline"]);

export type Tool = "select" | "point" | "line" | "circle" | "arc" | "spline" | "delete" | "trim" | "extend" | "fillet" | "chamfer";
/** The corner value box (fillet radius / chamfer distance) open at a corner. */
export type CornerBox = { op: CornerOp; corner: Corner; text: string; bad: boolean };
/** What the last SDK edit (trim, extend) said: its notes, or the error (which names ids). Shown in the status area. */
export type EditNote = { tone: "ok" | "fail"; text: string };
const EDIT_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["trim", "extend", "fillet", "chamfer"]);
/** The spline draft is a pen path: its anchors and, for each, the out-handle a drag pulled out (an offset; null: none). */
export type SplineDraft = { tool: "spline"; points: Spot[]; handles: ([number, number] | null)[] };
export type Draft = { tool: "line"; from: Spot } | { tool: "circle"; center: Spot } | { tool: "arc"; center: Spot; start?: Spot } | SplineDraft | null;
/** A drag of points.  `lead` is the point that snaps (an anchor; its handles follow it).  A dragged handle moves alone (each
 * side of an anchor has its own direction and pull); `mirror` is the opposite handle of its anchor, which turns into line with
 * it, keeping its own length, while Shift is held. */
export type Drag = {
  ids: string[];
  origin: Record<string, [number, number]>;
  start: [number, number];
  positions: Record<string, [number, number]>;
  releasing?: boolean;
  lead?: string;
  mirror?: { other: string; anchor: [number, number]; length: number };
};
export type ValueBox = { kind: ConstraintKind; targets: string[]; constraintId?: string; text: string; bad: boolean };

/** One pointer event in the sketch's terms: its screen position (px, local to the overlay), the plane position under
 * it (null when the ray misses the plane), the pixels per mm there, and the modifier keys. */
export type PointerInfo = { sx: number; sy: number; world: [number, number] | null; scale: number; shift: boolean; alt: boolean };

export type KeyOutcome = "handled" | "leave" | "ignored";

/** The state and the behaviour of the sketch editor, apart from where it is drawn: the document with its undo history,
 * the live solve, loops and the chosen profile, the tools and their drafts, drag with a temporary fix, the value box.
 * The overlay feeds it pointer events already mapped into the plane. */
export function useSketchEditor(initial: SketchDoc, modelPoints: readonly [number, number][] = [], projectFrom: readonly string[] = [], faceEdges: readonly Segment[] = []) {
  const [doc, setDoc] = useState<SketchDoc>(initial);
  const [tool, setTool] = useState<Tool>("select");
  const [selection, setSelection] = useState<string[]>([]);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number; pointId?: string; onSpline?: string; onEdge?: boolean } | null>(null);
  /** Anchor mode (Shift+A with a B-spline picked): a click on a curve adds an anchor, a click on an inner anchor removes it.
   * Holds the spline it was entered with; `anchorHover` is what a click would do where the pointer is. */
  const [anchorMode, setAnchorMode] = useState<string | null>(null);
  const [anchorHover, setAnchorHover] = useState<AnchorAction>(null);
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
  /** The press of the pen tool: the anchor it placed (or the first one, when it closes the path), where it is, and where the
   * press began on screen (a drag from there pulls out the anchor's handles). */
  const pen = useRef<{ index: number; at: [number, number]; sx: number; sy: number; closing: boolean } | null>(null);
  /** The last click of the select tool (a second one at the same place soon after is a double-click). */
  const lastClick = useRef<{ t: number; sx: number; sy: number } | null>(null);
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
    if (drag || !result || docRef.current.output === "wire") return;
    const { profile, inner } = choiceToIndices(choice, loops);
    const d = docRef.current;
    if (d.profile !== profile || d.inner.length !== inner.length || d.inner.some((v, i) => v !== inner[i])) commit({ ...d, profile, inner }, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choice, loopKey, drag, doc.profile, doc.inner, doc.output]);

  // A wire is made of one profile, a closed loop or an open chain, followed across edits by its key like a loop.  Unchosen,
  // it is the first open chain (a path is what a wire is usually for), else the first profile.
  const wires = useMemo(() => wireProfiles(result), [result]);
  const wireList = wires.map((w) => `${w.key}:${w.index}`).join("|");
  const [wireKey, setWireKey] = useState<string | null>(null);
  const wireReady = useRef(false);
  useEffect(() => {
    if (drag || !result || doc.output !== "wire") return;
    let key = wireKey;
    if (!wireReady.current) {
      wireReady.current = true;
      key = wires.find((w) => w.index === docRef.current.profile)?.key ?? null;
    }
    if (!key || !wires.some((w) => w.key === key)) key = (wires.find((w) => !w.closed) ?? wires[0])?.key ?? null;
    if (key !== wireKey) setWireKey(key);
    const index = wires.find((w) => w.key === key)?.index ?? 0;
    const d = docRef.current;
    if (d.profile !== index || d.inner.length) commit({ ...d, profile: index, inner: [] }, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wireList, doc.output, drag, wireKey, doc.profile]);
  const wire = doc.output === "wire" ? (wires.find((w) => w.key === wireKey) ?? null) : null;
  /** Face or wire: what the sketch cell makes (switching back to a face picks the chosen loop again). */
  const setOutput = useCallback((output: SketchOutput) => {
    const d = docRef.current;
    if ((d.output ?? "face") === output) return;
    const { output: _old, ...rest } = d;
    commit(output === "wire" ? { ...rest, output: "wire" } : rest);
  }, [commit]);

  // -- anchors and handles of B-splines in anchor form ---------------------------------------------------------------------
  const roles = useMemo(() => anchorRoles(doc), [doc]);
  /** The handles drawn and picked: those of the anchor-form splines in the selection; the others are hidden. */
  const shown = useMemo(() => shownHandles(doc, selection, roles), [doc, selection, roles]);
  const hidden = useMemo(() => new Set([...handlePoints(roles)].filter((id) => !shown.has(id))), [roles, shown]);

  // -- snapping -----------------------------------------------------------------------------------------------------------------
  /** Where curves of the sketch cross and no point is yet (the SDK's answer for the last solve): shown, and snapped to. */
  const crossings = useMemo(() => (result?.crossings ?? []).map((c) => c.at), [result]);
  const snapTargets = useMemo(() => {
    const all = new Map(pts);
    for (const id of handlePoints(roles)) all.delete(id); // a handle is not a place to draw to
    modelPoints.forEach((p, i) => all.set(`m:${i}`, p));
    crossings.forEach((p, i) => all.set(`x:${i}`, p));
    return all;
  }, [pts, modelPoints, crossings, roles]);

  const spotAt = useCallback(
    (world: [number, number], info: Pick<PointerInfo, "scale" | "alt">, curves = false): Spot => {
      const tol = PICK_PX / info.scale;
      const s = snap(world, snapTargets, { grid: snapOn && !info.alt ? gridStep(info.scale) : null, tol });
      const pointId = s.pointId?.startsWith("m:") || s.pointId?.startsWith("x:") ? undefined : s.pointId;
      if (pointId || !snapOn || info.alt) return { x: s.x, y: s.y, pointId };
      if (!curves) {
        if (s.kind === "point") return { x: s.x, y: s.y };
        const edge = edgeSnap(world, faceEdges, tol);
        return edge ? { x: edge[0], y: edge[1], onEdge: true } : { x: s.x, y: s.y };
      }
      // A point of the sketch wins; then the curve of a spline in anchor form beats the grid (a crossing on it keeps its place).
      if (s.kind === "point") {
        const on = curveAt(docRef.current, resultRef.current, [s.x, s.y], tol / 4);
        return on ? { x: s.x, y: s.y, onSpline: on.spline } : { x: s.x, y: s.y };
      }
      const on = curveAt(docRef.current, resultRef.current, world, tol);
      if (on) return { x: on.at[0], y: on.at[1], onSpline: on.spline };
      const edge = edgeSnap(world, faceEdges, tol); // the edges of the face the sketch is on beat the grid
      return edge ? { x: edge[0], y: edge[1], onEdge: true } : { x: s.x, y: s.y };
    },
    [snapTargets, snapOn, faceEdges],
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
      setEditNote({ tone: "fail", text: t("{{tool}} is not available while a draft is in progress: finish it or press Esc first", { tool: t(next) }) });
      return;
    }
    setEditNote(null);
    setHoverEnd(null);
    setCornerHover(null);
    setPendingLine(null);
    setCornerBox(null);
    setProjectOpen(false);
    setAnchorMode(null);
    setAnchorHover(null);
    setTool(next);
    setDraft(null);
    if (next !== "select") setSelection([]);
  }, []);

  // -- SDK edits (trim, extend) -----------------------------------------------------------------------------------------------
  /** Send one edit to the server (which runs the SDK function) and adopt the document it returns: undoable as one step,
   * re-solved by the live solve, the created entities flashed.  A failure is shown, never swallowed. */
  const runEdit = useCallback(
    async (request: EditRequest, select?: (next: SketchDoc, created: string[]) => string[]) => {
      setEditBusy(true);
      setEditNote(null);
      try {
        const response = await fetchSketchOp(request);
        const { doc: next, flash: created } = applyEdit(response);
        // The server resets the profile and the holes: the chosen loops are carried over to the loops that replace them and
        // the live solve writes the indices back.
        setChoice(remapChoice(loopsRef.current, choiceRef.current, findLoops(next, resultRef.current)));
        commit(next);
        setSelection(select ? select(next, created) : []);
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

  /** Delete items.  The anchor of a spline in anchor form is not deleted with its spline: the SDK removes it and merges the
   * spans beside it (one edit per anchor).  An end anchor or a handle stays, with a word on what to do instead. */
  const deleteItems = useCallback(
    async (ids: readonly string[]) => {
      const now = anchorRoles(docRef.current);
      const anchors = ids.filter((id) => now.get(id)?.kind === "anchor" && !now.get(id)?.end);
      const kept = ids.filter((id) => now.has(id) && !anchors.includes(id));
      const rest = ids.filter((id) => !now.has(id));
      if (rest.length) commit(removeItems(docRef.current, rest));
      setSelection([]);
      setHover(null);
      if (kept.length) {
        const role = now.get(kept[0])!;
        setEditNote({
          tone: "fail",
          text:
            role.kind === "handle"
              ? t("{{point}} is a handle of {{spline}}: a handle is not deleted (drag it, or remove its anchor {{anchor}})", { point: kept[0], spline: role.spline, anchor: role.anchor })
              : t("{{point}} is an end of {{spline}}: an end anchor cannot be removed (trim the spline, or select the curve to delete it)", { point: kept[0], spline: role.spline }),
        });
      }
      for (const id of anchors) {
        const role = anchorRoles(docRef.current).get(id);
        if (role?.kind === "anchor") await runEdit(removeAnchorRequest(docRef.current, role.spline, id), () => [role.spline]);
      }
    },
    [commit, runEdit],
  );
  const deleteSelection = useCallback(() => {
    if (selection.length) void deleteItems(selection);
  }, [selection, deleteItems]);

  /** Insert an anchor on an anchor-form spline where it was clicked (the SDK splits the span; the curve stays): the new anchor
   * is selected, so its handles show. */
  const insertAnchor = useCallback(
    (spline: string, at: [number, number]) =>
      void runEdit(insertAnchorRequest(docRef.current, spline, at), (next, created) => {
        const made = anchorRoles(next);
        const anchor = created.find((id) => made.get(id)?.kind === "anchor");
        return anchor ? [anchor] : [spline];
      }),
    [runEdit],
  );
  /** A drawing click on a spline's curve: the SDK adds an anchor there first, then the click goes on with that point. */
  const placeOnCurve = useCallback(
    async (spot: Spot, then: (spot: Spot) => void) => {
      let anchor: string | undefined;
      await runEdit(insertAnchorRequest(docRef.current, spot.onSpline!, [spot.x, spot.y]), (next, created) => {
        const made = anchorRoles(next);
        anchor = created.find((id) => made.get(id)?.kind === "anchor");
        return [];
      });
      const at = anchor ? docRef.current.points.find((p) => p.id === anchor) : undefined;
      if (at) then({ x: at.x, y: at.y, pointId: at.id });
    },
    [runEdit],
  );

  /** Shift+A: anchor mode on (a B-spline in anchor form, or a point of one, must be picked) or off. */
  const toggleAnchorMode = useCallback(() => {
    if (anchorMode) {
      setAnchorMode(null);
      setAnchorHover(null);
      return;
    }
    const d = docRef.current;
    const picked = selection.map((id) => roles.get(id)?.spline ?? id).find((id) => d.entities.some((e) => e.id === id && e.kind === "bspline"));
    const spline = d.entities.find((e) => e.id === picked);
    if (!spline) {
      setEditNote({ tone: "fail", text: t("anchor mode: pick a B-spline first (click its curve), then Shift+A") });
      return;
    }
    if (!isAnchorSpline(spline)) {
      setEditNote({ tone: "fail", text: t("anchor mode: {{spline}} has control points, not anchors: convert it first (K; the shape stays)", { spline: spline.id }) });
      return;
    }
    setTool("select");
    setDraft(null);
    setEditNote(null);
    setSelection([spline.id]);
    setAnchorMode(spline.id);
  }, [anchorMode, selection, roles]);

  /** The selected B-spline that has control points rather than anchors (the one a convert would change), or null. */
  const convertTarget = useMemo(() => {
    const picked = doc.entities.filter((e) => e.kind === "bspline" && selection.includes(e.id));
    return picked.length === 1 && !isAnchorSpline(picked[0]) ? picked[0].id : null;
  }, [doc.entities, selection]);
  const convertSpline = useCallback((spline: string) => void runEdit(convertSplineRequest(docRef.current, spline), () => [spline]), [runEdit]);
  /** S: the selected anchors become smooth (their two handles turn into one line, each keeping its length). */
  const smoothSelection = useCallback(() => {
    const anchors = selection.filter((id) => roles.get(id)?.kind === "anchor");
    const moved = smoothAnchors(docRef.current, anchors, ptsRef.current, roles);
    if (!Object.keys(moved).length) {
      setEditNote({ tone: "fail", text: t("smooth: select an anchor that has two handles (click a spline drawn with the spline tool, then one of its anchors)") });
      return;
    }
    const d = docRef.current;
    commit({ ...d, points: d.points.map((p) => (moved[p.id] ? { ...p, x: moved[p.id][0], y: moved[p.id][1] } : p)) });
  }, [selection, roles, commit]);

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
      setEditNote({ tone: "fail", text: t("project is not available while a draft is in progress: finish it or press Esc first") });
      return;
    }
    if (projectFrom.length === 0) {
      setEditNote({ tone: "fail", text: t("project: there is no other sketch in this notebook to project from; finish and add another sketch first") });
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
      const path: SplineDraft = draft?.tool === "spline" ? draft : { tool: "spline", points: [], handles: [] };
      const near = (a: Spot) => (a.pointId !== undefined && a.pointId === spot.pointId) || Math.hypot(a.x - spot.x, a.y - spot.y) <= pickTolerance.current;
      if (path.points.length >= 2 && near(path.points[0])) {
        finishSpline(path, true); // back on the first anchor: a closed path (it starts and ends on one point)
        return;
      }
      if (path.points.length >= 2 && near(path.points[path.points.length - 1])) {
        finishSpline(path, false); // the last anchor clicked again (a double click): done
        return;
      }
      setDraft({ tool: "spline", points: [...path.points, spot], handles: [...path.handles, null] });
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
  /** Make the anchor-form B-spline of the pen path (Enter, a second click on the last anchor; `closed`: back on the first). */
  const finishSpline = (path: SplineDraft, closed: boolean): void => {
    setDraft(null);
    const at = (spot: Spot): [number, number] => (spot.pointId ? (ptsRef.current.get(spot.pointId) ?? [spot.x, spot.y]) : [spot.x, spot.y]);
    const made = addPenSpline(docRef.current, path.points.map((spot, i) => ({ spot, handle: path.handles[i] })), closed, { auto, construction }, at);
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
        else setEditNote({ tone: "fail", text: t("extend: {{id}} has no end to extend (a circle is closed); pick a line or an arc", { id: hit.id }) });
      }
      return "handled";
    }
    if (tool === "fillet" || tool === "chamfer") {
      if (editBusy || cornerBox) return "handled";
      const op: CornerOp = tool === "fillet" ? "fillet_corner" : "chamfer_corner";
      const hit = hitTest(d, result, world, tol, hidden);
      if (!hit) return "handled";
      if (hit.kind === "point") {
        const corner = cornerAt(d, hit.id);
        if (corner) openCorner(op, corner);
        else setEditNote({ tone: "fail", text: t("{{tool}}: {{id}} is not a corner (a corner is a point shared by exactly two lines)", { tool: t(tool), id: hit.id }) });
        return "handled";
      }
      const line = d.entities.find((e) => e.id === hit.id);
      if (!line || line.kind !== "line") {
        setEditNote({ tone: "fail", text: t("{{tool}}: {{id}} is not a line; click a corner point or two lines in turn", { tool: t(tool), id: hit.id }) });
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
        setEditNote({ tone: "fail", text: t("{{tool}}: {{a}} and {{b}} do not meet at a corner of exactly two lines", { tool: t(tool), a: pendingLine, b: hit.id }) });
        setPendingLine(hit.id);
      }
      return "handled";
    }
    if (anchorMode && tool === "select") {
      if (editBusy) return "handled";
      const hit = hitTest(d, result, world, tol, hidden);
      const action = anchorAction(d, result, world, tol, hit?.kind === "point" ? hit.id : null, roles);
      if (action?.kind === "add") void runEdit(insertAnchorRequest(d, action.spline, action.at), () => [action.spline]);
      else if (action?.kind === "remove") void runEdit(removeAnchorRequest(d, action.spline, action.anchor), () => [action.spline]);
      else if (action?.kind === "refuse") setEditNote({ tone: "fail", text: action.text });
      setAnchorHover(null);
      return "handled";
    }
    if (tool === "select" || tool === "delete") {
      const hit = hitTest(d, result, world, tol, hidden);
      if (tool === "delete") {
        if (hit) void deleteItems([hit.id]);
        return "handled";
      }
      // A double-click on a B-spline adds an anchor there (a spline with control points says how to get anchors).
      const now = performance.now();
      const before = lastClick.current;
      lastClick.current = { t: now, sx: info.sx, sy: info.sy };
      const spline = hit?.kind === "entity" ? d.entities.find((e) => e.id === hit.id && e.kind === "bspline") : undefined;
      if (spline && before && now - before.t < 400 && Math.hypot(info.sx - before.sx, info.sy - before.sy) < 6) {
        lastClick.current = null;
        if (editBusy) return "handled";
        if (isAnchorSpline(spline)) insertAnchor(spline.id, world);
        else setEditNote({ tone: "fail", text: t("{{spline}} has control points, not anchors: convert it first (K, or the button by the curve; the shape stays)", { spline: spline.id }) });
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
      if (loop && d.output === "wire") {
        setWireKey(loop.key); // a closed loop as the wire
        setSelection([]);
        return "handled";
      }
      if (loop) {
        setChoice((c) => pickLoop(c, loop.key, shiftKey));
        if (!shiftKey) setSelection([]);
        return "handled";
      }
      if (!shiftKey) setSelection([]);
      return "handled";
    }
    if (ON_CURVE_TOOLS.has(tool)) {
      const spot = spotAt(world, info, true);
      const path = draftRef.current?.tool === "spline" ? draftRef.current.points : [];
      const ending = path.length >= 2 && [path[0], path[path.length - 1]].some((a) => Math.hypot(a.x - spot.x, a.y - spot.y) <= tol);
      if (spot.onSpline && !ending) {
        if (!editBusy) void placeOnCurve(spot, (made) => place(made));
        return "handled";
      }
    }
    if (tool === "spline") {
      // The pen: a press places an anchor (or finishes / closes the path, as a click does); a drag from it pulls out handles.
      const spot = spotAt(world, info);
      const current = draftRef.current;
      const path: SplineDraft = current?.tool === "spline" ? current : { tool: "spline", points: [], handles: [] };
      const near = (a: Spot) => (a.pointId !== undefined && a.pointId === spot.pointId) || Math.hypot(a.x - spot.x, a.y - spot.y) <= tol;
      const at = (a: Spot): [number, number] => (a.pointId ? (pts.get(a.pointId) ?? [a.x, a.y]) : [a.x, a.y]);
      if (path.points.length >= 2 && near(path.points[0])) {
        pen.current = { index: 0, at: at(path.points[0]), sx: info.sx, sy: info.sy, closing: true };
        return "press";
      }
      if (path.points.length >= 2 && near(path.points[path.points.length - 1])) {
        finishSpline(path, false);
        return "handled";
      }
      const next: SplineDraft = { tool: "spline", points: [...path.points, spot], handles: [...path.handles, null] };
      draftRef.current = next; // a drag may move before the next render
      setDraft(next);
      pen.current = { index: path.points.length, at: at(spot), sx: info.sx, sy: info.sy, closing: false };
      return "press";
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
        let ids = dragPoints(d, p.hit.id);
        const role = p.hit.kind === "point" ? roles.get(p.hit.id) : undefined;
        let lead: string | undefined;
        let mirror: Drag["mirror"];
        if (role?.kind === "anchor") {
          // an anchor carries its handles (a fixed handle stays)
          ids = [p.hit.id, ...role.handles.filter((h) => !isFixed(d, h))];
          lead = p.hit.id;
        } else if (role?.kind === "handle" && role.other && !isFixed(d, role.other)) {
          // the opposite handle of the anchor, which Shift turns into line with this one
          const a = pts.get(role.anchor);
          const o = pts.get(role.other);
          if (a && o) mirror = { other: role.other, anchor: a, length: Math.hypot(o[0] - a[0], o[1] - a[1]) };
        }
        if (ids.length && !ids.some((id) => isFixed(d, id))) {
          const origin: Record<string, [number, number]> = {};
          for (const id of ids) origin[id] = pts.get(id) ?? [0, 0];
          setDrag({ ids, origin, start: p.world, positions: origin, lead, mirror });
        }
      }
    }
    if (drag && !drag.releasing) {
      const positions: Record<string, [number, number]> = {};
      if (drag.ids.length === 1 || drag.lead) {
        // the lead point snaps; the points it carries move by as much
        const lead = drag.lead ?? drag.ids[0];
        const s = snap(world, snapTargets, { grid: snapOn && !info.alt ? gridStep(info.scale) : null, tol: snapOn ? tol : 0, skip: new Set(drag.ids) });
        const edge = s.kind !== "point" && snapOn && !info.alt ? edgeSnap(world, faceEdges, tol) : null;
        positions[lead] = edge ?? [s.x, s.y];
        const dx = s.x - drag.origin[lead][0];
        const dy = s.y - drag.origin[lead][1];
        for (const id of drag.ids) if (id !== lead) positions[id] = [drag.origin[id][0] + dx, drag.origin[id][1] + dy];
        // Shift while dragging a handle makes the anchor smooth: the opposite handle turns into line, keeping its own length
        const turned = drag.mirror && info.shift ? mirrorHandle(drag.mirror.anchor, positions[lead], drag.mirror.length) : null;
        if (drag.mirror && turned) positions[drag.mirror.other] = turned;
      } else {
        const dx = world[0] - drag.start[0];
        const dy = world[1] - drag.start[1];
        for (const id of drag.ids) positions[id] = [drag.origin[id][0] + dx, drag.origin[id][1] + dy];
      }
      setDrag({ ...drag, positions });
      return;
    }
    const path = draftRef.current;
    if (pen.current && path?.tool === "spline") {
      // pulling out the handles of the anchor just placed (or of the first anchor, when the press closes the path)
      const p = pen.current;
      if (Math.hypot(info.sx - p.sx, info.sy - p.sy) > 4) {
        const handles = [...path.handles];
        handles[p.index] = [world[0] - p.at[0], world[1] - p.at[1]];
        const next: SplineDraft = { ...path, handles };
        draftRef.current = next;
        setDraft(next);
      }
    }
    if (tool === "select" && anchorMode) {
      const hit = hitTest(docRef.current, result, world, tol, hidden);
      setAnchorHover(anchorAction(docRef.current, result, world, tol, hit?.kind === "point" ? hit.id : null, roles));
      setHover(null);
      setCursor({ x: world[0], y: world[1] });
    } else if (tool === "select") {
      setHover(hitTest(docRef.current, result, world, tol, hidden));
      setCursor({ x: world[0], y: world[1] });
    } else if (tool === "fillet" || tool === "chamfer") {
      const hit = cornerBox ? null : hitTest(docRef.current, result, world, tol, hidden);
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
      const s = spotAt(world, info, ON_CURVE_TOOLS.has(tool));
      setCursor({ x: s.x, y: s.y, pointId: s.pointId, onSpline: s.onSpline, onEdge: s.onEdge });
    }
  };

  const pointerUp = async () => {
    const p = press.current;
    press.current = null;
    const penPress = pen.current;
    pen.current = null;
    if (penPress?.closing && draftRef.current?.tool === "spline") {
      finishSpline(draftRef.current, true);
      return;
    }
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
      if (draft.points.length >= 2) finishSpline(draft, false);
      return "handled";
    }
    if (k === "a" && event.shiftKey) toggleAnchorMode(); // before A (arc): Shift+A is anchor mode
    else if (anchorMode && (k === "delete" || k === "backspace")) return "handled"; // a click removes in anchor mode
    else if (k === "s" && tool === "select") smoothSelection();
    else if (k === "k" && tool === "select") {
      if (convertTarget) convertSpline(convertTarget);
      else setEditNote({ tone: "fail", text: t("convert: select one B-spline that has control points (a spline drawn with the spline tool already has anchors)") });
    } else if (shortcuts[k]) chooseTool(shortcuts[k]);
    else if (k === "j") openProject();
    else if (k === "x") toggleConstruction();
    else if (k === "delete" || k === "backspace") deleteSelection();
    else if (k === "escape") {
      if (entry) setEntry(null);
      else if (box) setBox(null);
      else if (cornerBox) setCornerBox(null);
      else if (projectOpen) setProjectOpen(false);
      else if (pendingLine) setPendingLine(null);
      else if (anchorMode) {
        setAnchorMode(null);
        setAnchorHover(null);
      } else if (draft) setDraft(null);
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

  const typed = DRAW_TOOLS.has(tool) ? ` ${t("Or type numbers (Tab between fields, Enter places).")}` : "";
  const hint =
    (tool === "select" && anchorMode
      ? t("ANCHOR MODE: click a spline's curve to add an anchor (the curve stays), click an inner anchor to remove it. Esc or Shift+A leaves.")
      : tool === "select"
      ? shown.size
        ? t("Drag an anchor (its handles follow) or a handle: each side has its own direction and pull. Hold Shift while dragging a handle to put the other one in line (smooth); S smooths the selected anchors. Shift+A: anchor mode (add/remove anchors by clicking); Delete removes the selected anchor.")
        : convertTarget
          ? t("{{spline}} has control points, not anchors: K (or the button by the curve) converts it, keeping its shape.", { spline: convertTarget })
          : t("Click or shift-click to select; drag a point or a line to move it; click inside a loop for the profile, shift-click for a hole. Click a spline to show its handles.")
      : tool === "line"
        ? draft ? t("Click the next point; clicking an existing point ends the chain (a click on a spline's curve adds an anchor there and ends on it); Esc ends.") : t("Click the first point (on a spline's curve: an anchor is added there).")
        : tool === "circle"
          ? draft ? t("Click a point on the circle.") : t("Click the centre.")
          : tool === "spline"
            ? draft
              ? t("Click the next anchor; press and drag to pull out its handles; a click on another spline's curve adds an anchor there and goes through it. Finish: Enter, the last anchor again (double-click) or the button; the first anchor closes it. Esc drops it.")
              : t("Click the first anchor; press and drag to pull out its handles (a click alone makes a smooth curve through the anchors). A click on a spline's curve adds an anchor there and starts from it.")
          : tool === "arc"
            ? draft ? (draft.tool === "arc" && draft.start ? t("Click the end (counter-clockwise from start).") : t("Click the start point (sets the radius).")) : t("Click the centre.")
            : tool === "delete"
              ? t("Click an item to delete it.")
              : tool === "fillet" || tool === "chamfer"
                ? pendingLine
                  ? t("Click the second line of the corner ({{line}} is picked).", { line: pendingLine })
                  : tool === "fillet" ? t("Click a corner (a point shared by two lines) or two lines in turn, then type the radius: Enter commits, Esc cancels.") : t("Click a corner (a point shared by two lines) or two lines in turn, then type the distance: Enter commits, Esc cancels.")
              : tool === "trim"
                ? t("Click the part of a line, arc or circle to cut away; the SDK decides the piece between its neighbours.")
                : tool === "extend"
                  ? t("Click a line near the end to extend; it grows to the next entity.")
                  : t("Click to place a point; on a spline's curve the point is a new anchor of the spline.")) + typed;

  return {
    cornerHover, pendingLine, cornerBox, setCornerBox, submitCorner, projectOpen, setProjectOpen, openProject, projectSketch, projectFrom,
    doc, commit, undo, redo, edits, editNote, editBusy, flash, hoverEnd, runEdit, tool, chooseTool, selection, highlight, setHighlight, draft, cursor, hover, drag, box, setBox, result, error, auto, setAuto, snapOn,
    setSnapOn, construction, choice, pts, loops, applicable, blamed, fresh, crossings, finishSplineDraft: () => draft?.tool === "spline" && draft.points.length >= 2 && finishSpline(draft, false), entry,
    wires, wire, setWireKey, setOutput, faceEdges,
    anchorMode, anchorHover, toggleAnchorMode,
    roles, shown, hidden, convertTarget, convertSpline, insertAnchor, smoothSelection, pressingPen: () => pen.current !== null, setEntry, entryFields, submitEntry, failing, highlighted, fixedPoints, solved, badge, diagnostics, outer, hint, extents,
    openBox, applyConstraint, submitBox, deleteSelection, toggleConstruction, pointerDown, pointerMove, pointerUp, pointerLeave, key,
  };
}

export type SketchEditor = ReturnType<typeof useSketchEditor>;
