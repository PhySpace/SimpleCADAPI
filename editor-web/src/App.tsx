import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CellEditor, type NotebookCell, type NotebookFeature, type ParamMeta } from "@/components/CellEditor";
import { Dock } from "@/components/Dock";
import { FeatureDialog, type DialogRequest } from "@/components/FeatureDialog";
import { CommandBar } from "@/components/CommandBar";
import { FEATURE_ICONS } from "@/components/feature-icons";
import { FeatureTree } from "@/components/FeatureTree";
import { assemblyCommands, commandsFromSpecs } from "@/lib/commands";
import { AssemblyPanel } from "@/components/AssemblyPanel";
import { ConnectorGizmos, type Gizmo } from "@/components/ConnectorGizmos";
import { setRef } from "@/lib/assembly";
import { useAssemblyEditor, useConnectorDraft } from "@/lib/useAssembly";
import { Header } from "@/components/Header";
import { Inspector } from "@/components/Inspector";
import { SketchMode, type SketchSession } from "@/components/sketch/SketchMode";
import { LoadingMask } from "@/components/LoadingMask";
import { ModuleView, type ModuleState } from "@/components/ModuleView";
import { NotebookList } from "@/components/NotebookList";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getWorkspace, newNotebook, openNotebook, postViewport, type ModuleRow, type NotebookRow } from "@/lib/api";
import { parsePreview, type PreviewPart } from "@/lib/preview";
import { EnvelopeSocket, type Envelope } from "@/lib/envelope";
import { emptyDoc, normalizeDoc } from "@/lib/sketch";
import { frameFromEntity, type PlaneSpec } from "@/lib/sketch-plane";
import { useFeatures } from "@/lib/useFeatures";
import { assertCellRan, isCellCommand, type FeatureCommand, type FeatureRow, type Spec } from "@/lib/features";
import { useRunLog } from "@/lib/runlog";
import { useTheme } from "@/lib/theme";
import { selectionPayload, variableNames, type SelectionItem } from "@/lib/selection";
import { cn } from "@/lib/utils";
import { Boxes, Cable } from "lucide-react";
import { Viewport, type PickResult, type SelectionMode } from "@/scene/Viewport";
import type { SceneView } from "@/scene/scene-view";

const MODES: { mode: SelectionMode; label: string }[] = [
  { mode: "component", label: "comp" },
  { mode: "solid", label: "solid" },
  { mode: "face", label: "face" },
  { mode: "edge", label: "edge" },
  { mode: "vertex", label: "vert" },
];

/** Editor application: left = notebook (cells, workspace), middle = the live
 * model, right = the selection. The model is the in-memory scadpkg the kernel
 * publishes whenever the cells settle; picking in the viewport writes the
 * selection into the notebook (see `selection.set`). */
export function App() {
  const viewRef = useRef<SceneView | null>(null);
  // Whether a model of the open notebook is on screen (it may be the last run's,
  // restored while the kernel boots): then nothing is being waited for.
  const hasModel = useRef(false);
  const socketRef = useRef<EnvelopeSocket | null>(null);

  const [notebooks, setNotebooks] = useState<NotebookRow[]>([]);
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [moduleView, setModuleView] = useState<ModuleState | null>(null);
  const [leftTab, setLeftTab] = useState("notebook");
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
      setStatus(`${preview.nodes.length} ${preview.nodes.length === 1 ? "part" : "parts"} · ${preview.parts.size} distinct`);
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

    socket.on("preview", (envelope) => {
      setLoading(null);
      const shown = hasModel.current;
      hasModel.current = true;
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

  /** While the sketch plane is being chosen a face pick means "sketch on this face" and never reaches the selection. */
  const pickSketchFace = useCallback(
    async (result: PickResult) => {
      if (!result.entityId || result.mode !== "face") return;
      let geometry = result.entity?.geometry as Record<string, unknown> | undefined;
      let properties = result.entity?.properties as Record<string, unknown> | undefined;
      if (!geometry || Object.keys(geometry).length === 0) {
        const info = await askEntity(result.nodeId, result.entityId);
        geometry = info?.geometry;
        properties = info?.properties;
      }
      const frame = geometry ? frameFromEntity(geometry, properties) : null;
      if (!frame) {
        setSketchNotice("That face is not planar: click a planar face or a datum plane.");
        return;
      }
      choosePlane(frame);
    },
    [askEntity, choosePlane],
  );

  const leftTabRef = useRef(leftTab);
  leftTabRef.current = leftTab;
  const selectComponent = asm.setSelected;
  const handlePick = useCallback((result: PickResult) => {
    if (choosingRef.current) {
      void pickSketchFace(result);
      return;
    }
    if (sketchingRef.current) return;
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
      if (modeBeforeSketch.current === null) modeBeforeSketch.current = selectionMode;
      setSelectionMode("face"); // a face pick chooses the sketch plane
      setPicked([]);
      setSketchSession({ ...session, id: ++sketchCounter.current });
    },
    [selectionMode],
  );
  const startSketch = useCallback(() => {
    if (!sketchingRef.current) beginSketch({ mode: "new", name: "", plane: null, doc: emptyDoc() });
  }, [beginSketch]);
  const endSketch = useCallback(() => {
    setSketchSession(null);
    setSketchNotice(null);
    if (modeBeforeSketch.current !== null) setSelectionMode(modeBeforeSketch.current);
    modeBeforeSketch.current = null;
  }, []);
  /** Finish: the add or edit command; rejects with the server's message (shown in the sketch bar), leaves sketch mode on success. */
  const submitSketch = useCallback(
    async (command: FeatureCommand) => {
      const result = await gui.run(command);
      log.push("ok", command.op === "undo" || command.op === "redo" ? command.op : `${command.op} ${result.name}`);
      if (isCellCommand(command)) assertCellRan(result);
      endSketch();
    },
    [gui.run, log.push, endSketch],
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
  const commands = useMemo(
    () => [
      // The assembly layout is not a dialog: it is its own panel (registered below), so its spec is left out of the generic list.
      ...commandsFromSpecs((gui.catalog?.specs ?? []).filter((spec) => spec.id !== "assembly"), (spec) => (isSketchSpec(spec) ? startSketch() : openDialog({ spec })), FEATURE_ICONS),
      ...assemblyCommands(openAssembly, { assembly: Boxes, connectors: Cable }),
    ],
    [gui.catalog, openDialog, startSketch, openAssembly],
  );

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
          <ResizablePanel defaultSize={32} minSize={18} className="min-w-0">
            <div inert={sketching} className={cn("h-full", sketching && "opacity-40")}>
            <Tabs value={leftTab} onValueChange={setLeftTab} className="h-full">
              <TabsList>
                <TabsTrigger value="features">features</TabsTrigger>
                <TabsTrigger value="assembly">assembly</TabsTrigger>
                <TabsTrigger value="notebook">notebook</TabsTrigger>
                <TabsTrigger value="workspace">workspace</TabsTrigger>
                {moduleView && <TabsTrigger value="module">{moduleView.name}</TabsTrigger>}
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
                  onUndo={undo}
                  onRedo={redo}
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
          <ResizablePanel defaultSize={46} minSize={30} className="min-w-0">
            <div className="flex h-full flex-col">
              <div inert={sketching} className={cn("flex h-9 shrink-0 items-center gap-1 border-b-2 border-border px-2", sketching && "opacity-40")}>
                {MODES.map(({ mode, label }) => (
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
                  >
                    {label}
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
              <div className="relative min-h-0 flex-1">
                <Viewport
                  viewRef={viewRef}
                  selectionMode={selectionMode}
                  selection={selection}
                  sceneVersion={sceneVersion}
                  theme={theme.resolved}
                  onPick={handlePick}
                  onClear={handleClear}
                />
                {!sketching && viewRef.current && gizmos.length > 0 && (
                  <ConnectorGizmos view={viewRef.current} gizmos={gizmos} components={asm.doc.components} highlighted={gizmoHighlight} onPick={pickGizmo} />
                )}
                <div inert={sketching} className={cn(sketching && "opacity-40")}>
                  <CommandBar commands={commands} />
                </div>
                {sketchSession && viewRef.current && (
                  <SketchMode
                    session={sketchSession}
                    view={viewRef.current}
                    taken={gui.state.taken}
                    features={gui.state.features}
                    notice={sketchNotice}
                    onPlane={choosePlane}
                    onSubmit={submitSketch}
                    onExit={endSketch}
                  />
                )}
              </div>
            </div>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={22} minSize={14} className="min-w-0">
            <div inert={sketching} className={cn("h-full", sketching && "opacity-40")}>
              <Inspector selection={selection} />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
        <FeatureDialog
          request={dialog}
          state={gui.state}
          selection={selection}
          onSelectionMode={setSelectionMode}
          onSubmit={submitFeature}
          onClose={closeDialog}
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
