// Feature DAG tree for the re-studio rebuilt panel — the interaction model is
// copied from the main viewer's Features navigator (main.ts renderFeatureTree):
// apply_tag nodes are hidden, shared inputs collapse into REF rows, USED/IN
// badges expose fan-in/out, and clicking a row selects + expands.

import {
  Box,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Combine,
  GitBranch,
  Layers,
  LayoutDashboard,
  Link,
  Plus,
  Rotate3d,
  Scissors,
  createIcons,
} from 'lucide';
import type { ModelDocument, ModelNode } from '../scene2';

const lucideIcons = {
  Box,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Combine,
  GitBranch,
  Layers,
  LayoutDashboard,
  Link,
  Plus,
  Rotate3d,
  Scissors,
};

type IconName = keyof typeof lucideIcons;

function iconMarkup(name: IconName, className = 'ui-icon'): string {
  const iconName = name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
  return `<i data-lucide="${iconName}" class="${className}" aria-hidden="true"></i>`;
}

function renderIcons(root: Element): void {
  createIcons({ icons: lucideIcons, attrs: { 'stroke-width': 1.8 }, root });
}

function featureIconName(op: string): IconName {
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

export type FeatureTreeCallbacks = {
  onSelectFeature?: (feature: ModelNode) => void;
};

export class FeatureTreeView {
  private readonly host: HTMLElement;
  private readonly callbacks: FeatureTreeCallbacks;
  private model: ModelDocument | null = null;
  private selectedFeatureId: string | null = null;
  private focusFeatureInTree: ((featureId: string) => void) | null = null;

  constructor(host: HTMLElement, callbacks: FeatureTreeCallbacks = {}) {
    this.host = host;
    this.callbacks = callbacks;
    this.renderEmpty('no feature tree yet — the agent has not produced a rebuild');
  }

  get selectedFeature(): string | null {
    return this.selectedFeatureId;
  }

  setModel(model: ModelDocument | null): void {
    this.model = model;
    this.selectedFeatureId = null;
    this.render();
  }

  focusFeature(featureId: string): void {
    this.selectedFeatureId = featureId;
    this.focusFeatureInTree?.(featureId);
  }

  private renderEmpty(message: string): void {
    this.host.innerHTML = `<div class="tree-empty" style="padding:8px;color:#6f7d8e;font-size:12px">${message}</div>`;
  }

  private render(): void {
    this.host.replaceChildren();
    this.focusFeatureInTree = null;
    const model = this.model;
    if (!model || model.graph.nodes.length === 0) {
      this.renderEmpty('this package has no embedded operation DAG');
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
    const rowsById = new Map<string, HTMLButtonElement[]>();
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
      row.classList.toggle('selected', featureId === this.selectedFeatureId);
      const expanded = !reference && inputs.length > 0 && expandedPaths.has(path);
      const shared = (consumerCount.get(featureId) ?? 0) > 1;
      const prefixIcon = reference ? 'Link' : inputs.length ? (expanded ? 'ChevronDown' : 'ChevronRight') : 'CircleDot';
      row.setAttribute('aria-expanded', inputs.length && !reference ? String(expanded) : 'false');
      row.setAttribute('aria-label', reference ? `Reference to ${featureTreeLabel(feature)}` : featureTreeLabel(feature));
      row.innerHTML = `<span class="tree-chevron">${iconMarkup(prefixIcon, 'tree-chevron-icon')}</span><span class="tree-glyph feature-glyph">${iconMarkup(featureIconName(feature.op), 'tree-type-icon')}</span><span class="tree-label" title="${escapeHtml(feature.op)}">${escapeHtml(featureTreeLabel(feature))}</span>${reference ? '<span class="feature-reference-mark">REF</span>' : ''}${shared && !reference ? `<span class="feature-shared-mark" title="Used by ${consumerCount.get(featureId)} operations">USED ${consumerCount.get(featureId)}</span>` : ''}${inputs.length && !reference ? `<span class="feature-input-count" title="${inputs.length} visible graph input${inputs.length === 1 ? '' : 's'}">${inputs.length} IN</span>` : ''}`;
      renderIcons(row);
      row.addEventListener('click', () => {
        this.selectFeature(featureId);
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
      rowsById.set(featureId, [...(rowsById.get(featureId) ?? []), row]);
      if (!expanded) return;
      const children = document.createElement('div');
      children.className = 'feature-dag-children';
      parent.append(children);
      const nextAncestors = new Set(ancestors).add(featureId);
      inputs.forEach((input, index) => addFeatureRow(children, input, depth + 1, `${path}/${index}`, nextAncestors));
    };
    const rebuild = (): void => {
      this.host.replaceChildren();
      rowsByPath.clear();
      rowsById.clear();
      canonicalPathById.clear();
      rootIds.forEach((rootId, index) => addFeatureRow(this.host, rootId, 0, `root/${index}`, new Set()));
    };
    rebuild();
    this.focusFeatureInTree = (featureId: string): void => {
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

  private selectFeature(featureId: string): void {
    this.selectedFeatureId = featureId;
    const feature = this.model?.graph.nodes.find((item) => item.node_id === featureId);
    for (const row of this.host.querySelectorAll<HTMLButtonElement>('.tree-row')) {
      row.classList.toggle('selected', row.dataset.featureId === featureId);
    }
    if (feature) this.callbacks.onSelectFeature?.(feature);
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character] || character);
}
