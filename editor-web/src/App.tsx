import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CellEditor, type NotebookCell, type NotebookFeature, type ParamMeta } from "@/components/CellEditor";
import { Dock } from "@/components/Dock";
import { Header } from "@/components/Header";
import { Inspector } from "@/components/Inspector";
import { LoadingMask } from "@/components/LoadingMask";
import { ModuleView, type ModuleState } from "@/components/ModuleView";
import { NotebookList } from "@/components/NotebookList";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchPreview, getWorkspace, openNotebook, postViewport, type ModuleRow, type NotebookRow } from "@/lib/api";
import { parsePreview } from "@/lib/preview";
import { EnvelopeSocket, type Envelope } from "@/lib/envelope";
import { useRunLog } from "@/lib/runlog";
import { selectionPayload, variableNames, type SelectionItem } from "@/lib/selection";
import { cn } from "@/lib/utils";
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
  const [marimoUrl, setMarimoUrl] = useState<string | null>(null);
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

  const kind = notebooks.find((row) => row.path === currentPath)?.kind ?? null;
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

  const loadPreviewBytes = useCallback(async (buffer: ArrayBuffer, name: string | null) => {
    const view = viewRef.current;
    if (!view) return;
    try {
      const preview = parsePreview(buffer);
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
      setKernelAlive(Boolean(envelope["kernel"]));
      // No notebook: nothing to wait for. Else the model is on its way.
      if (hasModel.current) return;
      const stage = envelope["notebook"] ? (envelope["kernel"] ? "building the model" : "starting the kernel") : null;
      setLoading(stage);
      if (stage) setStatus(`${stage[0].toUpperCase()}${stage.slice(1)}…`);
      setMarimoUrl((envelope["marimo_url"] as string) ?? null);
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
      void fetchPreview().then((buffer) => loadPreviewBytes(buffer, (envelope["name"] as string) ?? null));
      log.modelShown();
    });

    // The details of a picked entity (a preview carries none), asked for when it was picked.
    socket.on("entity.info", (envelope) => {
      const entityId = String(envelope["entity_id"]);
      const entity = envelope["entity"] as { properties?: Record<string, unknown>; geometry?: Record<string, unknown>; tags?: string[] } | null;
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
  }, [loadPreviewBytes, log.push, log.cellStatus, log.knowCells, log.resetBatch, log.modelShown]);

  // -- selection -------------------------------------------------------------------

  const handlePick = useCallback((result: PickResult) => {
    const view = viewRef.current;
    const node = view?.nodes.find((item) => item.node_id === result.nodeId);
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
  }, []);

  const handleClear = useCallback(() => setPicked((previous) => (previous.length ? [] : previous)), []);

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

  // -- actions -----------------------------------------------------------------------

  const handleOpen = (path: string) => {
    setStatus(`opening ${path}…`);
    openNotebook(path).catch((error) => {
      log.push("error", `open failed: ${error.message}`);
      setLoading(null);
    });
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header
        notebook={notebook}
        kind={kind}
        kernelAlive={kernelAlive}
        status={status}
        marimoUrl={marimoUrl}
        running={running}
        onStop={handleStop}
        onRunAll={() => {
          setLoading("running all cells");
          socketRef.current?.send({ type: "rerun.request" });
        }}
      />
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ResizablePanelGroup className="min-h-0 flex-1">
          <ResizablePanel defaultSize={32} minSize={18} className="min-w-0">
            <Tabs value={leftTab} onValueChange={setLeftTab} className="h-full">
              <TabsList>
                <TabsTrigger value="notebook">notebook</TabsTrigger>
                <TabsTrigger value="workspace">workspace</TabsTrigger>
                {moduleView && <TabsTrigger value="module">{moduleView.name}</TabsTrigger>}
              </TabsList>
              <TabsContent value="notebook" className="min-h-0">
                <CellEditor
                  cells={cells}
                  features={features}
                  params={params}
                  socket={socketRef.current}
                  notebook={notebook}
                  onInterrupt={handleStop}
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
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={46} minSize={30} className="min-w-0">
            <div className="flex h-full flex-col">
              <div className="flex h-9 shrink-0 items-center gap-1 border-b-2 border-border px-2">
                {MODES.map(({ mode, label }) => (
                  <button
                    key={mode}
                    type="button"
                    className={cn(
                      "border-2 px-2 py-px text-[10px] font-semibold uppercase tracking-[0.1em] transition-colors",
                      selectionMode === mode
                        ? "border-white bg-white text-black"
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
              <div className="min-h-0 flex-1">
                <Viewport
                  viewRef={viewRef}
                  selectionMode={selectionMode}
                  selection={selection}
                  sceneVersion={sceneVersion}
                  onPick={handlePick}
                  onClear={handleClear}
                />
              </div>
            </div>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={22} minSize={14} className="min-w-0">
            <Inspector selection={selection} />
          </ResizablePanel>
        </ResizablePanelGroup>
        <LoadingMask active={loading !== null} message={loading ?? ""} />
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
