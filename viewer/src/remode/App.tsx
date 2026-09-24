// Reverse-engineering studio (re-mode) — React + shadcn/ui shell.
//
// Left: original STEP viewport with entity picking, circle/lasso region
// annotation and a free-form composer — picked entities and operation tips
// appear as inline colored chips, peers of plain text, and committed
// annotations float as pills over the bottom of the target viewer. Right
// top: rebuilt result (.scadpkg) plus the agent's comparison image. Right
// bottom: FTC source (CodeMirror), feature DAG, evaluation report, last
// submission, and the live context preview.
//
// Governance: the UI only selects and describes. It never edits geometry —
// every rebuild flows through the agent's code, and only this UI writes
// submissions.
//
// The imperative engines (SceneView/three.js, CodeMirror dock, the IME-safe
// TokenComposer and slash suggest) stay vanilla; React owns layout, state
// mirrors and chrome. The controller effect below is the single boot path
// and mirrors the data flow 1:1 — anything it mutates lives in refs, and
// UI mirrors sync through setState.

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import {
  Box,
  ClipboardCheck,
  Columns2,
  Dot,
  Eraser,
  Eye,
  Inbox,
  Lasso,
  Maximize2,
  MousePointer2,
  Plus,
  Send,
  Slash,
  Square,
  SquareCode,
  Workflow,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import { PythonEditor } from '../shared/components/source-dock';
import { openCadPackage, type PackageFiles } from '../shared/product-package';
import { buildFederatedFeatureModel, type ModelDocument, type SceneManifest } from '../shared/scene2';
import { MARK_COLORS, SceneView, type PickResult, type SelectionMode } from '../shared/scene-view';
import { TokenComposer, type ComposerTokenKind } from './composer';
import { agentSession } from '../agent/session';
import { reStudioEditorTheme } from './code-theme';
import { FeatureTreeView } from './feature-tree';
import { OpSuggest, type SuggestOperation } from './op-suggest';
import { opCategoryResolver, renderMarkup } from './markup';
import { Button } from './ui/button';
import { Resizable, ResizableHandle, ResizablePanel, HandleLine } from './ui/resizable';
import { Toaster } from './ui/sonner';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { ToggleGroup, ToggleGroupItem } from './ui/toggle';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip';
import { cn } from './ui/lib/utils';

/** Transient (pre-ADD) viewport highlight + live lasso stroke; must read
 *  against both pale models and the dark chrome, and stay clear of the
 *  committed-annotation MARK_COLORS palette. */
const DRAFT_COLOR = '#00c8ff';

type DraftEntry = { nodeId: string; entityId: string; canonical: string; kind: string };

type Annotation = {
  annotation_id: string;
  kind: 'free';
  intent: 'free';
  text: string;
  entries: DraftEntry[];
  operations: string[];
  screen_polygon?: Array<[number, number]>;
  color: string;
  created_at: string;
};

type SessionPayload = {
  target: { name: string | null; path: string | null; present: boolean };
  scene: { state: string; error: string | null; face_count?: number; edge_count?: number; vertex_count?: number; body_count?: number };
  annotations: number;
  submission: { seq: number; submitted_at: string } | null;
  artifacts: Record<string, { present: boolean; mtime?: number; size?: number }>;
};

type RegionResolveResponse = { entity_ids: string[]; count: string | number };

type OperationTip = {
  op_id: string;
  label: string;
  category: string;
  api: string[];
  reads: string[];
  doc_refs: string[];
  hint: string;
};

type OperationsPayload = {
  categories: Array<{ id: string; label: string; description: string }>;
  operations: OperationTip[];
  errors: string[];
};

type SubmissionAnnotation = {
  intent?: string;
  text?: string;
  color?: string;
  entity_ids?: string[];
  operations?: string[];
  unresolved_entity_ids?: string[];
};

type SubmissionRecord = {
  submission_seq?: number;
  submitted_at?: string;
  annotations?: SubmissionAnnotation[];
  note?: string;
};

type InspectorState = { canonical: string; rows: string[]; details: string };
// The Web Editor shell owns one session shared across modes.

// -- shared helpers (pure, module scope) --------------------------------------

function serializeAnnotation(annotation: Annotation): Record<string, unknown> {
  return {
    annotation_id: annotation.annotation_id,
    kind: annotation.kind,
    intent: annotation.intent,
    text: annotation.text,
    entity_ids: annotation.entries.map((entry) => entry.canonical),
    operations: annotation.operations,
    screen_polygon: annotation.screen_polygon ?? null,
    color: annotation.color,
    created_at: annotation.created_at,
  };
}

async function postAnnotation(action: 'add' | 'remove', annotation: Annotation): Promise<void> {
  try {
    await agentSession.recordAnnotation({ action, annotation: serializeAnnotation(annotation) });
  } catch {
    toast.error('annotation log unreachable');
  }
}

function postSelectEvent(entityIds: string[]): void {
  void agentSession.recordEvent({ type: 'select', entity_ids: entityIds }).catch(() => {});
}


function decodeFiles(encoded: Record<string, string>): PackageFiles {
  const files: PackageFiles = {};
  for (const [uri, base64] of Object.entries(encoded)) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    files[uri] = bytes;
  }
  return files;
}

// -- presentational components -------------------------------------------------

/** Renders serialized chip markup (`[label](token)`) with the live chip styling. */
function Markup({ text, opCategory }: { text: string; opCategory: (opId: string) => string | undefined }) {
  const hostRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const host = hostRef.current;
    if (host) host.replaceChildren(renderMarkup(text, opCategory));
  }, [text, opCategory]);
  return <span ref={hostRef} />;
}

/** Committed annotation as a capsule pill floating over the target viewer. */
function CapsulePill({
  annotation,
  opCategory,
  onRemove,
  onRecall,
}: {
  annotation: Annotation;
  opCategory: (opId: string) => string | undefined;
  onRemove: () => void;
  onRecall: () => void;
}) {
  return (
    <div
      className="group pointer-events-auto relative inline-flex max-w-[min(440px,72%)] cursor-pointer items-center gap-2 rounded-full border bg-panel/85 py-1 pr-1.5 pl-3 text-[10px] shadow-lg shadow-black/40 backdrop-blur-md transition-colors hover:bg-panel"
      style={{ borderColor: annotation.color }}
      onClick={onRecall}
    >
      <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: annotation.color }} />
      <span className="min-w-0 truncate">
        <Markup text={annotation.text} opCategory={opCategory} />
      </span>
      <button
        type="button"
        title="remove annotation"
        className="grid size-5 shrink-0 place-items-center rounded-full text-dim transition-colors hover:bg-white/10 hover:text-reddish"
        onClick={(event) => {
          event.stopPropagation();
          onRemove();
        }}
      >
        <X className="size-3" />
      </button>
      <div className="pointer-events-none absolute bottom-full left-0 z-30 mb-3 hidden w-max max-w-[min(560px,72vw)] rounded-xl border border-edge bg-panel/95 p-3 text-[10px] leading-[1.8] break-words text-ink shadow-2xl shadow-black/60 backdrop-blur group-hover:block">
        <Markup text={annotation.text} opCategory={opCategory} />
      </div>
    </div>
  );
}

/** On-demand entity facts card, floating top-left in the target viewport. */
function InspectorCard({ data, onClose }: { data: InspectorState; onClose: () => void }) {
  return (
    <div className="absolute top-3 left-3 z-30 max-w-sm rounded-xl border border-edge bg-panel/90 p-3 text-[10px] shadow-2xl shadow-black/50 backdrop-blur-md">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] text-lime">{data.canonical}</div>
          <div className="mt-0.5 text-dim">{data.rows.join(' · ')}</div>
        </div>
        <button
          type="button"
          title="close"
          className="grid size-5 place-items-center rounded-full text-dim hover:bg-white/10 hover:text-ink"
          onClick={onClose}
        >
          <X className="size-3" />
        </button>
      </div>
      <details className="mt-1">
        <summary className="cursor-pointer text-[10px] text-[#7fa8d4]">adjacency + geometry</summary>
        <pre className="mt-1.5 max-h-[200px] overflow-auto rounded-lg border border-line bg-void p-2 font-mono text-[10px] leading-[1.5] text-[#b8c4d4]">{data.details}</pre>
      </details>
    </div>
  );
}

function SubmissionView({ submission }: { submission: SubmissionRecord | null }) {
  if (!submission) return <div className="p-3 text-[11px] text-dim">no submission yet</div>;
  const rows = submission.annotations ?? [];
  return (
    <div className="flex flex-col gap-1.5 p-3 text-[11px]">
      <div className="font-mono text-[9px] text-dim">
        submission #{submission.submission_seq} · {submission.submitted_at ?? ''}
      </div>
      {rows.length ? (
        rows.map((annotation, index) => (
          <div key={index} className="flex items-center gap-2 py-0.5">
            <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: annotation.color ?? '#888' }} />
            <strong className="font-semibold">{annotation.intent}</strong>
            <span className="text-dim">{annotation.entity_ids?.length ?? 0} entities</span>
            {!!annotation.operations?.length && <span className="text-dim">{annotation.operations.length} ops</span>}
            {annotation.text && <span className="truncate text-dim">{annotation.text}</span>}
            {!!annotation.unresolved_entity_ids?.length && (
              <span className="text-amber">unresolved: {annotation.unresolved_entity_ids.join(', ')}</span>
            )}
          </div>
        ))
      ) : (
        <div className="text-dim">no annotations</div>
      )}
      {submission.note && <div className="mt-1.5 text-amber">note: {submission.note}</div>}
    </div>
  );
}

// -- the studio ----------------------------------------------------------------

declare global {
  interface Window {
    /** Debug/console access for the internal tool (also used by e2e verification). */
    __reDebug?: { originalView: SceneView; rebuiltView: SceneView; annotations: Annotation[]; composer: TokenComposer };
  }
}

export function ReStudio() {
  // hosts (must never unmount: three.js / CodeMirror bind to them once)
  const originalHostRef = useRef<HTMLDivElement>(null);
  const rebuiltHostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const composerAreaRef = useRef<HTMLDivElement>(null);
  const sourceEditorHostRef = useRef<HTMLDivElement>(null);
  const featureTreeHostRef = useRef<HTMLDivElement>(null);

  // imperative engines
  const originalViewRef = useRef<SceneView | null>(null);
  const rebuiltViewRef = useRef<SceneView | null>(null);
  const composerRef = useRef<TokenComposer | null>(null);
  const editorRef = useRef<PythonEditor | null>(null);
  const redrawRef = useRef<() => void>(() => {});
  const removeAnnotationRef = useRef<(annotationId: string) => void>(() => {});
  const showSourceFileRef = useRef<(path: string) => void>(() => {});
  const loadSubmissionRef = useRef<() => void>(() => {});

  // data mirrors of the pre-React dataflow
  const canonicalBySceneId = useRef(new Map<string, string>());
  const sceneIdByCanonical = useRef(new Map<string, string>());
  const nodeIdBySceneId = useRef(new Map<string, string>());
  const draft = useRef(new Map<string, DraftEntry>());
  const annotationsRef = useRef<Annotation[]>([]);
  const annotationCounter = useRef(0);
  const drawModeRef = useRef<'off' | 'lasso'>('off');
  const drawPoints = useRef<Array<[number, number]>>([]);
  const drawingRef = useRef(false);
  const currentPolygon = useRef<Array<[number, number]> | null>(null);
  const sourceFilesRef = useRef(new Map<string, string>());
  const currentSourcePathRef = useRef<string | null>(null);
  const packageModelRef = useRef<ModelDocument | null>(null);
  const artifactMtimesRef = useRef<Record<string, number>>({});
  const sceneBusyRef = useRef(true);

  // UI state
  const [targetName, setTargetName] = useState('no target');
  const [topStats, setTopStats] = useState('connecting');
  const [agentLabel, setAgentLabel] = useState('connecting');
  const [agentWaiting, setAgentWaiting] = useState(false);
  const [sceneReady, setSceneReady] = useState(false);
  const [sceneBusy, setSceneBusy] = useState(true);
  const [sceneStatus, setSceneStatus] = useState('loading scene');
  const [submitting, setSubmitting] = useState(false);
  const [canAdd, setCanAdd] = useState(false);
  const [composerHeight, setComposerHeight] = useState(112);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('face');
  const [drawMode, setDrawMode] = useState<'off' | 'lasso'>('off');
  const [inspector, setInspector] = useState<InspectorState | null>(null);
  const [rebuiltTab, setRebuiltTab] = useState('model');
  const [rebuiltState, setRebuiltState] = useState('waiting for agent');
  const [comparisonSrc, setComparisonSrc] = useState<string | null>(null);
  const [bottomTab, setBottomTab] = useState('source');
  const [sourcePaths, setSourcePaths] = useState<string[]>([]);
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [hasPackage, setHasPackage] = useState(false);
  const [rebuildPySeen, setRebuildPySeen] = useState(false);
  const [fallbackRows, setFallbackRows] = useState<Array<{ op: string; label: string }>>([]);
  const [evaluationText, setEvaluationText] = useState('');
  const [submission, setSubmission] = useState<SubmissionRecord | null>(null);
  const [operationsState, setOperationsState] = useState<OperationsPayload | null>(null);

  const opCategory = useMemo(() => opCategoryResolver(operationsState?.operations ?? []), [operationsState]);

  const contextText = useMemo(
    () =>
      JSON.stringify(
        {
          annotations: annotations.map(serializeAnnotation),
          _server_adds:
            'per-entity one-level neighborhood cards (entity geometry, edges with adjacent faces, vertices), operation tips (api, reads, doc_refs, hint), target summary, viewport snapshot',
        },
        null,
        2,
      ),
    [annotations],
  );

  // -- handlers on stable refs (safe to use from JSX and the controller) -------

  const applySelectionMode = (mode: string): void => {
    if (!mode) return;
    const value = mode as SelectionMode;
    setSelectionMode(value);
    originalViewRef.current?.setSelectionMode(value);
  };

  const applyDrawMode = (mode: string): void => {
    if (!mode) return;
    const value = mode as 'off' | 'lasso';
    drawModeRef.current = value;
    setDrawMode(value);
    if (value === 'off') {
      drawPoints.current = [];
      redrawRef.current();
    }
  };

  const clearDraft = (): void => {
    const view = originalViewRef.current;
    if (view) for (const entry of draft.current.values()) view.removeMark(`${entry.nodeId}::${entry.entityId}`);
    draft.current.clear();
    composerRef.current?.clear();
    currentPolygon.current = null;
    setInspector(null);
    redrawRef.current();
  };

  const startComposerResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = composerHeight;
    const move = (moveEvent: PointerEvent): void => {
      setComposerHeight(Math.round(Math.min(Math.max(startHeight + (startY - moveEvent.clientY), 64), 380)));
    };
    const finish = (): void => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
  };

  const fitBoth = (): void => {
    originalViewRef.current?.frame();
    rebuiltViewRef.current?.frame();
  };

  const recallAnnotation = (annotation: Annotation): void => {
    const view = originalViewRef.current;
    if (view) for (const entry of annotation.entries) view.addMark(entry.nodeId, entry.entityId, annotation.color);
  };

  const removeAnnotation = (annotationId: string): void => removeAnnotationRef.current(annotationId);

  const submit = async (): Promise<void> => {
    const view = originalViewRef.current;
    if (!view || submitting) return;
    setSubmitting(true);
    const snapshot = view.snapshotPng();
    try {
      const result = await agentSession.createSubmission<{ seq: number }>({ annotations: annotationsRef.current.map(serializeAnnotation), note: '', snapshot_png: snapshot });
      setAgentLabel(`submitted #${result.seq} — waiting for agent`);
      setAgentWaiting(true);
      toast(`submission #${result.seq} delivered; agent is reconstructing`);
      loadSubmissionRef.current();
    } catch (error) {
      toast.error(`submit failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSubmitting(false);
    }
  };

  const onBottomTabChange = (value: string): void => {
    setBottomTab(value);
    if (value === 'source') editorRef.current?.requestMeasure();
  };

  // -- controller: the single boot path (mount-once) ---------------------------

  useEffect(() => {
    const originalHost = originalHostRef.current!;
    const rebuiltHost = rebuiltHostRef.current!;
    const annotateCanvas = canvasRef.current!;
    const composerArea = composerAreaRef.current!;
    const sourceHost = sourceEditorHostRef.current!;
    const treeHost = featureTreeHostRef.current!;
    if (!originalHost || !rebuiltHost || !annotateCanvas || !composerArea || !sourceHost || !treeHost) return;

    const originalView = new SceneView(originalHost, { selectionMode: 'face' });
    const rebuiltView = new SceneView(rebuiltHost, { selectionMode: 'face' });
    originalViewRef.current = originalView;
    rebuiltViewRef.current = rebuiltView;

    const setStatus = (message: string): void => {
      toast(message, { duration: 3500 });
    };

    function indexSidecarIds(): void {
      canonicalBySceneId.current.clear();
      sceneIdByCanonical.current.clear();
      nodeIdBySceneId.current.clear();
      for (const node of originalView.nodes) {
        const sidecar = originalView.sidecarFor(node);
        if (!sidecar) continue;
        for (const entity of sidecar.entities) {
          const canonical = typeof entity.topo_id === 'string' ? entity.topo_id : null;
          if (!canonical) continue;
          canonicalBySceneId.current.set(entity.entity_id, canonical);
          sceneIdByCanonical.current.set(canonical, entity.entity_id);
          nodeIdBySceneId.current.set(entity.entity_id, node.node_id);
        }
      }
    }

    function markColor(index: number): string {
      return MARK_COLORS[index % MARK_COLORS.length];
    }

    function composerKind(kind: string): ComposerTokenKind {
      if (kind === 'edge' || kind === 'vertex' || kind === 'face') return kind;
      return 'face';
    }

    function addSelectionEntry(nodeId: string, entityId: string, kind: string, quiet = false): void {
      const canonical = canonicalBySceneId.current.get(entityId);
      if (!canonical || draft.current.has(canonical)) return;
      draft.current.set(canonical, { nodeId, entityId, canonical, kind });
      originalView.addMark(nodeId, entityId, DRAFT_COLOR);
      composer.insertToken({ token: canonical, label: canonical, kind: composerKind(kind) });
      if (!quiet) postSelectEvent([...draft.current.keys()]);
    }

    function toggleSelectionEntry(nodeId: string, entityId: string, kind: string): void {
      const canonical = canonicalBySceneId.current.get(entityId);
      if (canonical && draft.current.has(canonical)) {
        draft.current.delete(canonical);
        originalView.removeMark(`${nodeId}::${entityId}`);
        composer.removeToken(canonical);
        return;
      }
      addSelectionEntry(nodeId, entityId, kind);
    }

    async function inspectEntity(result: PickResult): Promise<void> {
      const canonical = canonicalBySceneId.current.get(result.entityId!);
      const entry = canonical ? draft.current.get(canonical) : undefined;
      if (!entry) return;
      try {
        const descriptor = await agentSession.describeEntity<Record<string, any>>(entry.canonical);
        const adjacency = descriptor.adjacency?.direct?.slice(0, 24) ?? [];
        const rows: string[] = [];
        if (descriptor.geometry?.type) rows.push(`type ${descriptor.geometry.type}`);
        if (descriptor.geometry?.area) rows.push(`area ${Number(descriptor.geometry.area).toFixed(2)} mm²`);
        if (descriptor.geometry?.length) rows.push(`len ${Number(descriptor.geometry.length).toFixed(2)} mm`);
        setInspector({
          canonical: entry.canonical,
          rows: rows.length ? rows : [entry.kind],
          details: JSON.stringify({ geometry: descriptor.geometry, adjacency: descriptor.adjacency }, null, 1).slice(0, 4000),
        });
      } catch {
        /* inspector is best-effort */
      }
    }

    // -- annotation composer + slash suggest ---------------------------------

    const composer: TokenComposer = new TokenComposer({
      placeholder: 'whats your idea to rebuild ?',
      hostClassName:
        're-composer-input block h-full w-full overflow-y-auto bg-transparent px-5 pt-5 pb-12 font-sans text-[12px] leading-relaxed text-ink',
      onChange: () => setCanAdd(!composer.isEmpty()),
      onCommit: () => addAnnotation(),
      onKeydown: (event) => opSuggest.handleKeydown(event),
    });
    composerRef.current = composer;
    composerArea.append(composer.host);

    const opSuggest: OpSuggest = new OpSuggest(composer);
    composerArea.prepend(opSuggest.popup);

    function addAnnotation(): void {
      const text = composer.value().trim();
      const tokens = composer.listTokens();
      const entityTokens = tokens.filter((token) => token.kind !== 'op');
      if (!text && !entityTokens.length) return;
      const entries = entityTokens
        .map((token) => draft.current.get(token.token))
        .filter((entry): entry is DraftEntry => Boolean(entry));
      const operations = [...new Set(tokens.filter((token) => token.kind === 'op').map((token) => token.token.replace(/^op:/, '')))];
      const color = markColor(annotationsRef.current.length);
      const annotation: Annotation = {
        annotation_id: `a${++annotationCounter.current}-${Date.now().toString(36)}`,
        kind: 'free',
        intent: 'free',
        text,
        entries,
        operations,
        screen_polygon: currentPolygon.current ?? undefined,
        color,
        created_at: new Date().toISOString(),
      };
      for (const entry of entries) {
        originalView.removeMark(`${entry.nodeId}::${entry.entityId}`);
        originalView.addMark(entry.nodeId, entry.entityId, color);
      }
      annotationsRef.current.push(annotation);
      setAnnotations([...annotationsRef.current]);
      draft.current.clear();
      composer.clear();
      currentPolygon.current = null;
      void postAnnotation('add', annotation);
    }

    function removeAnnotation(annotationId: string): void {
      const index = annotationsRef.current.findIndex((item) => item.annotation_id === annotationId);
      if (index < 0) return;
      const annotation = annotationsRef.current[index];
      for (const entry of annotation.entries) originalView.removeMark(`${entry.nodeId}::${entry.entityId}`);
      annotationsRef.current.splice(index, 1);
      setAnnotations([...annotationsRef.current]);
      void postAnnotation('remove', annotation);
    }
    removeAnnotationRef.current = removeAnnotation;

    // -- lasso canvas ----------------------------------------------------------

    function sizeAnnotateCanvas(): void {
      const bounds = originalHost.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio, 2);
      annotateCanvas.width = Math.max(1, Math.round(bounds.width * ratio));
      annotateCanvas.height = Math.max(1, Math.round(bounds.height * ratio));
      annotateCanvas.style.width = `${bounds.width}px`;
      annotateCanvas.style.height = `${bounds.height}px`;
      annotateCanvas.getContext('2d')?.setTransform(ratio, 0, 0, ratio, 0, 0);
      renderAnnotationsCanvas();
    }

    function renderAnnotationsCanvas(): void {
      const context = annotateCanvas.getContext('2d');
      if (!context) return;
      const bounds = originalHost.getBoundingClientRect();
      context.clearRect(0, 0, bounds.width, bounds.height);
      for (const annotation of annotationsRef.current) {
        if (!annotation.screen_polygon) continue;
        context.strokeStyle = annotation.color;
        context.lineWidth = 2;
        context.setLineDash([]);
        strokePolygon(context, annotation.screen_polygon);
      }
      if (drawModeRef.current !== 'off' && drawPoints.current.length > 1) {
        context.strokeStyle = DRAFT_COLOR;
        context.lineWidth = 2;
        context.setLineDash([6, 4]);
        strokePolygon(context, drawPoints.current, true);
        context.setLineDash([]);
      }
    }
    redrawRef.current = renderAnnotationsCanvas;

    function strokePolygon(context: CanvasRenderingContext2D, polygon: Array<[number, number]>, open = false): void {
      context.beginPath();
      polygon.forEach(([x, y], index) => (index ? context.lineTo(x, y) : context.moveTo(x, y)));
      if (!open) context.closePath();
      context.stroke();
    }

    function canvasPoint(event: PointerEvent): [number, number] {
      const bounds = annotateCanvas.getBoundingClientRect();
      return [event.clientX - bounds.left, event.clientY - bounds.top];
    }

    annotateCanvas.addEventListener('pointerdown', (event) => {
      if (drawModeRef.current === 'off') return;
      drawingRef.current = true;
      annotateCanvas.setPointerCapture(event.pointerId);
      drawPoints.current = [canvasPoint(event)];
      renderAnnotationsCanvas();
    });

    annotateCanvas.addEventListener('pointermove', (event) => {
      if (!drawingRef.current) return;
      const point = canvasPoint(event);
      const last = drawPoints.current[drawPoints.current.length - 1];
      if (drawModeRef.current === 'lasso' && last && Math.hypot(point[0] - last[0], point[1] - last[1]) < 3) return;
      drawPoints.current.push(point);
      renderAnnotationsCanvas();
    });

    annotateCanvas.addEventListener('pointerup', () => {
      if (!drawingRef.current) return;
      drawingRef.current = false;
      const polygon = drawPoints.current;
      drawPoints.current = [];
      if (polygon.length < 3) {
        renderAnnotationsCanvas();
        return;
      }
      void resolveRegion(polygon);
    });

    async function resolveRegion(polygon: Array<[number, number]>): Promise<void> {
      try {
        const result = await agentSession.resolveRegion<RegionResolveResponse>(originalView.getCameraState(), polygon);
        const wantedKind = originalView.selectionMode === 'vertex' ? 'vertex' : 'face';
        let added = 0;
        for (const canonical of result.entity_ids) {
          const sceneId = sceneIdByCanonical.current.get(canonical);
          const nodeId = sceneId ? nodeIdBySceneId.current.get(sceneId) : undefined;
          if (!sceneId || !nodeId) continue;
          const entity = originalView.entityFor(nodeId, sceneId);
          const kind = entity?.kind ?? 'face';
          if (kind !== wantedKind) continue;
          addSelectionEntry(nodeId, sceneId, kind, true);
          added += 1;
        }
        currentPolygon.current = polygon;
        setStatus(`region resolved: ${added} entities tagged`);
      } catch {
        toast.error('region resolve unreachable');
      }
      renderAnnotationsCanvas();
    }

    // -- picking ---------------------------------------------------------------

    originalView.onPick = (result) => {
      if (drawModeRef.current !== 'off' || !result.entityId) return;
      toggleSelectionEntry(result.nodeId, result.entityId, result.mode);
      if (result.entityId && draft.current.has(canonicalBySceneId.current.get(result.entityId) ?? '')) void inspectEntity(result);
    };

    // -- source panel (CodeMirror) + feature DAG tree ---------------------------

    const editor = new PythonEditor({ parent: sourceHost, theme: reStudioEditorTheme });
    editorRef.current = editor;
    const featureTree = new FeatureTreeView(treeHost, {});

    function showSourceFile(path: string, reveal?: { line: number; endLine: number }): void {
      const content = sourceFilesRef.current.get(path);
      if (content === undefined) return;
      if (path !== currentSourcePathRef.current) {
        currentSourcePathRef.current = path;
        editor.setContent(content);
        setCurrentPath(path);
      }
      if (reveal) editor.revealLines(reveal.line, reveal.endLine);
      else editor.clearHighlight();
    }
    showSourceFileRef.current = showSourceFile;

    function setSourceFile(path: string, content: string, prefer = false): void {
      sourceFilesRef.current.set(path, content);
      if (prefer || currentSourcePathRef.current === null) showSourceFile(path);
      setSourcePaths([...sourceFilesRef.current.keys()]);
    }

    /** FTC header fallback before the agent captures a package with a real DAG. */
    function renderFallbackFeatureTree(source: string): void {
      if (packageModelRef.current) return;
      const rows: Array<{ op: string; label: string }> = [];
      const headerPattern = /^#\s*----\s*feature:\s*(.+?)\s*\((.+?)\)\s*----/gm;
      let match: RegExpExecArray | null;
      while ((match = headerPattern.exec(source))) rows.push({ label: match[1], op: match[2] });
      setFallbackRows(rows);
    }

    // -- artifact / session loading ----------------------------------------------

    async function loadOriginalScene(): Promise<void> {
      try {
        const payload = await agentSession.getScene<{ files: Record<string, string> }>();
        await originalView.loadScene(decodeFiles(payload.files));
        indexSidecarIds();
        sceneBusyRef.current = false;
        setSceneBusy(false);
        setSceneReady(true);
        setStatus('scene ready — select and annotate');
      } catch (error) {
        setSceneStatus(`scene failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    async function loadRebuilt(mtime: number): Promise<void> {
      const response = await fetch(`/api/artifacts/rebuilt.scadpkg?v=${mtime}`);
      if (!response.ok) return;
      const opened = await openCadPackage(new Uint8Array(await response.arrayBuffer()));
      await rebuiltView.loadScene(opened.files);
      setRebuiltState('rebuilt package loaded');
      const manifest = JSON.parse(new TextDecoder().decode(opened.files['scene.json'])) as SceneManifest;
      const federated = buildFederatedFeatureModel(manifest, opened.files);
      packageModelRef.current = federated.model;
      for (const [path, content] of federated.sources) {
        const duplicate = [...sourceFilesRef.current.entries()].some(([, text]) => text === content);
        if (!duplicate) setSourceFile(path, content);
      }
      featureTree.setModel(packageModelRef.current);
      setHasPackage(true);
    }

    async function loadArtifactText(name: 'rebuild.py' | 'evaluation.json', mtime: number): Promise<void> {
      const response = await fetch(`/api/artifacts/${name}?v=${mtime}`);
      if (!response.ok) return;
      const text = await response.text();
      if (name === 'rebuild.py') {
        setRebuildPySeen(true);
        setSourceFile('rebuild.py', text, true);
        renderFallbackFeatureTree(text);
      } else {
        try {
          setEvaluationText(JSON.stringify(JSON.parse(text), null, 2));
        } catch {
          setEvaluationText(text);
        }
      }
    }

    async function loadSubmissionTab(): Promise<void> {
      try {
        setSubmission(await agentSession.getSubmission<SubmissionRecord>());
      } catch {
        setSubmission(null);
      }
    }
    loadSubmissionRef.current = () => void loadSubmissionTab();

    async function loadOperations(): Promise<void> {
      try {
        const payload = await agentSession.listOperations<OperationsPayload>();
        setOperationsState(payload);
        opSuggest.setOperations(payload.operations as SuggestOperation[]);
        if (payload.errors.length) toast(`operation registry: ${payload.errors.join('; ')}`);
      } catch {
        toast.error('operation registry unreachable — slash suggest offline');
      }
    }

    function updateSessionState(session: SessionPayload): void {
      setTargetName(session.target.name ?? 'no target');
      if (session.scene.state === 'ready') {
        setTopStats(
          `${session.scene.body_count ?? '?'} bodies · ${session.scene.face_count ?? '?'} faces · ${session.scene.edge_count ?? '?'} edges · ${annotationsRef.current.length} annotations`,
        );
      } else {
        setTopStats(`scene ${session.scene.state}`);
      }
      let changed = false;
      for (const [name, artifact] of Object.entries(session.artifacts)) {
        const mtime = artifact.mtime ?? 0;
        if (artifact.present && artifactMtimesRef.current[name] !== mtime) {
          changed = true;
          artifactMtimesRef.current[name] = mtime;
          if (name === 'rebuilt.scadpkg') void loadRebuilt(mtime);
          if (name === 'rebuild.py') void loadArtifactText('rebuild.py', mtime);
          if (name === 'evaluation.json') void loadArtifactText('evaluation.json', mtime);
          if (name === 'comparison.png') setComparisonSrc(`/api/artifacts/comparison.png?v=${mtime}`);
        }
        if (!artifact.present && artifactMtimesRef.current[name]) delete artifactMtimesRef.current[name];
      }
      if (changed && session.artifacts['rebuilt.scadpkg']?.present) {
        setAgentLabel('agent artifacts updated');
        setAgentWaiting(false);
      }
    }

    // -- boot ------------------------------------------------------------------

    window.__reDebug = { originalView, rebuiltView, annotations: annotationsRef.current, composer };

    const observer = new ResizeObserver(() => sizeAnnotateCanvas());
    observer.observe(originalHost);
    sizeAnnotateCanvas();

    const poll = window.setInterval(async () => {
      try {
        updateSessionState(await agentSession.getSession<SessionPayload>());
      } catch {
        /* server restarting */
      }
    }, 1200);

    const retryOriginal = window.setInterval(() => {
      if (!sceneBusyRef.current) window.clearInterval(retryOriginal);
      else void loadOriginalScene();
    }, 2500);

    void loadSubmissionTab();
    void loadOperations();
    void loadOriginalScene();

    return () => {
      window.clearInterval(poll);
      window.clearInterval(retryOriginal);
      observer.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -- layout --------------------------------------------------------------------

  return (
    <TooltipProvider>
      <div className="flex h-full min-h-0 flex-col overflow-hidden bg-void font-sans text-ink antialiased">
        {/* top bar */}
        <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
          <div className="flex items-center gap-2.5">
            <span className="grid size-6 -rotate-7 place-items-center border border-lime font-mono text-[10px] font-medium text-lime">RE</span>
            <div className="leading-tight">
              <div className="text-[12px] font-semibold tracking-tight">re-studio</div>
              <div className="font-mono text-[9px] tracking-[0.08em] text-dim uppercase">{targetName}</div>
            </div>
          </div>
          <div className="flex-1 truncate font-mono text-[9px] tracking-[0.04em] text-dim">{topStats}</div>
          <span className={cn('flex items-center gap-1.5 font-mono text-[9px] tracking-[0.04em]', agentWaiting ? 'text-amber' : 'text-dim')}>
            <span className={cn('size-1.5 rounded-full', agentWaiting ? 'animate-pulse bg-amber' : 'bg-lime/70')} />
            {agentLabel}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="sm" onClick={fitBoth}>
                <Maximize2 />
                FIT
              </Button>
            </TooltipTrigger>
            <TooltipContent>fit both viewports</TooltipContent>
          </Tooltip>
          <Button variant="default" size="sm" disabled={!sceneReady || submitting} onClick={() => void submit()}>
            <Send />
            SUBMIT
          </Button>
        </header>

        {/* workspace */}
        <Resizable orientation="horizontal" className="min-h-0 flex-1">
          <ResizablePanel defaultSize="46" minSize="22">
            <div className="flex h-full min-h-0 flex-col">
              {/* toolbar */}
              <div className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-b border-line bg-panel px-3 py-1">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[9px] tracking-[0.14em] text-faint">SELECT</span>
                  <ToggleGroup type="single" value={selectionMode} onValueChange={applySelectionMode}>
                    <ToggleGroupItem value="face">
                      <Square />
                      FACE
                    </ToggleGroupItem>
                    <ToggleGroupItem value="edge">
                      <Slash />
                      EDGE
                    </ToggleGroupItem>
                    <ToggleGroupItem value="vertex">
                      <Dot />
                      VERTEX
                    </ToggleGroupItem>
                  </ToggleGroup>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[9px] tracking-[0.14em] text-faint">DRAW</span>
                  <ToggleGroup type="single" value={drawMode} onValueChange={applyDrawMode}>
                    <ToggleGroupItem value="off">
                      <MousePointer2 />
                      OFF
                    </ToggleGroupItem>
                    <ToggleGroupItem value="lasso">
                      <Lasso />
                      LASSO
                    </ToggleGroupItem>
                  </ToggleGroup>
                </div>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="sm" onClick={clearDraft}>
                      <Eraser />
                      CLEAR
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>clear draft picks</TooltipContent>
                </Tooltip>
              </div>

              {/* target viewport */}
              <div ref={originalHostRef} className={cn('re-viewport relative min-h-0 flex-1 overflow-hidden bg-void', drawMode !== 'off' && 'cursor-crosshair')}>
                <canvas
                  ref={canvasRef}
                  className={cn(
                    'absolute inset-0 z-10',
                    drawMode !== 'off' ? 'pointer-events-auto cursor-crosshair' : 'pointer-events-none',
                  )}
                />

                {/* committed annotations float as capsules over the viewer bottom */}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex flex-wrap content-end gap-2 p-3">
                  {annotations.map((annotation) => (
                    <CapsulePill
                      key={annotation.annotation_id}
                      annotation={annotation}
                      opCategory={opCategory}
                      onRemove={() => removeAnnotation(annotation.annotation_id)}
                      onRecall={() => recallAnnotation(annotation)}
                    />
                  ))}
                </div>

                {inspector && <InspectorCard data={inspector} onClose={() => setInspector(null)} />}

                {sceneBusy && (
                  <div className="absolute inset-0 z-30 flex items-center justify-center gap-2.5 bg-void/80 text-[11px] text-dim">
                    <span className="size-4 animate-spin rounded-full border border-edge border-t-lime" />
                    {sceneStatus}
                  </div>
                )}
              </div>

              {/* composer — the panel IS the input; drag the top hairline to resize */}
              <div ref={composerAreaRef} className="relative shrink-0 border-t border-line bg-panel" style={{ height: composerHeight }}>
                <div
                  onPointerDown={startComposerResize}
                  title="drag to resize"
                  className="absolute inset-x-0 top-0 z-30 h-1.5 cursor-row-resize transition-colors hover:bg-lime/30"
                />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="default" size="icon" className="absolute right-3.5 bottom-3 rounded-full" disabled={!canAdd} title="add annotation" onClick={() => composerRef.current?.commit()}>
                      <Plus />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>add annotation</TooltipContent>
                </Tooltip>
              </div>
            </div>
          </ResizablePanel>

          <ResizableHandle className="w-1 cursor-col-resize">
            <HandleLine />
          </ResizableHandle>

          <ResizablePanel defaultSize="54" minSize="22">
            <Resizable orientation="vertical" className="min-h-0">
              {/* rebuilt viewport / comparison */}
              <ResizablePanel defaultSize="52" minSize="12">
                <Tabs value={rebuiltTab} onValueChange={setRebuiltTab} className="h-full min-h-0">
                  <TabsList className="w-full">
                    <TabsTrigger value="model">
                      <Box />
                      REBUILT MODEL
                    </TabsTrigger>
                    <TabsTrigger value="comparison">
                      <Columns2 />
                      COMPARISON
                    </TabsTrigger>
                    <span className="ml-auto pr-3 font-mono text-[9px] text-dim">{rebuiltState}</span>
                  </TabsList>
                  <TabsContent forceMount value="model">
                    <div ref={rebuiltHostRef} className="re-viewport h-full overflow-hidden bg-void" />
                  </TabsContent>
                  <TabsContent forceMount value="comparison">
                    {comparisonSrc ? (
                      <img src={comparisonSrc} alt="comparison" className="h-full w-full bg-void object-contain p-2" />
                    ) : (
                      <div className="grid h-full place-items-center text-[11px] text-dim">no comparison yet</div>
                    )}
                  </TabsContent>
                </Tabs>
              </ResizablePanel>

              <ResizableHandle className="h-1 cursor-row-resize">
                <HandleLine vertical />
              </ResizableHandle>

              {/* dock: source / features / evaluation / submission / context */}
              <ResizablePanel defaultSize="48" minSize="15">
                <Tabs value={bottomTab} onValueChange={onBottomTabChange} className="h-full min-h-0">
                  <TabsList className="w-full overflow-x-auto">
                    <TabsTrigger value="source">
                      <SquareCode />
                      SOURCE
                    </TabsTrigger>
                    <TabsTrigger value="features">
                      <Workflow />
                      FEATURE
                    </TabsTrigger>
                    <TabsTrigger value="evaluation">
                      <ClipboardCheck />
                      EVALUATION
                    </TabsTrigger>
                    <TabsTrigger value="submission">
                      <Inbox />
                      SUBMISSION
                    </TabsTrigger>
                    <TabsTrigger value="context">
                      <Eye />
                      CONTEXT
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent forceMount value="source" className="overflow-hidden">
                    <div className="flex h-full min-h-0 flex-col">
                      {sourcePaths.length > 1 && (
                        <div className="scroll-thin flex shrink-0 gap-1 overflow-x-auto border-b border-line bg-panel px-2 py-1.5">
                          {sourcePaths.map((path) => (
                            <button
                              key={path}
                              type="button"
                              onClick={() => showSourceFileRef.current(path)}
                              className={cn(
                                'shrink-0 rounded-md border px-2.5 py-1 font-mono text-[10px] transition-colors',
                                path === currentPath ? 'border-edge bg-panel text-ink' : 'border-line bg-inset text-dim hover:text-ink',
                              )}
                            >
                              {path}
                            </button>
                          ))}
                        </div>
                      )}
                      <div ref={sourceEditorHostRef} className="min-h-0 flex-1 overflow-hidden" />
                    </div>
                  </TabsContent>

                  <TabsContent forceMount value="features" className="scroll-thin overflow-auto">
                    <div ref={featureTreeHostRef} hidden={!hasPackage} />
                    {!hasPackage && (
                      <div className="flex flex-col gap-1.5 p-2.5">
                        {fallbackRows.length ? (
                          fallbackRows.map((row, index) => (
                            <div key={index} className="flex items-baseline gap-2.5 rounded-lg border border-line bg-inset px-2.5 py-1.5 text-[11px] hover:border-edge">
                              <span className="font-mono text-[10px] text-[#91b8ed]">{row.op}</span>
                              <span className="text-ink/80">{row.label}</span>
                            </div>
                          ))
                        ) : (
                          <div className="p-1 text-[11px] text-dim">
                            {rebuildPySeen ? 'no feature headers found in rebuild.py' : 'waiting for the agent — rebuild.py will appear here'}
                          </div>
                        )}
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent forceMount value="evaluation" className="scroll-thin overflow-auto">
                    <pre className="min-w-0 p-3 font-mono leading-relaxed whitespace-pre text-[11px] text-ink/85">{evaluationText}</pre>
                  </TabsContent>

                  <TabsContent forceMount value="submission" className="scroll-thin overflow-auto">
                    <SubmissionView submission={submission} />
                  </TabsContent>

                  <TabsContent forceMount value="context" className="scroll-thin overflow-auto">
                    <pre className="min-w-0 p-3 font-mono leading-relaxed whitespace-pre text-[11px] text-ink/85">{contextText}</pre>
                  </TabsContent>
                </Tabs>
              </ResizablePanel>
            </Resizable>
          </ResizablePanel>
        </Resizable>

        <Toaster />
      </div>
    </TooltipProvider>
  );
}
