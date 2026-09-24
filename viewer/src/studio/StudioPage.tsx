import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Boxes, Eye, EyeOff, FileCode2, Maximize2, PackageOpen, ScanFace, Square, Spline, Workflow } from 'lucide-react';
import { SourceDock } from '../shared/components/source-dock';
import { bindResizablePanels } from '../shared/components/panel-resizer';
import { entityMeasure, formatNumber, qlSelectorForEntity } from '../shared/entity-facts';
import { openCadPackage, type PackageFiles } from '../shared/product-package';
import { buildFederatedFeatureModel, type Entity, type EntitySidecar, type ModelDocument, type ModelNode, type SceneManifest, type SceneNode } from '../shared/scene2';
import { SceneView, type SelectionMode } from '../shared/scene-view';
import { FeatureTreeView } from '../remode/feature-tree';

type NavigatorTab = 'components' | 'features';
type StudioSelection =
  | { kind: 'scene' }
  | { kind: 'component'; node: SceneNode; entity: Entity | null; sidecar: EntitySidecar | null }
  | { kind: 'feature'; feature: ModelNode };

type TreeNodeProps = {
  node: SceneNode;
  childrenByParent: Map<string | null, SceneNode[]>;
  visibility: Map<string, boolean>;
  selectedNodeId: string | null;
  onSelect: (nodeId: string) => void;
  onToggleVisibility: (nodeId: string) => void;
  depth?: number;
};

const selectionModes: Array<{ mode: SelectionMode; label: string; title: string }> = [
  { mode: 'component', label: 'COMPONENT', title: 'Select components' },
  { mode: 'solid', label: 'SOLID', title: 'Select solids' },
  { mode: 'face', label: 'FACE', title: 'Select faces' },
  { mode: 'edge', label: 'EDGE', title: 'Select edges' },
  { mode: 'vertex', label: 'VERTEX', title: 'Select vertices' },
];

function featureLabel(feature: ModelNode): string {
  return feature.display.label || feature.op.replace(/^make_/, '').replaceAll('_', ' ');
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? 'null';
}

function TreeNode({ node, childrenByParent, visibility, selectedNodeId, onSelect, onToggleVisibility, depth = 0 }: TreeNodeProps) {
  const children = childrenByParent.get(node.node_id) ?? [];
  const visible = visibility.get(node.node_id) ?? true;
  const assembly = node.definition_kind === 'assembly';
  return (
    <>
      <button type="button" className={`group flex w-full items-center gap-2 border-0 border-l-2 px-3 py-2 text-left text-[12px] text-[#94a1b2] transition-colors hover:bg-[#171d24] hover:text-[#edf3f9] ${selectedNodeId === node.node_id ? 'border-l-lime bg-[#1a2324] text-[#f2f8fb]' : 'border-l-transparent'} ${visible ? '' : 'text-[#4d5a68]'}`} style={{ paddingLeft: `calc(12px + ${depth} * 16px)` }} onClick={() => onSelect(node.node_id)}>
        <span className="grid size-2.5 shrink-0 place-items-center text-[#697889]">{children.length ? '▾' : '·'}</span>
        <span className="grid size-3.5 shrink-0 place-items-center text-lime">{assembly ? <Boxes className="size-3.5" /> : <Box className="size-3.5" />}</span>
        <span className="min-w-0 flex-1 truncate" title={node.node_id}>{node.display_name || node.node_id}</span>
        <span className={`grid size-[18px] shrink-0 place-items-center text-[#43505e] group-hover:text-lime ${visible ? '' : 'text-lime opacity-60'}`} role="button" title={visible ? 'Hide occurrence' : 'Show occurrence'} aria-label={visible ? 'Hide occurrence' : 'Show occurrence'} onClick={(event) => { event.stopPropagation(); onToggleVisibility(node.node_id); }}>
          {visible ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
        </span>
      </button>
      {children.map((child) => <TreeNode key={child.node_id} node={child} {...{ childrenByParent, visibility, selectedNodeId, onSelect, onToggleVisibility }} depth={depth + 1} />)}
    </>
  );
}

function EmptyDetails({ message = 'Select an occurrence' }: { message?: string }) {
  return <div className="flex flex-col gap-2 px-1 py-[34px] text-[13px] leading-[1.55] text-dim"><Box className="size-7 text-[#536475]" /><strong className="text-[15px] text-[#bbc7d4]">{message}</strong><span>Choose a node or entity in the viewport to inspect evaluated data.</span></div>;
}

function DetailRows({ rows }: { rows: Array<[string, string]> }) {
  return <dl className="mt-[13px] grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-x-3 gap-y-2.5 font-mono text-[11px] leading-[1.45]">{rows.map(([label, value]) => <div key={label} className="contents"><dt className="text-[#657386]">{label}</dt><dd className="m-0 min-w-0 break-words text-right text-[#c5d0dc]" title={value}>{value}</dd></div>)}</dl>;
}

function SelectionDetails({ selection, onCopy }: { selection: StudioSelection; onCopy: (value: string) => void }) {
  if (selection.kind === 'scene') return <EmptyDetails message="Choose a product package" />;
  const feature = selection.kind === 'feature' ? selection.feature : null;
  const node = selection.kind === 'component' ? selection.node : null;
  const entity = selection.kind === 'component' ? selection.entity : null;
  const sidecar = selection.kind === 'component' ? selection.sidecar : null;
  const measure = entity ? entityMeasure(entity) : null;
  const selector = entity && sidecar ? qlSelectorForEntity(entity, sidecar) : null;
  const measureLabel = entity?.kind === 'face' ? 'Area' : entity?.kind === 'edge' ? 'Length' : entity?.kind === 'vertex' ? 'Position' : 'Volume';
  const measureValue = entity?.kind === 'vertex' ? String(entity.properties.position ?? 'n/a') : formatNumber(measure?.[1]);
  const icon = feature ? <Workflow className="size-6 shrink-0 text-lime" /> : entity?.kind === 'face' ? <ScanFace className="size-6 shrink-0 text-lime" /> : entity?.kind === 'edge' ? <Spline className="size-6 shrink-0 text-lime" /> : <Box className="size-6 shrink-0 text-lime" />;
  const preClass = 'mt-3 max-h-[260px] overflow-auto whitespace-pre-wrap break-words border border-line bg-void p-2.5 font-mono text-[9px] leading-[1.5] text-[#a9c77b]';
  return <>
    <div className="flex min-w-0 gap-[11px] border-b border-line pb-[19px]">{icon}<div className="min-w-0"><strong className="my-px mb-1.5 block break-words text-[16px] leading-[1.35] text-[#edf3f9]">{feature ? featureLabel(feature) : entity ? `${node!.display_name} / ${entity.entity_id}` : node!.display_name}</strong><span className="block break-words font-mono text-[11px] leading-[1.5] text-dim">{feature?.node_id ?? node!.definition_id}</span></div></div>
    <div className="py-[19px_4px]"><span className="block font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">{feature ? 'OPERATION' : 'OCCURRENCE'}</span><DetailRows rows={feature ? [['Function', feature.op], ['Category', feature.display.category || 'operation'], ['Inputs', feature.inputs.length ? feature.inputs.join(', ') : 'none'], ['Output count', String(feature.output_count)]] : [['Node', node!.node_id], ['Definition kind', node!.definition_kind], ['Visibility', 'Visible']]} /></div>
    {feature && <div className="py-[19px_4px]"><span className="block font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">PARAMETERS</span><pre className={preClass}>{jsonText(feature.params)}</pre></div>}
    {feature?.source?.path && <div className="py-[19px_4px]"><span className="block font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">SOURCE</span><p className="font-mono text-[12px] leading-[1.6] text-[#aebdcd]">{feature.source.path}:{feature.source.line}-{feature.source.end_line}</p></div>}
    {entity && <div className="py-[19px_4px]"><span className="block font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">EVALUATED ENTITY</span><DetailRows rows={[['Entity', entity.entity_id], ['Topology', entity.kind], ['Geometry', String(entity.geometry.type ?? 'unknown')], [measureLabel, `${measureValue} ${entity.kind === 'face' ? 'mm²' : entity.kind === 'edge' ? 'mm' : entity.kind === 'vertex' ? 'mm' : 'mm³'}`], ['Parents', String(entity.parent_entity_ids.length)], ['Children', String(entity.child_entity_ids.length)]]} /></div>}
    {entity && selector && <div className="py-[19px_4px]"><div className="flex items-center justify-between gap-2.5"><span className="font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">UNIQUE QL SELECTOR</span>{selector.unique && <button type="button" className="inline-flex items-center gap-1.5 rounded-[3px] border border-[#39484d] bg-[#18221c] px-2 py-1 font-mono text-[9px] tracking-[0.08em] text-lime hover:border-lime" onClick={() => onCopy(selector.expression)}><FileCode2 className="size-3" />COPY</button>}</div><pre className="mt-3 max-h-[240px] overflow-auto whitespace-pre-wrap break-words border border-[#39484d] bg-[#101a16] p-2.5 font-mono text-[10px] leading-[1.55] text-lime">{selector.unique ? selector.expression : 'The exported facts do not uniquely identify this entity.'}</pre></div>}
    {node && <div className="py-[19px_4px]"><span className="block font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">OCCURRENCE METADATA</span><pre className={preClass}>{jsonText(node.properties)}</pre></div>}
  </>;
}

export function StudioPage() {
  const workspaceRef = useRef<HTMLElement>(null);
  const navigatorPanelRef = useRef<HTMLElement>(null);
  const inspectorPanelRef = useRef<HTMLElement>(null);
  const navigatorResizerRef = useRef<HTMLDivElement>(null);
  const inspectorResizerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const sourceDockRef = useRef<SourceDock | null>(null);
  const sceneViewRef = useRef<SceneView | null>(null);
  const featureTreeRef = useRef<FeatureTreeView | null>(null);
  const sourceHostRef = useRef<HTMLDivElement>(null);
  const sourceListRef = useRef<HTMLDivElement>(null);
  const sourceDockElementRef = useRef<HTMLElement>(null);
  const sourceResizerRef = useRef<HTMLDivElement>(null);
  const sourceFilesResizerRef = useRef<HTMLDivElement>(null);
  const sourceCountRef = useRef<HTMLSpanElement>(null);
  const sourcePathRef = useRef<HTMLSpanElement>(null);
  const sourceEmptyRef = useRef<HTMLDivElement>(null);
  const sourceToggleRef = useRef<HTMLButtonElement>(null);
  const sourceCloseRef = useRef<HTMLButtonElement>(null);
  const [manifest, setManifest] = useState<SceneManifest | null>(null);
  const [model, setModel] = useState<ModelDocument | null>(null);
  const [visibility, setVisibility] = useState<Map<string, boolean>>(new Map());
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('component');
  const [selection, setSelection] = useState<StudioSelection>({ kind: 'scene' });
  const [tab, setTab] = useState<NavigatorTab>('components');
  const [status, setStatus] = useState('Waiting for package');
  const [loading, setLoading] = useState(false);
  const [packageSchema, setPackageSchema] = useState<string | null>(null);

  useEffect(() => {
    if (!viewportRef.current || !sourceHostRef.current || !sourceListRef.current || !sourceDockElementRef.current || !sourceResizerRef.current || !sourceFilesResizerRef.current || !sourceCountRef.current || !sourcePathRef.current || !sourceEmptyRef.current || !sourceToggleRef.current || !sourceCloseRef.current) return;
    const view = new SceneView(viewportRef.current, { selectionMode, onPick: (result) => {
      const currentManifest = manifestRef.current;
      if (!currentManifest) return;
      const node = currentManifest.nodes.find((item) => item.node_id === result.nodeId);
      if (!node) return;
      view.clearMarks();
      if (result.entityId) view.addMark(result.nodeId, result.entityId, '#fff04d');
      setSelection({ kind: 'component', node, entity: result.entity, sidecar: view.sidecarFor(node) });
      setStatus(`${result.mode}: ${result.entity?.entity_id ?? node.display_name}`);
    }});
    sceneViewRef.current = view;
    const sourceDock = new SourceDock({ dock: sourceDockElementRef.current, resizer: sourceResizerRef.current, fileListResizer: sourceFilesResizerRef.current, fileList: sourceListRef.current, fileCount: sourceCountRef.current, activePath: sourcePathRef.current, editorHost: sourceHostRef.current, emptyState: sourceEmptyRef.current, toggleButton: sourceToggleRef.current, closeButton: sourceCloseRef.current, workspace: workspaceRef.current! });
    sourceDockRef.current = sourceDock;
    const featureTree = new FeatureTreeView(document.querySelector<HTMLDivElement>('#studio-feature-tree')!, { onSelectFeature: (feature) => { setSelection({ kind: 'feature', feature }); setTab('features'); if (feature.source) sourceDock.reveal(feature.source); } });
    featureTreeRef.current = featureTree;
    const unbindPanels = workspaceRef.current && navigatorPanelRef.current && inspectorPanelRef.current && navigatorResizerRef.current && inspectorResizerRef.current
      ? bindResizablePanels({ workspace: workspaceRef.current, navigatorPanel: navigatorPanelRef.current, inspectorPanel: inspectorPanelRef.current, navigatorResizer: navigatorResizerRef.current, inspectorResizer: inspectorResizerRef.current })
      : undefined;
    return () => { unbindPanels?.(); featureTreeRef.current = null; sourceDockRef.current = null; sceneViewRef.current = null; sourceDock.dispose(); view.dispose(); };
    // The renderer must mount once. Selection mode is applied by the separate effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const manifestRef = useRef<SceneManifest | null>(null);
  manifestRef.current = manifest;

  useEffect(() => { sceneViewRef.current?.setSelectionMode(selectionMode); }, [selectionMode]);

  const loadPackage = useCallback(async (files: PackageFiles, schema: string) => {
    const view = sceneViewRef.current;
    if (!view) return;
    setLoading(true);
    setStatus('Opening product package');
    try {
      await view.loadScene(files);
      const nextManifest = view.engine.manifest;
      if (!nextManifest) throw new Error('scene manifest is missing');
      const federated = buildFederatedFeatureModel(nextManifest, files);
      manifestRef.current = nextManifest;
      setManifest(nextManifest);
      setModel(federated.model);
      setVisibility(new Map(nextManifest.nodes.map((node) => [node.node_id, true])));
      setSelection({ kind: 'scene' });
      setPackageSchema(schema);
      sourceDockRef.current?.setFiles(federated.sources);
      featureTreeRef.current?.setModel(federated.model);
      setStatus(`${nextManifest.nodes.length} occurrences · ${nextManifest.geometry_assets.length} geometry assets · ${federated.model.graph.nodes.length} features`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to open package');
      setManifest(null);
      setModel(null);
      sourceDockRef.current?.clear();
      featureTreeRef.current?.setModel(null);
    } finally { setLoading(false); }
  }, []);

  const openFile = useCallback(async (file: File | undefined) => {
    if (!file) return;
    try { const opened = await openCadPackage(new Uint8Array(await file.arrayBuffer())); await loadPackage(opened.files, opened.schemaVersion); }
    catch (error) { setStatus(error instanceof Error ? error.message : 'Unable to open package'); }
  }, [loadPackage]);

  const selectNode = useCallback((nodeId: string) => {
    const node = manifestRef.current?.nodes.find((item) => item.node_id === nodeId);
    if (!node || !sceneViewRef.current) return;
    sceneViewRef.current.clearMarks();
    setSelection({ kind: 'component', node, entity: null, sidecar: sceneViewRef.current.sidecarFor(node) });
    setStatus(node.display_name || node.node_id);
  }, []);

  const toggleVisibility = useCallback((nodeId: string) => {
    const next = !(visibility.get(nodeId) ?? true);
    sceneViewRef.current?.engine.setNodeVisible(nodeId, next);
    setVisibility((current) => new Map(current).set(nodeId, next));
    if (!next && selection.kind === 'component' && selection.node.node_id === nodeId) setSelection({ kind: 'scene' });
  }, [selection, visibility]);

  const copySelector = useCallback(async (value: string) => { try { await navigator.clipboard.writeText(value); setStatus('Selector copied'); } catch { setStatus('Clipboard access was denied'); } }, []);
  const childrenByParent = new Map<string | null, SceneNode[]>();
  for (const node of manifest?.nodes ?? []) childrenByParent.set(node.parent_node_id, [...(childrenByParent.get(node.parent_node_id) ?? []), node]);

  return (
    <main className="grid h-full min-h-0 grid-rows-[64px_minmax(0,1fr)_32px] max-[900px]:h-auto max-[900px]:min-h-screen max-[900px]:grid-rows-[64px_auto_32px]">
      <header className="flex items-center justify-between border-b border-line bg-panel px-6 max-[900px]:px-3.5"><div className="flex items-center gap-2.5"><span className="grid size-[30px] -rotate-7 place-items-center border border-lime font-mono text-[11px] font-medium text-lime">SC</span><div><strong className="block text-[14px] leading-[15px]">SimpleCAD</strong><span className="block font-mono text-[10px] tracking-[0.08em] text-dim uppercase">evaluated scene viewer</span></div></div><div className="flex items-center gap-[18px]"><button type="button" className="inline-flex items-center gap-1.5 rounded-[3px] border border-[#303b48] bg-[#151b22] px-2.5 py-2 font-mono text-[10px] font-medium tracking-[0.04em] text-[#aebdcd] transition-colors hover:border-lime hover:text-lime" onClick={() => document.getElementById('studio-file-input')?.click()}><PackageOpen className="size-[13px]" /><span>Open .scadpkg</span></button><input id="studio-file-input" type="file" accept=".scadpkg,application/vnd.simplecad.product+zip" hidden onChange={(event) => void openFile(event.target.files?.[0])} /></div></header>
      <section ref={workspaceRef} data-source-open="false" className="grid min-w-0 min-h-0 grid-cols-[var(--navigator-width)_7px_minmax(0,1fr)_7px_var(--inspector-width)] grid-rows-[minmax(0,1fr)_0_0] data-[source-open=true]:grid-rows-[minmax(0,1fr)_7px_var(--source-dock-height)] overflow-hidden max-[900px]:grid-cols-[210px_minmax(0,1fr)] max-[900px]:grid-rows-[minmax(620px,78vh)_auto_auto] max-[560px]:grid-cols-1 max-[560px]:grid-rows-[auto_minmax(420px,62vh)_auto_auto]" onDragOver={(event) => { event.preventDefault(); viewportRef.current?.setAttribute('data-drop-target', 'true'); }} onDragLeave={() => viewportRef.current?.removeAttribute('data-drop-target')} onDrop={(event) => { event.preventDefault(); viewportRef.current?.removeAttribute('data-drop-target'); void openFile(event.dataTransfer?.files[0]); }}>
        <aside ref={navigatorPanelRef} className="row-span-3 flex min-w-0 min-h-0 flex-col overflow-hidden bg-panel max-[900px]:row-span-1 max-[560px]:row-span-1"><div className="flex min-h-20 shrink-0 items-start justify-between border-b border-line px-[17px] pb-[15px] pt-[21px]"><div><span className="block font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">MODEL NAVIGATOR</span><h1 className="mt-1.5 text-[17px] font-semibold capitalize tracking-[-0.04em] text-[#eef4fb]">{manifest?.scene_id.replaceAll('-', ' ') ?? 'Loading scene'}</h1></div><span className="min-w-[27px] rounded-[3px] border border-[#2b3540] px-1.5 py-1 text-center font-mono text-[10px] text-[#8190a3]">{manifest?.nodes.length ?? 0}</span></div><div className="grid grid-cols-2 border-b border-line bg-inset"><button type="button" className={`flex items-center justify-center gap-1.5 border-0 border-b-2 px-2 py-2.5 font-mono text-[10px] uppercase transition-colors hover:bg-panel hover:text-ink ${tab === 'components' ? 'border-lime bg-[#151d1b] text-lime' : 'border-transparent text-dim'}`} onClick={() => setTab('components')}><Boxes className="size-[13px]" />Components</button><button type="button" className={`flex items-center justify-center gap-1.5 border-0 border-b-2 px-2 py-2.5 font-mono text-[10px] uppercase transition-colors hover:bg-panel hover:text-ink ${tab === 'features' ? 'border-lime bg-[#151d1b] text-lime' : 'border-transparent text-dim'}`} onClick={() => setTab('features')}><Workflow className="size-[13px]" />Features</button></div><div className="min-h-0 flex-1 overflow-auto py-3" hidden={tab !== 'components'}>{(childrenByParent.get(null) ?? []).map((n) => <TreeNode key={n.node_id} node={n} {...{ childrenByParent, visibility, selectedNodeId: selection.kind === 'component' ? selection.node.node_id : null, onSelect: selectNode, onToggleVisibility: toggleVisibility }} />)}{!manifest && <div className="px-4 py-6 font-mono text-[10px] leading-[1.6] text-[#718094]">Open a model package to inspect its occurrences.</div>}</div><div id="studio-feature-tree" className="min-h-0 flex-1 overflow-auto py-2" hidden={tab !== 'features'} /></aside>
        <div ref={navigatorResizerRef} className="relative z-[4] min-w-0 cursor-col-resize touch-none bg-panel before:absolute before:inset-y-0 before:left-[3px] before:w-px before:bg-line before:transition-colors hover:before:bg-lime focus-visible:before:bg-lime max-[900px]:hidden" role="separator" aria-label="Resize model navigator" tabIndex={0} />
        <section className="relative min-w-0 min-h-0 overflow-hidden bg-[radial-gradient(circle_at_52%_44%,#18222a_0,#0d1218_47%,#0b0e12_100%)] max-[900px]:min-h-[620px] max-[560px]:min-h-[420px]"><div ref={viewportRef} data-drop-target="false" className="absolute inset-0 overflow-hidden data-[drop-target=true]:outline data-[drop-target=true]:outline-2 data-[drop-target=true]:outline-lime data-[drop-target=true]:-outline-offset-2"><div className={`absolute inset-0 z-[3] flex flex-col items-center justify-center gap-[13px] bg-[rgb(11_14_18_/_0.75)] font-mono text-[11px] text-[#94a5b7] transition-opacity ${loading ? '' : 'pointer-events-none opacity-0'}`}><span className="size-[18px] animate-[spin_.7s_linear_infinite] rounded-full border border-[#364352] border-t-lime" /><span>Loading evaluated package</span></div><div className="absolute bottom-4 left-[17px] z-[2] flex items-center gap-1.5 rounded-[3px] border border-[#27323d] bg-[rgb(14_19_24_/_0.8)] px-2 py-1.5 font-mono text-[10px] text-[#8898aa] backdrop-blur"><span className={`size-1.5 rounded-full ${manifest ? 'bg-lime shadow-[0_0_10px_#b3e36b]' : 'bg-[#697583]'}`} />{status}</div><div className="absolute right-[15px] top-[15px] z-[2] flex items-stretch gap-1.5"><div className="flex items-center rounded-[3px] border border-[#303b48] bg-[rgb(21_27_34_/_0.92)] pl-2"><span className="mr-1 font-mono text-[8px] tracking-[0.08em] text-[#657386]">SELECT</span>{selectionModes.map(({ mode, label, title }) => <button key={mode} type="button" className={`inline-flex items-center justify-center gap-1 border-0 border-l border-[#303b48] px-2 py-1.5 font-mono text-[9px] text-[#aebdcd] transition-colors hover:text-lime ${selectionMode === mode ? 'bg-[#18221c] text-lime' : ''}`} title={title} onClick={() => setSelectionMode(mode)}>{mode === 'component' ? <Boxes className="size-3" /> : mode === 'solid' ? <Square className="size-3" /> : mode === 'face' ? <ScanFace className="size-3" /> : mode === 'edge' ? <Spline className="size-3" /> : <span>•</span>}<span>{label}</span></button>)}</div><button type="button" className="inline-flex items-center justify-center gap-1.5 rounded-[3px] border border-[#303b48] bg-[#151b22] px-2.5 py-1.5 font-mono text-[9px] text-[#aebdcd] hover:border-lime hover:text-lime" onClick={() => sceneViewRef.current?.frame()} title="Fit model"><Maximize2 className="size-3" />FIT</button></div></div></section>
        <div ref={inspectorResizerRef} className="relative z-[4] min-w-0 cursor-col-resize touch-none bg-panel before:absolute before:inset-y-0 before:left-[3px] before:w-px before:bg-line before:transition-colors hover:before:bg-lime focus-visible:before:bg-lime max-[900px]:hidden" role="separator" aria-label="Resize inspector" tabIndex={0} />
        <aside ref={inspectorPanelRef} className="row-span-3 flex min-w-0 min-h-0 flex-col overflow-hidden bg-panel max-[900px]:col-span-2 max-[900px]:row-span-1 max-[900px]:border-t max-[900px]:border-line max-[560px]:col-span-1"><div className="flex min-h-20 shrink-0 items-start justify-between border-b border-line px-[17px] pb-[15px] pt-[21px]"><span className="font-mono text-[9px] font-medium tracking-[0.15em] text-[#718096]">INSPECTOR</span><span className="rounded-[3px] border border-[#39484d] bg-[#18221c] px-1.5 py-1 font-mono text-[9px] text-lime">{selection.kind.toUpperCase()}</span></div><div className="min-h-0 flex-1 overflow-auto overscroll-contain px-[17px] py-5 text-[13px]"><SelectionDetails selection={selection} onCopy={(value) => void copySelector(value)} /></div></aside>
        <div ref={sourceResizerRef} className="relative z-[5] col-start-3 row-start-2 cursor-row-resize touch-none bg-panel before:absolute before:inset-x-0 before:top-[3px] before:h-px before:bg-[#29333e] hover:before:bg-lime max-[900px]:hidden" role="separator" aria-label="Resize source code panel" hidden />
        <section ref={sourceDockElementRef} className="col-start-3 row-start-3 grid min-w-0 min-h-0 grid-cols-[var(--source-files-width)_7px_minmax(0,1fr)] overflow-hidden border-t border-line bg-[#090c10] max-[900px]:col-span-2 max-[900px]:row-start-3 max-[900px]:h-[420px] max-[560px]:col-span-1 max-[560px]:grid-cols-1 max-[560px]:grid-rows-[120px_minmax(0,1fr)] max-[560px]:h-[520px]" aria-label="Embedded source code" hidden><aside className="flex min-w-0 min-h-0 flex-col overflow-hidden bg-inset"><div className="flex h-[34px] shrink-0 items-center justify-between border-b border-line bg-panel px-3"><span className="font-mono text-[9px] tracking-[0.15em] text-[#718096]">SOURCE FILES</span><span ref={sourceCountRef} className="min-w-[22px] rounded-[3px] border border-[#2b3540] px-1.5 py-1 text-center font-mono text-[10px] text-[#8190a3]">0</span></div><div ref={sourceListRef} className="min-h-0 flex-1 overflow-auto py-1.5" role="listbox" aria-label="Embedded source files" /></aside><div ref={sourceFilesResizerRef} className="relative z-[2] cursor-col-resize bg-panel before:absolute before:inset-y-0 before:left-[3px] before:w-px before:bg-[#29333e] hover:before:bg-lime max-[560px]:hidden" role="separator" aria-label="Resize source file list" /><section className="relative flex min-w-0 min-h-0 flex-col overflow-hidden"><div className="flex h-[34px] shrink-0 items-center gap-3 border-b border-line bg-panel px-3 font-mono text-[9px] text-[#91b8ed]"><span ref={sourcePathRef} className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">No source file selected</span><button ref={sourceCloseRef} type="button" className="ml-auto grid size-[23px] shrink-0 place-items-center border-0 bg-transparent text-lg leading-none text-dim hover:text-lime" aria-label="Close source code panel">×</button></div><div ref={sourceHostRef} className="source-editor min-w-0 min-h-0 flex-1 overflow-hidden" /><div ref={sourceEmptyRef} className="absolute inset-x-0 bottom-0 top-[34px] grid place-items-center bg-[#090c10] font-mono text-[10px] text-[#657386]">Open a model package with embedded source files.</div></section></section>
      </section>
      <footer className="flex items-center justify-between border-t border-line bg-panel px-[17px] font-mono text-[9px] text-[#657487] max-[560px]:px-3"><span>Package {packageSchema ?? 'none'} · {manifest?.units ?? 'mm'}</span><span className="flex items-center gap-3.5"><button ref={sourceToggleRef} type="button" className="rounded-[2px] border border-[#303b48] bg-transparent px-2 py-0.5 font-mono text-[8px] tracking-[0.08em] text-[#8190a3] uppercase hover:border-lime hover:text-lime disabled:cursor-default disabled:opacity-35" aria-expanded="false" disabled>Source</button><span className="max-[560px]:hidden text-[#4d5a68]">CAD-local precision retained · GLB transport assets</span></span></footer>
    </main>
  );
}
