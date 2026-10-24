// Render serialized annotation markup — plain text with every chip as
// `[label](token)` — back into DOM, so capsule text and hover bubbles carry
// the same face/edge/vertex/op tag styling as the live composer.

export type MarkupTokenKind = 'face' | 'edge' | 'vertex' | 'body' | 'op';

const MARKUP_PATTERN = /\[([^\]]+)\]\(([^)]+)\)/g;

function kindForToken(token: string): { kind: MarkupTokenKind; category?: string } {
  if (token.startsWith('op:')) return { kind: 'op', category: 'op' };
  if (token.startsWith('face:')) return { kind: 'face' };
  if (token.startsWith('edge:')) return { kind: 'edge' };
  if (token.startsWith('vertex:')) return { kind: 'vertex' };
  return { kind: 'body' };
}

/** Resolve an op token's category so op chips keep their per-category color. */
export function opCategoryResolver(operations: Array<{ op_id: string; category: string }>): (opId: string) => string | undefined {
  const byId = new Map(operations.map((operation) => [operation.op_id, operation.category]));
  return (opId: string) => byId.get(opId);
}

export function renderMarkup(text: string, opCategory?: (opId: string) => string | undefined): DocumentFragment {
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const match of text.matchAll(MARKUP_PATTERN)) {
    const start = match.index ?? 0;
    if (start > cursor) fragment.append(text.slice(cursor, start));
    const [, label, token] = match;
    const resolved = kindForToken(token);
    const chip = document.createElement('span');
    chip.className = resolved.kind === 'op'
      ? `re-token re-token-op re-opcat-${opCategory?.(token.slice(3)) ?? resolved.category}`
      : `re-token re-token-${resolved.kind}`;
    chip.dataset.token = token;
    chip.dataset.label = label;
    chip.dataset.kind = resolved.kind;
    const glyph = document.createElement('span');
    glyph.className = 're-token-glyph';
    glyph.textContent = resolved.kind === 'op' ? 'OP' : resolved.kind === 'face' ? 'F' : resolved.kind === 'edge' ? 'E' : resolved.kind === 'vertex' ? 'V' : 'B';
    const name = document.createElement('span');
    name.className = 're-token-label';
    name.textContent = label;
    chip.append(glyph, name);
    fragment.append(chip);
    cursor = start + match[0].length;
  }
  if (cursor < text.length) fragment.append(text.slice(cursor));
  return fragment;
}
