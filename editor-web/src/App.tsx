import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CellEditor, type NotebookCell, type NotebookFeature, type ParamMeta } from "@/components/CellEditor";
import { Dock } from "@/components/Dock";
import { FeatureDialog, type DialogRequest } from "@/components/FeatureDialog";
import { SelectionBar } from "@/components/SelectionBar";
import { selectionAnchorMm } from "@/lib/selection-anchor";
import { SketchScene } from "@/components/SketchScene";
import { CommandBar } from "@/components/CommandBar";
import { FEATURE_ICONS } from "@/components/feature-icons";
import { FeatureTree, type TreeSketches } from "@/components/FeatureTree";
import { assemblyCommands, commandsFromSpecs, fitScore, selectionContext, selectionHint, visibleCommands, whenFor, type Command } from "@/lib/commands";
import { type EditorMode } from "@/components/ModeSwitch";
import { sideStyle, useModeTransition } from "@/lib/useModeTransition";
import { AssemblyPanel } from "@/components/AssemblyPanel";
import { ConnectorGizmos, type Gizmo } from "@/components/ConnectorGizmos";
import { WorkplanePatches } from "@/components/WorkplanePatches";
import { TagSplits, parseTagSplits, type TagSplit } from "@/components/TagSplits";
import { PartialNotice } from "@/components/PartialModel";
import { describePartial, parsePartial, samePartial, type PartialModel } from "@/lib/partial";
import { WorkplanePlacePanel, WorkplanePlacer, type PlaceBase, type PlaceMode } from "@/components/WorkplanePlacer";
import { CurveDrawer } from "@/components/CurveDrawer";
import { CurveLines, curveEnds, parseCurves, type CurveSample } from "@/components/CurveLines";
import type { CurveDoc, DrawPlane } from "@/lib/curve3d";
import { NAMED_FRAMES, ZERO_PLACE, cleanValues, faceFrame, type PlaceFrame, type PlaceValues } from "@/lib/workplane-place";
import { parseWorkplanes, resolvePlane, workplanePlane, workplaneRequest, type WorkplaneFrame } from "@/lib/workplanes";
import { fitDistanceMm } from "@/lib/sketch-view";
import { viewPose } from "@/lib/sketch-plane";
import * as THREE from "three";
import { setRef } from "@/lib/assembly";
import { useAssemblyEditor, useConnectorDraft } from "@/lib/useAssembly";
import { Header } from "@/components/Header";
import { Inspector } from "@/components/Inspector";
import { SketchMode, type FaceCheck, type SketchAfter, type SketchSession } from "@/components/sketch/SketchMode";
import { LoadingMask } from "@/components/LoadingMask";
import { ModuleView, type ModuleState } from "@/components/ModuleView";
import { NotebookList } from "@/components/NotebookList";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getWorkspace, newNotebook, openNotebook, postViewport, type ModuleRow, type NotebookRow } from "@/lib/api";
import { parsePreview, previewSummary, type PreviewPart } from "@/lib/preview";
import { EnvelopeSocket, type Envelope } from "@/lib/envelope";
import { emptyDoc, normalizeDoc } from "@/lib/sketch";
import { frameFromEntity, type PlaneSpec } from "@/lib/sketch-plane";
import { useFeatures } from "@/lib/useFeatures";
import { describeSketch, nextSketchSelection, readHidden, sketchCentre, sketchInfos, toggleHidden, writeHidden } from "@/lib/sketch-scene";
import { useSketchShapes } from "@/lib/useSketchShapes";
import type { Vec3 } from "@/lib/sketch-plane";
import { PALETTES } from "@/scene/theme";
import { assertCellRan, isCellCommand, pickedPayload, type FeatureCommand, type FeatureRow, type Spec } from "@/lib/features";
import { useRunLog } from "@/lib/runlog";
import { useTheme } from "@/lib/theme";
import { selectionPayload, variableNames, type SelectionItem } from "@/lib/selection";
import { cn } from "@/lib/utils";
import { Boxes, Cable } from "lucide-react";
import { Viewport, type PickResult, type SelectionMode } from "@/scene/Viewport";
import type { SceneView } from "@/scene/scene-view";

/** The pick intents and their keys: 1 vertex, 2 edge, 3 face, 4 solid (Plasticity's order), 5 component, 6 sketch. */
const MODES: { mode: SelectionMode; label: string; key: string }[] = [
  { mode: "component", label: "comp", key: "5" },
  { mode: "solid", label: "solid", key: "4" },
  { mode: "face", label: "face", key: "3" },
  { mode: "edge", label: "edge", key: "2" },
  { mode: "vertex", label: "vert", key: "1" },
  { mode: "sketch", label: "sketch", key: "6" },
];

/** Editor application: left = notebook (cells, workspace), middle = the live
 * model, right = the selection. The model is the in-memory scadpkg the kernel
 * publishes whenever the cells settle; picking in the viewport writes the
 * selection into the notebook (see `selection.set`). */
const MANUAL_TABS = ["features", "assembly"];

export function App() {
  const viewRef = useRef<SceneView | null>(null);
  // Whether a model of the open notebook is on screen (it may be the last run's,
  // restored while the kernel boots): then nothing is being waited for.
  const hasModel = useRef(false);
  const socketRef = useRef<EnvelopeSocket | null>(null);

  const [notebooks, setNotebooks] = useState<NotebookRow[]>([]);
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [moduleView, setModuleView] = useState<ModuleState | null>(null);
  // Two modes, never mixed on one page: manual (features, assemblies) and code (notebook, workspace).  The left tab says which.
  const [leftTab, setLeftTab] = useState("features");
  const mode: EditorMode = MANUAL_TABS.includes(leftTab) ? "manual" : "code";
  const lastTab = useRef<Record<EditorMode, string>>({ manual: "features", code: "notebook" });
  lastTab.current[mode] = leftTab;
  const [modeTarget, setModeTarget] = useState<EditorMode | null>(null);
  const motion = useModeTransition((target) => {
    setLeftTab(lastTab.current[target as EditorMode]);
    setModeTarget(null);
  });
  const changeMode = (target: EditorMode) => {
    setModeTarget(target);
    motion.go(target);
  };
  const [notebook, setNotebook] = useState<string | null>(null);
  // The notebook the server says is open (workspace-relative): what the list
  // highlights.  It changes the moment another is asked for, not when its
  // kernel is up, and a late answer of the workspace list cannot undo it.
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [kernelAlive, setKernelAlive] = useState(false);
  const [status, setStatus] = useState("Connecting…");

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
  // A workplane being placed by hand (Space): its base, the numbers the handles write, move or turn, its name.
  const [placing, setPlacing] = useState<{ base: string; values: PlaceValues; mode: PlaceMode; name: string; face: { item: SelectionItem; frame: PlaceFrame } | null; error: string | null } | null>(null);
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
    log.push("info", "stop requested");
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
      setStatus(previewSummary(preview.nodes));
      if (framedNotebook.current !== name) {
        view.frame();
        framedNotebook.current = name;
      }
      setSceneVersion((version) => version + 1);
      log.push("ok", `model shown: ${preview.nodes.length} ${preview.nodes.length === 1 ? "part" : "parts"}`);
    } catch (error) {
      log.push("error", error instanceof Error ? error.message : "unable to open the preview");
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
      const stage = envelope["notebook"] ? (envelope["kernel"] ? "building the model" : "starting the kernel") : null;
      setLoading(stage);
      setStatus(stage ? `${stage[0].toUpperCase()}${stage.slice(1)}…` : "No notebook yet: create one in the workspace tab");
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
      refreshFeatures();
      setNotebook(String(envelope["notebook"] ?? ""));
      setCurrentPath((envelope["path"] as string) ?? null);
      setStatus(`opening ${envelope["notebook"]}…`);
      setLoading(`opening ${envelope["notebook"]}`);
      log.resetBatch();
      log.push("info", `opening ${envelope["notebook"]}`);
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
      log.push("error", `a cell changed on disk while you were editing it: kept the file's version. Your unsaved text was:\n${mine.length > 600 ? `${mine.slice(0, 600)}…` : mine}`);
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
        log.push("info", `showing ${title.charAt(0).toLowerCase()}${title.slice(1)}: ${reason}`);
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
        setStatus(envelope["info"]);
        log.push("info", envelope["info"]);
      } else if (typeof envelope["working"] === "string") {
        setStatus(envelope["working"]);
        log.push("run", envelope["working"]);
        setLoading(envelope["working"].replace(/…$/, ""));
      } else if (typeof envelope["exported"] === "string") {
        setStatus(`exported ${envelope["exported"]}`);
        log.push("ok", `exported ${envelope["exported"]}`);
      } else if (typeof envelope["created"] === "string") {
        setStatus(`created ${envelope["created"]}`);
        log.push("ok", `created ${envelope["created"]}`);
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
  const refusal = (type: string | null) => `This face is ${type ? `a ${type.toLowerCase()}` : "curved"}: a sketch needs a flat face. Pick a flat face or a datum plane.`;

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
  const handlePick = useCallback((result: PickResult) => {
    if (placingRef.current || drawingRef.current) return; // a click on the handles, or a curve's point, is not a pick
    if (dialogRef.current?.spec.id === "hole") return; // a click places the hole (HolePlacer), it picks nothing
    if (choosingRef.current) {
      void pickSketchFace(result);
      return;
    }
    if (sketchingRef.current) return;
    setPickedSketches((previous) => (previous.length ? [] : previous));
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
    setBarNote(null);
  }, []);

  /** A click on a sketch (or on nothing) in the sketch selection mode, or on a sketch row of the tree. */
  const pickSketch = useCallback((name: string | null, additive: boolean) => {
    if (sketchingRef.current) return;
    setBarNote(null);
    if (name === null) {
      if (!additive) {
        setPickedSketches((previous) => (previous.length ? [] : previous));
        setPicked((previous) => (previous.length ? [] : previous));
      }
      return;
    }
    setPicked((previous) => (previous.length ? [] : previous));
    setPickedSketches((previous) => nextSketchSelection(previous, name, additive));
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

  const openDialog = useCallback(
    (request: DialogRequest) => {
      if (modeBeforeDialog.current === null) modeBeforeDialog.current = selectionMode;
      setDialog(request);
    },
    [selectionMode],
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
      log.push("ok", command.op === "undo" || command.op === "redo" ? command.op : `${command.op} ${result.name}`);
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
        log.push("ok", command.op === "undo" || command.op === "redo" ? command.op : `${command.op} ${result.name}`);
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
    if (sketchingRef.current) return;
    const active = workplanesRef.current.find((wp) => wp.name === activeWorkplaneRef.current);
    if (active) {
      const plane = workplanePlane(active); // the active workplane: the sketch cell writes plane=<it>
      beginSketch({ mode: "new", name: "", plane, doc: emptyDoc(plane) });
    } else beginSketch({ mode: "new", name: "", plane: null, doc: emptyDoc() });
  }, [beginSketch]);
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
      log.push("ok", command.op === "undo" || command.op === "redo" ? command.op : `${command.op} ${result.name}`);
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
  const context = useMemo(() => selectionContext(selection, pickedSketches), [selection, pickedSketches]);

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
      setBarNote("A workplane needs one flat face, a face and an edge, two parallel faces, three vertices or one edge.");
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
      log.push("ok", `add ${result.name}`);
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
    if (sketchingRef.current || placingRef.current) return;
    const active = activeWorkplaneRef.current;
    setPicked([]);
    setDrawing({ plane: active && workplanesRef.current.some((wp) => wp.name === active) ? active : "XY", error: null });
  }, []);
  const commitCurve = useCallback(
    async (doc: CurveDoc, name: string) => {
      setGuiBusy(true);
      try {
        const result = await gui.run({ op: "add", spec: "curve", name, values: { curve: doc } });
        assertCellRan(result);
        log.push("ok", `add ${result.name}`);
        setDrawing(null);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setDrawing((d) => (d ? { ...d, error: message } : d));
      } finally {
        setGuiBusy(false);
      }
    },
    [gui.run, log.push],
  );
  // W: draw a 3D curve (not while typing, sketching or placing a workplane).
  useEffect(() => {
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
    const out: PlaceBase[] = (["XY", "XZ", "YZ"] as const).map((name) => ({ value: name, label: name, frame: NAMED_FRAMES[name] }));
    for (const wp of workplanes) out.push({ value: wp.name, label: wp.name, frame: { origin: wp.origin, x_axis: wp.x_axis, y_axis: wp.y_axis, normal: wp.normal } });
    if (placing?.face) out.push({ value: "face", label: "picked face", frame: placing.face.frame });
    return out;
  }, [workplanes, placing?.face]);
  const placeBase = placeBases.find((item) => item.value === placing?.base) ?? placeBases[0];

  /** Start placing: on the picked flat face, else on the active workplane (one after another builds a 3D frame of
   * planes), else on XY. */
  const startPlacing = useCallback(() => {
    const items = selectionRef.current;
    const face = items.length === 1 && items[0].kind === "face" ? items[0] : null;
    const frame = face ? faceFrame(face.properties) : null;
    if (face && !frame) {
      setBarNote("That face is not flat: a workplane lies on a plane. Pick a flat face, or nothing to place one on the active workplane.");
      return;
    }
    const taken = gui.state?.taken ?? [];
    let name = "wp";
    for (let n = 2; taken.includes(name); n++) name = `wp_${n}`;
    const base = face ? "face" : activeWorkplaneRef.current && workplanesRef.current.some((wp) => wp.name === activeWorkplaneRef.current) ? activeWorkplaneRef.current : "XY";
    setBarNote(null);
    setPlacing({ base, values: ZERO_PLACE, mode: "translate", name, face: face && frame ? { item: face, frame } : null, error: null });
  }, [gui.state?.taken]);

  const createPlaced = useCallback(async () => {
    const current = placingRef.current;
    if (!current) return;
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
      log.push("ok", `add ${result.name}`);
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
  }, [gui.run, log.push]);

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
  const allCommands = useMemo<Command[]>(
    () => [
      // The assembly layout is not a dialog: it is its own panel (registered below), so its spec is left out of the generic list.
      ...commandsFromSpecs((gui.catalog?.specs ?? []).filter((spec) => spec.id !== "assembly" && spec.id !== "workplane" && spec.id !== "curve"), openSpec, FEATURE_ICONS),
      {
        id: "curve_draw",
        label: "3D curve",
        group: "Sketch",
        keywords: ["curve", "wire", "path", "3d", "polyline", "spline", "arc", "rail", "sweep"],
        description: "Draw a path in space (W): lines, arcs and splines on workplanes, snapped to the model; it becomes a wire to sweep along or loft through.",
        icon: FEATURE_ICONS.sketch,
        run: () => startDrawing(),
      },
      {
        id: "workplane_place",
        label: "Workplane",
        group: "Datums",
        keywords: ["workplane", "datum", "plane", "offset", "rotate", "move", "space"],
        description: "Place a workplane with handles (Space): on the picked flat face, else on the active workplane, else on XY; move and turn it, then sketch on it.",
        icon: FEATURE_ICONS.workplane_from_selection,
        run: () => startPlacing(),
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
    [gui.catalog, openSpec, sketchOnSelectedFace, editSelectedSketch, openAssembly, workplaneFromSelection, startPlacing, startDrawing],
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
  const anchorMm = useMemo(() => {
    const view = viewRef.current;
    if (!view) return null;
    const first = sketchList.find((info) => info.name === pickedSketches[0]);
    const sketchAt = first ? sketchCentre(first.doc, sketchShapes.get(first.name)?.shape ?? null) : null;
    return selectionAnchorMm(view, selection, sketchAt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, pickedSketches, sketchList, sketchShapes, sceneVersion]);

  /** A command from the assembly panel: rejects with the server's message (shown in the panel). */
  const runPanelCommand = useCallback(
    async (command: FeatureCommand) => {
      const result = await gui.run(command);
      log.push("ok", command.op === "set_connectors" ? "connectors set" : `${command.op} ${result.name}`);
      if (isCellCommand(command)) assertCellRan(result);
    },
    [gui.run, log.push],
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
      openDialog({ spec, edit: feature });
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
    setStatus(`opening ${path}…`);
    openNotebook(path).catch((error) => {
      log.push("error", `open failed: ${error.message}`);
      setLoading(null);
    });
  };

  const handleCreate = async (name: string, kind: "part" | "assembly") => {
    setStatus(`creating ${name}…`);
    await newNotebook(name, kind);
    // the server opens it: show its cells
    setLeftTab("notebook");
  };

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
        features={gui.state}
        onUndo={undo}
        onRedo={redo}
        mode={modeTarget ?? mode}
        onMode={changeMode}
        modeLocked={sketching || motion.moving}
        running={running}
        onStop={handleStop}
        onRunAll={() => {
          setLoading("running all cells");
          socketRef.current?.send({ type: "rerun.request" });
        }}
      />
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ResizablePanelGroup className="min-h-0 flex-1">
          <ResizablePanel defaultSize={23} minSize={16} className="min-w-0" style={{ overflow: "hidden" }}>
            <div inert={sketching || motion.moving} className={cn("h-full", sketching && "opacity-40")} style={sideStyle(motion.phase, -1)}>
            <Tabs value={leftTab} onValueChange={setLeftTab} className="h-full min-w-0 overflow-hidden">
              <TabsList>
                {mode === "manual" ? (
                  <>
                    <TabsTrigger value="features">features</TabsTrigger>
                    <TabsTrigger value="assembly">assembly</TabsTrigger>
                  </>
                ) : (
                  <>
                    <TabsTrigger value="notebook">notebook</TabsTrigger>
                    <TabsTrigger value="workspace">workspace</TabsTrigger>
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
            </div>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={55} minSize={30} className="min-w-0 overflow-hidden">
            <div className="flex h-full flex-col">
              <div inert={sketching} className={cn("flex h-9 shrink-0 items-center gap-1 border-b-2 border-border px-2", sketching && "opacity-40")}>
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
                    title={`${label} (${key})`}
                  >
                    {label}
                    <span className="ml-1 opacity-50">{key}</span>
                  </button>
                ))}
                <span className="flex-1" />
                <span className="label hidden xl:inline">ctrl+click: add</span>
                <button
                  type="button"
                  className="border-2 border-transparent px-2 py-px text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground hover:border-input hover:text-foreground"
                  onClick={() => viewRef.current?.frame()}
                >
                  fit
                </button>
              </div>
              <div className="relative min-h-0 flex-1 overflow-hidden">
                <Viewport
                  viewRef={viewRef}
                  selectionMode={selectionMode}
                  selection={selection}
                  sceneVersion={sceneVersion}
                  theme={theme.resolved}
                  onPick={handlePick}
                  onClear={handleClear}
                  onSketchPick={pickSketch}
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
                {!sketching && !placing && !drawing && viewRef.current && <TagSplits view={viewRef.current} splits={tagSplits} sceneVersion={sceneVersion} />}
                {partial && !sketching && <PartialNotice partial={partial} titles={cellTitles} />}
                {viewRef.current && curves.length > 0 && <CurveLines view={viewRef.current} curves={curves} />}
                {drawing && viewRef.current && (
                  <CurveDrawer
                    view={viewRef.current}
                    planes={drawPlanes}
                    others={curveSnapPoints}
                    plane={drawing.plane}
                    busy={guiBusy}
                    error={drawing.error}
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
                {mode === "manual" && (
                  <div inert={sketching} className={cn(sketching && "opacity-40")}>
                    <CommandBar commands={commands} fit={fit} hint={hint} />
                  </div>
                )}
                {mode === "manual" && !sketching && !dialog && leftTab !== "assembly" && loading === null && viewRef.current && (
                  <SelectionBar view={viewRef.current} commands={commands} context={context} anchorMm={anchorMm} icons={FEATURE_ICONS} notice={barNote} disabled={barDisabled} />
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
          <ResizableHandle />
          <ResizablePanel defaultSize={22} minSize={14} className="min-w-0" style={{ overflow: "hidden" }}>
            <div inert={sketching || motion.moving} className={cn("h-full", sketching && "opacity-40")} style={sideStyle(motion.phase, 1)}>
              <Inspector selection={selection} sketches={inspectedSketches} />
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
        onClear={log.clear}
        onSeen={log.markSeen}
      />
    </div>
  );
}

export type { Envelope };
