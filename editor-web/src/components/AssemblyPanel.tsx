import { Anchor, Crosshair, Link2, Loader2, Plus, RefreshCw, Search, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { transformConnector,
  AXES,
  KINDS,
  KIND_LABEL,
  addComponent,
  addConnectorFromFace,
  addConstraint,
  applyCommand,
  assemblyProblems,
  assemblyStatus,
  compatibleAxes,
  connectorProblems,
  disableExplode,
  enableExplode,
  hasPhase,
  idProblem,
  needsDrive,
  radiusFields,
  removeComponent,
  removeConnector,
  removeConstraint,
  renameComponent,
  renameConnector,
  setAxis,
  setConnectorsCommand,
  setExplodeFactor,
  setExplodeVector,
  setGround,
  setKind,
  setRef,
  updateComponent,
  updateConstraint,
  type AssemblyDoc,
  type AxisName,
  type Component,
  type Constraint,
  type ConstraintKind,
  type ConnectorFrame,
} from "@/lib/assembly";
import type { FeatureCommand, FeatureState } from "@/lib/features";
import { isDescribed, filterSelection } from "@/lib/features";
import type { SelectionItem } from "@/lib/selection";
import type { AssemblyEditor, ConnectorDraft } from "@/lib/useAssembly";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";
import type { SelectionMode } from "@/scene/Viewport";

const select = "h-7 min-w-0 flex-1 border-2 border-input bg-background px-1 text-[12px] text-foreground focus-visible:border-focus focus-visible:outline-none disabled:opacity-50 aria-[invalid=true]:border-fail";
const head = "flex items-center gap-2 border-b border-border px-2 py-1.5";

/** A number box that holds its own text while typing and tells the document only a valid number (or "" for none). */
function NumberField({ label, value, onChange, optional = false, width = "w-16", testid }: { label: string; value: number | undefined; onChange: (v: number | undefined) => void; optional?: boolean; width?: string; testid?: string }) {
  const [text, setText] = useState(value === undefined ? "" : String(value));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    // An outside change (another notebook, a reset) replaces what is shown; typing in progress is left alone.
    setText((t) => (Number(t) === value && t.trim() !== "" ? t : value === undefined ? (t.trim() === "" ? t : "") : String(value)));
  }, [value]);
  return (
    <label className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{label}</span>
      <Input
        data-testid={testid}
        aria-label={label}
        aria-invalid={bad}
        className={cn("h-7 px-1", width)}
        value={text}
        inputMode="decimal"
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          if (next.trim() === "") {
            setBad(!optional);
            if (optional) onChange(undefined);
            return;
          }
          const n = Number(next);
          if (Number.isFinite(n) && /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(next.trim())) {
            setBad(false);
            onChange(n);
          } else setBad(true);
        }}
      />
    </label>
  );
}

function Section({ title, count, children, aside }: { title: string; count?: number; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="border-b-2 border-border">
      <div className={cn(head, "bg-accent/40")}>
        <span className="label">{title}{count !== undefined && ` (${count})`}</span>
        <span className="flex-1" />
        {aside}
      </div>
      {children}
    </section>
  );
}

function Problems({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="px-2 py-1 text-[11px] text-fail" data-testid="assembly-problems">
      {items.map((text) => (
        <li key={text} className="flex gap-1"><TriangleAlert className="mt-0.5 size-3 shrink-0" /> {text}</li>
      ))}
    </ul>
  );
}

// -- the part's own connectors --------------------------------------------------------------------------------------------------

function ConnectorsSection({
  state,
  draft,
  selection,
  busy,
  onSelectionMode,
  onRun,
  onPlace,
}: {
  state: FeatureState;
  draft: ConnectorDraft;
  selection: SelectionItem[];
  busy: boolean;
  onSelectionMode: (mode: SelectionMode) => void;
  onRun: (command: FeatureCommand) => Promise<void>;
  /** Place a connector on the picked face with the handles (the viewport's connector placer). */
  onPlace: () => void;
}) {
  const [note, setNote] = useState<{ tone: "ok" | "fail"; text: string } | null>(null);
  const [working, setWorking] = useState(false);
  const faces = filterSelection(selection, "face");
  const problems = connectorProblems(draft.list);

  const apply = async () => {
    if (problems.length || working) return;
    setWorking(true);
    try {
      await onRun(setConnectorsCommand(draft.list));
      setNote({ tone: "ok", text: "connectors written into the part's product cell" });
    } catch (e) {
      setNote({ tone: "fail", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setWorking(false);
    }
  };

  return (
    <Section
      title={t("Connectors of this part")}
      count={draft.list.length}
      aside={
        <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" title={t("Pick faces in the viewport")} onClick={() => onSelectionMode("face")} data-testid="connector-face-mode">
          <Crosshair /> {t("face mode")}
        </Button>
      }
    >
      <div className="flex flex-col gap-1.5 px-2 py-2" data-testid="connectors-section">
        {draft.list.length === 0 && <p className="text-[11px] text-muted-foreground">{t("No connectors yet. A connector is a frame (origin, x, y) an assembly joins parts by: pick a planar face and add one.")}</p>}
        <ul className="flex flex-col gap-1">
          {draft.list.map((c) => (
            <ConnectorRow key={c.id} c={c} active={draft.selected === c.id} onSelect={() => draft.setSelected(draft.selected === c.id ? null : c.id)} list={draft.list} setList={draft.setList} onSelected={draft.setSelected} />
          ))}
        </ul>
        <div className="flex items-center gap-1.5">
          <Button type="button" size="sm" data-testid="connector-place" disabled={faces.length !== 1} title={faces.length === 1 ? t("Place a connector on the picked face with the handles") : t("Pick one flat face first")} onClick={onPlace}>
            <Plus /> {t("on picked face")}
          </Button>
          <span className="text-[10px] text-muted-foreground">
            {faces.length === 1 ? t("Place it with the handles, name it, add it.") : faces.length === 0 ? t("Pick a flat face (face mode), or use Connector on the selection bar.") : t("{{count}} faces picked: pick exactly one.", { count: faces.length })}
          </span>
        </div>
        <Problems items={problems} />
        {note && (
          <p role={note.tone === "fail" ? "alert" : "status"} data-testid="connector-note" className={cn("text-[11px]", note.tone === "fail" ? "text-fail" : "text-pass")}>
            {note.text}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" data-testid="connectors-apply" disabled={busy || working || problems.length > 0 || !draft.dirty} onClick={() => void apply()}>
            {working ? t("working…") : t("apply connectors")}
          </Button>
          {draft.dirty && <span className="text-[10px] text-focus">{t("unsent changes")}</span>}
          {!state.product && <span className="text-[10px] text-muted-foreground">{t("no product yet")}</span>}
        </div>
      </div>
    </Section>
  );
}

function ConnectorRow({ c, active, onSelect, list, setList, onSelected }: { c: ConnectorFrame; active: boolean; onSelect: () => void; list: ConnectorFrame[]; setList: (l: ConnectorFrame[]) => void; onSelected: (id: string | null) => void }) {
  const [text, setText] = useState(c.id);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setText(c.id), [c.id]);
  const commit = () => {
    if (text === c.id) return setError(null);
    const out = renameConnector(list, c.id, text);
    if ("error" in out) return setError(out.error);
    setError(null);
    setList(out.list);
    onSelected(text);
  };
  const f = (v: readonly number[]) => v.map((n) => Math.round(n * 1000) / 1000).join(", ");
  return (
    <li className={cn("border-2 px-1.5 py-1", active ? "border-focus" : "border-border")} data-testid={`connector-${c.id}`}>
      <div className="flex items-center gap-1.5">
        <button type="button" aria-label={`highlight ${c.id}`} onClick={onSelect} className="text-muted-foreground hover:text-foreground"><Anchor className="size-3.5" /></button>
        <Input aria-label={`connector id ${c.id}`} aria-invalid={error !== null} className="h-6 flex-1 px-1" value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
        <Button type="button" size="icon" variant="ghost" className="h-6 w-6" aria-label={`delete connector ${c.id}`} onClick={() => { setList(removeConnector(list, c.id)); onSelected(null); }}><Trash2 /></Button>
      </div>
      <div className="mt-0.5 pl-5 text-[10px] leading-tight text-muted-foreground">
        at {f(c.origin)} mm<br />x ({f(c.x_axis)}) z ({f(c.z_axis ?? [0, 0, 0])})
      </div>
      {active && <FrameEditor c={c} list={list} setList={setList} />}
      {error && <p className="pl-5 text-[11px] text-fail">{error}</p>}
    </li>
  );
}

/** Change a connector's frame by hand: its origin, a move along its own axes, a turn about one of them. */
function FrameEditor({ c, list, setList }: { c: ConnectorFrame; list: ConnectorFrame[]; setList: (l: ConnectorFrame[]) => void }) {
  const round = (n: number) => String(Math.round(n * 1000) / 1000);
  const [origin, setOrigin] = useState<string[]>(c.origin.map(round));
  const [move, setMove] = useState<string[]>(["0", "0", "0"]);
  const [axis, setAxis] = useState<"x" | "y" | "z">("z");
  const [angle, setAngle] = useState("90");
  useEffect(() => setOrigin(c.origin.map(round)), [c.origin]);
  const numbers = (parts: string[]) => {
    const out = parts.map((p) => Number(p));
    return out.every((n) => Number.isFinite(n)) ? (out as [number, number, number]) : null;
  };
  const apply = (change: Parameters<typeof transformConnector>[2]) => setList(transformConnector(list, c.id, change));
  const triple = (values: string[], set: (v: string[]) => void, label: string) => (
    <div className="grid grid-cols-3 gap-1">
      {["x", "y", "z"].map((a, i) => (
        <Input key={a} aria-label={`${label} ${a}`} className="h-6 px-1 text-[11px]" inputMode="decimal" value={values[i]} onChange={(e) => set(values.map((v, k) => (k === i ? e.target.value : v)))} />
      ))}
    </div>
  );
  const originNumbers = numbers(origin);
  const moveNumbers = numbers(move);
  const degrees = Number(angle);
  return (
    <div className="mt-1 flex flex-col gap-1 pl-5" data-testid={`frame-editor-${c.id}`}>
      <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t("origin (mm)")}</span>
      <div className="flex items-center gap-1">
        <div className="flex-1">{triple(origin, setOrigin, "origin")}</div>
        <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={!originNumbers} onClick={() => originNumbers && apply({ origin: originNumbers })}>{t("set")}</Button>
      </div>
      <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t("move along its own x, y, z (mm)")}</span>
      <div className="flex items-center gap-1">
        <div className="flex-1">{triple(move, setMove, "move")}</div>
        <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={!moveNumbers} onClick={() => moveNumbers && (apply({ move: moveNumbers }), setMove(["0", "0", "0"]))}>{t("move")}</Button>
      </div>
      <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t("turn about its own axis")}</span>
      <div className="flex items-center gap-1">
        {(["x", "y", "z"] as const).map((a) => (
          <Button key={a} type="button" size="sm" variant={axis === a ? "default" : "outline"} className="h-6 w-6 px-0" aria-pressed={axis === a} onClick={() => setAxis(a)}>{a}</Button>
        ))}
        <Input aria-label={t("turn angle")} className="h-6 w-14 px-1 text-[11px]" inputMode="decimal" value={angle} onChange={(e) => setAngle(e.target.value)} />
        <span className="text-[10px] text-muted-foreground">{t("deg")}</span>
        <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={!Number.isFinite(degrees)} onClick={() => apply({ rotate: { axis, degrees } })}>{t("turn")}</Button>
        <Button type="button" size="sm" variant="ghost" className="h-6 px-1.5" title={t("Turn the frame over (180 deg about its x axis): z points the other way")} onClick={() => apply({ rotate: { axis: "x", degrees: 180 } })}>{t("flip z")}</Button>
      </div>
    </div>
  );
}

// -- the assembly ----------------------------------------------------------------------------------------------------------------

function PartPicker({ editor, onPick }: { editor: AssemblyEditor; onPick: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rows = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return editor.parts.filter((p) => words.every((w) => `${p.name} ${p.path}`.toLowerCase().includes(w)));
  }, [editor.parts, query]);
  return (
    <div className="flex flex-col gap-1">
      <Button type="button" size="sm" variant="outline" data-testid="component-add" onClick={() => { setOpen((v) => !v); if (!open) editor.refreshParts(); }}>
        <Plus /> {t("add component")}
      </Button>
      {open && (
        <div className="border-2 border-primary bg-popover" data-testid="part-picker">
          <div className="flex items-center gap-1.5 border-b border-border px-1.5">
            <Search className="size-3.5 text-muted-foreground" />
            <input autoFocus aria-label={t("Search parts")} placeholder={t("search the workspace's parts")} className="h-7 flex-1 bg-transparent text-[12px] outline-none" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <ul className="max-h-40 overflow-y-auto">
            {rows.map((p) => (
              <li key={p.path}>
                <button type="button" data-testid={`part-${p.name}`} className="flex w-full items-center justify-between gap-2 px-2 py-1 text-left text-[12px] hover:bg-accent" onClick={() => { onPick(p.path); setOpen(false); setQuery(""); }}>
                  <span className="text-name">{p.name}</span>
                  <span className="truncate text-[10px] text-muted-foreground">{p.path}</span>
                </button>
              </li>
            ))}
            {rows.length === 0 && <li className="px-2 py-2 text-[11px] text-muted-foreground">{editor.partsError ?? (editor.parts.length === 0 ? t("No part notebooks in this workspace yet.") : t("No part matches."))}</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

function ComponentCard({ c, doc, editor }: { c: Component; doc: AssemblyDoc; editor: AssemblyEditor }) {
  const [text, setText] = useState(c.id);
  useEffect(() => setText(c.id), [c.id]);
  const problem = text === c.id ? null : idProblem(doc, c.id, text);
  const selected = editor.selected === c.id;
  const commit = () => {
    if (text === c.id || problem) {
      if (problem) setText(c.id);
      return;
    }
    editor.setDoc(renameComponent(doc, c.id, text));
    if (selected) editor.setSelected(text);
  };
  const entry = editor.cache[c.part];
  return (
    <li className={cn("border-2 px-2 py-1.5", selected ? "border-focus" : "border-border")} data-testid={`component-${c.id}`}>
      <div className="flex items-center gap-1.5">
        <button type="button" aria-pressed={selected} title={t("Select: its connectors are drawn in the viewport")} data-testid={`select-${c.id}`} onClick={() => editor.setSelected(selected ? null : c.id)} className={cn("text-muted-foreground hover:text-foreground", selected && "text-focus")}>
          <Anchor className="size-3.5" />
        </button>
        <Input aria-label={`component id ${c.id}`} aria-invalid={problem !== null} title={problem ?? t("component id")} className="h-6 w-28 px-1" value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
        <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground" title={c.part}>{c.part}</span>
        <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground" title={t("The grounded component never moves")}>
          <input type="radio" name="ground" aria-label={`ground ${c.id}`} data-testid={`ground-${c.id}`} checked={doc.ground === c.id} onChange={() => editor.setDoc(setGround(doc, c.id))} />
          {t("ground")}
        </label>
        <Button type="button" size="icon" variant="ghost" className="h-6 w-6" aria-label={`remove ${c.id}`} data-testid={`remove-${c.id}`} onClick={() => { editor.setDoc(removeComponent(doc, c.id)); if (selected) editor.setSelected(null); }}><Trash2 /></Button>
      </div>
      {problem && <p className="text-[11px] text-fail">{problem}</p>}
      <div className="mt-1.5 flex flex-wrap items-end gap-1.5">
        {(["x", "y", "z"] as const).map((axis, i) => (
          <NumberField key={axis} label={`${axis} mm`} testid={`origin-${c.id}-${axis}`} value={c.origin[i]} onChange={(v) => v !== undefined && editor.setDoc(updateComponent(doc, c.id, { origin: c.origin.map((o, j) => (j === i ? v : o)) as [number, number, number] }))} />
        ))}
        <label className="flex flex-col gap-0.5">
          <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t("x axis")}</span>
          <select aria-label={`${c.id} x axis`} className={cn(select, "w-14 flex-none")} value={c.x_axis} onChange={(e) => editor.setDoc(setAxis(doc, c.id, "x_axis", e.target.value as AxisName))}>
            {AXES.map((a) => <option key={a} value={a} disabled={!compatibleAxes(c.y_axis).includes(a)} title={compatibleAxes(c.y_axis).includes(a) ? undefined : "along the same line as the y axis"}>{a}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t("y axis")}</span>
          <select aria-label={`${c.id} y axis`} className={cn(select, "w-14 flex-none")} value={c.y_axis} onChange={(e) => editor.setDoc(setAxis(doc, c.id, "y_axis", e.target.value as AxisName))}>
            {AXES.map((a) => <option key={a} value={a} disabled={!compatibleAxes(c.x_axis).includes(a)} title={compatibleAxes(c.x_axis).includes(a) ? undefined : "along the same line as the x axis"}>{a}</option>)}
          </select>
        </label>
      </div>
      {entry?.status === "error" && <p className="mt-1 text-[11px] text-fail">{t("connectors of {{part}}: {{error}}", { part: c.part, error: entry.error })}</p>}
    </li>
  );
}

function ConnectorPicker({ k, side, doc, editor }: { k: Constraint; side: "a" | "b"; doc: AssemblyDoc; editor: AssemblyEditor }) {
  const ref = k[side];
  const component = doc.components.find((c) => c.id === ref.component);
  const path = component?.part ?? "";
  const entry = path ? editor.cache[path] : undefined;
  const { loadConnectors } = editor;
  useEffect(() => {
    if (path) loadConnectors(path);
  }, [path, loadConnectors]);
  const armed = editor.target?.constraint === k.id && editor.target.side === side;
  const ids = entry?.connectors.map((c) => c.id) ?? [];
  const manual = entry?.status === "error" || (entry?.status === "ok" && ids.length === 0);
  return (
    <div className="flex items-center gap-1" data-testid={`picker-${k.id}-${side}`}>
      <span className="w-3 text-[10px] font-bold uppercase text-muted-foreground">{side}</span>
      <select aria-label={`${k.id} ${side} component`} className={select} value={ref.component} onChange={(e) => editor.setDoc(setRef(doc, k.id, side, { component: e.target.value }))}>
        <option value="">{t("component…")}</option>
        {doc.components.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
      </select>
      {manual ? (
        <Input aria-label={`${k.id} ${side} connector`} className="h-7 min-w-0 flex-1 px-1" placeholder={t("connector id")} value={ref.connector} onChange={(e) => editor.setDoc(setRef(doc, k.id, side, { connector: e.target.value.trim() }))} title={entry?.error ?? t("this part declares no connectors: type an id")} />
      ) : (
        <select aria-label={`${k.id} ${side} connector`} className={select} value={ref.connector} disabled={!component || entry?.status === "loading"} onChange={(e) => editor.setDoc(setRef(doc, k.id, side, { connector: e.target.value }))}>
          <option value="">{entry?.status === "loading" ? t("loading…") : t("connector…")}</option>
          {ids.map((id) => <option key={id} value={id}>{id}</option>)}
          {ref.connector && !ids.includes(ref.connector) && entry?.status === "ok" && <option value={ref.connector}>{ref.connector} (not declared)</option>}
        </select>
      )}
      {entry?.status === "loading" && <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-label={t("loading connectors")} />}
      <Button type="button" size="icon" variant={armed ? "default" : "ghost"} className="h-6 w-6" aria-pressed={armed} aria-label={`pick ${k.id} ${side} in the viewport`} title={t("Pick this connector by clicking its gizmo in the viewport")} data-testid={`arm-${k.id}-${side}`} onClick={() => editor.setTarget(armed ? null : { constraint: k.id, side })}>
        <Crosshair />
      </Button>
    </div>
  );
}

function ConstraintCard({ k, doc, editor }: { k: Constraint; doc: AssemblyDoc; editor: AssemblyEditor }) {
  const patch = (p: Partial<Constraint>) => editor.setDoc(updateConstraint(doc, k.id, p));
  const unit = k.kind === "revolute" ? "deg" : "mm";
  return (
    <li className="border-2 border-border px-2 py-1.5" data-testid={`constraint-${k.id}`}>
      <div className="flex items-center gap-1.5">
        <Link2 className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="w-8 shrink-0 text-[11px] text-name">{k.id}</span>
        <select aria-label={`${k.id} kind`} className={select} value={k.kind} onChange={(e) => editor.setDoc(setKind(doc, k.id, e.target.value as ConstraintKind))}>
          {KINDS.map((kind) => <option key={kind} value={kind}>{t(KIND_LABEL[kind])}</option>)}
        </select>
        <Button type="button" size="icon" variant="ghost" className="h-6 w-6" aria-label={`remove constraint ${k.id}`} onClick={() => { editor.setDoc(removeConstraint(doc, k.id)); if (editor.target?.constraint === k.id) editor.setTarget(null); }}><Trash2 /></Button>
      </div>
      <div className="mt-1 flex flex-col gap-1">
        <ConnectorPicker k={k} side="a" doc={doc} editor={editor} />
        <ConnectorPicker k={k} side="b" doc={doc} editor={editor} />
      </div>
      {(needsDrive(k.kind) || radiusFields(k.kind).length > 0 || hasPhase(k.kind)) && (
        <div className="mt-1.5 flex flex-wrap items-end gap-1.5">
          {needsDrive(k.kind) && (
            <>
              <NumberField label={t("drive {{unit}}", { unit })} testid={`drive-${k.id}`} optional value={k.drive} onChange={(v) => patch({ drive: v })} />
              <NumberField label={t("limit lo {{unit}}", { unit })} testid={`limit-lo-${k.id}`} optional value={k.limit?.[0]} onChange={(v) => patch({ limit: v === undefined && k.limit?.[1] === undefined ? undefined : [v ?? Number.NaN, k.limit?.[1] ?? Number.NaN] })} />
              <NumberField label={t("limit hi {{unit}}", { unit })} testid={`limit-hi-${k.id}`} optional value={k.limit?.[1]} onChange={(v) => patch({ limit: v === undefined && k.limit?.[0] === undefined ? undefined : [k.limit?.[0] ?? Number.NaN, v ?? Number.NaN] })} />
            </>
          )}
          {radiusFields(k.kind).map((f) => (
            <NumberField key={f.key} label={`${t(f.label)} mm`} testid={`${f.key}-${k.id}`} width="w-20" value={k[f.key]} onChange={(v) => patch({ [f.key]: v } as Partial<Constraint>)} />
          ))}
          {hasPhase(k.kind) && <NumberField label={t("phase deg")} testid={`phase-${k.id}`} optional value={k.phase} onChange={(v) => patch({ phase: v })} />}
        </div>
      )}
    </li>
  );
}

/** The exploded view: a switch, the factor and an optional centre and axis.  The notebook shows the pushed-apart placement
 * (scad.explode_rassembly); the factor also becomes a slider in the parameters panel, so 0 puts everything back. */
function ExplodeSection({ doc, editor }: { doc: AssemblyDoc; editor: AssemblyEditor }) {
  const explode = doc.explode;
  const entry = (v: number | undefined) => (v === undefined || Number.isNaN(v) ? undefined : v);
  return (
    <Section
      title={t("Exploded view")}
      aside={<Switch aria-label={t("Exploded view")} data-testid="explode-switch" checked={Boolean(explode)} onCheckedChange={(on) => editor.setDoc(on ? enableExplode(doc) : disableExplode(doc))} />}
    >
      <div className="flex flex-col gap-1.5 px-2 py-2" data-testid="explode-section">
        <p className="text-[11px] text-muted-foreground">{t("Components move away from the assembly centre; with an axis they move along it, to the side they are on.")}</p>
        {explode && (
          <>
            <div className="flex flex-wrap items-end gap-1.5">
              <NumberField label={t("factor")} testid="explode-factor" width="w-20" value={Number.isFinite(explode.factor) ? explode.factor : undefined} onChange={(v) => editor.setDoc(setExplodeFactor(doc, v ?? Number.NaN))} />
              <span className="pb-1.5 text-[10px] text-muted-foreground">{t("0 puts everything back")}</span>
            </div>
            {(["center", "axis"] as const).map((key) => (
              <div key={key} className="flex flex-wrap items-end gap-1.5">
                <span className="w-12 pb-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t(key)}{key === "center" ? " mm" : ""}</span>
                {(["x", "y", "z"] as const).map((axis, i) => (
                  <NumberField key={axis} label={`${key} ${axis}`} testid={`explode-${key}-${axis}`} optional value={entry(explode[key]?.[i])} onChange={(v) => editor.setDoc(setExplodeVector(doc, key, i, v))} />
                ))}
              </div>
            ))}
            <span className="text-[10px] text-muted-foreground">{t("centre: empty = the centre of the whole assembly; axis: empty = away from the centre.")}</span>
          </>
        )}
      </div>
    </Section>
  );
}

function AssemblySection({ state, editor, busy, onRun }: { state: FeatureState; editor: AssemblyEditor; busy: boolean; onRun: (command: FeatureCommand) => Promise<void> }) {
  const { doc } = editor;
  const [name, setName] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const { refreshParts } = editor;
  useEffect(() => refreshParts(), [refreshParts]);
  // A limit with only one side typed is not a limit yet: it is sent as none until both are numbers.
  const sendable = useMemo(
    () => ({ ...doc, constraints: doc.constraints.map((k) => (k.limit && k.limit.some((v) => !Number.isFinite(v)) ? { ...k, limit: undefined } : k)) }),
    [doc],
  );
  const half = doc.constraints.filter((k) => k.limit && k.limit.some((v) => !Number.isFinite(v))).map((k) => t("{{id}}: type both limits or neither", { id: k.id }));
  const problems = [...assemblyProblems(sendable), ...half];
  const status = assemblyStatus(state);
  const taken = state.taken;

  const apply = async () => {
    if (problems.length || working) return;
    setWorking(true);
    setError(null);
    setApplied(false);
    try {
      await onRun(applyCommand(sendable, state.assembly ?? null, state.assembly ? undefined : name));
      setApplied(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  };
  const nameTaken = !state.assembly && name.trim() !== "" && taken.includes(name.trim());

  return (
    <>
      <Section
        title={t("Components")}
        count={doc.components.length}
        aside={<Button type="button" size="icon" variant="ghost" className="h-6 w-6" title={t("Refresh the list of parts")} aria-label={t("Refresh parts")} onClick={editor.refreshParts}><RefreshCw /></Button>}
      >
        <div className="flex flex-col gap-1.5 px-2 py-2" data-testid="components-section">
          {doc.components.length === 0 && <p className="text-[11px] text-muted-foreground">{t("No components. Add a part notebook of this workspace; the first one added is the ground.")}</p>}
          <ul className="flex flex-col gap-1.5">
            {doc.components.map((c) => <ComponentCard key={c.id} c={c} doc={doc} editor={editor} />)}
          </ul>
          <PartPicker editor={editor} onPick={(path) => { const made = addComponent(doc, path); editor.setDoc(made.doc); editor.setSelected(made.id); editor.loadConnectors(path); }} />
        </div>
      </Section>
      <Section
        title={t("Constraints")}
        count={doc.constraints.length}
        aside={
          <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" data-testid="constraint-add" disabled={doc.components.length < 2} title={doc.components.length < 2 ? "Add two components first" : "Add a joint or a mate"} onClick={() => editor.setDoc(addConstraint(doc).doc)}>
            <Plus /> constraint
          </Button>
        }
      >
        <div className="flex flex-col gap-1.5 px-2 py-2" data-testid="constraints-section">
          {doc.constraints.length === 0 && <p className="text-[11px] text-muted-foreground">{t("No constraints: every component sits at its placement. A joint moves one component about a connector of another; a drive becomes a slider.")}</p>}
          <ul className="flex flex-col gap-1.5">
            {doc.constraints.map((k) => <ConstraintCard key={k.id} k={k} doc={doc} editor={editor} />)}
          </ul>
          {editor.target && <p className="text-[11px] text-focus" data-testid="pick-hint">Click a connector gizmo in the viewport to fill {editor.target.constraint} {editor.target.side.toUpperCase()}.</p>}
        </div>
      </Section>
      <ExplodeSection doc={doc} editor={editor} />
      <div className="flex flex-col gap-1.5 px-2 py-2" data-testid="assembly-apply-area">
        {!state.assembly && (
          <label className="flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{t("feature name (optional)")}</span>
            <Input aria-label={t("Assembly name")} data-testid="assembly-name" aria-invalid={nameTaken} placeholder={t("assembly")} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <Problems items={problems} />
        {error && <p role="alert" data-testid="assembly-error" className="border-2 border-fail px-2 py-1 text-[11px] text-fail">{error}</p>}
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" data-testid="assembly-apply" disabled={busy || working || problems.length > 0 || nameTaken || (doc.components.length === 0)} onClick={() => void apply()}>
            {working ? t("working…") : state.assembly ? t("apply") : t("add assembly")}
          </Button>
          {editor.dirty && <span className="text-[10px] text-focus">{t("unsent changes")}</span>}
          {applied && !editor.dirty && <span className="text-[10px] text-pass">{t("applied")}</span>}
        </div>
        <div data-testid="assembly-status" className="flex items-start gap-2 border border-border px-2 py-1 text-[11px]">
          <span className={cn("mt-1 inline-block h-2 w-2 shrink-0", !status ? "bg-muted-foreground" : status.errors.length ? "bg-fail" : status.running ? "bg-focus" : "bg-pass")} />
          <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
            {!status
              ? t("not in the notebook yet")
              : status.errors.length
                ? <span className="text-fail">{status.errors.join("\n")}</span>
                : status.running
                  ? t("solving…")
                  : t("solved: the constraints hold (drag a joint's slider in the notebook's parameters)")}
          </span>
        </div>
      </div>
    </>
  );
}

/** The left column's assembly tab: the part's connectors (when the notebook has a product) and the assembly layout. */
export function AssemblyPanel({
  state,
  editor,
  connectors,
  selection,
  busy,
  onSelectionMode,
  onRun,
  onPlaceConnector,
}: {
  state: FeatureState;
  editor: AssemblyEditor;
  connectors: ConnectorDraft;
  selection: SelectionItem[];
  busy: boolean;
  onSelectionMode: (mode: SelectionMode) => void;
  /** Runs the command; rejects with the server's message (shown inline). */
  onRun: (command: FeatureCommand) => Promise<void>;
  onPlaceConnector: () => void;
}) {
  return (
    <div className="h-full overflow-y-auto" data-testid="assembly-panel">
      {state.product && <ConnectorsSection state={state} draft={connectors} selection={selection} busy={busy} onSelectionMode={onSelectionMode} onRun={onRun} onPlace={onPlaceConnector} />}
      <AssemblySection state={state} editor={editor} busy={busy} onRun={onRun} />
    </div>
  );
}
