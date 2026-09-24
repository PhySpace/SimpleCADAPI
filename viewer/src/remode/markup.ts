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
    const kindClasses: Record<MarkupTokenKind, string> = {
      face: 'text-[#a8cdf5] border-[#33587e] bg-[rgb(79_156_240_/_0.13)]',
      edge: 'text-[#a9e2bd] border-[#2f5c42] bg-[rgb(79_197_122_/_0.13)]',
      vertex: 'text-[#f2c4a3] border-[#7c5232] bg-[rgb(224_129_79_/_0.13)]',
      body: 'text-[#e7d5a8] border-[#79622f] bg-[rgb(201_162_79_/_0.13)]',
      op: 'text-[#cdd3dd] border-[#4a5462] bg-[rgb(148_163_184_/_0.13)]',
    };
    chip.className = `inline-flex items-center gap-1 mx-px rounded-full border px-[7px] text-[9px] leading-[1.7] align-baseline select-all whitespace-nowrap ${kindClasses[resolved.kind]}`;
    chip.dataset.token = token;
    chip.dataset.label = label;
    chip.dataset.kind = resolved.kind;
    const glyph = document.createElement('span');
    glyph.className = 'font-mono text-[8px] font-bold leading-none tracking-[0.04em] opacity-85';
    glyph.textContent = resolved.kind === 'op' ? 'OP' : resolved.kind === 'face' ? 'F' : resolved.kind === 'edge' ? 'E' : resolved.kind === 'vertex' ? 'V' : 'B';
    const name = document.createElement('span');
    name.className = 'font-mono';
    name.textContent = label;
    chip.append(glyph, name);
    fragment.append(chip);
    cursor = start + match[0].length;
  }
  if (cursor < text.length) fragment.append(text.slice(cursor));
  return fragment;
}
