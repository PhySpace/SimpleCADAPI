import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CellEditor, type NotebookCell, type NotebookFeature, type ParamMeta } from "@/components/CellEditor";
import { Header } from "@/components/Header";
import { Inspector } from "@/components/Inspector";
import { ModuleView, type ModuleState } from "@/components/ModuleView";
import { NotebookList } from "@/components/NotebookList";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchPackage, getWorkspace, openNotebook, postViewport, type ModuleRow, type NotebookRow } from "@/lib/api";
import { EnvelopeSocket, type Envelope } from "@/lib/envelope";
import { selectionPayload, variableNames, type SelectionItem } from "@/lib/selection";
import { cn } from "@/lib/utils";
import { Viewport, type PickResult, type SelectionMode } from "@/scene/Viewport";
import { openCadPackage } from "@/scene/product-package";
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
  const socketRef = useRef<EnvelopeSocket | null>(null);

  const [notebooks, setNotebooks] = useState<NotebookRow[]>([]);
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [moduleView, setModuleView] = useState<ModuleState | null>(null);
  const [leftTab, setLeftTab] = useState("notebook");
  const [notebook, setNotebook] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [kernelAlive, setKernelAlive] = useState(false);
  const [marimoUrl, setMarimoUrl] = useState<string | null>(null);
  const [status, setStatus] = useState("Connecting…");

  const [params, setParams] = useState<ParamMeta[]>([]);
  const [cells, setCells] = useState<NotebookCell[]>([]);
  const [features, setFeatures] = useState<NotebookFeature[]>([]);
  const [picked, setPicked] = useState<Omit<SelectionItem, "variable">[]>([]);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("solid");
  const [sceneVersion, setSceneVersion] = useState(0);

  const selection: SelectionItem[] = useMemo(() => {
    const names = variableNames(picked);
    return picked.map((item, index) => ({ ...item, variable: names[index] }));
  }, [picked]);

  // -- package → viewport -------------------------------------------------------

  // Camera framing is disruptive during slider drags; frame once per notebook.
  const framedNotebook = useRef<string | null>(null);

  const loadPackageBytes = useCallback(async (bytes: Uint8Array, name: string | null) => {
    const view = viewRef.current;
    if (!view) return;
    try {
      const opened = await openCadPackage(bytes);
      await view.loadScene(opened.files);
      const manifest = view.engine.manifest;
      if (!manifest) throw new Error("scene manifest missing");
      setStatus(`${manifest.nodes.length} occurrences · ${manifest.geometry_assets.length} geometry assets`);
      if (framedNotebook.current !== name) {
        view.frame();
        framedNotebook.current = name;
      }
      setSceneVersion((version) => version + 1);
    } catch (error) {
      setStatus(error instanceof Error ? `error: ${error.message}` : "error: unable to open package");
    }
  }, []);

  // -- socket + lifecycle --------------------------------------------------------

  useEffect(() => {
    const socket = new EnvelopeSocket(`ws://${window.location.host}/ws`);
    socketRef.current = socket;

    const refreshWorkspace = () =>
      void getWorkspace().then((data) => {
        setNotebooks(data.notebooks);
        setModules(data.modules ?? []);
        setKind(data.notebooks.find((row) => row.current)?.kind ?? null);
      });

    socket.on("hello", (envelope) => {
      setNotebook((envelope["notebook"] as string) ?? null);
      setKernelAlive(Boolean(envelope["kernel"]));
      setMarimoUrl((envelope["marimo_url"] as string) ?? null);
      refreshWorkspace();
    });

    // Another notebook is being opened: drop the old model and its state now,
    // the kernel takes a few seconds to boot and publish the new one.
    socket.on("opening", (envelope) => {
      viewRef.current?.clearScene();
      framedNotebook.current = null;
      setCells([]);
      setParams([]);
      setFeatures([]);
      setPicked([]);
      setNotebook(String(envelope["notebook"] ?? ""));
      setStatus(`opening ${envelope["notebook"]}…`);
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

    socket.on("notebook.cells", (envelope) => setCells((envelope["cells"] as NotebookCell[]) ?? []));
    socket.on("notebook.features", (envelope) => setFeatures((envelope["features"] as NotebookFeature[]) ?? []));

    socket.on("package", (envelope) => {
      void fetchPackage().then((bytes) => loadPackageBytes(bytes, (envelope["name"] as string) ?? null));
    });

    socket.on("status", (envelope) => {
      // An empty error means "the model is fine again": keep the package line.
      if (typeof envelope["error"] === "string") {
        if (envelope["error"]) setStatus(`error: ${envelope["error"]}`);
      } else if (typeof envelope["working"] === "string") setStatus(envelope["working"]);
      else if (typeof envelope["exported"] === "string") setStatus(`exported ${envelope["exported"]}`);
      else if (typeof envelope["created"] === "string") setStatus(`created ${envelope["created"]}`);
    });

    socket.connect();
    return () => socket.close();
  }, [loadPackageBytes]);

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
    const send = window.setTimeout(
      () => socketRef.current?.send({ type: "selection.set", items: selectionPayload(selection) }),
      120,
    );
    const snapshot = window.setTimeout(() => {
      const png = viewRef.current?.snapshotPng();
      if (png) void postViewport(png).catch(() => undefined);
    }, 600);
    return () => {
      window.clearTimeout(send);
      window.clearTimeout(snapshot);
    };
  }, [selection]);

  // -- actions -----------------------------------------------------------------------

  const handleOpen = (path: string) => {
    setStatus(`opening ${path}…`);
    openNotebook(path).catch((error) => setStatus(`error: open failed: ${error.message}`));
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header
        notebook={notebook}
        kind={kind}
        kernelAlive={kernelAlive}
        status={status}
        marimoUrl={marimoUrl}
        onRunAll={() => socketRef.current?.send({ type: "rerun.request" })}
      />
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
              />
            </TabsContent>
            <TabsContent value="workspace" className="min-h-0">
              <NotebookList
                notebooks={notebooks}
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
    </div>
  );
}

export type { Envelope };
