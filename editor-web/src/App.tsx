import { useCallback, useEffect, useRef, useState } from "react";

import { CellEditor, type NotebookCell, type NotebookFeature, type ParamMeta } from "@/components/CellEditor";
import { Header } from "@/components/Header";
import { Inspector, type FederatedNode } from "@/components/Inspector";
import { NotebookList } from "@/components/NotebookList";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  fetchPackage,
  getWorkspace,
  newNotebook,
  openNotebook,
  select as publishSelection,
  type NotebookRow,
} from "@/lib/api";
import { EnvelopeSocket, type Envelope } from "@/lib/envelope";
import { Viewport, type PickResult, type SelectionMode } from "@/scene/Viewport";
import { openCadPackage } from "@/scene/product-package";
import { buildFederatedFeatureModel } from "@/scene/scene2";
import type { SceneView } from "@/scene/scene-view";

type FederatedModel = ReturnType<typeof buildFederatedFeatureModel>["model"];

/** Editor application: left = workspace + notebook editing, right = live
 * model preview driven by the in-memory scadpkg stream (architecture rule 4).
 */
export function App() {
  const viewRef = useRef<SceneView | null>(null);
  const socketRef = useRef<EnvelopeSocket | null>(null);

  const [notebooks, setNotebooks] = useState<NotebookRow[]>([]);
  const [notebook, setNotebook] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [kernelAlive, setKernelAlive] = useState(false);
  const [marimoUrl, setMarimoUrl] = useState<string | null>(null);
  const [status, setStatus] = useState("Connecting…");

  const [params, setParams] = useState<ParamMeta[]>([]);
  const [cells, setCells] = useState<NotebookCell[]>([]);
  const [features, setFeatures] = useState<NotebookFeature[]>([]);
  const [federated, setFederated] = useState<FederatedNode[]>([]);
  const [pick, setPick] = useState<PickResult | null>(null);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("solid");
  const [packageInfo, setPackageInfo] = useState<{
    name: string | null;
    revision: number;
    occurrences: number;
    assets: number;
    exported: string | null;
  } | null>(null);

  // -- package → viewport (the UI update path) --------------------------------

  // Camera framing is disruptive during slider drags; frame once per notebook.
  const framedNotebook = useRef<string | null>(null);

  const loadPackageBytes = useCallback(async (bytes: Uint8Array, revision: number, name: string | null) => {
    const view = viewRef.current;
    if (!view) return;
    try {
      const opened = await openCadPackage(bytes);
      await view.loadScene(opened.files);
      const manifest = view.engine.manifest;
      if (!manifest) throw new Error("scene manifest missing");
      const federatedModel = buildFederatedFeatureModel(manifest, opened.files);
      setFederated(
        federatedModel.model.graph.nodes.map((node) => ({
          id: node.node_id,
          label: node.display?.label ?? node.op,
          kind: node.op,
        })),
      );
      setPackageInfo({
        name,
        revision,
        occurrences: manifest.nodes.length,
        assets: manifest.geometry_assets.length,
        exported: null,
      });
      setStatus(
        `${manifest.nodes.length} occurrences · ${manifest.geometry_assets.length} geometry assets · ${federatedModel.model.graph.nodes.length} features`,
      );
      if (framedNotebook.current !== name) {
        view.frame();
        framedNotebook.current = name;
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to open package");
    }
  }, []);

  // -- socket + lifecycle ------------------------------------------------------

  useEffect(() => {
    const socket = new EnvelopeSocket(`ws://${window.location.host}/ws`);
    socketRef.current = socket;

    socket.on("hello", (envelope) => {
      setNotebook((envelope["notebook"] as string) ?? null);
      setKernelAlive(Boolean(envelope["kernel"]));
      setMarimoUrl((envelope["marimo_url"] as string) ?? null);
      void getWorkspace().then((data) => {
        setNotebooks(data.notebooks);
        const current = data.notebooks.find((row) => row.current);
        if (current) setKind(current.kind);
      });
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

    socket.on("notebook.cells", (envelope) => setCells((envelope["cells"] as NotebookCell[]) ?? []));
    socket.on("notebook.features", (envelope) => setFeatures((envelope["features"] as NotebookFeature[]) ?? []));

    socket.on("package", (envelope) => {
      const revision = Number(envelope["revision"] ?? 0);
      void fetchPackage().then((bytes) =>
        loadPackageBytes(bytes, revision, (envelope["name"] as string) ?? null),
      );
    });

    socket.on("status", (envelope) => {
      // An empty error means "the model is fine again": keep the package line.
      if (typeof envelope["error"] === "string") {
        if (envelope["error"]) setStatus(`error: ${envelope["error"]}`);
      }
      else if (typeof envelope["exported"] === "string") {
        setStatus(`exported ${envelope["exported"]}`);
        setPackageInfo((previous) => (previous ? { ...previous, exported: envelope["exported"] as string } : previous));
      } else if (typeof envelope["created"] === "string") setStatus(`created ${envelope["created"]}`);
    });

    socket.connect();
    return () => socket.close();
  }, [loadPackageBytes]);

  // -- actions ------------------------------------------------------------------

  const handlePick = useCallback((result: PickResult) => {
    setPick(result);
    // Publish for agents (GET /api/studio/selected), including a compact
    // entity payload so the agent sees what the human sees.
    void publishSelection({
      notebook: notebook,
      node_id: result.nodeId,
      entity_id: result.entityId,
      mode: result.mode,
      entity: result.entity
        ? { kind: result.entity.kind, id: result.entity.entity_id, data: result.entity.properties ?? null }
        : null,
    }).catch(() => undefined);
  }, [notebook]);

  const refreshWorkspace = useCallback(() => {
    void getWorkspace().then((data) => {
      setNotebooks(data.notebooks);
      const current = data.notebooks.find((row) => row.current);
      setKind(current?.kind ?? null);
    });
  }, []);

  const handleOpen = (path: string) => {
    setStatus(`opening ${path}…`);
    openNotebook(path)
      .then(refreshWorkspace)
      .catch((error) => setStatus(`open failed: ${error.message}`));
  };

  const handleNew = (name: string, newKind: "part" | "assembly") => {
    newNotebook(name, newKind)
      .then(refreshWorkspace)
      .catch((error) => setStatus(`create failed: ${error.message}`));
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header
        notebook={notebook}
        kind={kind}
        kernelAlive={kernelAlive}
        status={status}
        marimoUrl={marimoUrl}
        onExport={() => socketRef.current?.send({ type: "export.request" })}
        onRerun={() => socketRef.current?.send({ type: "rerun.request" })}
        onNewNotebook={handleNew}
      />
      <ResizablePanelGroup className="min-h-0 flex-1">
        <ResizablePanel defaultSize={30} minSize={18} className="min-w-0">
          <Tabs defaultValue="notebook" className="h-full">
            <TabsList className="mx-2 mt-2">
              <TabsTrigger value="notebook">notebook</TabsTrigger>
              <TabsTrigger value="workspace">workspace</TabsTrigger>
            </TabsList>
            <TabsContent value="notebook" className="h-[calc(100%-3rem)]">
              <CellEditor cells={cells} features={features} params={params} socket={socketRef.current} />
            </TabsContent>
            <TabsContent value="workspace" className="h-[calc(100%-3rem)]">
              <NotebookList notebooks={notebooks} onOpen={handleOpen} />
            </TabsContent>
          </Tabs>
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={48} minSize={30} className="min-w-0">
          <div className="flex h-full flex-col">
            <div className="flex items-center gap-1.5 border-b px-2 py-1">
              {(["solid", "face", "edge"] as SelectionMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase ${
                    selectionMode === mode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"
                  }`}
                  onClick={() => setSelectionMode(mode)}
                >
                  {mode}
                </button>
              ))}
              <span className="flex-1" />
              <button
                type="button"
                className="rounded px-2 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground hover:bg-accent"
                onClick={() => viewRef.current?.frame()}
              >
                fit
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <Viewport viewRef={viewRef} selectionMode={selectionMode} onPick={handlePick} />
            </div>
          </div>
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={22} minSize={14} className="min-w-0">
          <Inspector pick={pick} features={federated} packageInfo={packageInfo} />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

export type { Envelope };
