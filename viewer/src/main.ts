import './style.css';

import { strFromU8 } from 'fflate';
import {
  Box,
  Boxes,
  Combine,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  CopyCheck,
  Eye,
  EyeOff,
  GitBranch,
  Link,
  Layers,
  LayoutDashboard,
  Maximize2,
  PackageOpen,
  Plus,
  Rotate3d,
  ScanFace,
  Scissors,
  Spline,
  Workflow,
  createIcons,
} from 'lucide';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { bindClickSelection } from './components/click-selection';
import { bindResizablePanels } from './components/panel-resizer';
import { SourceDock } from './components/source-dock';
import { addWideEdgeVisual, cadPointToGltf, disposeObject, materialFor, placementMatrix } from './cad-three';
import { entityCenter, entityMeasure, formatNumber, qlSelectorForEntity } from './entity-facts';
import { openCadPackage, type PackageFiles } from './product-package';
import {
  buildFederatedFeatureModel,
  type Asset,
  type ConnectorSnapshot,
  type Definition,
  type Entity,
  type EntitySidecar,
  type FaceGroup,
  type Joint,
  type ModelDocument,
  type ModelNode,
  type OperationSource,
  type SceneManifest,
  type SceneNode,
  type SourceRecord,
  type Transform,
  type Vec3,
} from './scene2';

type SelectionMode = 'component' | 'solid' | 'face' | 'edge' | 'vertex';

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) throw new Error('viewer root is missing');

const lucideIcons = {
  Box,
  Boxes,
  Combine,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  CopyCheck,
  Eye,
  EyeOff,
  GitBranch,
  Link,
  Layers,
  LayoutDashboard,
  Maximize2,
  PackageOpen,
  Plus,
  Rotate3d,
  ScanFace,
  Scissors,
  Spline,
  Workflow,
};

function iconMarkup(name: keyof typeof lucideIcons, className = 'ui-icon'): string {
  const iconName = name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
  return `<i data-lucide="${iconName}" class="${className}" aria-hidden="true"></i>`;
}

function renderIcons(root: Element): void {
  createIcons({
    icons: lucideIcons,
    attrs: { 'stroke-width': 1.8 },
    root,
  });
}

app.innerHTML = `
  <main class="shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">SC</span><div><strong>SimpleCAD</strong><span>evaluated scene viewer</span></div></div>
       <div class="top-actions"><button id="open-button" class="quiet-button">${iconMarkup('PackageOpen')}<span>Open .scadpkg</span></button><input id="file-input" type="file" accept=".scadpkg,application/vnd.simplecad.product+zip" hidden /></div>
    </header>
    <section class="workspace">
       <aside id="navigator-panel" class="panel tree-panel"><div class="panel-heading"><div><span class="eyebrow">MODEL NAVIGATOR</span><h1 id="scene-title">Loading scene</h1></div></div><div class="navigator-tabs" role="tablist" aria-label="Model navigator views"><button id="components-tab" class="navigator-tab active" role="tab" aria-selected="true" aria-controls="components-view"><span>${iconMarkup('Boxes', 'tab-icon')}</span><span>Components</span><span id="node-count" class="count">0</span></button><button id="features-tab" class="navigator-tab" role="tab" aria-selected="false" aria-controls="features-view"><span>${iconMarkup('Workflow', 'tab-icon')}</span><span>Features</span><span id="feature-count" class="count">0</span></button></div><div id="components-view" class="navigator-view active" role="tabpanel" aria-labelledby="components-tab"><div id="tree" class="tree"></div></div><div id="features-view" class="navigator-view" role="tabpanel" aria-labelledby="features-tab" hidden><div id="feature-tree" class="tree feature-tree"><div class="tree-empty">Open a model-backed scene to inspect its operations.</div></div></div></aside>
       <div id="navigator-resizer" class="panel-resizer" role="separator" aria-label="Resize model navigator" aria-orientation="vertical" tabindex="0"></div>
       <section id="viewport-column" class="viewport-wrap">
          <div class="viewport-stage"><div id="viewport" class="viewport"><div id="loading" class="loading"><span class="spinner"></span><span>Loading evaluated package</span></div><div id="hud" class="hud"><span id="status-dot" class="status-dot"></span><span id="status">Waiting for package</span></div><div class="viewport-tools"><div class="selection-tools" aria-label="Selection intent"><span class="tool-label">SELECT</span><button class="selection-mode active" data-selection-mode="component" title="Select components">${iconMarkup('Boxes')}<span>COMPONENT</span></button><button class="selection-mode" data-selection-mode="solid" title="Select solids">${iconMarkup('Box')}<span>SOLID</span></button><button class="selection-mode" data-selection-mode="face" title="Select faces">${iconMarkup('ScanFace')}<span>FACE</span></button><button class="selection-mode" data-selection-mode="edge" title="Select edges">${iconMarkup('Spline')}<span>EDGE</span></button><button class="selection-mode" data-selection-mode="vertex" title="Select vertices">${iconMarkup('CircleDot')}<span>VERTEX</span></button></div><button id="interfaces-button" title="Show connectors and joints">${iconMarkup('GitBranch')}<span>INTERFACES</span></button><button id="fit-button" title="Fit all">${iconMarkup('Maximize2')}<span>FIT</span></button></div></div></div>
       </section>
       <div id="inspector-resizer" class="panel-resizer" role="separator" aria-label="Resize Inspector" aria-orientation="vertical" tabindex="0"></div>
        <aside id="inspector-panel" class="panel details-panel"><div class="panel-heading"><span class="eyebrow">INSPECTOR</span><span id="selection-kind" class="tag">SCENE</span></div><div id="details" class="details"><div class="empty-state"><span class="empty-cross">${iconMarkup('Box', 'empty-state-icon')}</span><strong>Select an occurrence</strong><span>Choose a node or face in the viewport to inspect evaluated data.</span></div></div></aside>
       <div id="source-dock-resizer" class="source-dock-resizer" role="separator" aria-label="Resize source code panel" aria-orientation="horizontal" tabindex="0" hidden></div>
       <section id="source-dock" class="source-dock" aria-label="Embedded source code" hidden>
         <aside class="source-files-panel">
           <div class="source-dock-heading"><span class="eyebrow">SOURCE FILES</span><span id="source-file-count" class="count">0</span></div>
           <div id="source-file-list" class="source-file-list" role="listbox" aria-label="Embedded source files"></div>
         </aside>
         <div id="source-files-resizer" class="source-files-resizer" role="separator" aria-label="Resize source file list" aria-orientation="vertical" tabindex="0"></div>
         <section class="source-editor-panel">
           <div class="source-editor-heading"><span id="source-active-path">No source file selected</span><button id="source-close-button" class="source-close-button" type="button" aria-label="Close source code panel">×</button></div>
           <div id="source-editor" class="source-editor"></div>
           <div id="source-empty-state" class="source-empty-state">Open a model package with embedded source files.</div>
         </section>
       </section>
    </section>
     <footer class="footer"><span id="package-meta">No package loaded</span><span class="footer-actions"><button id="source-toggle-button" class="footer-button" type="button" aria-expanded="false" disabled>Source</button><span class="footer-note">CAD-local precision retained · GLB transport assets</span></span></footer>
  </main>`;

renderIcons(app);

const viewport = document.querySelector<HTMLDivElement>('#viewport')!;
const loading = document.querySelector<HTMLDivElement>('#loading')!;
const sceneTitle = document.querySelector<HTMLHeadingElement>('#scene-title')!;
const tree = document.querySelector<HTMLDivElement>('#tree')!;
const details = document.querySelector<HTMLDivElement>('#details')!;
const selectionKind = document.querySelector<HTMLSpanElement>('#selection-kind')!;
const nodeCount = document.querySelector<HTMLSpanElement>('#node-count')!;
const interfacesButton = document.querySelector<HTMLButtonElement>('#interfaces-button')!;
const status = document.querySelector<HTMLSpanElement>('#status')!;
const statusDot = document.querySelector<HTMLSpanElement>('#status-dot')!;
const packageMeta = document.querySelector<HTMLSpanElement>('#package-meta')!;
const workspace = document.querySelector<HTMLElement>('.workspace')!;
const navigatorPanel = document.querySelector<HTMLElement>('#navigator-panel')!;
const inspectorPanel = document.querySelector<HTMLElement>('#inspector-panel')!;
const navigatorResizer = document.querySelector<HTMLElement>('#navigator-resizer')!;
const inspectorResizer = document.querySelector<HTMLElement>('#inspector-resizer')!;
const featureTree = document.querySelector<HTMLDivElement>('#feature-tree')!;
const featureCount = document.querySelector<HTMLSpanElement>('#feature-count')!;
const componentsTab = document.querySelector<HTMLButtonElement>('#components-tab')!;
const featuresTab = document.querySelector<HTMLButtonElement>('#features-tab')!;
const componentsView = document.querySelector<HTMLDivElement>('#components-view')!;
const featuresView = document.querySelector<HTMLDivElement>('#features-view')!;
const sourceDock = new SourceDock({
  dock: document.querySelector<HTMLElement>('#source-dock')!,
  resizer: document.querySelector<HTMLElement>('#source-dock-resizer')!,
  fileListResizer: document.querySelector<HTMLElement>('#source-files-resizer')!,
  fileList: document.querySelector<HTMLElement>('#source-file-list')!,
  fileCount: document.querySelector<HTMLElement>('#source-file-count')!,
  activePath: document.querySelector<HTMLElement>('#source-active-path')!,
  editorHost: document.querySelector<HTMLElement>('#source-editor')!,
  emptyState: document.querySelector<HTMLElement>('#source-empty-state')!,
  toggleButton: document.querySelector<HTMLButtonElement>('#source-toggle-button')!,
  closeButton: document.querySelector<HTMLButtonElement>('#source-close-button')!,
  workspace,
});


bindResizablePanels({ workspace, navigatorPanel, inspectorPanel, navigatorResizer, inspectorResizer });

const threeScene = new THREE.Scene();
threeScene.background = new THREE.Color('#0b0e12');
const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1000);
camera.up.set(0, 0, 1);
camera.position.set(2.4, 2.1, 3.0);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;
viewport.append(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 0.01;
controls.maxDistance = 1000;

threeScene.add(new THREE.HemisphereLight('#d9e9ff', '#10141b', 1.7));
const keyLight = new THREE.DirectionalLight('#fff8e9', 3.1);
keyLight.position.set(4, 7, 5);
threeScene.add(keyLight);
threeScene.add(keyLight.target);
const fillLight = new THREE.DirectionalLight('#8db4ff', 1.1);
fillLight.position.set(-5, -6, 7);
threeScene.add(fillLight);
threeScene.add(fillLight.target);

const modelRoot = new THREE.Group();
modelRoot.name = 'scene-package';
threeScene.add(modelRoot);
const loader = new GLTFLoader();
const geometryCache = new Map<string, THREE.Object3D>();
const edgeCache = new Map<string, THREE.Object3D>();
const entityCache = new Map<string, EntitySidecar>();
const nodeObjects = new Map<string, THREE.Group>();
const nodeRows = new Map<string, HTMLButtonElement>();
const nodeVisibility = new Map<string, boolean>();
const manifestByDefinition = new Map<string, Definition>();
let currentManifest: SceneManifest | null = null;
let currentFiles: PackageFiles | null = null;
let currentModel: ModelDocument | null = null;
const sourceFiles = new Map<string, string>();
let selectedNodeId: string | null = null;
let selectedFeatureId: string | null = null;
let selectedOverlays: THREE.Object3D[] = [];
let interfaceRoot: THREE.Group | null = null;
let interfacesVisible = true;
const featureRows = new Map<string, HTMLButtonElement[]>();
let focusFeatureInTree: ((featureId: string) => void) | null = null;
let selectionMode: SelectionMode = 'component';

function setStatus(message: string, ready = false): void {
  status.textContent = message;
  statusDot.classList.toggle('ready', ready);
}

function bytesFor(files: PackageFiles, uri: string): Uint8Array {
  const value = files[uri];
  if (!value) throw new Error(`package member is missing: ${uri}`);
  return value;
}

async function loadGlb(files: PackageFiles, uri: string): Promise<THREE.Object3D> {
  const bytes = bytesFor(files, uri);
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const gltf = await loader.parseAsync(buffer, '');
  return gltf.scene;
}

function sidecarForNode(node: SceneNode | undefined): EntitySidecar | null {
  if (!currentManifest || !currentFiles || !node?.entity_asset_id) return null;
  const asset = currentManifest.entity_assets.find((item) => item.asset_id === node.entity_asset_id);
  if (!asset) return null;
  const cached = entityCache.get(asset.asset_id);
  if (cached) return cached;
  const parsed = JSON.parse(strFromU8(bytesFor(currentFiles, asset.uri))) as EntitySidecar;
  if (parsed.schema_version !== '2.0' || parsed.definition_id !== node.definition_id) throw new Error(`entity sidecar identity differs: ${asset.uri}`);
  entityCache.set(asset.asset_id, parsed);
  return parsed;
}

async function instantiateNode(node: SceneNode): Promise<THREE.Group> {
  if (!currentManifest || !currentFiles) throw new Error('scene package is not loaded');
  const group = new THREE.Group();
  group.name = node.display_name || node.node_id;
  const geometryAsset = node.geometry_asset_id ? currentManifest.geometry_assets.find((asset) => asset.asset_id === node.geometry_asset_id) : undefined;
  if (geometryAsset) {
    let geometry = geometryCache.get(geometryAsset.asset_id);
    if (!geometry) {
      geometry = await loadGlb(currentFiles, geometryAsset.uri);
      geometryCache.set(geometryAsset.asset_id, geometry);
    }
    const renderGeometry = geometry.clone(true);
    renderGeometry.traverse((child) => {
      if (child instanceof THREE.Mesh) child.material = materialFor(node);
    });
    group.add(renderGeometry);
  }
  const sidecar = sidecarForNode(node);
  const edgeAsset = sidecar ? currentManifest.geometry_assets.find((asset) => asset.asset_id === sidecar.edge_asset_id) : undefined;
  if (edgeAsset) {
    let edge = edgeCache.get(edgeAsset.asset_id);
    if (!edge) {
      edge = await loadGlb(currentFiles, edgeAsset.uri);
      edgeCache.set(edgeAsset.asset_id, edge);
    }
    const edgeInstance = edge.clone(true);
    edgeInstance.traverse((child) => {
      if (child instanceof THREE.LineSegments) addWideEdgeVisual(child, { width: renderer.domElement.clientWidth, height: renderer.domElement.clientHeight });
    });
    group.add(edgeInstance);
  }
  if (sidecar) {
    const vertices = sidecar.entities.filter((entity) => entity.kind === 'vertex');
    if (vertices.length) {
      const positions = new Float32Array(vertices.length * 3);
      vertices.forEach((entity, index) => {
        const position = entity.properties.position;
        if (Array.isArray(position) && position.length === 3 && position.every((item) => typeof item === 'number')) cadPointToGltf(position as Vec3).toArray(positions, index * 3);
      });
      const vertexGeometry = new THREE.BufferGeometry();
      vertexGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      const vertexPoints = new THREE.Points(vertexGeometry, new THREE.PointsMaterial({ color: '#d8ff83', size: 7, sizeAttenuation: false, depthWrite: false, transparent: true, opacity: 0.48 }));
      vertexPoints.visible = selectionMode === 'vertex';
      vertexPoints.userData.pickRole = 'vertex';
      vertexPoints.userData.vertexEntityIds = vertices.map((entity) => entity.entity_id);
      group.add(vertexPoints);
    }
  }
  return group;
}

function applySelectionModeVisibility(): void {
  for (const object of nodeObjects.values()) {
    object.traverse((child) => {
      if (child.userData.pickRole === 'vertex') child.visible = selectionMode === 'vertex';
    });
  }
}

function clearModel(): void {
  clearSelectionOverlay();
  for (const object of geometryCache.values()) disposeObject(object);
  for (const object of edgeCache.values()) disposeObject(object);
  while (modelRoot.children.length) {
    const child = modelRoot.children[0];
    disposeObject(child);
    modelRoot.remove(child);
  }
  nodeObjects.clear();
  nodeRows.clear();
  edgeCache.clear();
  entityCache.clear();
  interfaceRoot = null;
  entityCache.clear();
  nodeVisibility.clear();
  currentModel = null;
  sourceFiles.clear();
  sourceDock.clear();
  featureRows.clear();
  featureTree.innerHTML = '<div class="tree-empty">Open a model-backed scene to inspect its operations.</div>';
  featureCount.textContent = '0';
  selectedNodeId = null;
  selectedFeatureId = null;
  focusFeatureInTree = null;
}
function interfaceFrameMatrix(transform: Transform): THREE.Matrix4 {
  return placementMatrix(transform);
}

function addInterfaceAxis(parent: THREE.Object3D, direction: Vec3, color: number, interfaceId: string, nodeId: string): void {
  const geometry = new THREE.BufferGeometry();
  const length = 0.012;
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, direction[0] * length, direction[1] * length, direction[2] * length], 3));
  const line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.9 }));
  line.userData.interfaceId = interfaceId;
  line.userData.nodeId = nodeId;
  line.userData.interfaceKind = 'connector';
  line.renderOrder = 20;
  parent.add(line);
}

function renderInterfaces(manifest: SceneManifest): void {
  interfaceRoot?.removeFromParent();
  interfaceRoot = new THREE.Group();
  interfaceRoot.name = 'interfaces';
  interfaceRoot.visible = interfacesVisible;
  interfaceRoot.userData.pickable = true;
  modelRoot.add(interfaceRoot);
  const connectorGroups = new Map<string, THREE.Group>();
  for (const connector of manifest.connectors) {
    const nodeObject = nodeObjects.get(connector.node_id);
    if (!nodeObject) continue;
    const frame = new THREE.Group();
    frame.name = connector.connector_snapshot_id;
    frame.matrixAutoUpdate = false;
    frame.matrix.copy(interfaceFrameMatrix(connector.local_frame));
    frame.userData.interfaceId = connector.connector_snapshot_id;
    frame.userData.interfaceKind = 'connector';
    frame.userData.nodeId = connector.node_id;
    frame.visible = interfacesVisible;
    addInterfaceAxis(frame, [1, 0, 0], 0xe56b6f, connector.connector_snapshot_id, connector.node_id);
    addInterfaceAxis(frame, [0, 0, -1], 0x80c783, connector.connector_snapshot_id, connector.node_id);
    addInterfaceAxis(frame, [0, 1, 0], 0x78a9e6, connector.connector_snapshot_id, connector.node_id);
    nodeObject.add(frame);
    connectorGroups.set(connector.connector_snapshot_id, frame);
  }
  modelRoot.updateMatrixWorld(true);
  for (const joint of manifest.joints) {
    const first = connectorGroups.get(joint.connector_a.connector_snapshot_id);
    const second = connectorGroups.get(joint.connector_b.connector_snapshot_id);
    if (!first || !second) continue;
    const start = new THREE.Vector3().setFromMatrixPosition(first.matrixWorld);
    const end = new THREE.Vector3().setFromMatrixPosition(second.matrixWorld);
    const geometry = new THREE.BufferGeometry().setFromPoints([start, end]);
    const line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: 0xf2c14e, depthTest: false, transparent: true, opacity: 0.95 }));
    line.name = joint.joint_id;
    line.userData.interfaceId = joint.joint_id;
    line.userData.interfaceKind = 'joint';
    line.userData.pickable = true;
    line.renderOrder = 21;
    interfaceRoot.add(line);
  }
}

function linkInterfaceFeature(featureId: string | null): void {
  if (!featureId || !currentModel) return;
  selectedFeatureId = featureId;
  for (const [id, rows] of featureRows) rows.forEach((row) => row.classList.toggle('selected', id === featureId));
  setNavigatorTab('features');
  focusFeatureInTree?.(featureId);
  const feature = currentModel.graph.nodes.find((item) => item.node_id === featureId);
  if (feature?.source) sourceDock.reveal(feature.source);
}

function selectInterface(interfaceId: string): void {
  if (!currentManifest) return;
  clearSelectionOverlay();
  selectedNodeId = null;
  const connector = currentManifest.connectors.find((item) => item.connector_snapshot_id === interfaceId);
  const joint = currentManifest.joints.find((item) => item.joint_id === interfaceId);
  const sourceFeatureId = connector?.source_feature_id ?? joint?.source_feature_id ?? null;
  selectionKind.textContent = connector ? 'CONNECTOR' : 'JOINT';
  if (connector) {
    const node = currentManifest.nodes.find((item) => item.node_id === connector.node_id);
    details.innerHTML = `<div class="detail-title"><span class="detail-icon">${iconMarkup('GitBranch', 'detail-icon-svg')}</span><div><strong>${escapeHtml(connector.name)}</strong><span class="detail-definition-path">${escapeHtml(connector.connector_snapshot_id)}</span></div></div><div class="detail-section"><span class="eyebrow">CONNECTOR</span><dl><dt>Node</dt><dd>${escapeHtml(connector.node_id)}</dd><dt>Definition</dt><dd>${escapeHtml(connector.definition_id)}</dd><dt>Anchor</dt><dd>${escapeHtml(connector.anchor_kind)}</dd><dt>Connector</dt><dd>${escapeHtml(connector.connector_id)}</dd></dl></div><div class="detail-section"><span class="eyebrow">LOCAL FRAME</span><pre class="params">${escapeHtml(jsonText(connector.local_frame))}</pre></div>${connector.binding ? metadataSection('BINDING', connector.binding) : ''}${connector.forwarded_from ? metadataSection('FORWARDED FROM', connector.forwarded_from) : ''}${sourceFeatureId ? `<div class="detail-section"><span class="eyebrow">SOURCE FEATURE</span><button id="interface-source" class="copy-button">${escapeHtml(sourceFeatureId)}</button></div>` : ''}`;
    if (node) nodeRows.get(node.node_id)?.classList.add('selected');
  } else if (joint) {
    details.innerHTML = `<div class="detail-title"><span class="detail-icon">${iconMarkup('GitBranch', 'detail-icon-svg')}</span><div><strong>${escapeHtml(joint.joint_type)}</strong><span class="detail-definition-path">${escapeHtml(joint.joint_id)}</span></div></div><div class="detail-section"><span class="eyebrow">JOINT</span><dl><dt>Assembly</dt><dd>${escapeHtml(joint.assembly_definition_id)}</dd><dt>Connector A</dt><dd>${escapeHtml(joint.connector_a.connector_snapshot_id)}</dd><dt>Connector B</dt><dd>${escapeHtml(joint.connector_b.connector_snapshot_id)}</dd></dl></div><div class="detail-section"><span class="eyebrow">PARAMETERS</span><pre class="params">${escapeHtml(jsonText(joint.parameters))}</pre></div>${joint.limits ? metadataSection('LIMITS', joint.limits) : ''}${sourceFeatureId ? `<div class="detail-section"><span class="eyebrow">SOURCE FEATURE</span><button id="interface-source" class="copy-button">${escapeHtml(sourceFeatureId)}</button></div>` : ''}`;
  } else return;
  renderIcons(details);
  details.querySelector<HTMLButtonElement>('#interface-source')?.addEventListener('click', () => linkInterfaceFeature(sourceFeatureId));
  linkInterfaceFeature(sourceFeatureId);
}

function renderTree(manifest: SceneManifest): void {
  tree.replaceChildren();
  nodeRows.clear();
  const byParent = new Map<string | null, SceneNode[]>();
  for (const node of manifest.nodes) byParent.set(node.parent_node_id, [...(byParent.get(node.parent_node_id) ?? []), node]);
  const append = (parent: HTMLElement, parentId: string | null, depth: number): void => {
    for (const node of byParent.get(parentId) ?? []) {
      const row = document.createElement('button');
      row.className = 'tree-row';
      row.style.setProperty('--depth', String(depth));
      row.dataset.nodeId = node.node_id;
      const visible = nodeVisibility.get(node.node_id) ?? true;
      row.classList.toggle('hidden-node', !visible);
      const hasChildren = (byParent.get(node.node_id)?.length ?? 0) > 0;
      const isAssembly = node.definition_kind === 'assembly';
      row.innerHTML = `<span class="tree-chevron">${iconMarkup(hasChildren ? 'ChevronDown' : 'CircleDot', 'tree-chevron-icon')}</span><span class="tree-glyph">${iconMarkup(isAssembly ? 'Boxes' : 'Box', 'tree-type-icon')}</span><span class="tree-label">${escapeHtml(node.display_name || node.node_id)}</span><span class="tree-visibility" role="button" aria-label="Toggle visibility" title="Toggle visibility">${iconMarkup(visible ? 'Eye' : 'EyeOff', 'tree-visibility-icon')}</span>`;
      renderIcons(row);
      row.addEventListener('click', () => {
        if (!canSelectNode(node.node_id)) {
          setStatus('Occurrence is hidden', true);
          return;
        }
        selectNode(node.node_id);
        highlightComponent(node.node_id);
      });
      row.querySelector<HTMLElement>('.tree-visibility')!.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleNodeVisibility(node.node_id);
      });
      parent.append(row);
      nodeRows.set(node.node_id, row);
      append(parent, node.node_id, depth + 1);
    }
  };
  append(tree, null, 0);
}

function featureIconName(op: string): keyof typeof lucideIcons {
  if (/^(make_box|make_cylinder|make_sphere|make_cone|make_torus|make_(?:rounded_)?box)/.test(op)) return 'Box';
  if (/^(union|fuse|compound|assemble|combine)/.test(op)) return 'Combine';
  if (/^(cut|subtract|difference)/.test(op)) return 'Scissors';
  if (/^(add|make_|extrude|revolve|loft|sweep|fillet|chamfer|shell|offset|thicken)/.test(op)) return 'Plus';
  if (/^(transform|translate|rotate|scale|mirror)/.test(op)) return 'Rotate3d';
  if (/^(select|query|filter|where|geo_)/.test(op)) return 'GitBranch';
  if (/^(sketch|profile|wire|face)/.test(op)) return 'Layers';
  return 'LayoutDashboard';
}

function featureLabel(feature: ModelNode): string {
  return feature.display?.label || feature.op.replace(/^make_/, '').replace(/_r(.*)$/, ' $1').replaceAll('_', ' ');
}

function featureTreeLabel(feature: ModelNode): string {
  const operation = featureLabel(feature);
  const targets = feature.source?.assignment_targets.filter((target) => target.trim().length > 0) ?? [];
  return targets.length ? `${targets.join(', ')} = ${operation}` : operation;
}

function renderFeatureTree(): void {
  featureRows.clear();
  featureTree.replaceChildren();
  const model = currentModel;
  if (!model || model.graph.nodes.length === 0) {
    featureTree.innerHTML = '<div class="tree-empty">This package has no embedded operation DAG.</div>';
    focusFeatureInTree = null;
    featureCount.textContent = '0';
    return;
  }

  const byId = new Map(model.graph.nodes.map((feature) => [feature.node_id, feature]));
  const visibleFeatures = model.graph.nodes.filter((feature) => !/^apply_tag(?:_|$)/.test(feature.op));
  const visibleIds = new Set(visibleFeatures.map((feature) => feature.node_id));
  const resolvedInputCache = new Map<string, string[]>();
  const resolveVisibleInput = (featureId: string, path = new Set<string>()): string[] => {
    if (visibleIds.has(featureId)) return [featureId];
    if (path.has(featureId)) return [];
    const cached = resolvedInputCache.get(featureId);
    if (cached) return cached;
    const feature = byId.get(featureId);
    if (!feature || !/^apply_tag(?:_|$)/.test(feature.op)) return [];
    const nextPath = new Set(path).add(featureId);
    const resolved = [...new Set(feature.inputs.flatMap((input) => resolveVisibleInput(input, nextPath)))];
    resolvedInputCache.set(featureId, resolved);
    return resolved;
  };
  const inputsById = new Map<string, string[]>();
  const consumerCount = new Map<string, number>();
  for (const feature of visibleFeatures) {
    const inputs = [...new Set(feature.inputs.flatMap((input) => resolveVisibleInput(input)))];
    inputsById.set(feature.node_id, inputs);
    for (const input of inputs) consumerCount.set(input, (consumerCount.get(input) ?? 0) + 1);
  }
  const rootIds = [...new Set((model.leaf_ids ?? []).flatMap((id) => resolveVisibleInput(id)))];
  if (!rootIds.length) {
    rootIds.push(...visibleFeatures.filter((feature) => !consumerCount.has(feature.node_id)).map((feature) => feature.node_id));
  }

  const expandedPaths = new Set<string>(rootIds.map((_, index) => `root/${index}`));
  const canonicalPathById = new Map<string, string>();
  const pathToFeature = (targetId: string): string | null => {
    const visit = (featureId: string, path: string, ancestors: Set<string>): string | null => {
      if (featureId === targetId) return path;
      if (ancestors.has(featureId)) return null;
      const nextAncestors = new Set(ancestors).add(featureId);
      for (const [index, input] of (inputsById.get(featureId) ?? []).entries()) {
        const resolved = visit(input, `${path}/${index}`, nextAncestors);
        if (resolved) return resolved;
      }
      return null;
    };
    for (const [index, rootId] of rootIds.entries()) {
      const resolved = visit(rootId, `root/${index}`, new Set());
      if (resolved) return resolved;
    }
    return null;
  };
  const rowsByPath = new Map<string, HTMLButtonElement>();
  const addFeatureRow = (parent: HTMLElement, featureId: string, depth: number, path: string, ancestors: Set<string>): void => {
    const feature = byId.get(featureId);
    if (!feature) return;
    const inputs = inputsById.get(featureId) ?? [];
    const canonicalPath = canonicalPathById.get(featureId);
    const reference = canonicalPath !== undefined || ancestors.has(featureId);
    if (!reference) canonicalPathById.set(featureId, path);
    const row = document.createElement('button');
    row.className = `tree-row feature-tree-row${reference ? ' feature-reference-row' : ''}`;
    row.style.setProperty('--depth', String(depth));
    row.dataset.featureId = featureId;
    row.dataset.featurePath = path;
    row.classList.toggle('selected', featureId === selectedFeatureId);
    const expanded = !reference && inputs.length > 0 && expandedPaths.has(path);
    const shared = (consumerCount.get(featureId) ?? 0) > 1;
    const prefixIcon = reference ? 'Link' : inputs.length ? (expanded ? 'ChevronDown' : 'ChevronRight') : 'CircleDot';
    row.setAttribute('aria-expanded', inputs.length && !reference ? String(expanded) : 'false');
    row.setAttribute('aria-label', reference ? `Reference to ${featureTreeLabel(feature)}` : featureTreeLabel(feature));
    row.innerHTML = `<span class="tree-chevron">${iconMarkup(prefixIcon, 'tree-chevron-icon')}</span><span class="tree-glyph feature-glyph">${iconMarkup(featureIconName(feature.op), 'tree-type-icon')}</span><span class="tree-label" title="${escapeHtml(feature.op)}">${escapeHtml(featureTreeLabel(feature))}</span>${reference ? '<span class="feature-reference-mark">REF</span>' : ''}${shared && !reference ? `<span class="feature-shared-mark" title="Used by ${consumerCount.get(featureId)} operations">USED ${consumerCount.get(featureId)}</span>` : ''}${inputs.length && !reference ? `<span class="feature-input-count" title="${inputs.length} visible graph input${inputs.length === 1 ? '' : 's'}">${inputs.length} IN</span>` : ''}`;
    renderIcons(row);
    row.addEventListener('click', () => {
      selectFeature(featureId);
      if (reference) {
        const targetPath = canonicalPathById.get(featureId);
        const target = targetPath ? rowsByPath.get(targetPath) : undefined;
        target?.scrollIntoView({ block: 'center' });
        target?.classList.add('feature-reference-target');
        window.setTimeout(() => target?.classList.remove('feature-reference-target'), 700);
        return;
      }
      if (!inputs.length) return;
      if (expandedPaths.has(path)) expandedPaths.delete(path);
      else expandedPaths.add(path);
      rebuild();
    });
    parent.append(row);
    rowsByPath.set(path, row);
    featureRows.set(featureId, [...(featureRows.get(featureId) ?? []), row]);
    if (!expanded) return;
    const children = document.createElement('div');
    children.className = 'feature-dag-children';
    parent.append(children);
    const nextAncestors = new Set(ancestors).add(featureId);
    inputs.forEach((input, index) => addFeatureRow(children, input, depth + 1, `${path}/${index}`, nextAncestors));
  };
  const rebuild = (): void => {
    featureTree.replaceChildren();
    featureRows.clear();
    canonicalPathById.clear();
    rowsByPath.clear();
    rootIds.forEach((rootId, index) => addFeatureRow(featureTree, rootId, 0, `root/${index}`, new Set()));
  };
  rebuild();
  featureCount.textContent = String(visibleFeatures.length);
  focusFeatureInTree = (featureId: string): void => {
    const targetPath = pathToFeature(featureId);
    if (!targetPath) return;
    const segments = targetPath.split('/');
    for (let depth = 2; depth < segments.length; depth += 1) expandedPaths.add(segments.slice(0, depth).join('/'));
    rebuild();
    const canonicalPath = canonicalPathById.get(featureId) ?? targetPath;
    const row = rowsByPath.get(canonicalPath);
    row?.scrollIntoView({ block: 'center' });
    row?.classList.add('feature-reference-target');
    window.setTimeout(() => row?.classList.remove('feature-reference-target'), 700);
  };
}

function escapeHtml(value: string): string { return value.replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character] || character); }

function sourceLocationMarkup(source: OperationSource): string {
  const start = Math.max(1, source.line);
  const end = Math.max(start, source.end_line);
  const location = source.path ? `${source.path}:${start}${end !== start ? `-${end}` : ''}` : 'Source path is unavailable';
  return `<div class="source-file-path">${escapeHtml(location)}</div>${source.path && sourceFiles.has(source.path) ? '<p class="detail-muted">The embedded file is open in the Source dock.</p>' : `<pre class="source-call"><code>${escapeHtml(source.call_text ?? '')}</code></pre>`}`;
}

function sourceLocationsMarkup(sources: OperationSource[]): string {
  if (sources.length <= 1) return sources[0] ? sourceLocationMarkup(sources[0]) : '<p class="detail-muted">Source mapping unavailable.</p>';
  return sources.map((source, index) => `<button class="source-location" data-source-index="${index}" type="button">${sourceLocationMarkup(source)}</button>`).join('');
}

function jsonText(value: unknown): string {
  const rendered = JSON.stringify(value, null, 2);
  return rendered === undefined ? 'null' : rendered;
}

function featureIdForGeometry(entity: Entity | undefined): string | null {
  if (!currentModel || !entity) return null;
  const source = entity.source;
  if (source.kind !== 'feature_output' || typeof source.definition_id !== 'string' || typeof source.graph_id !== 'string' || typeof source.node_id !== 'string') return null;
  return currentModel.graph.nodes.find((feature) => feature.definition_id === source.definition_id && feature.graph_id === source.graph_id && feature.local_node_id === source.node_id)?.node_id ?? null;
}

function metadataSection(title: string, value: Record<string, unknown> | undefined): string {
  if (!value || Object.keys(value).length === 0) return '';
  return `<div class="detail-section"><span class="eyebrow">${escapeHtml(title)}</span><pre class="params">${escapeHtml(jsonText(value))}</pre></div>`;
}

function sourceIdentityRows(source: SourceRecord | undefined): string {
  if (!source) return '<dt>Source</dt><dd>unavailable</dd>';
  const rows: Array<[string, unknown]> = [['Kind', source.kind]];
  if (source.graph_id) rows.push(['Graph', source.graph_id]);
  if (source.node_id) rows.push(['Operation', source.node_id]);
  if (typeof source.output_slot === 'number') rows.push(['Output slot', source.output_slot]);
  if (source.semantic_type) rows.push(['Semantic type', source.semantic_type]);
  if (source.semantic_id) rows.push(['Semantic ID', source.semantic_id]);
  if (source.source_id) rows.push(['Source ID', source.source_id]);
  if (source.root_id) rows.push(['Root ID', source.root_id]);
  if (source.topo_id) rows.push(['Topology ID', source.topo_id]);
  return rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd title="${escapeHtml(String(value))}">${escapeHtml(String(value))}</dd>`).join('');
}


function selectNode(nodeId: string, entityId?: string): void {
  if (!currentManifest) return;
  if (!canSelectNode(nodeId)) {
    setStatus('Occurrence is hidden', true);
    return;
  }
  clearSelectionOverlay();
  selectedNodeId = nodeId;
  selectedFeatureId = null;
  for (const [id, row] of nodeRows) row.classList.toggle('selected', id === nodeId);
  for (const rows of featureRows.values()) rows.forEach((row) => row.classList.remove('selected'));
  const node = currentManifest.nodes.find((item) => item.node_id === nodeId);
  if (!node) return;
  const sidecar = sidecarForNode(node);
  const entity = sidecar?.entities.find((item) => item.entity_id === entityId);
  const solid = sidecar?.entities.find((item) => item.kind === 'solid');
  const inspected = entity ?? solid;
  selectionKind.textContent = inspected?.kind.toUpperCase() ?? node.definition_kind.toUpperCase();
  const linkedFeatureId = featureIdForGeometry(inspected);
  selectedFeatureId = linkedFeatureId;
  for (const [id, rows] of featureRows) rows.forEach((row) => row.classList.toggle('selected', id === linkedFeatureId));
  if (linkedFeatureId) {
    setNavigatorTab('features');
    focusFeatureInTree?.(linkedFeatureId);
    const feature = currentModel?.graph.nodes.find((item) => item.node_id === linkedFeatureId);
    if (feature?.source) sourceDock.reveal(feature.source);
  }
  const measure = inspected ? entityMeasure(inspected) : null;
  const measureLabel = inspected?.kind === 'face' ? 'Area' : inspected?.kind === 'edge' ? 'Length' : inspected?.kind === 'vertex' ? 'Position' : 'Volume';
  const measureUnit = inspected?.kind === 'face' ? 'mm²' : inspected?.kind === 'edge' ? 'mm' : inspected?.kind === 'vertex' ? 'mm' : 'mm³';
  const position = inspected?.kind === 'vertex' && Array.isArray(inspected.properties.position) ? inspected.properties.position as Vec3 : undefined;
  const measureValue = position ? position.map(formatNumber).join(', ') : formatNumber(measure?.[1]);
  const componentPath = node.parent_node_id ? node.node_id.replace(/^node\//, '').replace(/\/[^/]+$/, '') : 'root';
  const selector = inspected && sidecar ? qlSelectorForEntity(inspected, sidecar) : null;
  const iconName: keyof typeof lucideIcons = inspected?.kind === 'face' ? 'ScanFace' : inspected?.kind === 'edge' ? 'Spline' : inspected?.kind === 'vertex' ? 'CircleDot' : node.definition_kind === 'assembly' ? 'Boxes' : 'Box';
  const occurrenceObject = nodeObjects.get(nodeId);
  const effectiveVisible = occurrenceObject ? isEffectivelyVisible(occurrenceObject) : (nodeVisibility.get(nodeId) ?? true);
  const tags = inspected?.tags ?? [];
  details.innerHTML = `
    <div class="detail-title"><span class="detail-icon">${iconMarkup(iconName, 'detail-icon-svg')}</span><div><strong>${escapeHtml(entity ? `${node.display_name} / ${entity.entity_id}` : node.display_name)}</strong><span class="detail-definition-path">${escapeHtml(node.definition_id)}</span></div></div>
    <div class="detail-section"><span class="eyebrow">OCCURRENCE</span><dl><dt>Node</dt><dd class="path-value" title="${escapeHtml(node.node_id)}">${escapeHtml(node.node_id)}</dd><dt>Component path</dt><dd class="path-value">${escapeHtml(componentPath)}</dd><dt>Visibility</dt><dd>${effectiveVisible ? 'Visible' : 'Hidden'}</dd><dt>Definition kind</dt><dd>${escapeHtml(node.definition_kind)}</dd></dl></div>
    ${inspected ? `<div class="detail-section"><span class="eyebrow">EVALUATED ENTITY</span><dl><dt>Entity</dt><dd title="${escapeHtml(inspected.entity_id)}">${escapeHtml(inspected.entity_id)}</dd><dt>Topology</dt><dd>${escapeHtml(inspected.kind)}</dd><dt>Geometry</dt><dd>${escapeHtml(String(inspected.geometry.type ?? 'unknown'))}</dd><dt>${measureLabel}</dt><dd>${escapeHtml(measureValue || 'n/a')} ${measureUnit}</dd><dt>Parents</dt><dd>${inspected.parent_entity_ids.length}</dd><dt>Children</dt><dd>${inspected.child_entity_ids.length}</dd></dl></div>` : ''}
    <div class="detail-section"><span class="eyebrow">NAMING & SOURCE</span><dl><dt>Definition</dt><dd title="${escapeHtml(node.definition_id)}">${escapeHtml(node.definition_id)}</dd>${inspected ? sourceIdentityRows(inspected.source) : '<dt>Source</dt><dd>unavailable</dd>'}</dl></div>
    ${inspected ? `<div class="detail-section"><span class="eyebrow">TAGS</span>${tags.length ? `<div class="tag-list">${tags.map((tag: string) => `<span>${escapeHtml(tag)}</span>`).join('')}</div>` : '<p class="detail-muted">No evaluated tags.</p>'}</div>` : ''}
    ${selector ? `<div class="detail-section"><div class="detail-section-heading"><span class="eyebrow">UNIQUE QL SELECTOR</span>${selector.unique ? `<button id="copy-ql" class="copy-button">${iconMarkup('Copy', 'button-icon')}<span>COPY</span></button>` : ''}</div>${selector.unique ? `<pre class="selector-code">${escapeHtml(selector.expression)}</pre>` : '<p class="selector-warning">The exported tags and geometric facts do not uniquely identify this entity. No selector was fabricated.</p>'}</div>` : ''}
    ${inspected ? metadataSection('ENTITY METADATA', inspected.properties) : ''}
    ${metadataSection('OCCURRENCE METADATA', node.properties)}
    <div class="detail-section"><span class="eyebrow">DEFINITION</span><dl><dt>Type</dt><dd>${escapeHtml(node.definition_kind)}</dd><dt>Geometry</dt><dd>${node.geometry_asset_id ? 'GLB / cached' : 'none'}</dd><dt>Entity sidecar</dt><dd>${node.entity_asset_id ? 'available' : 'none'}</dd></dl></div>`;
  renderIcons(details);
  const copyButton = details.querySelector<HTMLButtonElement>('#copy-ql');
  copyButton?.addEventListener('click', async () => {
    if (!selector?.unique) return;
    try {
      await navigator.clipboard.writeText(selector.expression);
      copyButton.innerHTML = `${iconMarkup('CopyCheck', 'button-icon')}<span>COPIED</span>`;
      renderIcons(copyButton);
    } catch {
      setStatus('Clipboard access was denied', currentManifest !== null);
    }
  });
  if (entityId) highlightEntity(nodeId, entityId);
}

function selectFeature(featureId: string): void {
  if (!currentModel) return;
  clearSelectionOverlay();
  selectedFeatureId = featureId;
  selectedNodeId = null;
  for (const row of nodeRows.values()) row.classList.remove('selected');
  for (const [id, rows] of featureRows) rows.forEach((row) => row.classList.toggle('selected', id === featureId));
  const feature = currentModel.graph.nodes.find((item) => item.node_id === featureId);
  if (!feature) return;
  selectionKind.textContent = 'FEATURE';
  const inputs = feature.inputs.length ? feature.inputs.join(', ') : 'none';
  const assignment = feature.source?.assignment_targets.length ? feature.source.assignment_targets.join(', ') : 'unassigned';
  details.innerHTML = `<div class="detail-title"><span class="detail-icon">${iconMarkup(featureIconName(feature.op), 'detail-icon-svg')}</span><div><strong>${escapeHtml(featureLabel(feature))}</strong><span class="detail-definition-path">${escapeHtml(feature.node_id)}</span></div></div><div class="detail-section"><span class="eyebrow">OPERATION</span><dl><dt>Function</dt><dd>${escapeHtml(feature.op)}</dd><dt>Category</dt><dd>${escapeHtml(feature.display?.category || 'operation')}</dd><dt>Assigned to</dt><dd>${escapeHtml(assignment)}</dd><dt>Inputs</dt><dd title="${escapeHtml(inputs)}">${escapeHtml(inputs)}</dd><dt>Output count</dt><dd>${feature.output_count ?? 1}</dd></dl></div>${feature.sources.length ? `<div class="detail-section source-section"><span class="eyebrow">SOURCE (${feature.sources.length})</span><div id="feature-sources">${sourceLocationsMarkup(feature.sources)}</div></div>` : ''}<div class="detail-section"><span class="eyebrow">PARAMETERS</span><pre class="params">${escapeHtml(jsonText(feature.params))}</pre></div>`;
  renderIcons(details);
  const sourceButtons = [...details.querySelectorAll<HTMLButtonElement>('[data-source-index]')];
  sourceButtons.forEach((button) => button.addEventListener('click', () => {
    const source = feature.sources[Number(button.dataset.sourceIndex)];
    if (source) sourceDock.reveal(source);
  }));
  if (feature.source) sourceDock.reveal(feature.source);
}

function clearFeatureSelection(): void {
  if (selectedFeatureId === null) return;
  selectedFeatureId = null;
  selectionKind.textContent = 'SCENE';
  for (const rows of featureRows.values()) rows.forEach((row) => row.classList.remove('selected'));
   details.innerHTML = `<div class="empty-state"><span class="empty-cross">${iconMarkup('LayoutDashboard', 'empty-state-icon')}</span><strong>Feature selection cleared</strong><span>Select a Blueprint node to inspect its operation and dependencies.</span></div>`;
   renderIcons(details);
}

function clearSelectionOverlay(): void {
  for (const overlay of selectedOverlays) {
    overlay.parent?.remove(overlay);
    overlay.traverse((object) => {
      if (!(object instanceof THREE.Mesh || object instanceof THREE.LineSegments || object instanceof THREE.Points || object instanceof LineSegments2)) return;
      object.geometry.dispose();
      const material = object.material;
      (Array.isArray(material) ? material : [material]).forEach((item) => item.dispose());
    });
  }
  selectedOverlays = [];
}

function isEffectivelyVisible(object: THREE.Object3D): boolean {
  for (let current: THREE.Object3D | null = object; current; current = current.parent) {
    if (!current.visible) return false;
    if (current === modelRoot) break;
  }
  return true;
}

function canSelectNode(nodeId: string): boolean {
  if (!currentManifest?.nodes.some((node) => node.node_id === nodeId)) return false;
  const object = nodeObjects.get(nodeId);
  return !!object && isEffectivelyVisible(object) && (nodeVisibility.get(nodeId) ?? true);
}

function attachSelectionOverlay(source: THREE.Object3D, overlay: THREE.Object3D): void {
  overlay.name = 'selection-overlay';
  overlay.userData.pickable = false;
  overlay.renderOrder = 10;
  overlay.matrix.copy(source.matrix);
  overlay.matrixAutoUpdate = false;
  overlay.visible = source.visible;
  source.parent?.add(overlay);
  selectedOverlays.push(overlay);
}

function highlightEntity(nodeId: string, entityId?: string): void {
  clearSelectionOverlay();
  const node = currentManifest?.nodes.find((item) => item.node_id === nodeId);
  const object = nodeObjects.get(nodeId);
  const sidecar = sidecarForNode(node);
  if (!object || !sidecar) return;
  const entityGroup = entityId ? sidecar.face_groups.find((group: FaceGroup) => group.entity_id === entityId) : undefined;
  const edgeGroup = entityId ? sidecar.edge_groups.find((group: FaceGroup) => group.entity_id === entityId) : undefined;
  object.traverse((child: THREE.Object3D) => {
    if (selectedOverlays.length || !isEffectivelyVisible(child) || !(child instanceof THREE.Mesh || child instanceof THREE.LineSegments || child instanceof THREE.Points)) return;
    const source = child as THREE.Mesh | THREE.LineSegments | THREE.Points;
    const range = entityGroup || edgeGroup;
    const isVertex = entityId?.startsWith('entity/vertex/') && source instanceof THREE.Points;
    if (!range && !isVertex && entityId !== 'entity/solid/0') return;
    if (entityGroup && !(source instanceof THREE.Mesh)) return;
    if (edgeGroup && !entityGroup && !(source instanceof THREE.LineSegments)) return;
    if (isVertex && !source.userData.vertexEntityIds?.includes(entityId)) return;
    const material = source instanceof THREE.LineSegments
      ? new LineMaterial({ color: '#fff04d', linewidth: 5, worldUnits: false, depthTest: false, transparent: true, opacity: 1 })
      : source instanceof THREE.Points
        ? new THREE.PointsMaterial({ color: '#fff04d', size: 16, sizeAttenuation: false, depthTest: false, transparent: true, opacity: 1 })
      : new THREE.MeshBasicMaterial({ color: '#fff04d', transparent: true, opacity: 0.78, depthTest: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 });
    let overlay: THREE.Object3D;
    if (source instanceof THREE.LineSegments && range) {
      const lineGeometry = new LineSegmentsGeometry();
      const positions: number[] = [];
      const index = source.geometry.index;
      const position = source.geometry.getAttribute('position');
      for (let offset = range.first_index; offset < range.first_index + range.index_count; offset += 2) {
        const a = index ? index.getX(offset) : offset;
        const b = index ? index.getX(offset + 1) : offset + 1;
        positions.push(position.getX(a), position.getY(a), position.getZ(a), position.getX(b), position.getY(b), position.getZ(b));
      }
      lineGeometry.setPositions(positions);
      const lineMaterial = material as LineMaterial;
      lineMaterial.resolution.set(renderer.domElement.clientWidth, renderer.domElement.clientHeight);
      overlay = new LineSegments2(lineGeometry, lineMaterial);
    } else if (source instanceof THREE.Points) {
      const geometry = source.geometry.clone();
      const vertexIndex = source.userData.vertexEntityIds.indexOf(entityId);
      geometry.setDrawRange(vertexIndex, 1);
      overlay = new THREE.Points(geometry, material as THREE.PointsMaterial);
    } else {
      const geometry = source.geometry.clone();
      if (range) geometry.setDrawRange(range.first_index, range.index_count);
      overlay = new THREE.Mesh(geometry, material as THREE.MeshBasicMaterial);
    }
    attachSelectionOverlay(source, overlay);
  });
}

function highlightComponent(nodeId: string): void {
  clearSelectionOverlay();
  const node = nodeObjects.get(nodeId);
  if (!node) return;
  const meshes: THREE.Mesh[] = [];
  node.traverse((child: THREE.Object3D) => {
    if (child instanceof THREE.Mesh && !(child instanceof LineSegments2) && child.userData.pickable !== false && isEffectivelyVisible(child)) meshes.push(child);
  });
  for (const child of meshes) {
    const geometry = child.geometry.clone();
    const material = new THREE.MeshBasicMaterial({ color: '#fff04d', transparent: true, opacity: 0.44, depthTest: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 });
    attachSelectionOverlay(child, new THREE.Mesh(geometry, material));
  }
}

function toggleNodeVisibility(nodeId: string): void {
  const object = nodeObjects.get(nodeId);
  const row = nodeRows.get(nodeId);
  if (!object || !row) return;
  object.visible = !object.visible;
  nodeVisibility.set(nodeId, object.visible);
  row.classList.toggle('hidden-node', !object.visible);
  const visibility = row.querySelector<HTMLElement>('.tree-visibility');
  if (visibility) {
    visibility.innerHTML = iconMarkup(object.visible ? 'Eye' : 'EyeOff', 'tree-visibility-icon');
    visibility.setAttribute('aria-label', object.visible ? 'Hide occurrence' : 'Show occurrence');
    visibility.setAttribute('title', object.visible ? 'Hide occurrence' : 'Show occurrence');
    renderIcons(visibility);
  }
  if (selectedNodeId && !canSelectNode(selectedNodeId)) {
    clearSelectionOverlay();
    selectedNodeId = null;
    selectedFeatureId = null;
    for (const selectedRow of nodeRows.values()) selectedRow.classList.remove('selected');
    for (const rows of featureRows.values()) rows.forEach((selectedRow) => selectedRow.classList.remove('selected'));
    selectionKind.textContent = 'SCENE';
    details.innerHTML = `<div class="empty-state"><span class="empty-cross">${iconMarkup('EyeOff', 'empty-state-icon')}</span><strong>Selection hidden</strong><span>The selected occurrence is hidden.</span></div>`;
    renderIcons(details);
  } else if (!isEffectivelyVisible(object)) clearSelectionOverlay();
}

function frameModel(): void {
  const box = new THREE.Box3().setFromObject(modelRoot);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.5, 0.01);
  camera.position.copy(center).add(new THREE.Vector3(1, 0.78, 1).normalize().multiplyScalar(radius * 2.4));
  camera.near = Math.max(radius / 100, 0.001);
  camera.far = Math.max(radius * 100, 10);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.maxDistance = radius * 12;
  controls.update();
}

async function loadPackage(files: PackageFiles, packageSchema: string): Promise<void> {
  const manifest = JSON.parse(strFromU8(bytesFor(files, 'scene.json'))) as SceneManifest;
  if (manifest.schema_version !== '2.0') throw new Error(`unsupported scene schema: ${manifest.schema_version}`);
  clearModel();
  currentManifest = manifest;
  currentFiles = files;
  manifestByDefinition.clear();
  for (const definition of manifest.definitions) manifestByDefinition.set(definition.definition_id, definition);
  const federated = buildFederatedFeatureModel(manifest, files);
  currentModel = federated.model;
  for (const [path, content] of federated.sources) sourceFiles.set(path, content);
  sourceDock.setFiles(sourceFiles);
  renderTree(manifest);
  renderFeatureTree();
  sceneTitle.textContent = manifest.scene_id.replaceAll('-', ' ');
  nodeCount.textContent = String(manifest.nodes.length);
  packageMeta.textContent = `Package ${packageSchema} · Scene ${manifest.schema_version} · ${manifest.units} · ${manifest.definitions.length} definitions`;
  const nodesByParent = new Map<string | null, SceneNode[]>();
  for (const node of manifest.nodes) nodesByParent.set(node.parent_node_id, [...(nodesByParent.get(node.parent_node_id) ?? []), node]);
  const build = async (parent: THREE.Object3D, parentId: string | null): Promise<void> => {
    for (const node of nodesByParent.get(parentId) ?? []) {
      const object = new THREE.Group();
      object.name = node.node_id;
      object.matrixAutoUpdate = false;
      object.matrix.copy(placementMatrix(node.transform));
      object.visible = nodeVisibility.get(node.node_id) ?? true;
      object.userData.nodeId = node.node_id;
      object.userData.definitionId = node.definition_id;
      nodeObjects.set(node.node_id, object);
      parent.add(object);
      if (node.node_kind === 'part' || node.node_kind === 'solid') {
        const instance = await instantiateNode(node);
        instance.traverse((child: THREE.Object3D) => { child.userData.nodeId = node.node_id; child.userData.definitionId = node.definition_id; });
        object.add(instance);
      }
      await build(object, node.node_id);
    }
  };
  await build(modelRoot, null);
  renderInterfaces(manifest);
  frameModel();
  loading.classList.add('hidden');
  setStatus(`${manifest.nodes.length} occurrences · ${manifest.geometry_assets.length} geometry assets · ${currentModel.graph.nodes.length} features`, true);
}


document.querySelector<HTMLButtonElement>('#fit-button')!.addEventListener('click', frameModel);
interfacesButton.addEventListener('click', () => {
  interfacesVisible = !interfacesVisible;
  if (interfaceRoot) interfaceRoot.visible = interfacesVisible;
  interfacesButton.classList.toggle('active', interfacesVisible);
  setStatus(interfacesVisible ? 'Interfaces visible' : 'Interfaces hidden', currentManifest !== null);
});
const selectionModeButtons = Array.from(document.querySelectorAll<HTMLButtonElement>('.selection-mode'));
for (const button of selectionModeButtons) {
  button.addEventListener('click', () => {
    selectionMode = button.dataset.selectionMode as SelectionMode;
    selectionModeButtons.forEach((item) => item.classList.toggle('active', item === button));
    clearSelectionOverlay();
    applySelectionModeVisibility();
    setStatus(`Selection intent: ${selectionMode.toUpperCase()}`, currentManifest !== null);
  });
}
const fileInput = document.querySelector<HTMLInputElement>('#file-input')!;
document.querySelector<HTMLButtonElement>('#open-button')!.addEventListener('click', () => fileInput.click());
const setNavigatorTab = (tab: 'components' | 'features'): void => {
  const features = tab === 'features';
  componentsTab.classList.toggle('active', !features);
  featuresTab.classList.toggle('active', features);
  componentsTab.setAttribute('aria-selected', String(!features));
  featuresTab.setAttribute('aria-selected', String(features));
  componentsView.hidden = features;
  featuresView.hidden = !features;
};
componentsTab.addEventListener('click', () => setNavigatorTab('components'));
featuresTab.addEventListener('click', () => setNavigatorTab('features'));
fileInput.addEventListener('change', async () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  try {
    loading.classList.remove('hidden');
    setStatus('Opening product package');
    const opened = await openCadPackage(new Uint8Array(await file.arrayBuffer()));
    await loadPackage(opened.files, opened.schemaVersion);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Unable to open package');
    loading.classList.add('hidden');
  }
});

viewport.addEventListener('dragover', (event) => {
  event.preventDefault();
  viewport.classList.add('drop-target');
});
viewport.addEventListener('dragleave', () => viewport.classList.remove('drop-target'));
viewport.addEventListener('drop', async (event) => {
  event.preventDefault();
  viewport.classList.remove('drop-target');
  const file = event.dataTransfer?.files[0];
  if (!file) return;
  try {
    loading.classList.remove('hidden');
    setStatus('Opening product package');
    const opened = await openCadPackage(new Uint8Array(await file.arrayBuffer()));
    await loadPackage(opened.files, opened.schemaVersion);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Unable to open package');
    loading.classList.add('hidden');
  }
});

function resize(): void {
  const width = viewport.clientWidth;
  const height = viewport.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / Math.max(height, 1);
  camera.updateProjectionMatrix();
  for (const overlay of selectedOverlays) {
    overlay.traverse((object) => {
      if (object instanceof LineSegments2) object.material.resolution.set(width, height);
    });
  }
  modelRoot.traverse((object) => {
    if (object instanceof LineSegments2) object.material.resolution.set(width, height);
  });
}
new ResizeObserver(resize).observe(viewport);
resize();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let selectionPointerActive = false;

function pointerRay(event: PointerEvent): void {
  const bounds = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const distance = camera.position.distanceTo(controls.target);
  const worldPerPixel = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)) * distance / Math.max(bounds.height, 1);
  raycaster.params.Line.threshold = worldPerPixel * 5;
  raycaster.params.Points.threshold = worldPerPixel * 8;
}

function validSelectionHit(event: PointerEvent): THREE.Intersection | null {
  pointerRay(event);
  const hits = raycaster.intersectObjects(modelRoot.children, true).filter((hit) => {
    if (hit.object.userData.pickable === false || !isEffectivelyVisible(hit.object)) return false;
    if (typeof hit.object.userData.interfaceId === 'string') return interfacesVisible;
    const nodeId = hit.object.userData.nodeId;
    return typeof nodeId === 'string' && canSelectNode(nodeId);
  });
  const interfaceHit = hits.find((hit) => typeof hit.object.userData.interfaceId === 'string');
  if (interfaceHit) return interfaceHit;
  const meshHit = hits.find((hit) => hit.object instanceof THREE.Mesh);
  if (selectionMode === 'component' || selectionMode === 'solid' || selectionMode === 'face') {
    return meshHit ?? null;
  }
  const candidate = hits.find((hit) => selectionMode === 'edge' ? hit.object instanceof THREE.LineSegments : hit.object instanceof THREE.Points);
  if (!candidate) return null;
  if (!meshHit) return candidate;
  const occlusionAllowance = selectionMode === 'edge' ? raycaster.params.Line.threshold : raycaster.params.Points.threshold;
  return candidate.distance <= meshHit.distance + occlusionAllowance * 1.5 ? candidate : null;
}

function commitSelection(event: PointerEvent): void {
  const hit = validSelectionHit(event);
  if (!hit) {
    setStatus(`No ${selectionMode} at pointer`, currentManifest !== null);
    return;
  }
  const interfaceId = hit.object.userData.interfaceId;
  if (typeof interfaceId === 'string') {
    selectInterface(interfaceId);
    return;
  }
  const nodeId = hit.object.userData.nodeId;
  if (typeof nodeId !== 'string') return;
  const sceneNode = currentManifest?.nodes.find((node) => node.node_id === nodeId);
  const sidecar = sidecarForNode(sceneNode);
  if (selectionMode === 'component') {
    selectNode(nodeId);
    highlightComponent(nodeId);
    return;
  }
  if (selectionMode === 'solid') {
    const solidId = sidecar?.entities.find((entity) => entity.kind === 'solid')?.entity_id;
    if (solidId) selectNode(nodeId, solidId);
    return;
  }
  let entityId: string | undefined;
  if (selectionMode === 'face' && hit.object instanceof THREE.Mesh && typeof hit.faceIndex === 'number') {
    const triangleOffset = hit.faceIndex * 3;
    entityId = sidecar?.face_groups.find((group: FaceGroup) => triangleOffset >= group.first_index && triangleOffset < group.first_index + group.index_count)?.entity_id;
  } else if (selectionMode === 'edge' && hit.object instanceof THREE.LineSegments && typeof hit.index === 'number') {
    entityId = sidecar?.edge_groups.find((group: FaceGroup) => hit.index! >= group.first_index && hit.index! < group.first_index + group.index_count)?.entity_id;
  } else if (selectionMode === 'vertex' && hit.object instanceof THREE.Points && typeof hit.index === 'number') {
    entityId = hit.object.userData.vertexEntityIds?.[hit.index];
  }
  if (entityId) selectNode(nodeId, entityId);
  else setStatus(`No ${selectionMode} at pointer`, true);
}

bindClickSelection({
  element: renderer.domElement,
  camera,
  controls,
  onPointerStateChange: (active) => { selectionPointerActive = active; },
  onClick: commitSelection,
});
renderer.domElement.addEventListener('pointermove', (event) => {
  if (selectionPointerActive) return;
  renderer.domElement.style.cursor = validSelectionHit(event) ? 'crosshair' : 'default';
});
renderer.domElement.addEventListener('pointerleave', () => {
  renderer.domElement.style.cursor = 'default';
});
renderer.setAnimationLoop(() => { controls.update(); renderer.render(threeScene, camera); });

loading.classList.add('hidden');
details.innerHTML = `<div class="empty-state"><span class="empty-cross">${iconMarkup('PackageOpen', 'empty-state-icon')}</span><strong>Choose a product package</strong><span>Open a .scadpkg file or drop one into the viewport.</span></div>`;
renderIcons(details);
