import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CellEditor, type NotebookCell, type NotebookFeature, type ParamMeta } from "@/components/CellEditor";
import type { ParamValue } from "@/components/ParamControl";
import { Dock } from "@/components/Dock";
import { FeatureDialog, type DialogRequest } from "@/components/FeatureDialog";
import { SelectionBar } from "@/components/SelectionBar";
import { selectionAnchorMm } from "@/lib/selection-anchor";
import { SketchScene } from "@/components/SketchScene";
import { CommandBar } from "@/components/CommandBar";
import { FEATURE_ICONS } from "@/components/feature-icons";
import { FeatureTree, type TreeSketches } from "@/components/FeatureTree";
import { assemblyCommands, commandsFromSpecs, fitScore, plainLabel, selectionContext, selectionHint, visibleCommands, whenFor, type Command } from "@/lib/commands";
import { ModeSwitch, type EditorMode } from "@/components/ModeSwitch";
import { MANUAL_MODE } from "@/lib/manual-mode";
import { Button } from "@/components/ui/button";
import { AssemblyPanel } from "@/components/AssemblyPanel";
import { ConnectorGizmos, type Gizmo } from "@/components/ConnectorGizmos";
import { WorkplanePatches } from "@/components/WorkplanePatches";
import { TagSplits, parseTagSplits, type TagSplit } from "@/components/TagSplits";
import { NewNotebookPrompt } from "@/components/NewNotebookPrompt";
import { FloatingPanels } from "@/components/FloatingPanels";
import { OperationPanel } from "@/components/OperationPanel";
import { PressPullHandle } from "@/components/PressPullHandle";
import { addPick, featureParams, pickSlot, quickStart, refLabel, removePick } from "@/lib/operation-session";
import { createSettler, SETTLE_MS } from "@/lib/settle";
import { PartialNotice } from "@/components/PartialModel";
import { describePartial, parsePartial, samePartial, type PartialModel } from "@/lib/partial";
import { WorkplanePlacePanel, WorkplanePlacer, type PlaceBase, type PlaceMode } from "@/components/WorkplanePlacer";
import { CurveDrawer } from "@/components/CurveDrawer";
import { CurveLines, curveEnds, parseCurves, type CurveSample } from "@/components/CurveLines";
import { splitPath, type CurveDoc, type DrawPlane } from "@/lib/curve3d";
import { NAMED_FRAMES, ZERO_PLACE, cleanValues, faceFrame, placedFrame, type PlaceFrame, type PlaceValues } from "@/lib/workplane-place";
import { parseWorkplanes, resolvePlane, workplanePlane, workplaneRequest, type WorkplaneFrame } from "@/lib/workplanes";
import { fitDistanceMm } from "@/lib/sketch-view";
import { viewPose } from "@/lib/sketch-plane";
import * as THREE from "three";
import { addConnectorFrame, connectorFrameFromFace, setConnectorsCommand, setRef } from "@/lib/assembly";
import { useAssemblyEditor, useConnectorDraft } from "@/lib/useAssembly";
import { Header } from "@/components/Header";
import { Inspector } from "@/components/Inspector";
import { SketchMode, type FaceCheck, type SketchAfter, type SketchSession } from "@/components/sketch/SketchMode";
import { LoadingMask } from "@/components/LoadingMask";
import { ModuleView, type ModuleState } from "@/components/ModuleView";
import { NotebookList } from "@/components/NotebookList";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { deleteNotebook, getWorkspace, newNotebook, openNotebook, postViewport, type ModuleRow, type NotebookRow } from "@/lib/api";
import { SURFACE_NODE_PREFIX, isSurfaceNode, parsePreview, previewSummary, type PreviewPart } from "@/lib/preview";
import { closedLoop, gordonFamilies, loopNormal } from "@/lib/curve-net";
import { EnvelopeSocket, type Envelope } from "@/lib/envelope";
import { emptyDoc, normalizeDoc } from "@/lib/sketch";
import { frameFromEntity, type PlaneSpec } from "@/lib/sketch-plane";
import { useFeatures } from "@/lib/useFeatures";
import { describeSketch, nextSketchSelection, readHidden, sketchCentre, sketchInfos, toggleHidden, writeHidden } from "@/lib/sketch-scene";
import { useSketchShapes } from "@/lib/useSketchShapes";
import type { Vec3 } from "@/lib/sketch-plane";
import { PALETTES } from "@/scene/theme";
import { assertCellRan, cellFailure, isCellCommand, pickedPayload, suggestName, type FeatureCommand, type FeatureRow, type SelectionPayload, type Spec } from "@/lib/features";
import { useRunLog } from "@/lib/runlog";
import { useTheme } from "@/lib/theme";
import { selectionPayload, variableNames, type SelectionItem } from "@/lib/selection";
import { cn } from "@/lib/utils";
import { Boxes, Cable, Play, Square } from "lucide-react";
import { Viewport, type PickResult, type SelectionMode } from "@/scene/Viewport";
import type { SceneView } from "@/scene/scene-view";
import { t, useI18n } from "@/i18n";

/** The pick intents and their keys: 1 vertex, 2 edge, 3 face, 4 solid (Plasticity's order), 5 component, 6 sketch. */
/** How long the left column slides from one mode to the other. */
const MODE_SLIDE_MS = 380;

const ALL_MODES: { mode: SelectionMode; label: string; key: string }[] = [
  { mode: "component", label: "comp", key: "5" },
  { mode: "solid", label: "solid", key: "4" },
  { mode: "face", label: "face", key: "3" },
  { mode: "edge", label: "edge", key: "2" },
  { mode: "vertex", label: "vert", key: "1" },
  { mode: "sketch", label: "sketch / curve / surface", key: "6" },
];
/** What a click can pick; sketches and curves are manual mode's. */
const MODES = ALL_MODES.filter((item) => MANUAL_MODE || item.mode !== "sketch");

/** Editor application: left = notebook (cells, workspace), middle = the live
 * model, right = the selection. The model is the in-memory scadpkg the kernel
 * publishes whenever the cells settle; picking in the viewport writes the
 * selection into the notebook (see `selection.set`). */
/** The tabs of each mode; the workspace tab is in both (opening or making a notebook is not a code-only thing). */
const MANUAL_TABS = ["features", "assembly"];
const CODE_TABS = ["notebook", "module"];

export function App() {
  useI18n(); // a change of language renders the whole editor again
  const viewRef = useRef<SceneView | null>(null);
  // Whether a model of the open notebook is on screen (it may be the last run's,
  // restored while the kernel boots): then nothing is being waited for.
  const hasModel = useRef(false);
  const socketRef = useRef<EnvelopeSocket | null>(null);

  const [notebooks, setNotebooks] = useState<NotebookRow[]>([]);
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [moduleView, setModuleView] = useState<ModuleState | null>(null);
  // Two modes, never mixed on one page: manual (features, assemblies) and code (notebook, workspace).  The left tab says which.
  const [leftTab, setLeftTab] = useState(MANUAL_MODE ? "features" : "notebook");
  const [sharedMode, setSharedMode] = useState<EditorMode>(MANUAL_MODE ? "manual" : "code"); // the mode the workspace tab is shown in
  const mode: EditorMode = MANUAL_TABS.includes(leftTab) ? "manual" : CODE_TABS.includes(leftTab) ? "code" : sharedMode;
  if (mode !== sharedMode) setSharedMode(mode);
  const lastTab = useRef<Record<EditorMode, string>>({ manual: "features", code: "notebook" });
  lastTab.current[mode] = leftTab;
  // A mode change slides the left column like the switch's thumb: the two modes' panels sit side by side on one strip
  // (manual on the left, code on the right) and it moves to the other one; the mode is changed when it has arrived.
  const [modeTarget, setModeTarget] = useState<EditorMode | null>(null);
  const moving = modeTarget !== null;
  const changeMode = (target: EditorMode) => {
    if (moving || target === mode) return;
    setModeTarget(target);
    window.setTimeout(() => {
      setSharedMode(target);
      setLeftTab(lastTab.current[target]);
      setModeTarget(null);
    }, window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 0 : MODE_SLIDE_MS);
  };
  const [notebook, setNotebook] = useState<string | null>(null);
  const notebookRef = useRef(notebook);
  notebookRef.current = notebook;
  // an operation or a drawing was started with no notebook open: ask for one first
  const [needNotebook, setNeedNotebook] = useState(false);
  /** True (and the person is asked to create a notebook) when none is open: every operation is written into one. */
  const noNotebook = useCallback((): boolean => {
    if (notebookRef.current) return false;
    setNeedNotebook(true);
    return true;
  }, []);
  // The notebook the server says is open (workspace-relative): what the list
  // highlights.  It changes the moment another is asked for, not when its
  // kernel is up, and a late answer of the workspace list cannot undo it.
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [kernelAlive, setKernelAlive] = useState(false);
  const [status, setStatus] = useState(() => t("Connecting…"));

  const [params, setParams] = useState<ParamMeta[]>([]);
  const [cells, setCells] = useState<NotebookCell[]>([]);
  const [features, setFeatures] = useState<NotebookFeature[]>([]);
  const [picked, setPicked] = useState<Omit<SelectionItem, "variable">[]>([]);
  // The notebook's workplanes as the kernel reported them, and the one Space made (or chose) last: new sketches go on it.
  const [workplanes, setWorkplanes] = useState<WorkplaneFrame[]>([]);
  const [tagSplits, setTagSplits] = useState<TagSplit[]>([]);
  // A cell failed: the model shown is the one before it (the preview says which step failed); null when it is whole.
  const [partial, setPartial] = useState<PartialModel | null>(null);
  const partialRef = useRef<PartialModel | null>(null);
  const cellTitles = useMemo(() => new Map(cells.map((cell) => [cell.id, cell.title ?? ""])), [cells]);
  const [curves, setCurves] = useState<CurveSample[]>([]);
  const curvesRef = useRef(curves);
  curvesRef.current = curves;
  // A workplane being placed by hand (Space): its base, the numbers the handles write, move or turn, its name.
  // A workplane, or a connector of the part, being placed by hand: its base, the numbers the handles write, move or turn,
  // its name.
  const [placing, setPlacing] = useState<{ kind: "workplane" | "connector"; base: string; values: PlaceValues; mode: PlaceMode; name: string; face: { item: SelectionItem; frame: PlaceFrame } | null; error: string | null } | null>(null);
  const placingRef = useRef(placing);
  placingRef.current = placing;
  // A 3D curve being drawn in the viewport (W): the plane it starts on, the error of a failed commit.
  const [drawing, setDrawing] = useState<{ plane: string; error: string | null } | null>(null);
  const drawingRef = useRef(drawing);
  drawingRef.current = drawing;
  const [activeWorkplane, setActiveWorkplane] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("solid");
  const [sceneVersion, setSceneVersion] = useState(0);
  // The workspace is veiled while a model is being made: the kernel starting, a
  // notebook opening, a module reloading, every cell running.  It ends when the
  // model arrives (`package`) or the work fails.  Interactive rebuilds (a
  // slider, one cell) are not veiled.
  const [loading, setLoading] = useState<string | null>("connecting");

  // GUI features: the REST state is richer than `notebook.features`, so it is refreshed on every cells event.
  const gui = useFeatures();
  const refreshFeatures = gui.refresh;
  const [dialog, setDialog] = useState<DialogRequest | null>(null);
  const dialogRef = useRef(dialog);
  dialogRef.current = dialog;
  const [guiBusy, setGuiBusy] = useState(false);
  const [guiError, setGuiError] = useState<string | null>(null);
  const modeBeforeDialog = useRef<SelectionMode | null>(null);

  // Sketch mode: drawing happens in the viewport (see components/sketch). `plane: null` is the plane choice.
  const [sketchSession, setSketchSession] = useState<SketchSession | null>(null);
  const [sketchNotice, setSketchNotice] = useState<string | null>(null);
  const sketchCounter = useRef(0);
  const modeBeforeSketch = useRef<SelectionMode | null>(null);
  const sketching = sketchSession !== null;
  const sketchingRef = useRef(false);
  sketchingRef.current = sketching;
  const choosingRef = useRef(false);
  choosingRef.current = sketchSession !== null && sketchSession.plane === null;
  const infoWaiters = useRef(new Map<string, (entity: { properties?: Record<string, unknown>; geometry?: Record<string, unknown> } | null) => void>());

  // Assembly: the layout draft, the part's own connector draft, and what the viewport draws for them.
  const asm = useAssemblyEditor(gui.state, currentPath);
  const conn = useConnectorDraft(gui.state, currentPath);

  // Sketches as objects of the scene: the notebook's sketch features (solved by the SDK, drawn in the viewport), which of them a
  // person hid (remembered per notebook), which are selected or under the pointer, and the arrow of the push a form describes.
  // A sketch on a workplane is drawn where the kernel says that workplane is now (its face may have moved).
  const sketchList = useMemo(
    () => sketchInfos(gui.state.features).map((info) => ({ ...info, doc: { ...info.doc, plane: resolvePlane(info.doc.plane, workplanes) } })),
    [gui.state.features, workplanes],
  );
  const sketchShapes = useSketchShapes(sketchList);
  const [hiddenSketches, setHiddenSketches] = useState<Set<string>>(() => new Set());
  const hiddenRef = useRef(hiddenSketches);
  hiddenRef.current = hiddenSketches;
  useEffect(() => setHiddenSketches(readHidden(currentPath)), [currentPath]);
  const toggleSketchHidden = useCallback(
    (name: string) => {
      const next = toggleHidden(hiddenRef.current, name);
      writeHidden(currentPath, next);
      setHiddenSketches(next);
    },
    [currentPath],
  );
  const [pickedSketches, setPickedSketches] = useState<string[]>([]);
  /** The 3D curves picked (with the sketches: the sketch selection mode picks both). */
  const [pickedCurves, setPickedCurves] = useState<string[]>([]);
  const [hoverCurve, setHoverCurve] = useState<string | null>(null);
  /** The notebook's surfaces the preview shows (face and shell values no later cell builds on), and those picked. */
  const [surfaces, setSurfaces] = useState<string[]>([]);
  const surfacesRef = useRef(surfaces);
  surfacesRef.current = surfaces;
  const [pickedSurfaces, setPickedSurfaces] = useState<string[]>([]);
  // Sketches are drawn while they are what a click picks, while one is picked or edited, and while a form takes a
  // sketch profile; otherwise they would only clutter the model.
  const dialogTakesProfile = !!dialog?.spec.slots.some((slot) => slot.kind === "profile");
  const sketchesShown = selectionMode === "sketch" || pickedSketches.length > 0 || sketchSession !== null || dialogTakesProfile;
  const shownSketches = useMemo(
    () => (sketchesShown ? hiddenSketches : new Set(sketchList.map((info) => info.name))),
    [sketchesShown, hiddenSketches, sketchList],
  );
  const [hoverSketch, setHoverSketch] = useState<string | null>(null);
  const [pushArrow, setPushArrow] = useState<{ sketch: string; direction: Vec3; distance: number } | null>(null);
  const [barNote, setBarNote] = useState<string | null>(null);
  // A sketch that is gone (deleted, undone) is no longer selected.
  useEffect(() => {
    setPickedSketches((previous) => (previous.every((name) => sketchList.some((info) => info.name === name)) ? previous : previous.filter((name) => sketchList.some((info) => info.name === name))));
  }, [sketchList]);

  const kind = notebooks.find((row) => row.path === currentPath)?.kind ?? null;
  const theme = useTheme();
  const log = useRunLog();
  const running = cells.some((cell) => cell.status === "running" || cell.status === "queued");
  const handleStop = useCallback(() => {
    socketRef.current?.send({ type: "interrupt.request" });
    setLoading(null);
    log.push("info", t("stop requested"));
    log.resetBatch();
  }, [log.push, log.resetBatch]);

  const selection: SelectionItem[] = useMemo(() => {
    const names = variableNames(picked);
    return picked.map((item, index) => ({ ...item, variable: names[index] }));
  }, [picked]);

  // -- package → viewport -------------------------------------------------------

  // Camera framing is disruptive during slider drags; frame once per notebook.
  const framedNotebook = useRef<string | null>(null);
  // The parts of the preview on screen, by key: a frame leaves out the ones a page has (see lib/preview.ts).
  const partCache = useRef<Map<string, PreviewPart>>(new Map());

  const loadPreviewBytes = useCallback(async (buffer: ArrayBuffer, name: string | null) => {
    const view = viewRef.current;
    if (!view) return;
    try {
      const preview = parsePreview(buffer, partCache.current);
      if (preview.missing.length) {
        // The frame left out parts this page does not hold: ask for the whole model.
        socketRef.current?.send({ type: "preview.resync" });
        return;
      }
      partCache.current = preview.parts; // the parts on screen: the next frame may leave them out
      view.loadPreview(preview);
      // a sketch made into a face is drawn by the sketch layer: its surface node stays hidden
      const sketchNames = new Set(sketchListRef.current.map((info) => info.name));
      const surfaceNodes = preview.nodes.filter((node) => isSurfaceNode(node.nodeId) && !sketchNames.has(node.definitionId));
      for (const node of preview.nodes) if (isSurfaceNode(node.nodeId) && sketchNames.has(node.definitionId)) view.engine.setNodeVisible(node.nodeId, false);
      setSurfaces(surfaceNodes.map((node) => node.definitionId));
      setStatus(previewSummary(preview.nodes));
      // the first model of a notebook is framed (a notebook with no solid yet has nothing to frame)
      if (framedNotebook.current !== name && preview.nodes.length > 0) {
        view.frame();
        framedNotebook.current = name;
      }
      setSceneVersion((version) => version + 1);
      const solids = preview.nodes.length - preview.nodes.filter((node) => isSurfaceNode(node.nodeId)).length;
      log.push(
        "ok",
        solids === 0
          ? surfaceNodes.length ? t("{{count}} surfaces shown, no solid yet", { count: surfaceNodes.length }) : t("no solid yet")
          : t("model shown: {{summary}}", { summary: previewSummary(preview.nodes) }),
      );
    } catch (error) {
      log.push("error", error instanceof Error ? error.message : t("unable to open the preview"));
    }
  }, [log.push]);

  // -- socket + lifecycle --------------------------------------------------------

  useEffect(() => {
    const socket = new EnvelopeSocket(`ws://${window.location.host}/ws`);
    socketRef.current = socket;

    const refreshWorkspace = () =>
      void getWorkspace().then((data) => {
        setNotebooks(data.notebooks);
        setModules(data.modules ?? []);
        setCurrentPath((path) => path ?? data.notebooks.find((row) => row.current)?.path ?? null);
      });

    socket.on("hello", (envelope) => {
      setNotebook((envelope["notebook"] as string) ?? null);
      setCurrentPath((envelope["path"] as string) ?? null);
      // an empty workspace: the way forward is the workspace tab's "new"
      if (!envelope["notebook"]) setLeftTab("workspace");
      setKernelAlive(Boolean(envelope["kernel"]));
      refreshFeatures();
      // No notebook: nothing to wait for. Else the model is on its way.
      if (hasModel.current) return;
      const stage = envelope["notebook"] ? (envelope["kernel"] ? t("building the model") : t("starting the kernel")) : null;
      setLoading(stage);
      setStatus(stage ? `${stage}…` : t("No notebook yet: create one in the workspace tab"));
      refreshWorkspace();
    });

    // Another notebook is being opened: drop the old model and its state now,
    // the kernel takes a few seconds to boot and publish the new one.
    socket.on("opening", (envelope) => {
      hasModel.current = false;
      viewRef.current?.clearScene();
      framedNotebook.current = null;
      setCells([]);
      setParams([]);
      setFeatures([]);
      setPicked([]);
      setDialog(null);
      setSketchSession(null);
      // what the server sends of a model (and replays to a new page) is the open notebook's: none of it carries over
      setWorkplanes([]);
      setTagSplits([]);
      setCurves([]);
      partialRef.current = null;
      setPartial(null);
      setPlacing(null);
      setDrawing(null);
      setActiveWorkplane(null);
      setGuiError(null);
      setSketchNotice(null);
      setHiddenSketches(new Set());
      setPickedSketches([]);
      setPickedCurves([]);
      setPickedSurfaces([]);
      setHoverSketch(null);
      setPushArrow(null);
      setBarNote(null);
      refreshFeatures();
      setNotebook(String(envelope["notebook"] ?? ""));
      setCurrentPath((envelope["path"] as string) ?? null);
      setStatus(`${t("opening {{name}}", { name: envelope["notebook"] })}…`);
      setLoading(t("opening {{name}}", { name: envelope["notebook"] }));
      log.resetBatch();
      log.push("info", t("opening {{name}}", { name: envelope["notebook"] }));
      setSceneVersion((version) => version + 1);
      refreshWorkspace();
    });

    socket.on("params.schema", (envelope) => {
      const vars = (envelope["vars"] as ParamMeta[] | undefined) ?? [];
      setParams(vars.map((param) => ({ ...param })));
    });

    socket.on("params.values", (envelope) => {
      const values = envelope["values"] as Record<string, number | boolean>;
      setParams((previous) =>
        previous.map((param) => (param.id in values ? { ...param, value: values[param.id] } : param)),
      );
    });

    socket.on("module", (envelope) => {
      if (!envelope["path"]) {
        setModuleView(null);
        setLeftTab((tab) => (tab === "module" ? "notebook" : tab));
        return;
      }
      const state = envelope as unknown as ModuleState;
      setModuleView(state);
      if (state.origin === "open") setLeftTab("module");
    });

    // The live state of a cell's run: its button is run or stop by it.
    socket.on("cell.status", (envelope) => {
      const id = String(envelope["id"]);
      const status = String(envelope["status"]);
      setCells((previous) => previous.map((cell) => (cell.id === id ? { ...cell, status } : cell)));
      log.cellStatus(id, status, (envelope["title"] as string | null) ?? null);
    });

    socket.on("notebook.cells", (envelope) => {
      const next = (envelope["cells"] as NotebookCell[]) ?? [];
      setCells(next);
      log.knowCells(next);
      refreshFeatures();
    });
    // A notebook was added or removed under the workspace (an agent wrote one).
    socket.on("workspace.changed", () => refreshWorkspace());
    // The server dropped an edit made on a cell that had changed on disk.
    socket.on("cell.conflict", (envelope) => {
      const mine = String(envelope["mine"] ?? "");
      log.push("error", `${t("a cell changed on disk while you were editing it: kept the file's version. Your unsaved text was:")}\n${mine.length > 600 ? `${mine.slice(0, 600)}…` : mine}`);
    });
    socket.on("notebook.features", (envelope) => setFeatures((envelope["features"] as NotebookFeature[]) ?? []));
    socket.on("workplanes", (envelope) => setWorkplanes(parseWorkplanes(envelope["workplanes"])));
    socket.on("tag_splits", (envelope) => setTagSplits(parseTagSplits(envelope["splits"])));
    socket.on("curves", (envelope) => setCurves(parseCurves(envelope["curves"])));

    socket.on("preview", (envelope) => {
      setLoading(null);
      const shown = hasModel.current;
      hasModel.current = true;
      // Every preview says whether it is whole or the model before a failing step (an unchanged one too); a new failure
      // is noted in the log once (the cell's own error is logged already), not on every slider tick that fails the same way.
      const nextPartial = parsePartial(envelope["partial"]);
      if (nextPartial && !samePartial(partialRef.current, nextPartial)) {
        const { title, reason } = describePartial(nextPartial);
        log.push("info", t("showing {{what}}: {{reason}}", { what: title, reason }));
      }
      partialRef.current = nextPartial;
      setPartial(nextPartial);
      // The kernel published the model that is already on screen: nothing to
      // reload.  (A page that has none yet, a refresh replaying this envelope, needs it.)
      if (envelope["unchanged"] && shown) {
        log.modelShown();
        return;
      }
      // The model came with the event (one binary frame); a bare envelope without it is only a notice.
      const bytes = envelope["bytes"];
      if (bytes instanceof ArrayBuffer) void loadPreviewBytes(bytes, (envelope["name"] as string) ?? null);
      log.modelShown();
    });

    // The details of a picked entity (a preview carries none), asked for when it was picked.
    socket.on("entity.info", (envelope) => {
      const entityId = String(envelope["entity_id"]);
      const entity = envelope["entity"] as { properties?: Record<string, unknown>; geometry?: Record<string, unknown>; tags?: string[] } | null;
      infoWaiters.current.get(entityId)?.(entity);
      setPicked((previous) =>
        previous.map((item) =>
          item.entityId === entityId
            ? { ...item, pending: false, properties: entity?.properties ?? item.properties ?? {}, geometry: entity?.geometry ?? item.geometry ?? {}, tags: entity?.tags ?? item.tags }
            : item,
        ),
      );
    });

    // Messages of the server.  Errors go to the log (the dock opens on one), not the header.
    socket.on("status", (envelope) => {
      if (typeof envelope["error"] === "string") {
        if (envelope["error"]) {
          log.push("error", envelope["error"]);
          setLoading(null);
        }
      } else if (typeof envelope["info"] === "string") {
        setStatus(t(envelope["info"]));
        log.push("info", t(envelope["info"]));
        setLoading(null); // a notice ends a wait as well (an empty notebook has no model to wait for)
      } else if (typeof envelope["working"] === "string") {
        setStatus(envelope["working"]);
        log.push("run", envelope["working"]);
        setLoading(envelope["working"].replace(/…$/, ""));
      } else if (typeof envelope["exported"] === "string") {
        setStatus(t("exported {{path}}", { path: envelope["exported"] }));
        log.push("ok", t("exported {{file}}", { file: envelope["exported"] }));
      } else if (typeof envelope["created"] === "string") {
        setStatus(t("created {{path}}", { path: envelope["created"] }));
        log.push("ok", t("created {{name}}", { name: envelope["created"] }));
      }
    });

    socket.connect();
    return () => socket.close();
  }, [loadPreviewBytes, refreshFeatures, log.push, log.cellStatus, log.knowCells, log.resetBatch, log.modelShown]);

  // -- selection -------------------------------------------------------------------

  /** The details of one entity from the kernel (null when it does not answer in time). */
  const askEntity = useCallback(
    (nodeId: string, entityId: string) =>
      new Promise<{ properties?: Record<string, unknown>; geometry?: Record<string, unknown> } | null>((resolve) => {
        const timer = window.setTimeout(() => {
          infoWaiters.current.delete(entityId);
          resolve(null);
        }, 5000);
        infoWaiters.current.set(entityId, (entity) => {
          window.clearTimeout(timer);
          infoWaiters.current.delete(entityId);
          resolve(entity);
        });
        socketRef.current?.send({ type: "entity.info", entity_id: entityId, node_id: nodeId });
      }),
    [],
  );

  const choosePlane = useCallback((plane: PlaneSpec) => {
    setSketchNotice(null);
    setSketchSession((session) => (session ? { ...session, plane, doc: { ...session.doc, plane } } : session));
  }, []);

  /** What a face is to a sketch: its plane frame (null when it is not flat) and the kind of surface.  The kernel is asked once
   * per face (concurrent askers share the answer); a pick that already carries its details is not asked about. */
  const faceCache = useRef(new Map<string, Promise<{ frame: ReturnType<typeof frameFromEntity>; type: string | null }>>());
  const resolveFace = useCallback(
    (nodeId: string, entityId: string, entity?: { properties?: Record<string, unknown> | null; geometry?: Record<string, unknown> | null } | null) => {
      const key = `${nodeId}::${entityId}`;
      const cached = faceCache.current.get(key);
      if (cached) return cached;
      const answer = (async () => {
        let geometry = entity?.geometry ?? undefined;
        let properties = entity?.properties ?? undefined;
        if (!geometry || Object.keys(geometry).length === 0) {
          const info = await askEntity(nodeId, entityId);
          geometry = info?.geometry;
          properties = info?.properties;
        }
        const type = typeof geometry?.type === "string" ? geometry.type : null;
        return { frame: geometry ? frameFromEntity(geometry, properties) : null, type };
      })();
      faceCache.current.set(key, answer);
      return answer;
    },
    [askEntity],
  );
  useEffect(() => {
    faceCache.current.clear();
  }, [sceneVersion]);
  const faceCheck = useCallback(
    async (result: PickResult): Promise<FaceCheck> => {
      if (!result.entityId) return { planar: false, type: null };
      const face = await resolveFace(result.nodeId, result.entityId, result.entity);
      return { planar: face.frame !== null, type: face.type };
    },
    [resolveFace],
  );
  const refusal = (type: string | null) => (type ? t("This face is a {{type}}: a sketch needs a flat face. Pick a flat face or a datum plane.", { type: type.toLowerCase() }) : t("This face is curved: a sketch needs a flat face. Pick a flat face or a datum plane."));

  /** While the sketch plane is being chosen a face pick means "sketch on this face" and never reaches the selection. */
  const pickSketchFace = useCallback(
    async (result: PickResult) => {
      if (!result.entityId || result.mode !== "face") return;
      const face = await resolveFace(result.nodeId, result.entityId, result.entity);
      if (!face.frame) {
        setSketchNotice(refusal(face.type));
        return;
      }
      choosePlane(face.frame);
    },
    [resolveFace, choosePlane],
  );

  const leftTabRef = useRef(leftTab);
  leftTabRef.current = leftTab;
  const selectComponent = asm.setSelected;
  /** The session's pick editor (declared with the session below): a click during an operation goes to it. */
  const editSessionPicksRef = useRef<(items: SelectionPayload[]) => void>(() => {});
  const handlePick = useCallback((result: PickResult) => {
    if (placingRef.current || drawingRef.current) return; // a click on the handles, or a curve's point, is not a pick
    if (dialogRef.current?.spec.id === "hole") return; // a click places the hole (HolePlacer), it picks nothing
    if (choosingRef.current) {
      void pickSketchFace(result);
      return;
    }
    if (sketchingRef.current) return;
    setPickedSketches((previous) => (previous.length ? [] : previous));
    setPickedCurves((previous) => (previous.length ? [] : previous));
    setPickedSurfaces((previous) => (previous.length ? [] : previous));
    setBarNote(null);
    const view = viewRef.current;
    const node = view?.nodes.find((item) => item.node_id === result.nodeId);
    // With the assembly tab open, clicking a part of the model selects its component (its connectors are drawn).
    if (leftTabRef.current === "assembly" && node?.component_id && result.mode === "component") selectComponent(node.component_id);
    const entity = result.entity;
    const item: Omit<SelectionItem, "variable"> = {
      key: `${result.nodeId}::${result.entityId ?? "component"}`,
      kind: result.mode === "component" ? "component" : ((entity?.kind ?? result.mode) as SelectionItem["kind"]),
      nodeId: result.nodeId,
      entityId: result.entityId,
      definitionId: node?.definition_id ?? null,
      properties: entity?.properties ?? null,
      geometry: entity?.geometry ?? null,
      tags: entity?.tags ?? null,
    };
    // An operation in progress that takes several picks: a click on the model adds what it hits (the server names it)
    const current = sessionRef.current;
    if (current) {
      if (current.pick && item.kind === current.pick.entity && item.entityId) editSessionPicksRef.current(addPick(sessionHeldRef.current, { ...item, variable: "" }));
      return;
    }
    // A preview carries no entity details: ask the kernel for them.
    const needsDetails = Boolean(view?.isPreview) && Boolean(item.entityId) && Object.keys(item.properties ?? {}).length === 0;
    if (needsDetails && item.entityId) {
      item.pending = true;
      socketRef.current?.send({ type: "entity.info", entity_id: item.entityId, node_id: item.nodeId });
    }
    setPicked((previous) => {
      if (!result.additive) return [item];
      return previous.some((other) => other.key === item.key)
        ? previous.filter((other) => other.key !== item.key)
        : [...previous, item];
    });
  }, [pickSketchFace, selectComponent]);

  const handleClear = useCallback(() => {
    if (sketchingRef.current) return;
    setPicked((previous) => (previous.length ? [] : previous));
    setPickedSketches((previous) => (previous.length ? [] : previous));
    setPickedCurves((previous) => (previous.length ? [] : previous));
    setPickedSurfaces((previous) => (previous.length ? [] : previous));
    setBarNote(null);
  }, []);

  /** A click on a sketch (or on nothing) in the sketch selection mode, or on a sketch row of the tree. */
  const pickSketch = useCallback((name: string | null, additive: boolean) => {
    if (sketchingRef.current) return;
    setBarNote(null);
    if (name === null) {
      if (!additive) {
        setPickedSketches((previous) => (previous.length ? [] : previous));
    setPickedCurves((previous) => (previous.length ? [] : previous));
    setPickedSurfaces((previous) => (previous.length ? [] : previous));
        setPicked((previous) => (previous.length ? [] : previous));
      }
      return;
    }
    setPicked((previous) => (previous.length ? [] : previous));
    // sketches, curves and surfaces share the click: a plain click picks one of any, Ctrl/Cmd adds it to the others
    const kind = curvesRef.current.some((curve) => curve.name === name) ? "curve" : surfacesRef.current.includes(name) ? "surface" : "sketch";
    const pick = (previous: string[]) => nextSketchSelection(previous, name, additive);
    const keep = (mine: boolean) => (previous: string[]) => (mine || additive || !previous.length ? previous : []);
    setPickedSketches(kind === "sketch" ? pick : keep(false));
    setPickedCurves(kind === "curve" ? pick : keep(false));
    setPickedSurfaces(kind === "surface" ? pick : keep(false));
  }, []);

  // The notebook follows the selection: the server writes it as ql code into
  // the selection cell, and the viewport image is saved for coding agents.
  const firstSelection = useRef(true);
  useEffect(() => {
    if (firstSelection.current) {
      firstSelection.current = false;
      return;
    }
    // The notebook gets the selection when every picked entity is described.
    const waiting = selection.some((item) => item.pending);
    const send = window.setTimeout(() => {
      if (!waiting) socketRef.current?.send({ type: "selection.set", items: selectionPayload(selection) });
    }, 40);
    const snapshot = window.setTimeout(() => {
      const png = viewRef.current?.snapshotPng();
      if (png) void postViewport(png).catch(() => undefined);
    }, 600);
    return () => {
      window.clearTimeout(send);
      window.clearTimeout(snapshot);
    };
  }, [selection]);

  // Never veil for ever: whatever failed to say so ends it after three minutes.
  useEffect(() => {
    if (loading === null) return;
    const timer = window.setTimeout(() => setLoading(null), 180_000);
    return () => window.clearTimeout(timer);
  }, [loading]);

  // -- GUI features ------------------------------------------------------------------------------

  // -- an operation in progress (lib/operation-session.ts): added at once, its numbers tuned live by the selection ----------

  /** `handle`: an arrow on the picked face (mm, world) that drags the number whose name ends in `param`: a press / pull's
   * distance along the face's outward normal, a shell's wall thickness into the body.
   * `pick`: the selection a click on the model adds to (the faces a shell opens, the edges a fillet rounds), see
   * lib/operation-session.ts; `edits`: the feature edits those clicks made (Esc undoes them with the rest). */
  type OpSession = {
    slug: string; cell: string | null; title: string; specId: string; anchorMm: Vec3 | null; editing: boolean; busy: boolean; error: string | null;
    handle: { origin: Vec3; normal: Vec3; param: string; min?: number } | null;
    pick: ReturnType<typeof pickSlot>;
    edits: number;
  };
  const [session, setSession] = useState<OpSession | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const anchorRef = useRef<Vec3 | null>(null);
  const paramsRef = useRef<ParamMeta[]>([]);
  const sessionSettler = useRef(createSettler<ParamValue>(SETTLE_MS, (values) => socketRef.current?.send({ type: "param.set", values })));
  const sessionParams = useMemo(() => (session ? featureParams(params, session.slug) : []), [params, session]);
  /** The number the session's arrow drags. */
  const sessionDistance = session?.handle ? sessionParams.find((param) => param.id.endsWith(session.handle!.param)) : undefined;
  /** What the session's pick slot holds, as references (in the feature's cell). */
  const sessionHeld = useMemo(() => {
    if (!session?.pick || !session.cell) return [];
    return gui.state.features.find((feature) => feature.cell === session.cell)?.gui?.refs?.[session.pick.slot] ?? [];
  }, [session, gui.state.features]);
  /** The numbers changed in the session (the server's `modified` may not have come back yet when Enter is pressed). */
  const sessionTouched = useRef(new Set<string>());
  /** The numbers of the session the notebook source does not have yet. */
  const touchedParams = () =>
    sessionRef.current
      ? featureParams(paramsRef.current, sessionRef.current.slug)
          .filter((param) => param.modified || sessionTouched.current.has(param.id))
          .map((param) => param.id)
      : [];
  /** Keep: the tuned numbers are written into the notebook. */
  const confirmSession = useCallback(() => {
    const current = sessionRef.current;
    if (!current || current.busy) return;
    sessionSettler.current.flush();
    const names = touchedParams();
    if (names.length) socketRef.current?.send({ type: "param.commit", names });
    sessionTouched.current.clear();
    setSession(null);
    log.push("ok", t("kept {{name}}", { name: current.slug }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [log.push]);
  /** Take back: a new feature is undone, an edited one gets its numbers back. */
  const cancelSession = useCallback(() => {
    const current = sessionRef.current;
    if (!current || current.busy) return;
    const names = touchedParams();
    sessionSettler.current.flush();
    if (names.length) socketRef.current?.send({ type: "param.revert", names });
    sessionTouched.current.clear();
    setSession(null);
    // the picks added while tuning are edits of their own: they go back first, then the feature itself when it is new
    const steps = current.edits + (current.editing ? 0 : 1);
    void (async () => {
      for (let step = 0; step < steps; step += 1) await gui.run({ op: "undo" });
    })()
      .then(() => steps && log.push("info", t("took back {{name}}", { name: current.slug })))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gui.run, log.push]);
  /** Start `spec` on the selection with its defaults when that is all it needs (else false: the dialog opens). */
  const tryQuick = useCallback(
    (request: DialogRequest): boolean => {
      if (request.edit) return false;
      const start = quickStart(request.spec, gui.state, selectionRef.current, request.prefill);
      if (!start) return false;
      const title = t(plainLabel(request.spec.id, request.spec.label));
      // a press / pull drags its distance out of the face, a shell its wall thickness into the body
      const arrow = ({ press_pull: { param: "_DISTANCE", into: false }, shell: { param: "_THICKNESS", into: true } } as const)[request.spec.id as "press_pull" | "shell"];
      const picked = arrow ? selectionRef.current.find((item) => item.kind === "face") : undefined;
      const frame = picked?.entityId ? (viewRef.current?.faceFrameMm(picked.nodeId, picked.entityId) ?? null) : null;
      const handle =
        frame && arrow
          ? { origin: frame.centroid, normal: (arrow.into ? frame.normal.map((v) => -v) : frame.normal) as Vec3, param: arrow.param, ...(arrow.into ? { min: 0.1 } : {}) }
          : null;
      setSession({
        slug: start.name, cell: null, title, specId: request.spec.id, anchorMm: frame?.centroid ?? anchorRef.current, editing: false, busy: true, error: null,
        handle, pick: pickSlot(request.spec), edits: 0,
      });
      setDialog(null);
      gui
        .run(start.command)
        .then((result) => {
          log.push("ok", t("added {{name}}", { name: result.name }));
          const failure = cellFailure(result);
          setSession((current) => (current ? { ...current, slug: result.name, cell: result.cell?.id ?? null, busy: false, error: failure } : current));
          setPicked([]); // what was picked is the feature's now; the panel stays where it was
        })
        .catch((error) => {
          setSession(null);
          setGuiError(error instanceof Error ? error.message : String(error));
        });
      return true;
    },
    [gui.state, gui.run, log.push],
  );
  /** Write a new list into the session's pick slot (a click added to it, the panel took one out): an edit of the feature. */
  const editSessionPicks = useCallback(
    (items: SelectionPayload[]) => {
      const current = sessionRef.current;
      if (!current?.pick || !current.cell || current.busy) return;
      const { cell, pick } = current;
      setSession({ ...current, busy: true });
      gui
        .run({ op: "edit", cell, values: {}, selections: { [pick.slot]: items } })
        .then((result) => setSession((now) => (now && now.cell === cell ? { ...now, busy: false, edits: now.edits + 1, error: cellFailure(result) } : now)))
        .catch((error) => setSession((now) => (now && now.cell === cell ? { ...now, busy: false, error: error instanceof Error ? error.message : String(error) } : now)));
    },
    [gui.run],
  );
  const sessionHeldRef = useRef(sessionHeld);
  sessionHeldRef.current = sessionHeld;
  editSessionPicksRef.current = editSessionPicks;

  /** Tune the numbers of a feature of the tree in place (Esc gives them back). */
  const editInPlace = useCallback((feature: FeatureRow, spec: Spec): boolean => {
    if (!featureParams(paramsRef.current, feature.slug).length) return false;
    setSession({
      slug: feature.slug, cell: feature.cell, title: t(plainLabel(spec.id, spec.label)), specId: spec.id, anchorMm: anchorRef.current, editing: true, busy: false, error: null,
      handle: null, pick: feature.gui?.refs?.[pickSlot(spec)?.slot ?? ""] ? pickSlot(spec) : null, edits: 0,
    });
    return true;
  }, []);

  const openDialog = useCallback(
    (request: DialogRequest) => {
      if (noNotebook()) return;
      if (sessionRef.current) confirmSession(); // another operation: the one in progress is kept first
      if (tryQuick(request)) return;
      if (modeBeforeDialog.current === null) modeBeforeDialog.current = selectionMode;
      setDialog(request);
    },
    [selectionMode, noNotebook, confirmSession, tryQuick],
  );
  const closeDialog = useCallback(() => {
    setDialog(null);
    if (modeBeforeDialog.current !== null) setSelectionMode(modeBeforeDialog.current);
    modeBeforeDialog.current = null;
  }, []);

  /** A command from the dialog: rejects with the server's message (shown in the dialog), closes on success. */
  const submitFeature = useCallback(
    async (command: FeatureCommand) => {
      const result = await gui.run(command);
      log.push("ok", command.op === "undo" || command.op === "redo" ? t(command.op) : t("{{op}} {{name}}", { op: t(command.op), name: result.name }));
      if (isCellCommand(command)) assertCellRan(result); // the cell failed: say so in the dialog instead of closing
      closeDialog();
    },
    [gui.run, log.push, closeDialog],
  );

  /** A command from the tree or the shortcuts: its failure shows above the tree. */
  const runFeature = useCallback(
    async (command: FeatureCommand) => {
      setGuiBusy(true);
      setGuiError(null);
      try {
        const result = await gui.run(command);
        log.push("ok", command.op === "undo" || command.op === "redo" ? t(command.op) : t("{{op}} {{name}}", { op: t(command.op), name: result.name }));
      } catch (error) {
        setGuiError(error instanceof Error ? error.message : String(error));
      } finally {
        setGuiBusy(false);
      }
    },
    [gui.run, log.push],
  );
  const undo = useCallback(() => void runFeature({ op: "undo" }), [runFeature]);
  const redo = useCallback(() => void runFeature({ op: "redo" }), [runFeature]);

  // Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z undo and redo a feature change, unless a text field has the focus.
  useEffect(() => {
    if (!MANUAL_MODE) return;
    const onKey = (event: KeyboardEvent) => {
      if (sketchingRef.current) return; // the sketch has its own undo
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.key.toLowerCase() !== "z") return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true], .cm-editor")) return;
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // The command registry the bar reads: today the feature catalog, later sketch and assembly commands too.
  const beginSketch = useCallback(
    (session: Omit<SketchSession, "id">) => {
      setDialog(null);
      setSketchNotice(null);
      setBarNote(null);
      setPickedSketches([]);
      setPickedCurves([]);
      setPickedSurfaces([]);
      if (modeBeforeSketch.current === null) modeBeforeSketch.current = selectionMode;
      setSelectionMode("face"); // a face pick chooses the sketch plane
      setPicked([]);
      setSketchSession({ ...session, id: ++sketchCounter.current });
    },
    [selectionMode],
  );
  const workplanesRef = useRef(workplanes);
  workplanesRef.current = workplanes;
  const activeWorkplaneRef = useRef(activeWorkplane);
  activeWorkplaneRef.current = activeWorkplane;
  const startSketch = useCallback(() => {
    if (sketchingRef.current || noNotebook()) return;
    const active = workplanesRef.current.find((wp) => wp.name === activeWorkplaneRef.current);
    if (active) {
      const plane = workplanePlane(active); // the active workplane: the sketch cell writes plane=<it>
      beginSketch({ mode: "new", name: "", plane, doc: emptyDoc(plane) });
    } else beginSketch({ mode: "new", name: "", plane: null, doc: emptyDoc() });
  }, [beginSketch, noNotebook]);
  const endSketch = useCallback(() => {
    setSketchSession(null);
    setSketchNotice(null);
    if (modeBeforeSketch.current !== null) setSelectionMode(modeBeforeSketch.current);
    modeBeforeSketch.current = null;
  }, []);
  /** Finish: the add or edit command; rejects with the server's message (shown in the sketch bar), leaves sketch mode on success.
   * With `after.extrude` ("finish and extrude") the new sketch is selected and the extrude form opens on it. */
  const submitSketch = useCallback(
    async (command: FeatureCommand, after?: SketchAfter) => {
      const result = await gui.run(command);
      log.push("ok", command.op === "undo" || command.op === "redo" ? t(command.op) : t("{{op}} {{name}}", { op: t(command.op), name: result.name }));
      if (isCellCommand(command)) assertCellRan(result);
      const restore = modeBeforeSketch.current;
      endSketch();
      const extrude = after?.extrude ? gui.catalog?.specs.find((spec) => spec.id === "extrude_sketch") : undefined;
      if (extrude && after?.extrude) {
        setPicked([]);
        setPickedSketches([result.name]);
        modeBeforeDialog.current = restore ?? modeBeforeDialog.current;
        setDialog({ spec: extrude, prefill: { profile: result.name, distance: after.extrude.distance } });
      }
    },
    [gui.run, gui.catalog, log.push, endSketch],
  );

  const isSketchSpec = (spec: Spec) => spec.slots.some((slot) => slot.kind === "sketch");
  const openAssembly = useCallback(
    (section: "assembly" | "connectors" = "assembly") => {
      setLeftTab("assembly");
      if (section === "connectors") setSelectionMode("face"); // faces are what a connector is placed on
      else setSelectionMode((mode) => (mode === "face" ? "component" : mode));
    },
    [],
  );

  // What the selection is, for the commands that fit it (kept in refs so the registry itself is not rebuilt at every click).
  const selectionRef = useRef(selection);
  selectionRef.current = selection;
  const pickedSketchesRef = useRef(pickedSketches);
  pickedSketchesRef.current = pickedSketches;
  const sketchListRef = useRef(sketchList);
  sketchListRef.current = sketchList;
  const pickedCurvesRef = useRef(pickedCurves);
  pickedCurvesRef.current = pickedCurves;
  // a curve gone from the notebook is no longer picked
  const livePickedCurves = useMemo(() => pickedCurves.filter((name) => curves.some((curve) => curve.name === name)), [pickedCurves, curves]);
  const livePickedSurfaces = useMemo(() => pickedSurfaces.filter((name) => surfaces.includes(name)), [pickedSurfaces, surfaces]);
  const pickedSurfacesRef = useRef(livePickedSurfaces);
  pickedSurfacesRef.current = livePickedSurfaces;
  /** What the picked curves make together (a closed loop, flat or not; a network of two crossing families). */
  const curveShape = useMemo(() => {
    const picked = livePickedCurves.flatMap((name) => curves.filter((curve) => curve.name === name));
    const loop = picked.length ? closedLoop(picked) : null;
    return { loop, normal: loop ? loopNormal(loop) : null, families: gordonFamilies(picked) };
  }, [livePickedCurves, curves]);
  const curveShapeRef = useRef(curveShape);
  curveShapeRef.current = curveShape;
  const context = useMemo(
    () =>
      selectionContext(selection, pickedSketches, livePickedCurves, {
        surfaces: livePickedSurfaces.length,
        shells: livePickedSurfaces.filter((name) => gui.state.bodies.some((body) => body.name === name && body.produces === "shell")).length,
        curveLoop: curveShape.loop !== null,
        curveFlat: curveShape.normal !== null,
        curveNet: curveShape.families !== null,
      }),
    [selection, pickedSketches, livePickedCurves, livePickedSurfaces, curveShape, gui.state.bodies],
  );

  /** "Sketch on this face": the plane chooser's own path, started from the selected face (a clear refusal for a curved one). */
  const sketchOnSelectedFace = useCallback(async () => {
    const face = selectionRef.current.find((item) => item.kind === "face");
    if (!face || !face.entityId) {
      startSketch();
      return;
    }
    const resolved = await resolveFace(face.nodeId, face.entityId, { geometry: face.geometry, properties: face.properties });
    if (!resolved.frame) {
      setBarNote(refusal(resolved.type));
      return;
    }
    setBarNote(null);
    beginSketch({ mode: "new", name: "", plane: resolved.frame, doc: emptyDoc(resolved.frame) });
  }, [resolveFace, startSketch, beginSketch]);

  /** "Workplane from selection" (Space): the workplane cell of the constructor the selection names; it becomes the active
   * workplane and the camera turns to it once the kernel reports its frame. */
  const workplaneFromSelection = useCallback(async () => {
    const request = workplaneRequest(selectionRef.current);
    if (!request) {
      setBarNote(t("A workplane needs one flat face, a face and an edge, two parallel faces, three vertices or one edge."));
      return;
    }
    setBarNote(null);
    setGuiBusy(true);
    setGuiError(null);
    try {
      const selections = Object.fromEntries(Object.entries(request.selections).map(([slot, items]) => [slot, items.map(pickedPayload)]));
      const command: FeatureCommand = { op: "add", spec: "workplane", values: { method: request.method }, selections };
      const result = await gui.run(command);
      assertCellRan(result);
      log.push("ok", t("added {{name}}", { name: result.name }));
      setPicked([]);
      turnedTo.current = null;
      setActiveWorkplane(result.name);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setGuiError(message);
      setBarNote(message);
    } finally {
      setGuiBusy(false);
    }
  }, [gui.run, log.push]);

  // -- drawing a 3D curve ----------------------------------------------------------------------------------------------

  /** The planes a 3D curve is drawn on: the datum planes and every workplane (as the kernel reported its frame). */
  const drawPlanes = useMemo<DrawPlane[]>(
    () => [
      ...(["XY", "XZ", "YZ"] as const).map((name) => ({ name, workplane: false, ...NAMED_FRAMES[name] })),
      ...workplanes.map((wp) => ({ name: wp.name, workplane: true, origin: wp.origin, x_axis: wp.x_axis, y_axis: wp.y_axis, normal: wp.normal })),
    ],
    [workplanes],
  );
  /** The points of the notebook's 3D curves, from their documents: a new path snaps to them. */
  const curveSnapPoints = useMemo(
    () =>
      (gui.state?.features ?? []).flatMap((feature) =>
        feature.gui?.spec === "curve"
          ? ((feature.gui.values?.curve as CurveDoc | undefined)?.points ?? []).map((point) => ({ at: point.at, label: `${feature.slug}.${point.id}` }))
          : [],
      ).concat(curveEnds(curves)),
    [gui.state?.features, curves],
  );
  const startDrawing = useCallback(() => {
    if (sketchingRef.current || placingRef.current || noNotebook()) return;
    const active = activeWorkplaneRef.current;
    setPicked([]);
    setDrawing({ plane: active && workplanesRef.current.some((wp) => wp.name === active) ? active : "XY", error: null });
  }, [noNotebook]);
  /** The path drawn becomes one curve feature per line, arc or spline (each an edge: path, path_2 ...), each starting at
   * the end of the one before; all of them or none (a failing one takes back the ones added before it). */
  const commitCurve = useCallback(
    async (doc: CurveDoc, name: string) => {
      setGuiBusy(true);
      const names: string[] = [];
      while (names.length < doc.curves.length) names.push(names.length ? suggestName(name, [...gui.state.taken, ...names]) : name);
      let added = 0;
      try {
        for (const [index, part] of splitPath(doc, names).entries()) {
          const result = await gui.run({ op: "add", spec: "curve", name: names[index], values: { curve: part } });
          added += 1;
          assertCellRan(result);
          log.push("ok", t("added {{name}}", { name: result.name }));
        }
        setDrawing(null);
      } catch (error) {
        for (; added > 0; added -= 1) await gui.run({ op: "undo" }).catch(() => undefined);
        const message = error instanceof Error ? error.message : String(error);
        setDrawing((d) => (d ? { ...d, error: message } : d));
      } finally {
        setGuiBusy(false);
      }
    },
    [gui.run, gui.state.taken, log.push],
  );
  // W: draw a 3D curve (not while typing, sketching or placing a workplane).
  useEffect(() => {
    if (!MANUAL_MODE) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "w" || event.repeat || event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) return;
      if (drawingRef.current || sketchingRef.current || placingRef.current) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true], .cm-editor, [role=dialog]")) return;
      event.preventDefault();
      startDrawing();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [startDrawing]);

  // -- placing a workplane by hand ----------------------------------------------------------------------------------

  /** The bases a workplane can be placed on: the datum planes, every workplane of the notebook, and the picked face. */
  const placeBases = useMemo<PlaceBase[]>(() => {
    if (placing?.kind === "connector" && placing.face) return [{ value: "face", label: t("picked face"), frame: placing.face.frame }];
    const out: PlaceBase[] = (["XY", "XZ", "YZ"] as const).map((name) => ({ value: name, label: name, frame: NAMED_FRAMES[name] }));
    for (const wp of workplanes) out.push({ value: wp.name, label: wp.name, frame: { origin: wp.origin, x_axis: wp.x_axis, y_axis: wp.y_axis, normal: wp.normal } });
    if (placing?.face) out.push({ value: "face", label: t("picked face"), frame: placing.face.frame });
    return out;
  }, [workplanes, placing?.face, placing?.kind]);
  const placeBase = placeBases.find((item) => item.value === placing?.base) ?? placeBases[0];

  /** Start placing: on the picked flat face, else on the active workplane (one after another builds a 3D frame of
   * planes), else on XY. */
  const startPlacing = useCallback(() => {
    if (noNotebook()) return;
    const items = selectionRef.current;
    const face = items.length === 1 && items[0].kind === "face" ? items[0] : null;
    const frame = face ? faceFrame(face.properties) : null;
    if (face && !frame) {
      setBarNote(t("That face is not flat: a workplane lies on a plane. Pick a flat face, or nothing to place one on the active workplane."));
      return;
    }
    const taken = gui.state?.taken ?? [];
    let name = "wp";
    for (let n = 2; taken.includes(name); n++) name = `wp_${n}`;
    const base = face ? "face" : activeWorkplaneRef.current && workplanesRef.current.some((wp) => wp.name === activeWorkplaneRef.current) ? activeWorkplaneRef.current : "XY";
    setBarNote(null);
    setPlacing({ kind: "workplane", base, values: ZERO_PLACE, mode: "translate", name, face: face && frame ? { item: face, frame } : null, error: null });
  }, [gui.state?.taken, noNotebook]);

  /** Start placing a connector of the part on the picked flat face: its frame there, moved and turned with the handles. */
  const startConnector = useCallback(() => {
    if (noNotebook()) return;
    const items = selectionRef.current;
    const face = items.length === 1 && items[0].kind === "face" ? items[0] : null;
    const frame = face ? connectorFrameFromFace(face) : null;
    if (!face || !frame) {
      setBarNote(t("A connector is placed on one flat face: pick it first (face mode)."));
      return;
    }
    setBarNote(null);
    setPlacing({
      kind: "connector",
      base: "face",
      values: ZERO_PLACE,
      mode: "translate",
      name: "",
      face: { item: face, frame: { origin: frame.origin, x_axis: frame.x_axis, y_axis: frame.y_axis, normal: frame.z_axis } },
      error: null,
    });
  }, []);

  const createPlaced = useCallback(async () => {
    const current = placingRef.current;
    if (!current) return;
    if (current.kind === "connector") {
      // the part's connectors with this one added, written into the product cell (set_connectors)
      const base = current.face?.frame;
      if (!base) return;
      const made = addConnectorFrame(conn.list, placedFrame(base, cleanValues(current.values)), current.name);
      if ("error" in made) {
        setPlacing((p) => (p ? { ...p, error: made.error } : p));
        return;
      }
      try {
        const command = setConnectorsCommand(made.list);
        const result = await gui.run(command);
        if (isCellCommand(command)) assertCellRan(result);
        conn.setList(made.list);
        conn.setSelected(made.id);
        log.push("ok", t("connector {{id}} added", { id: made.id }));
        setPlacing(null);
        setPicked([]);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setPlacing((p) => (p ? { ...p, error: message } : p));
      }
      return;
    }
    setGuiBusy(true);
    try {
      const values = cleanValues(current.values);
      const command: FeatureCommand = {
        op: "add",
        spec: "workplane",
        name: current.name,
        values: {
          method: "offset",
          base: current.base,
          move: values.move,
          rx: values.rx,
          ry: values.ry,
          rz: values.rz,
          ...(current.base === "face" && current.face ? { x_dir: current.face.frame.x_axis } : {}),
        },
        ...(current.base === "face" && current.face ? { selections: { face: [pickedPayload(current.face.item)] } } : {}),
      };
      const result = await gui.run(command);
      assertCellRan(result);
      log.push("ok", t("added {{name}}", { name: result.name }));
      setPlacing(null);
      setPicked([]);
      turnedTo.current = `stay:${result.name}`; // the camera stays where the person placed it from
      setActiveWorkplane(result.name);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPlacing((p) => (p ? { ...p, error: message } : p));
    } finally {
      setGuiBusy(false);
    }
  }, [gui.run, log.push, conn]);

  // While placing: G move, R turn, Enter create, Esc cancel (not while typing in a field, except the fields' own Enter).
  useEffect(() => {
    if (!placing) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const typing = !!target?.closest("input, textarea, select, [contenteditable=true], .cm-editor");
      if (event.key === "Escape") {
        event.preventDefault();
        setPlacing(null);
      } else if (event.key === "Enter" && !typing) {
        event.preventDefault();
        void createPlaced();
      } else if (!typing && (event.key === "g" || event.key === "r")) {
        event.preventDefault();
        setPlacing((p) => (p ? { ...p, mode: event.key === "g" ? "translate" : "rotate" } : p));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [placing !== null, createPlaced]); // eslint-disable-line react-hooks/exhaustive-deps

  // The camera turns to the active workplane (straight at it, the model in view) when its frame arrives or changes.
  const turnedTo = useRef<string | null>(null);
  const turnToWorkplane = useCallback((wp: WorkplaneFrame) => {
    const view = viewRef.current;
    if (!view) return;
    const bounds = view.modelBoundsMm();
    const extent = bounds ? Math.max(...bounds.max.map((v, i) => v - bounds.min[i])) : 60;
    const distance = fitDistanceMm(Math.max(extent, 20) * 1.4, view.engine.camera.fov, view.engine.camera.aspect);
    const pose = viewPose(workplanePlane(wp), wp.origin, distance);
    void view.rig.animateTo({
      position: new THREE.Vector3(pose.position[0] / 1000, pose.position[1] / 1000, pose.position[2] / 1000),
      target: new THREE.Vector3(pose.target[0] / 1000, pose.target[1] / 1000, pose.target[2] / 1000),
      up: new THREE.Vector3(...pose.up),
    });
  }, []);
  useEffect(() => {
    const wp = workplanes.find((item) => item.name === activeWorkplane);
    if (!wp || sketchingRef.current) return;
    const key = JSON.stringify(wp);
    if (turnedTo.current === key) return;
    const stay = turnedTo.current === `stay:${wp.name}`; // placed by hand, in this view: keep the view
    turnedTo.current = key;
    if (!stay) turnToWorkplane(wp);
  }, [workplanes, activeWorkplane, turnToWorkplane]);
  useEffect(() => {
    // a workplane that is gone (its cell deleted, another notebook) is no longer active
    if (activeWorkplane && workplanes.length && !workplanes.some((wp) => wp.name === activeWorkplane)) setActiveWorkplane(null);
  }, [workplanes, activeWorkplane]);

  // 1..6 switch what a click picks (see MODES), unless a text field has the focus or a sketch is being drawn (its keys
  // are its tools and typed numbers).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.repeat || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (sketchingRef.current) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true], .cm-editor, [role=dialog]")) return;
      const found = MODES.find((item) => item.key === event.key);
      if (!found) return;
      event.preventDefault();
      setSelectionMode(found.mode);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Space: a workplane from the selection; with nothing selected, look at the active workplane again.
  useEffect(() => {
    if (!MANUAL_MODE) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== " " || event.repeat || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (sketchingRef.current || placingRef.current || drawingRef.current) return; // space pans the sketch view
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, button, [contenteditable=true], .cm-editor, [role=dialog]")) return;
      event.preventDefault();
      if (event.shiftKey) {
        // Shift+Space: look straight at the active workplane again
        const wp = workplanesRef.current.find((item) => item.name === activeWorkplaneRef.current);
        if (wp) turnToWorkplane(wp);
        return;
      }
      const items = selectionRef.current;
      // one flat face, or nothing: place a workplane with the handles; the other picks name their constructor
      if (items.length === 0 || (items.length === 1 && items[0].kind === "face")) startPlacing();
      else void workplaneFromSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [workplaneFromSelection, turnToWorkplane, startPlacing]);

  const handleEditFeatureRef = useRef<(feature: FeatureRow, spec: Spec) => void>(() => undefined);
  const editSelectedSketch = useCallback(() => {
    const info = sketchListRef.current.find((item) => item.name === pickedSketchesRef.current[0]);
    const feature = info ? gui.state.features.find((row) => row.cell === info.cell) : undefined;
    const spec = feature?.gui ? gui.catalog?.specs.find((item) => item.id === feature.gui?.spec) : undefined;
    if (feature && spec) handleEditFeatureRef.current(feature, spec);
  }, [gui.state.features, gui.catalog]);

  const openSpec = useCallback(
    (spec: Spec, preset?: Record<string, unknown>) => {
      if (isSketchSpec(spec)) startSketch();
      else openDialog({ spec, ...(preset ? { prefill: preset } : {}), ...(spec.id === "hole" && selectionRef.current.some((item) => item.kind === "face") ? { fromFace: true } : {}) });
    },
    [openDialog, startSketch],
  );
  /** The surfaces made from the picked curves, and what is made of the picked surfaces: each the SDK operation (or the
   * feature) of its own, its values filled from the picks; it starts at once when they are all it needs. */
  const surfaceCommands = useMemo<Command[]>(() => {
    const start = (specId: string, prefill: () => Record<string, unknown>) => () => {
      const spec = gui.catalog?.specs.find((item) => item.id === specId);
      if (spec) openDialog({ spec, prefill: prefill() });
    };
    const curvesPicked = () => [...pickedCurvesRef.current];
    const loopOrder = () => curveShapeRef.current.loop?.map((curve) => curve.name) ?? curvesPicked();
    const command = (id: string, label: string, description: string, keywords: string[], run: () => void): Command => ({
      id, label, group: "Surfaces", keywords, description, icon: FEATURE_ICONS.curve, when: whenFor(id), contextOnly: true, run,
    });
    return [
      command("ruled_surface", "Ruled surface between two curves", "The surface of straight lines between two picked curves.", ["ruled", "surface", "between"],
        start("op.make_ruled_surface_rface", () => ({ edge_a: curvesPicked()[0], edge_b: curvesPicked()[1] }))),
      command("loft_surface", "Loft a surface through curves", "A smooth surface through the picked curves, in the order picked.", ["loft", "surface", "skin", "through"],
        start("op.loft_rshell", () => ({ sections: curvesPicked() }))),
      command("fill_curves", "Fill a loop of curves", "A surface filling the closed loop the picked curves make.", ["fill", "patch", "surface", "boundary"],
        start("fill", () => ({ curves: loopOrder() }))),
      command("plane_from_curves", "Flat face from curves", "The flat face the picked curves bound (they make a closed loop in one plane).", ["face", "plane", "flat", "fill"],
        start("flat_face", () => ({ curves: loopOrder(), normal: curveShapeRef.current.normal ?? [0, 0, 1] }))),
      command("gordon_surface", "Surface through a curve network", "A surface through two families of crossing curves (found from where they cross).", ["gordon", "network", "surface", "mesh"],
        start("op.make_gordon_surface_rface", () => ({ ...(curveShapeRef.current.families ?? {}) }))),
      command("sew_surfaces", "Sew surfaces", "One shell sewn from the picked surfaces along the edges they share.", ["sew", "join", "shell", "surface"],
        start("sew", () => ({ surfaces: [...pickedSurfacesRef.current] }))),
      command("close_shell", "Close into a solid", "The solid the picked closed shell bounds.", ["solid", "close", "shell", "fill"],
        start("solid_from_shell", () => ({ shell: pickedSurfacesRef.current[0] }))),
    ];
  }, [gui.catalog, openDialog]);
  const allCommands = useMemo<Command[]>(
    () => [
      // The assembly layout is not a dialog: it is its own panel (registered below), so its spec is left out of the generic list.
      ...commandsFromSpecs((gui.catalog?.specs ?? []).filter((spec) => spec.id !== "assembly" && spec.id !== "workplane" && spec.id !== "curve"), openSpec, FEATURE_ICONS),
      {
        id: "curve_draw",
        label: "3D curve",
        group: "Sketch",
        keywords: ["curve", "wire", "path", "3d", "polyline", "spline", "arc", "rail", "sweep"],
        description: "Draw curves in space (W): lines, arcs and splines on workplanes, snapped to the model; each is an edge, one after another joined end to end (pick several to sweep along them, or to make a surface).",
        icon: FEATURE_ICONS.curve,
        run: () => startDrawing(),
      },
      {
        id: "workplane_place",
        label: "Workplane",
        group: "Datums",
        keywords: ["workplane", "datum", "plane", "offset", "rotate", "move", "space"],
        description: "Place a workplane with handles (Space): on the picked flat face, else on the active workplane, else on XY; move and turn it, then sketch on it.",
        icon: FEATURE_ICONS.workplane_from_selection,
        when: whenFor("workplane_place"),
        run: () => startPlacing(),
      },
      {
        id: "connector_place",
        label: "Connector",
        group: "Product",
        keywords: ["connector", "frame", "mate", "joint", "interface", "assembly"],
        description: "Place a connector of this part on the picked flat face: move and turn its frame with the handles, then add it (assemblies join parts at connectors).",
        icon: FEATURE_ICONS.workplane_from_selection,
        when: whenFor("connector_place"),
        run: () => startConnector(),
      },
      {
        id: "workplane_from_selection",
        label: "Workplane from selection",
        group: "Datums",
        keywords: ["workplane", "datum", "plane", "frame", "space", "offset", "midplane"],
        description: "A workplane from the selection (Space): a flat face, a face and an edge, two parallel faces, three vertices or an edge. New sketches go on it.",
        icon: FEATURE_ICONS.workplane_from_selection,
        when: whenFor("workplane_from_selection"),
        run: () => void workplaneFromSelection(),
      },
      {
        id: "sketch_on_face",
        label: "Sketch on face",
        group: "Sketch",
        keywords: ["plane", "surface", "draw", "sketch"],
        description: "Start a sketch on the selected flat face.",
        icon: FEATURE_ICONS.sketch,
        when: whenFor("sketch_on_face"),
        contextOnly: true,
        run: () => void sketchOnSelectedFace(),
      },
      {
        id: "sweep_along",
        label: "Sweep along a curve",
        group: "Solids",
        keywords: ["sweep", "path", "rail", "pipe", "curve", "wire"],
        description: "Sweep a profile along the picked 3D curve; a sketch picked with it is the profile.",
        icon: FEATURE_ICONS.curve,
        when: whenFor("sweep_along"),
        contextOnly: true,
        run: () => {
          const spec = gui.catalog?.specs.find((item) => item.id === "op.sweep_rsolid");
          const path = pickedCurvesRef.current[0];
          if (!spec || !path) return;
          const profile = pickedSketchesRef.current[0];
          openDialog({ spec, prefill: { path, ...(profile ? { profile } : {}) } });
        },
      },
      ...surfaceCommands,
      {
        id: "join_curves",
        label: "Join curves into a wire",
        group: "Curves",
        keywords: ["wire", "join", "chain", "path", "curve", "connect"],
        description: "One wire through the picked curves (they must connect end to end, in any order): a path to sweep along, a section to loft through.",
        icon: FEATURE_ICONS.curve,
        when: whenFor("join_curves"),
        contextOnly: true,
        run: () => {
          const spec = gui.catalog?.specs.find((item) => item.id === "wire");
          if (spec) openDialog({ spec, prefill: { curves: [...pickedCurvesRef.current] } });
        },
      },
      {
        id: "edit_sketch",
        label: "Edit sketch",
        group: "Sketch",
        keywords: ["change", "modify", "redraw"],
        description: "Open the selected sketch for editing.",
        icon: FEATURE_ICONS.sketch,
        when: whenFor("edit_sketch"),
        contextOnly: true,
        run: editSelectedSketch,
      },
      ...assemblyCommands(openAssembly, { assembly: Boxes, connectors: Cable }),
    ],
    [gui.catalog, openSpec, openDialog, surfaceCommands, sketchOnSelectedFace, editSelectedSketch, openAssembly, workplaneFromSelection, startPlacing, startDrawing, startConnector],
  );
  // The stand-alone combine commands (Cut, Union, Intersect, Cut/Boss with sketch) are offered only while several bodies are open:
  // a new solid says how it meets the body in its own dialog.
  const commands = useMemo(() => visibleCommands(allCommands, { openBodies: gui.state.open.length }), [allCommands, gui.state.open.length]);
  // A curved face cannot carry a sketch: the action stays visible, greyed, with the reason.
  const barDisabled = useMemo<Record<string, string>>(() => {
    const faces = selection.filter((item) => item.kind === "face");
    const type = faces.length === 1 && typeof faces[0].geometry?.type === "string" ? faces[0].geometry.type : null;
    const out: Record<string, string> = {};
    if (type && type.toLowerCase() !== "plane") out.sketch_on_face = refusal(type);
    return out;
  }, [selection]);
  const fit = useMemo(() => fitScore(context), [context]);
  const hint = useMemo(() => selectionHint(context, commands), [context, commands]);
  const anchorMm: Vec3 | null = useMemo(() => {
    const view = viewRef.current;
    if (!view) return null;
    const first = sketchList.find((info) => info.name === pickedSketches[0]);
    // a picked curve: the middle of its drawn line
    const curve = curves.find((item) => item.name === livePickedCurves[0]);
    const middle = curve ? curve.edges[Math.floor(curve.edges.length / 2)] : null;
    const sketchAt = first ? sketchCentre(first.doc, sketchShapes.get(first.name)?.shape ?? null) : middle ? middle[Math.floor(middle.length / 2)] : null;
    return selectionAnchorMm(view, selection, sketchAt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, pickedSketches, livePickedCurves, curves, sketchList, sketchShapes, sceneVersion]);
  anchorRef.current = anchorMm;
  paramsRef.current = params;

  /** A command from the assembly panel: rejects with the server's message (shown in the panel). */
  const runPanelCommand = useCallback(
    async (command: FeatureCommand) => {
      if (noNotebook()) throw new Error(t("No notebook is open: create one first."));
      const result = await gui.run(command);
      log.push("ok", command.op === "set_connectors" ? t("connectors set") : t("{{op}} {{name}}", { op: t(command.op), name: result.name }));
      if (isCellCommand(command)) assertCellRan(result);
    },
    [gui.run, log.push, noNotebook],
  );

  /** The frames the viewport draws: the selected component's connectors (all components' while a picker is armed),
   * and the open part's own connectors. */
  const gizmos = useMemo<Gizmo[]>(() => {
    if (leftTab !== "assembly") return [];
    const out: Gizmo[] = [];
    for (const c of asm.doc.components) {
      if (!(c.id === asm.selected || asm.target)) continue;
      for (const frame of asm.cache[c.part]?.connectors ?? []) out.push({ key: `${c.id}.${frame.id}`, owner: c.id, frame });
    }
    if (gui.state.product) for (const frame of conn.list) out.push({ key: frame.id, owner: null, frame });
    return out;
  }, [leftTab, asm.doc.components, asm.selected, asm.target, asm.cache, gui.state.product, conn.list]);
  const gizmoHighlight = useMemo(() => {
    const set = new Set<string>();
    if (conn.selected) set.add(conn.selected);
    for (const k of asm.doc.constraints) for (const side of [k.a, k.b]) if (side.component && side.connector) set.add(`${side.component}.${side.connector}`);
    return set;
  }, [conn.selected, asm.doc.constraints]);
  const pickGizmo = useCallback(
    (g: Gizmo) => {
      if (g.owner === null) {
        conn.setSelected(conn.selected === g.frame.id ? null : g.frame.id);
        return;
      }
      if (asm.target) {
        asm.setDoc(setRef(asm.doc, asm.target.constraint, asm.target.side, { component: g.owner, connector: g.frame.id }));
        asm.setTarget(null);
      } else asm.setSelected(g.owner);
    },
    [asm, conn],
  );

  const handleEditFeature = (feature: FeatureRow, spec: Spec) => {
    if (spec.id === "assembly") {
      openAssembly("assembly");
      return;
    }
    if (!isSketchSpec(spec)) {
      if (sessionRef.current) confirmSession();
      if (!editInPlace(feature, spec)) openDialog({ spec, edit: feature });
      return;
    }
    const doc = normalizeDoc(feature.gui?.values?.sketch);
    beginSketch({ mode: "edit", cell: feature.cell, name: feature.slug, plane: doc.plane, doc });
  };
  handleEditFeatureRef.current = handleEditFeature;

  const treeSketches = useMemo<TreeSketches>(
    () => ({
      infos: sketchList,
      hidden: hiddenSketches,
      selected: pickedSketches,
      hover: hoverSketch,
      onToggleHidden: toggleSketchHidden,
      onSelect: pickSketch,
      onHover: setHoverSketch,
    }),
    [sketchList, hiddenSketches, pickedSketches, hoverSketch, toggleSketchHidden, pickSketch],
  );
  const dialogSketches = useMemo(
    () => ({ infos: sketchList, shapes: sketchShapes, picked: pickedSketches.length === 1 ? pickedSketches[0] : null, onPreview: setPushArrow }),
    [sketchList, sketchShapes, pickedSketches],
  );
  const inspectedSketches = useMemo(
    () =>
      pickedSketches.flatMap((name) => {
        const info = sketchList.find((item) => item.name === name);
        const solved = sketchShapes.get(name);
        return info ? [{ name, rows: describeSketch(info, solved?.shape ?? null, solved?.solve ?? null) }] : [];
      }),
    [pickedSketches, sketchList, sketchShapes],
  );

  // -- actions -----------------------------------------------------------------------

  const handleOpen = (path: string) => {
    setStatus(`${t("opening {{name}}", { name: path })}…`);
    openNotebook(path).catch((error) => {
      log.push("error", t("open failed: {{reason}}", { reason: error.message }));
      setLoading(null);
    });
  };

  const handleCreate = async (name: string, kind: "part" | "assembly") => {
    setStatus(`${t("creating {{name}}", { name })}…`);
    await newNotebook(name, kind);
    // the server opens it: show its features (manual mode) or its cells (code mode)
    setLeftTab(mode === "manual" ? "features" : "notebook");
  };

  // One layout for both modes: the panels are the left column (what it shows is the mode), the selection kinds and the
  // inspector float over the viewport (see the floating layer below).
  const taskOpen = sketching || !!placing || !!drawing;
  /** The left column of mode `m`: its tabs, on the tab it was left on. */
  const panelFor = (m: EditorMode) => (
            <Tabs value={m === mode ? leftTab : lastTab.current[m]} onValueChange={m === mode ? setLeftTab : undefined} className="h-full min-w-0 overflow-hidden">
              <TabsList>
                {m === "manual" ? (
                  <>
                    <TabsTrigger value="features">{t("features")}</TabsTrigger>
                    <TabsTrigger value="assembly">{t("assembly")}</TabsTrigger>
                    <TabsTrigger value="workspace">{t("workspace")}</TabsTrigger>
                  </>
                ) : (
                  <>
                    <TabsTrigger value="notebook">{t("notebook")}</TabsTrigger>
                    <TabsTrigger value="workspace">{t("workspace")}</TabsTrigger>
                    {moduleView && <TabsTrigger value="module">{moduleView.name}</TabsTrigger>}
                  </>
                )}
              </TabsList>
              <TabsContent value="features" className="flex min-h-0 flex-col">
                <FeatureTree
                  catalog={gui.catalog}
                  state={gui.state}
                  busy={guiBusy}
                  error={guiError ?? gui.error}
                  onEdit={handleEditFeature}
                  onDelete={(feature) => void runFeature({ op: "delete", cell: feature.cell })}
                  onUseProduct={(body) => void runFeature({ op: "use_as_product", body })}
                  onRepairRef={(cell, slot, index, choice) => void runFeature({ op: "ref_repair", cell, slot, index, choice })}
                  onUndo={undo}
                  onRedo={redo}
                  sketches={treeSketches}
                />
              </TabsContent>
              <TabsContent value="assembly" className="min-h-0">
                <AssemblyPanel
                  state={gui.state}
                  editor={asm}
                  connectors={conn}
                  selection={selection}
                  busy={guiBusy}
                  onSelectionMode={setSelectionMode}
                  onRun={runPanelCommand}
                  onPlaceConnector={startConnector}
                />
              </TabsContent>
              <TabsContent value="notebook" className="min-h-0">
                <CellEditor
                  cells={cells}
                  features={features}
                  params={params}
                  socket={socketRef.current}
                  notebook={notebook}
                  onInterrupt={handleStop}
                  onConflict={(cell, mine) =>
                    log.push(
                      "error",
                      `${cell.title ?? "cell"} changed on disk while you were editing it: kept the file's version. Your unsaved text was:\n${mine.length > 600 ? `${mine.slice(0, 600)}…` : mine}`,
                    )
                  }
                />
              </TabsContent>
              <TabsContent value="workspace" className="min-h-0">
                <NotebookList
                  notebooks={notebooks}
                  current={currentPath}
                  modules={modules}
                  openModule={moduleView?.path ?? null}
                  onOpen={handleOpen}
                  onOpenModule={(path) => socketRef.current?.send({ type: "module.open", path })}
                  onCreate={handleCreate}
                  onDelete={async (path) => {
                    const { trash } = await deleteNotebook(path);
                    log.push("ok", t("deleted {{path}} (kept in {{trash}})", { path, trash }));
                  }}
                />
              </TabsContent>
              {moduleView && (
                <TabsContent value="module" className="min-h-0">
                  <ModuleView
                    module={moduleView}
                    socket={socketRef.current}
                    onClose={() => socketRef.current?.send({ type: "module.close" })}
                  />
                </TabsContent>
              )}
            </Tabs>
  );
  const modeChips = (
    <>
                {MODES.map(({ mode, label, key }) => (
                  <button
                    key={mode}
                    type="button"
                    className={cn(
                      "border-2 px-2 py-px text-[10px] font-semibold uppercase tracking-[0.1em] transition-colors",
                      selectionMode === mode
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-transparent text-muted-foreground hover:border-input hover:text-foreground",
                    )}
                    onClick={() => setSelectionMode(mode)}
                    title={`${t(label)} (${key})`}
                  >
                    {t(label)}
                    <span className="ml-1 opacity-50">{key}</span>
                  </button>
                ))}
                <button
                  type="button"
                  className="border-2 border-transparent px-2 py-px text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground hover:border-input hover:text-foreground"
                  onClick={() => viewRef.current?.frame()}
                >
                  {t("fit")}
                </button>
    </>
  );
  const inspectedCurves = useMemo(
    () =>
      livePickedCurves.flatMap((name) => {
        const curve = curves.find((item) => item.name === name);
        if (!curve) return [];
        const length = curve.edges.reduce((sum, edge) => sum + edge.slice(1).reduce((s2, p, i) => s2 + Math.hypot(p[0] - edge[i][0], p[1] - edge[i][1], p[2] - edge[i][2]), 0), 0);
        return [{ name, kind: "curve" as const, rows: [{ label: t("kind"), value: t(curve.kind) }, { label: t("edges"), value: String(curve.edges.length) }, { label: t("length"), value: `${length.toFixed(1)} mm` }] }];
      }),
    [livePickedCurves, curves],
  );
  const inspectedSurfaces = useMemo(
    () =>
      livePickedSurfaces.map((name) => ({
        name,
        kind: "surface" as const,
        rows: [{ label: t("kind"), value: t(gui.state.bodies.find((body) => body.name === name)?.produces ?? "surface") }],
      })),
    [livePickedSurfaces, gui.state.bodies],
  );
  /** What the viewport highlights: the picked entities, and the picked surfaces whole. */
  const viewportHighlights = useMemo(
    () => [...selection, ...livePickedSurfaces.map((name) => ({ nodeId: SURFACE_NODE_PREFIX + name, entityId: null }))],
    [selection, livePickedSurfaces],
  );
  const inspectorPanel = <Inspector selection={selection} sketches={[...inspectedSketches, ...inspectedCurves, ...inspectedSurfaces]} />;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <div inert={sketching} className={cn(sketching && "opacity-50")}>
      <Header
        notebook={notebook}
        kind={kind}
        kernelAlive={kernelAlive}
        status={status}
        themePreference={theme.preference}
        onTheme={theme.cycle}
      />
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ResizablePanelGroup className="min-h-0 flex-1">
          <ResizablePanel id="browser" defaultSize={23} minSize={16} className="min-w-0" style={{ overflow: "hidden" }}>
            <div className={cn("flex h-full flex-col", sketching && "opacity-40")} inert={sketching}>
              <div className="flex shrink-0 items-center gap-2 border-b-2 border-border px-2 py-1.5">
                {MANUAL_MODE && <ModeSwitch mode={modeTarget ?? mode} onChange={changeMode} disabled={sketching || moving} />}
                <span className="flex-1" />
                {mode === "code" &&
                  (running ? (
                    <Button size="sm" variant="destructive" onClick={handleStop} title={t("Stop the run (interrupt the kernel)")}>
                      <Square className="fill-current" /> {t("stop")}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      title={t("Run every cell")}
                      onClick={() => {
                        setLoading(t("running all cells"));
                        socketRef.current?.send({ type: "rerun.request" });
                      }}
                    >
                      <Play /> {t("run all")}
                    </Button>
                  ))}
              </div>
              <div inert={moving} className="min-h-0 flex-1 overflow-hidden">
                {!MANUAL_MODE ? (
                  panelFor("code")
                ) : (
                <div
                  className="flex h-full w-[200%]"
                  style={{
                    transform: (modeTarget ?? mode) === "code" ? "translateX(-50%)" : "translateX(0)",
                    transition: moving ? `transform ${MODE_SLIDE_MS}ms cubic-bezier(0.45, 0, 0.2, 1)` : "none",
                  }}
                >
                  <div className="h-full w-1/2 min-w-0">{(mode === "manual" || moving) && panelFor("manual")}</div>
                  <div className="h-full w-1/2 min-w-0">{(mode === "code" || moving) && panelFor("code")}</div>
                </div>
                )}
              </div>
            </div>
          </ResizablePanel>
          <ResizableHandle id="browser-handle" />
          <ResizablePanel id="viewport" defaultSize={55} minSize={30} className="min-w-0 overflow-hidden">
            <div className="flex h-full flex-col">
              <div className="relative min-h-0 flex-1 overflow-hidden">
                <Viewport
                  viewRef={viewRef}
                  selectionMode={selectionMode}
                  selection={viewportHighlights}
                  sceneVersion={sceneVersion}
                  theme={theme.resolved}
                  onPick={handlePick}
                  onClear={handleClear}
                  onSketchPick={pickSketch}
                  sketching={sketching}
                />
                <SketchScene
                  viewRef={viewRef}
                  infos={sketchList}
                  shapes={sketchShapes}
                  hidden={shownSketches}
                  editing={sketchSession?.mode === "edit" ? sketchSession.name : null}
                  selected={pickedSketches}
                  hover={hoverSketch}
                  arrow={pushArrow}
                  theme={theme.resolved}
                  hoverEnabled={selectionMode === "sketch" && !sketching}
                  onHover={setHoverSketch}
                />
                {viewRef.current && workplanes.length > 0 && <WorkplanePatches view={viewRef.current} workplanes={workplanes} active={activeWorkplane} />}
                {needNotebook && <NewNotebookPrompt onCreate={(name) => handleCreate(name, "part")} onClose={() => setNeedNotebook(false)} />}
                {viewRef.current && curves.length > 0 && (
                  <CurveLines view={viewRef.current} curves={curves} selected={livePickedCurves} hover={hoverCurve} hoverEnabled={selectionMode === "sketch"} onHover={setHoverCurve} />
                )}
                {drawing && viewRef.current && (
                  <CurveDrawer
                    view={viewRef.current}
                    planes={drawPlanes}
                    others={curveSnapPoints}
                    plane={drawing.plane}
                    busy={guiBusy}
                    error={drawing.error}
                    defaultName={suggestName("path", gui.state.taken)}
                    onCommit={(doc, name) => void commitCurve(doc, name)}
                    onCancel={() => setDrawing(null)}
                  />
                )}
                {placing && viewRef.current && placeBase && (
                  <>
                    <WorkplanePlacer
                      view={viewRef.current}
                      base={placeBase.frame}
                      values={placing.values}
                      mode={placing.mode}
                      half={20}
                      onChange={(values) => setPlacing((p) => (p ? { ...p, values } : p))}
                    />
                    <WorkplanePlacePanel
                      title={placing.kind === "connector" ? "Connector" : "Workplane"}
                      createLabel={placing.kind === "connector" ? "Add" : "Create"}
                      bases={placeBases}
                      base={placeBase.value}
                      values={placing.values}
                      mode={placing.mode}
                      name={placing.name}
                      busy={guiBusy}
                      error={placing.error}
                      onBase={(base) => setPlacing((p) => (p ? { ...p, base } : p))}
                      onMode={(mode) => setPlacing((p) => (p ? { ...p, mode } : p))}
                      onValues={(values) => setPlacing((p) => (p ? { ...p, values } : p))}
                      onName={(name) => setPlacing((p) => (p ? { ...p, name } : p))}
                      onCreate={() => void createPlaced()}
                      onCancel={() => setPlacing(null)}
                    />
                  </>
                )}
                {!sketching && viewRef.current && gizmos.length > 0 && (
                  <ConnectorGizmos view={viewRef.current} gizmos={gizmos} components={asm.doc.components} highlighted={gizmoHighlight} onPick={pickGizmo} armed={!!asm.target} />
                )}
                {/* mounted in both modes: it slides up from the bottom edge into manual mode and back down out of it */}
                {MANUAL_MODE && (
                  <div inert={sketching} className={cn(sketching && "opacity-40")}>
                    <CommandBar commands={commands} fit={fit} hint={hint} shown={(modeTarget ?? mode) === "manual"} />
                  </div>
                )}
                {session?.handle && viewRef.current && sessionDistance && (
                  <PressPullHandle
                    view={viewRef.current}
                    origin={session.handle.origin}
                    normal={session.handle.normal}
                    distance={Number(sessionDistance.value)}
                    min={session.handle.min}
                    onChange={(distance, done) => {
                      sessionTouched.current.add(sessionDistance.id);
                      sessionSettler.current.push(sessionDistance.id, distance);
                      if (done) sessionSettler.current.flush();
                    }}
                  />
                )}
                {session && viewRef.current && (
                  <OperationPanel
                    view={viewRef.current}
                    anchorMm={session.anchorMm}
                    title={session.editing ? `${session.title} · ${session.slug}` : session.title}
                    params={sessionParams}
                    error={session.error ?? (session.cell ? (partial?.failed.find((cell) => cell.cell === session.cell)?.error ?? null) : null)}
                    busy={session.busy}
                    editing={session.editing}
                    picks={
                      session.pick && session.cell
                        ? {
                            label: t(session.pick.label),
                            hint: session.pick.entity === "edge" ? t("Click edges on the model to add them") : t("Click faces on the model to add them"),
                            items: sessionHeld.map(refLabel),
                            onRemove: (index) => editSessionPicks(removePick(sessionHeld, index)),
                          }
                        : undefined
                    }
                    onParam={(id, value, now) => {
                      sessionTouched.current.add(id);
                      sessionSettler.current.push(id, value);
                      if (now) sessionSettler.current.flush();
                    }}
                    onConfirm={confirmSession}
                    onCancel={cancelSession}
                    onMore={() => {
                      const current = sessionRef.current;
                      const row = current?.cell ? gui.state.features.find((feature) => feature.cell === current.cell) : undefined;
                      const spec = current ? gui.catalog?.specs.find((item) => item.id === current.specId) : undefined;
                      confirmSession();
                      if (row && spec) setDialog({ spec, edit: row });
                    }}
                  />
                )}
                {mode === "manual" && !session && !sketching && !dialog && !placing && !drawing && leftTab !== "assembly" && loading === null && viewRef.current && (
                  <SelectionBar view={viewRef.current} commands={commands} context={context} anchorMm={anchorMm} icons={FEATURE_ICONS} notice={barNote} disabled={barDisabled} />
                )}
                {(
                  <FloatingPanels
                    inspector={inspectorPanel}
                    chips={modeChips}
                    selectionCount={selection.length}
                    task={taskOpen}
                    locked={sketching || moving}
                    leftNotice={!taskOpen && viewRef.current ? <TagSplits docked view={viewRef.current} splits={tagSplits} sceneVersion={sceneVersion} /> : null}
                    rightNotice={partial && !sketching ? <PartialNotice docked partial={partial} titles={cellTitles} /> : null}
                  />
                )}
                {sketchSession && viewRef.current && (
                  <SketchMode
                    session={sketchSession}
                    view={viewRef.current}
                    taken={gui.state.taken}
                    features={gui.state.features}
                    notice={sketchNotice}
                    faceCheck={faceCheck}
                    faceInk={PALETTES[theme.resolved].selection}
                    sketchPlanes={sketchList.map((info) => ({ name: info.name, plane: info.doc.plane }))}
                    workplanes={workplanes.map((wp) => ({ name: wp.name, plane: workplanePlane(wp) }))}
                    onPlane={choosePlane}
                    onSubmit={submitSketch}
                    onExit={endSketch}
                  />
                )}
              </div>
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
        <FeatureDialog
          request={dialog}
          state={gui.state}
          selection={selection}
          sketches={dialogSketches}
          onSelectionMode={setSelectionMode}
          onSubmit={submitFeature}
          onClose={closeDialog}
          view={viewRef.current}
        />
        <LoadingMask active={loading !== null} message={loading ?? ""} theme={theme.resolved} />
      </div>
      <Dock
        entries={log.entries}
        batch={log.batch}
        status={status}
        unseenErrors={log.unseenErrors}
        quiet={!!session}
        onClear={log.clear}
        onSeen={log.markSeen}
      />
    </div>
  );
}

export type { Envelope };
