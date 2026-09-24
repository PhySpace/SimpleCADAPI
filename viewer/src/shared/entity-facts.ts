// Entity measurement + QL selector synthesis, extracted from main.ts so the
// package viewer and the reverse-engineering mode agree on what the LLM sees.

import type { Entity, EntitySidecar, Vec3 } from './scene2';

export function pythonLiteral(value: unknown): string {
  if (value === null) return 'None';
  if (value === true) return 'True';
  if (value === false) return 'False';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : 'None';
  return JSON.stringify(String(value));
}

export function formatNumber(value: unknown): string {
  return typeof value === 'number' ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value) : 'n/a';
}

export function entityCenter(entity: Entity): Vec3 | null {
  const value = entity.kind === 'vertex' ? entity.properties.position : entity.properties.centroid;
  return Array.isArray(value) && value.length === 3 && value.every((item) => typeof item === 'number') ? value as Vec3 : null;
}

export function entityMeasure(entity: Entity): [string, number] | null {
  const path = entity.kind === 'solid' ? 'geom.volume' : entity.kind === 'face' ? 'geom.area' : entity.kind === 'edge' ? 'geom.length' : null;
  const value = entity.kind === 'solid' ? entity.properties.volume : entity.kind === 'face' ? entity.properties.area : entity.kind === 'edge' ? entity.properties.length : null;
  return path && typeof value === 'number' ? [path, value] : null;
}

export function qlSelectorForEntity(entity: Entity, sidecar: EntitySidecar): { expression: string; unique: boolean } {
  type Fact = { expression: string; matches: (candidate: Entity) => boolean };
  const candidates = sidecar.entities.filter((candidate) => candidate.kind === entity.kind);
  const facts: Fact[] = [];
  for (const tag of entity.tags) facts.push({ expression: `Q.tag(${pythonLiteral(tag)})`, matches: (candidate) => candidate.tags.includes(tag) });
  const geometryType = entity.geometry.type;
  if (typeof geometryType === 'string' && !geometryType.startsWith('other_') && geometryType !== 'brep_solid' && geometryType !== 'point') {
    const expected = geometryType.toUpperCase().replace(/^BSPLINE_(CURVE|SURFACE)$/, 'BSPLINE');
    facts.push({ expression: `Q.prop("geom.type", "==", ${pythonLiteral(expected)})`, matches: (candidate) => candidate.geometry.type === geometryType });
  }
  const measure = entityMeasure(entity);
  if (measure) facts.push({ expression: `Q.prop(${pythonLiteral(measure[0])}, "==", ${pythonLiteral(measure[1])})`, matches: (candidate) => entityMeasure(candidate)?.[1] === measure[1] });
  const center = entityCenter(entity);
  if (center) {
    (['x', 'y', 'z'] as const).forEach((axis, index) => facts.push({
      expression: `Q.prop("geom.center.${axis}", "==", ${pythonLiteral(center[index])})`,
      matches: (candidate) => entityCenter(candidate)?.[index] === center[index],
    }));
  }
  let matches = candidates;
  const selectedFacts: Fact[] = [];
  for (const fact of facts) {
    const narrowed = matches.filter(fact.matches);
    if (narrowed.length < matches.length) {
      selectedFacts.push(fact);
      matches = narrowed;
    }
    if (matches.length === 1) break;
  }
  const unique = matches.length === 1 && matches[0].entity_id === entity.entity_id;
  const factory = entity.kind === 'solid' ? 'Q.ShapeSelector(target_kind="solid")' : `Q.${entity.kind}s()`;
  const lines = [factory];
  if (typeof entity.source.node_id === 'string') lines.push(`.from_source(${pythonLiteral(entity.source.node_id)}, ${typeof entity.source.output_slot === 'number' ? entity.source.output_slot : 0})`);
  if (selectedFacts.length === 1) lines.push(`.where(${selectedFacts[0].expression})`);
  if (selectedFacts.length > 1) lines.push(`.where(Q.and_(\n    ${selectedFacts.map((fact) => fact.expression).join(',\n    ')}\n))`);
  lines.push('.exactly(1)');
  return { expression: `(${lines.map((line) => `    ${line}`).join('\n')}\n)`, unique };
}
