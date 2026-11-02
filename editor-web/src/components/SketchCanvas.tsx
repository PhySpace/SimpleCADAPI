import { Construction, Crosshair, Circle, Magnet, Maximize, MousePointer2, Slash, Spline, Trash2, Undo2, WandSparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Switch } from "@/components/ui/switch";
import {
  CONSTRAINT_INFO,
  PLANES,
  addArc,
  addCircle,
  addConstraint,
  addLine,
  applicableConstraints,
  applySolved,
  arcSweep,
  blamedConstraints,
  choiceToIndices,
  circleRadius,
  constraintAnchor,
  constraintTargets,
  dimensionValue,
  dragDoc,
  dragPoints,
  ensurePoint,
  entityMap,
  findLoops,
  fitView,
  formatValue,
  gridStep,
  hitTest,
  isDimensional,
  isFixed,
  LatestSolver,
  loopAt,
  measure,
  parseDimension,
  pickLoop,
  reconcileChoice,
  choiceFromDoc,
  removeConstraint,
  removeItems,
  screenToWorld,
  seedDelta,
  setConstruction,
  snap,
  solvedPoints,
  statusBadge,
  worldToScreen,
  writable,
  zoomAt,
  fetchSolve,
  type Choice,
  type ConstraintKind,
  type Hit,
  type SConstraint,
  type SketchDoc,
  type SolveResult,
  type Spot,
  type View,
  type Plane,
} from "@/lib/sketch";
import { cn } from "@/lib/utils";

type Tool = "select" | "point" | "line" | "circle" | "arc" | "delete";
type Draft = { tool: "line"; from: Spot } | { tool: "circle"; center: Spot } | { tool: "arc"; center: Spot; start?: Spot } | null;
type Drag = { ids: string[]; origin: Record<string, [number, number]>; start: [number, number]; positions: Record<string, [number, number]>; releasing?: boolean };
type ValueBox = { kind: ConstraintKind; targets: string[]; constraintId?: string; text: string; bad: boolean };

export type SketchReport = { status: SolveResult["status"] | null; loops: number; outerReady: boolean; error: string | null };

const INK = "var(--foreground)";
const MUTED = "var(--muted-foreground)";
const PASS = "var(--pass)";
const FAIL = "var(--fail)";
const FOCUS = "var(--focus)";
const NAME = "var(--name)";

const TOOLS: { id: Tool; label: string; key: string; icon: typeof Slash }[] = [
  { id: "select", label: "Select / move", key: "V", icon: MousePointer2 },
  { id: "point", label: "Point", key: "P", icon: Crosshair },
  { id: "line", label: "Line (chained; Esc ends)", key: "L", icon: Slash },
  { id: "circle", label: "Circle: centre, then radius", key: "C", icon: Circle },
  { id: "arc", label: "Arc: centre, start, end (counter-clockwise)", key: "A", icon: Spline },
  { id: "delete", label: "Delete", key: "D", icon: Trash2 },
];

const SHORT: Record<ConstraintKind, string> = {
  fix: "fix", coincident: "coinc", point_on: "on", horizontal: "horiz", vertical: "vert", points_horizontal: "align h", points_vertical: "align v",
  parallel: "para", perpendicular: "perp", collinear: "colin", tangent: "tang", concentric: "conc", midpoint: "mid", symmetric: "sym",
  equal_length: "= len", equal_radius: "= rad", length: "length", distance: "dist", distance_x: "dist x", distance_y: "dist y",
  line_distance: "line dist", angle: "angle", radius: "radius", diameter: "diam",
};
const TOOLBAR_KINDS = Object.keys(SHORT) as ConstraintKind[];
const TOOLBAR_ORDER: ConstraintKind[] = [
  "horizontal", "vertical", "points_horizontal", "points_vertical", "coincident", "point_on", "midpoint", "parallel", "perpendicular", "collinear", "tangent",
  "concentric", "equal_length", "equal_radius", "symmetric", "fix", "length", "distance", "distance_x", "distance_y", "line_distance", "angle", "radius", "diameter",
].filter((k) => TOOLBAR_KINDS.includes(k as ConstraintKind)) as ConstraintKind[];

/** The 2D constrained-sketch editor: draws with snapping, solves live through /api/sketch/solve, shows constraints,
 * dimensions and the solver's verdict, and picks the profile (outer loop and holes) of the sketch. */
export function SketchCanvas({ doc, onDoc, onReport }: { doc: SketchDoc; onDoc: (doc: SketchDoc) => void; onReport?: (report: SketchReport) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 640, h: 480 });
  const [view, setView] = useState<View>({ scale: 8, ox: 320, oy: 240 });
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
  const [panning, setPanning] = useState(false);

  const docRef = useRef(doc);
  docRef.current = doc;
  const history = useRef<SketchDoc[]>([]);
  const future = useRef<SketchDoc[]>([]);
  const space = useRef(false);
  const press = useRef<{ hit: Hit; sx: number; sy: number; world: [number, number]; shift: boolean; wasSelected: boolean } | null>(null);
  const panRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const fitted = useRef(false);
  const choiceReady = useRef(doc.points.length === 0);

  // -- document changes (history) --------------------------------------------------------------------------------------
  const commit = useCallback(
    (next: SketchDoc, record = true) => {
      if (record) {
        history.current = [...history.current.slice(-80), docRef.current];
        future.current = [];
      }
      docRef.current = next;
      onDoc(next);
    },
    [onDoc],
  );
  const undo = useCallback(() => {
    const previous = history.current.pop();
    if (!previous) return;
    future.current.push(docRef.current);
    docRef.current = previous;
    onDoc(previous);
    setSelection([]);
    setDraft(null);
  }, [onDoc]);
  const redo = useCallback(() => {
    const next = future.current.pop();
    if (!next) return;
    history.current.push(docRef.current);
    docRef.current = next;
    onDoc(next);
  }, [onDoc]);

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

  useEffect(() => {
    const outer = loops.find((l) => l.key === choice.outer);
    onReport?.({ status: result?.status ?? null, loops: loops.length, outerReady: Boolean(outer && outer.index !== null), error });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.status, loopKey, choice.outer, error]);

  // -- size, fit, wheel ---------------------------------------------------------------------------------------------------
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setSize({ w: Math.max(el.clientWidth, 200), h: Math.max(el.clientHeight, 200) }));
    observer.observe(el);
    setSize({ w: Math.max(el.clientWidth, 200), h: Math.max(el.clientHeight, 200) });
    el.focus({ preventScroll: true });
    return () => observer.disconnect();
  }, []);
  const fit = useCallback(() => {
    const list = [...pts.values()];
    for (const e of docRef.current.entities)
      if (e.kind !== "line") {
        const c = pts.get(e.center ?? "");
        if (c) {
          const r = circleRadius(docRef.current, e, pts, result);
          list.push([c[0] - r, c[1] - r], [c[0] + r, c[1] + r]);
        }
      }
    setView(fitView(list, size.w, size.h));
  }, [pts, result, size]);
  useEffect(() => {
    if (fitted.current || !result) return;
    fitted.current = true;
    if (doc.points.length) fit();
    else setView({ scale: 8, ox: size.w / 2, oy: size.h / 2 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      setView((v) => zoomAt(v, event.clientX - rect.left, event.clientY - rect.top, Math.exp(-event.deltaY * 0.0015)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // -- helpers --------------------------------------------------------------------------------------------------------------
  const grid = gridStep(view.scale);
  const tolWorld = 9 / view.scale;
  const local = (event: { clientX: number; clientY: number }): [number, number] => {
    const rect = svg.current!.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };
  const spotAt = useCallback(
    (world: [number, number], shift = false): Spot => {
      const s = snap(world, pts, { grid: snapOn && !shift ? grid : null, tol: tolWorld });
      return { x: s.x, y: s.y, pointId: s.pointId };
    },
    [pts, snapOn, grid, tolWorld],
  );

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

  const submitBox = () => {
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
  };

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

  const chooseTool = (next: Tool) => {
    setTool(next);
    setDraft(null);
    if (next !== "select") setSelection([]);
  };

  // -- pointer ------------------------------------------------------------------------------------------------------------------
  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    wrap.current?.focus({ preventScroll: true });
    const [sx, sy] = local(event);
    const target = event.target as Element;
    const labelOf = target.closest("[data-cid]")?.getAttribute("data-cid");
    if (event.button === 1 || (event.button === 0 && space.current)) {
      event.preventDefault();
      panRef.current = { sx, sy, ox: view.ox, oy: view.oy };
      setPanning(true);
      svg.current?.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== 0) return;
    if (labelOf) {
      setHighlight((h) => (h === labelOf ? null : labelOf));
      return;
    }
    const world = screenToWorld(view, sx, sy);
    const d = docRef.current;
    const opts = { auto, construction };
    if (tool === "select" || tool === "delete") {
      const hit = hitTest(d, result, world, tolWorld);
      if (tool === "delete") {
        if (hit) {
          commit(removeItems(d, [hit.id]));
          setHover(null);
        }
        return;
      }
      if (hit) {
        const wasSelected = selection.includes(hit.id);
        if (event.shiftKey) setSelection((s) => (s.includes(hit.id) ? s.filter((id) => id !== hit.id) : [...s, hit.id]));
        else if (!wasSelected) setSelection([hit.id]);
        press.current = { hit, sx, sy, world, shift: event.shiftKey, wasSelected };
        svg.current?.setPointerCapture(event.pointerId);
        return;
      }
      const loop = loopAt(loops, world);
      if (loop) {
        setChoice((c) => pickLoop(c, loop.key, event.shiftKey));
        if (!event.shiftKey) setSelection([]);
        return;
      }
      if (!event.shiftKey) setSelection([]);
      return;
    }
    const spot = spotAt(world, event.altKey);
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
      commit(made.doc);
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
        commit(made.doc);
        setDraft(null);
      }
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
        return;
      }
      const made = addArc(d, draft.center, draft.start, spot, opts);
      if (made) {
        commit(made.doc);
        setDraft(null);
      }
    }
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const [sx, sy] = local(event);
    if (panRef.current) {
      const p = panRef.current;
      setView((v) => ({ ...v, ox: p.ox + sx - p.sx, oy: p.oy + sy - p.sy }));
      return;
    }
    const world = screenToWorld(view, sx, sy);
    if (press.current && !drag) {
      const p = press.current;
      if (Math.hypot(sx - p.sx, sy - p.sy) > 4 && !p.shift) {
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
      const single = drag.ids.length === 1;
      const positions: Record<string, [number, number]> = {};
      if (single) {
        const s = snap(world, pts, { grid: snapOn && !event.altKey ? grid : null, tol: 0, skip: new Set(drag.ids) });
        positions[drag.ids[0]] = [s.x, s.y];
      } else {
        const dx = world[0] - drag.start[0];
        const dy = world[1] - drag.start[1];
        for (const id of drag.ids) positions[id] = [drag.origin[id][0] + dx, drag.origin[id][1] + dy];
      }
      setDrag({ ...drag, positions });
      return;
    }
    if (tool === "select") setHover(hitTest(docRef.current, result, world, tolWorld));
    else {
      const s = spotAt(world, event.altKey);
      setCursor({ x: s.x, y: s.y, pointId: s.pointId });
    }
    if (tool === "select") setCursor({ x: world[0], y: world[1] });
  };

  const onPointerUp = async (event: React.PointerEvent<SVGSVGElement>) => {
    if (panRef.current) {
      panRef.current = null;
      setPanning(false);
      return;
    }
    const p = press.current;
    press.current = null;
    if (svg.current?.hasPointerCapture(event.pointerId)) svg.current.releasePointerCapture(event.pointerId);
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

  // -- keyboard ----------------------------------------------------------------------------------------------------------------
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const tag = (event.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const key = event.key.toLowerCase();
    if (event.metaKey || event.ctrlKey) {
      if (key === "z") {
        event.preventDefault();
        event.stopPropagation();
        if (event.shiftKey) redo();
        else undo();
      }
      return;
    }
    if (key === " ") {
      space.current = true;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const shortcuts: Record<string, Tool> = { v: "select", p: "point", l: "line", c: "circle", a: "arc", d: "delete" };
    if (shortcuts[key]) {
      chooseTool(shortcuts[key]);
    } else if (key === "x") toggleConstruction();
    else if (key === "f") fit();
    else if (key === "delete" || key === "backspace") deleteSelection();
    else if (key === "escape") {
      if (box) setBox(null);
      else if (draft) setDraft(null);
      else if (tool !== "select") setTool("select");
      else setSelection([]);
    } else return;
    event.preventDefault();
    event.stopPropagation();
  };
  const onKeyUp = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === " ") space.current = false;
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

  const strokeOf = (id: string, construct?: boolean) => {
    if (failing.has(id)) return FAIL;
    if (highlighted.has(id)) return NAME;
    if (selection.includes(id)) return FOCUS;
    if (hover?.id === id) return FOCUS;
    if (construct) return MUTED;
    return solved ? PASS : INK;
  };
  const w2s = (x: number, y: number) => worldToScreen(view, x, y);

  const gridPaths = useMemo(() => {
    const [x0, y1] = screenToWorld(view, 0, size.h);
    const [x1, y0] = screenToWorld(view, size.w, 0);
    const lines: string[] = [];
    const major: string[] = [];
    for (let x = Math.ceil(x0 / grid) * grid; x <= x1; x += grid) {
      const sx = view.ox + x * view.scale;
      (Math.abs(Math.round(x / grid)) % 5 === 0 ? major : lines).push(`M${sx} 0V${size.h}`);
    }
    for (let y = Math.ceil(y1 / grid) * grid; y <= y0; y += grid) {
      const sy = view.oy - y * view.scale;
      (Math.abs(Math.round(y / grid)) % 5 === 0 ? major : lines).push(`M0 ${sy}H${size.w}`);
    }
    return { minor: lines.join(""), major: major.join("") };
  }, [view, size, grid]);

  const stacks = new Map<string, number>();
  const labelNodes = doc.constraints.map((c) => {
    const anchor = constraintAnchor(c, doc, result);
    if (!anchor) return null;
    const [ax, ay] = w2s(anchor.x, anchor.y);
    const key = `${Math.round(ax / 12)}:${Math.round(ay / 12)}`;
    const n = stacks.get(key) ?? 0;
    stacks.set(key, n + 1);
    const sx = ax + anchor.nx * anchor.offset + anchor.ny * 13 * n;
    const sy = ay - anchor.ny * anchor.offset + anchor.nx * 13 * n;
    const dimensional = isDimensional(c.kind);
    const isBlamed = blamed.has(c.id);
    const color = isBlamed ? FAIL : highlight === c.id ? NAME : dimensional ? (c.driving === false ? MUTED : NAME) : MUTED;
    const text = dimensional
      ? `${CONSTRAINT_INFO[c.kind].glyph && (c.kind === "radius" || c.kind === "diameter") ? CONSTRAINT_INFO[c.kind].glyph : ""}${formatValue(dimensionValue(c, doc, result), c.kind)}`
      : CONSTRAINT_INFO[c.kind].glyph;
    if (!text || c.kind === "coincident") return null;
    const label = c.driving === false ? `(${text})` : text;
    return (
      <text
        key={c.id}
        data-cid={c.id}
        x={sx}
        y={sy}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={dimensional ? 11 : 10}
        fontWeight={dimensional ? 700 : 600}
        fill={color}
        stroke="var(--background)"
        strokeWidth={3}
        paintOrder="stroke"
        style={{ cursor: "pointer", fontFamily: "var(--mono)" }}
        onDoubleClick={() => dimensional && openBox(c.kind, c.targets, c)}
      >
        {label}
      </text>
    );
  });

  const arcPath = (e: { start?: string; end?: string; center?: string }, projectEnd = false) => {
    const c = pts.get(e.center ?? "");
    const s = pts.get(e.start ?? "");
    const en = pts.get(e.end ?? "");
    if (!c || !s || !en) return "";
    const r = Math.hypot(s[0] - c[0], s[1] - c[1]);
    const sweep = arcSweep(c, s, en);
    const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
    const endPt: [number, number] = projectEnd ? [c[0] + r * Math.cos(a0 + sweep), c[1] + r * Math.sin(a0 + sweep)] : en;
    const [x0, y0] = w2s(s[0], s[1]);
    const [x1, y1] = w2s(endPt[0], endPt[1]);
    return `M${x0} ${y0}A${r * view.scale} ${r * view.scale} 0 ${sweep > Math.PI ? 1 : 0} 0 ${x1} ${y1}`;
  };

  const preview = () => {
    if (!draft || !cursor) return null;
    const dash = "5 4";
    if (draft.tool === "line") {
      const from = draft.from.pointId ? (pts.get(draft.from.pointId) ?? [draft.from.x, draft.from.y]) : [draft.from.x, draft.from.y];
      const [x0, y0] = w2s(from[0], from[1]);
      const [x1, y1] = w2s(cursor.x, cursor.y);
      return <path d={`M${x0} ${y0}L${x1} ${y1}`} stroke={FOCUS} strokeWidth={1.5} strokeDasharray={dash} fill="none" />;
    }
    const centre = draft.center.pointId ? (pts.get(draft.center.pointId) ?? [draft.center.x, draft.center.y]) : [draft.center.x, draft.center.y];
    const [cx, cy] = w2s(centre[0], centre[1]);
    if (draft.tool === "circle") {
      const r = Math.hypot(cursor.x - centre[0], cursor.y - centre[1]) * view.scale;
      return (
        <g stroke={FOCUS} strokeWidth={1.5} strokeDasharray={dash} fill="none">
          <circle cx={cx} cy={cy} r={r} />
          <path d={`M${cx} ${cy}L${w2s(cursor.x, cursor.y).join(" ")}`} />
        </g>
      );
    }
    if (!draft.start) return <path d={`M${cx} ${cy}L${w2s(cursor.x, cursor.y).join(" ")}`} stroke={FOCUS} strokeWidth={1.5} strokeDasharray={dash} fill="none" />;
    const start = draft.start.pointId ? (pts.get(draft.start.pointId) ?? [draft.start.x, draft.start.y]) : [draft.start.x, draft.start.y];
    const fake = new Map<string, [number, number]>([
      ["c", [centre[0], centre[1]]],
      ["s", [start[0], start[1]]],
      ["e", [cursor.x, cursor.y]],
    ]);
    const c = fake.get("c")!;
    const s = fake.get("s")!;
    const sweep = arcSweep(c, s, [cursor.x, cursor.y]);
    const r = Math.hypot(s[0] - c[0], s[1] - c[1]);
    const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
    const endPt: [number, number] = [c[0] + r * Math.cos(a0 + sweep), c[1] + r * Math.sin(a0 + sweep)];
    const [x0, y0] = w2s(s[0], s[1]);
    const [x1, y1] = w2s(endPt[0], endPt[1]);
    return (
      <g stroke={FOCUS} strokeWidth={1.5} strokeDasharray={dash} fill="none">
        <path d={`M${x0} ${y0}A${r * view.scale} ${r * view.scale} 0 ${sweep > Math.PI ? 1 : 0} 0 ${x1} ${y1}`} />
        <path d={`M${cx} ${cy}L${x0} ${y0}M${cx} ${cy}L${x1} ${y1}`} opacity={0.5} />
      </g>
    );
  };

  const boxAnchor = box
    ? (() => {
        const a = constraintAnchor({ id: "tmp_box", kind: box.kind, targets: box.targets }, doc, result);
        const [x, y] = a ? w2s(a.x, a.y) : [size.w / 2, 40];
        return { x: Math.min(Math.max(x + (a ? a.nx * a.offset * 1.5 : 0), 60), size.w - 90), y: Math.min(Math.max(y - (a ? a.ny * a.offset * 1.5 : 0), 24), size.h - 24) };
      })()
    : null;

  const coordText = cursor ? `x ${cursor.x.toFixed(2)}  y ${cursor.y.toFixed(2)} mm` : "";
  const hint =
    tool === "select"
      ? "Click or shift-click to select; drag a point or a line to move it; click inside a loop to make it the profile, shift-click for a hole."
      : tool === "line"
        ? draft ? "Click the next point; clicking an existing point ends the chain; Esc ends." : "Click the first point."
        : tool === "circle"
          ? draft ? "Click a point on the circle." : "Click the centre."
          : tool === "arc"
            ? draft ? (draft.tool === "arc" && draft.start ? "Click the end (counter-clockwise from start)." : "Click the start point (sets the radius).") : "Click the centre."
            : tool === "delete"
              ? "Click an item to delete it."
              : "Click to place a point.";

  const setPlane = (plane: Plane) => commit({ ...doc, plane });

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b-2 border-border px-2 py-1.5">
        <div className="flex items-center gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">plane</span>
          {PLANES.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={doc.plane === p}
              onClick={() => setPlane(p)}
              className={cn("h-6 border-2 px-2 text-[11px] font-semibold", doc.plane === p ? "border-primary bg-primary text-primary-foreground" : "border-input hover:border-primary")}
            >
              {p}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          require fully constrained
          <Switch checked={doc.fully_constrained} onCheckedChange={(v) => commit({ ...doc, fully_constrained: v })} aria-label="Require fully constrained" />
        </label>
        <span
          data-testid="sketch-status"
          className={cn(
            "border-2 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em]",
            badge.tone === "pass" && "border-pass text-pass",
            badge.tone === "fail" && "border-fail text-fail",
            badge.tone === "focus" && "border-focus text-focus",
            badge.tone === "muted" && "border-input text-muted-foreground",
          )}
        >
          {badge.label}
        </span>
        {doc.fully_constrained && !solved && result && <span className="text-[10px] uppercase tracking-[0.08em] text-fail">needs dof 0 to add</span>}
        <span className="ml-auto text-[10px] text-muted-foreground">{coordText}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1 border-b-2 border-border px-2 py-1.5" aria-label="Constraints">
        {TOOLBAR_ORDER.map((kind) => (
          <button
            key={kind}
            type="button"
            disabled={!applicable.has(kind)}
            title={`${CONSTRAINT_INFO[kind].label}${isDimensional(kind) ? " (opens a value box)" : ""}`}
            onClick={() => applyConstraint(kind)}
            className={cn(
              "h-6 border-2 px-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] transition-colors",
              applicable.has(kind) ? "border-primary hover:border-focus hover:bg-focus hover:text-primary-foreground" : "border-border text-muted-foreground opacity-40",
              isDimensional(kind) && applicable.has(kind) && "border-name text-name",
            )}
          >
            {SHORT[kind]}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1">
        <div
          ref={wrap}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onKeyUp={onKeyUp}
          data-testid="sketch-canvas"
          className="relative min-w-0 flex-1 overflow-hidden bg-background outline-none focus-visible:outline-none"
        >
          <svg
            ref={svg}
            width={size.w}
            height={size.h}
            className="block touch-none select-none"
            style={{ cursor: panning ? "grabbing" : tool === "select" ? (hover ? "pointer" : "default") : "crosshair" }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={(e) => void onPointerUp(e)}
            onPointerLeave={() => {
              setHover(null);
              if (!draft) setCursor(null);
            }}
            onContextMenu={(e) => e.preventDefault()}
          >
            <path d={gridPaths.minor} stroke="var(--border)" strokeWidth={0.5} opacity={0.6} fill="none" />
            <path d={gridPaths.major} stroke="var(--border)" strokeWidth={1} fill="none" />
            <path d={`M0 ${view.oy}H${size.w}`} stroke={NAME} strokeWidth={1} opacity={0.6} />
            <path d={`M${view.ox} 0V${size.h}`} stroke={NAME} strokeWidth={1} opacity={0.6} />
            {loops.map((loop) => {
              const isOuter = loop.key === choice.outer;
              const isInner = choice.inner.includes(loop.key);
              return (
                <path
                  key={loop.key}
                  d={`${loop.polygon.map((p, i) => `${i ? "L" : "M"}${w2s(p[0], p[1]).join(" ")}`).join("")}Z`}
                  fill={isOuter ? FOCUS : isInner ? NAME : MUTED}
                  fillOpacity={isOuter ? 0.2 : isInner ? 0.3 : 0.07}
                  stroke="none"
                  data-loop={loop.key}
                  data-role={isOuter ? "outer" : isInner ? "hole" : "loop"}
                  pointerEvents="none"
                />
              );
            })}
            {doc.entities.map((e) => {
              const color = strokeOf(e.id, e.construction);
              const width = selection.includes(e.id) || hover?.id === e.id ? 2.6 : 1.8;
              const common = { stroke: color, strokeWidth: width, fill: "none", strokeDasharray: e.construction ? "6 4" : undefined, strokeLinecap: "round" as const };
              if (e.kind === "line") {
                const a = pts.get(e.start ?? "");
                const b = pts.get(e.end ?? "");
                if (!a || !b) return null;
                return <path key={e.id} d={`M${w2s(a[0], a[1]).join(" ")}L${w2s(b[0], b[1]).join(" ")}`} {...common} />;
              }
              if (e.kind === "circle") {
                const c = pts.get(e.center ?? "");
                if (!c) return null;
                const [cx, cy] = w2s(c[0], c[1]);
                return <circle key={e.id} cx={cx} cy={cy} r={circleRadius(doc, e, pts, result) * view.scale} {...common} />;
              }
              return <path key={e.id} d={arcPath(e, true)} {...common} />;
            })}
            {doc.points.map((p) => {
              const at = pts.get(p.id) ?? [p.x, p.y];
              const [sx, sy] = w2s(at[0], at[1]);
              const fixed = fixedPoints.has(p.id);
              const color = failing.has(p.id) ? FAIL : highlighted.has(p.id) ? NAME : selection.includes(p.id) || hover?.id === p.id ? FOCUS : fixed || solved ? PASS : MUTED;
              return fixed ? (
                <rect key={p.id} x={sx - 4} y={sy - 4} width={8} height={8} fill={color} stroke="var(--background)" strokeWidth={1} data-point={p.id} />
              ) : (
                <circle key={p.id} cx={sx} cy={sy} r={selection.includes(p.id) ? 4.5 : 3.5} fill={color} stroke="var(--background)" strokeWidth={1} data-point={p.id} />
              );
            })}
            {labelNodes}
            {preview()}
            {cursor && tool !== "select" && tool !== "delete" && (() => {
              const [sx, sy] = w2s(cursor.x, cursor.y);
              return cursor.pointId ? <circle cx={sx} cy={sy} r={7} fill="none" stroke={FOCUS} strokeWidth={1.5} /> : <path d={`M${sx - 5} ${sy}H${sx + 5}M${sx} ${sy - 5}V${sy + 5}`} stroke={FOCUS} strokeWidth={1} />;
            })()}
          </svg>
          <div className="absolute left-2 top-2 flex flex-col border-2 border-primary bg-popover" role="toolbar" aria-label="Sketch tools">
            {TOOLS.map((t) => (
              <button
                key={t.id}
                type="button"
                title={`${t.label} (${t.key})`}
                aria-label={t.label}
                aria-pressed={tool === t.id}
                data-tool={t.id}
                onClick={() => chooseTool(t.id)}
                className={cn("flex size-7 items-center justify-center border-b border-border last:border-b-0", tool === t.id ? "bg-primary text-primary-foreground" : "hover:bg-accent")}
              >
                <t.icon className="size-3.5" />
              </button>
            ))}
            <button
              type="button"
              title="Construction geometry (X): toggles the selected lines, or what you draw next"
              aria-label="Construction"
              aria-pressed={construction}
              onClick={toggleConstruction}
              className={cn("flex size-7 items-center justify-center border-t-2 border-border", construction ? "bg-focus text-primary-foreground" : "hover:bg-accent")}
            >
              <Construction className="size-3.5" />
            </button>
            <button
              type="button"
              title="Auto constraints: near-horizontal and vertical lines are constrained as you draw"
              aria-label="Auto constraints"
              aria-pressed={auto}
              onClick={() => setAuto((v) => !v)}
              className={cn("flex size-7 items-center justify-center border-t border-border", auto ? "bg-accent" : "text-muted-foreground hover:bg-accent")}
            >
              <WandSparkles className="size-3.5" />
            </button>
            <button
              type="button"
              title="Snap to grid and points (hold Alt to skip once)"
              aria-label="Snap"
              aria-pressed={snapOn}
              onClick={() => setSnapOn((v) => !v)}
              className={cn("flex size-7 items-center justify-center border-t border-border", snapOn ? "bg-accent" : "text-muted-foreground hover:bg-accent")}
            >
              <Magnet className="size-3.5" />
            </button>
            <button type="button" title="Fit to the sketch (F)" aria-label="Fit" onClick={fit} className="flex size-7 items-center justify-center border-t-2 border-border hover:bg-accent">
              <Maximize className="size-3.5" />
            </button>
            <button type="button" title="Undo (Ctrl/Cmd+Z)" aria-label="Undo" onClick={undo} className="flex size-7 items-center justify-center border-t border-border hover:bg-accent">
              <Undo2 className="size-3.5" />
            </button>
          </div>
          <div className="pointer-events-none absolute bottom-1.5 left-2 right-2 text-[10px] text-muted-foreground">
            {hint} <span className="opacity-70">Pan: middle-drag or space-drag; zoom: wheel.</span>
          </div>
          {box && boxAnchor && (
            <div className="absolute z-10 flex items-center gap-1 border-2 border-primary bg-popover p-1 shadow-[4px_4px_0_var(--shadow-hard)]" style={{ left: boxAnchor.x - 50, top: boxAnchor.y - 14 }}>
              <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{CONSTRAINT_INFO[box.kind].label}</span>
              <input
                autoFocus
                data-testid="sketch-value"
                aria-label="Dimension value"
                aria-invalid={box.bad}
                value={box.text}
                onFocus={(e) => e.currentTarget.select()}
                onChange={(e) => setBox({ ...box, text: e.target.value, bad: false })}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submitBox();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    setBox(null);
                    wrap.current?.focus();
                  }
                }}
                className="h-6 w-16 border-2 border-input bg-background px-1 text-[12px] focus-visible:border-focus focus-visible:outline-none aria-[invalid=true]:border-fail"
              />
              <span className="text-[10px] uppercase text-muted-foreground">{CONSTRAINT_INFO[box.kind].unit}</span>
            </div>
          )}
        </div>
        <aside className="flex w-56 shrink-0 flex-col overflow-y-auto border-l-2 border-border" aria-label="Constraint list">
          <div className="border-b-2 border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em]">constraints ({doc.constraints.length})</div>
          <ul className="flex flex-col" data-testid="constraint-list">
            {doc.constraints.length === 0 && <li className="px-2 py-1.5 text-[11px] text-muted-foreground">Select geometry, then pick a constraint above.</li>}
            {doc.constraints.map((c) => (
              <li
                key={c.id}
                data-constraint={c.id}
                onClick={() => setHighlight((h) => (h === c.id ? null : c.id))}
                className={cn("flex cursor-pointer items-center gap-1 border-b border-border px-2 py-1 text-[11px]", highlight === c.id && "bg-accent", blamed.has(c.id) && "text-fail")}
              >
                <span className="min-w-0 flex-1 truncate">
                  <b className="uppercase">{SHORT[c.kind]}</b> <span className="text-muted-foreground">{c.targets.join(", ")}</span>
                  {isDimensional(c.kind) && <span className="text-name"> {formatValue(dimensionValue(c, doc, result), c.kind)}</span>}
                </span>
                {isDimensional(c.kind) && (
                  <button
                    type="button"
                    title={c.driving === false ? "Reference dimension: click to make it driving" : "Driving dimension: click to make it a reference"}
                    onClick={(e) => {
                      e.stopPropagation();
                      commit({ ...doc, constraints: doc.constraints.map((k) => (k.id === c.id ? { ...k, driving: k.driving === false } : k)) });
                    }}
                    className="border border-input px-1 text-[9px] font-bold uppercase hover:border-primary"
                  >
                    {c.driving === false ? "ref" : "drv"}
                  </button>
                )}
                <button
                  type="button"
                  aria-label={`Delete ${c.id}`}
                  title="Delete constraint"
                  onClick={(e) => {
                    e.stopPropagation();
                    commit(removeConstraint(doc, c.id));
                  }}
                  className="text-muted-foreground hover:text-fail"
                >
                  <Trash2 className="size-3" />
                </button>
              </li>
            ))}
          </ul>
          <div className="border-y-2 border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em]">diagnostics</div>
          <ul data-testid="diagnostics">
            {diagnostics.length === 0 && <li className="px-2 py-1.5 text-[11px] text-muted-foreground">{error ?? "none"}</li>}
            {diagnostics.map((d, i) => (
              <li
                key={i}
                onClick={() => d.constraint_id && setHighlight(d.constraint_id)}
                className={cn("border-b border-border px-2 py-1 text-[11px]", d.severity === "error" ? "text-fail" : "text-muted-foreground", d.constraint_id && "cursor-pointer")}
              >
                {d.constraint_id && <b>{d.constraint_id} </b>}
                {d.message}
              </li>
            ))}
          </ul>
          <div className="border-y-2 border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em]">profile</div>
          <div className="px-2 py-1.5 text-[11px] text-muted-foreground" data-testid="profile-info">
            {loops.length === 0 ? (
              "Close a loop of lines, or draw a circle."
            ) : (
              <>
                {loops.length} loop{loops.length === 1 ? "" : "s"}; outer <span className="text-focus">{doc.profile}</span>
                {doc.inner.length > 0 && (
                  <>
                    , holes <span className="text-name">{doc.inner.join(", ")}</span>
                  </>
                )}
                . Click a loop for the outer profile; shift-click toggles a hole.
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
