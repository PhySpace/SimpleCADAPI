// Slash-triggered operation autocomplete for the annotation composer.
//
// Typing `/` in the composer opens a dropdown that floats ABOVE the input
// (the composer sits at the bottom of the screen). Text after the slash
// filters candidates case-insensitively over op id and label; ArrowUp /
// ArrowDown move the highlight, Enter (or click) inserts the highlighted
// operation as an `op:` token and removes the `/query` text, Esc closes.
//
// IME safety: while a CJK composition is active nothing opens and no
// navigation key is consumed — the composer's own commit guard stays in
// charge of Enter.

import type { TokenComposer } from './composer';

export type SuggestOperation = {
  op_id: string;
  label: string;
  category: string;
  hint: string;
};

type SlashRange = { node: Text; offset: number };

const CATEGORY_LABELS: Record<string, string> = {
  sketch: 'SKETCH',
  boolean: 'BOOLEAN',
  solid: 'SOLID',
  primitive: 'PRIMITIVE',
  modify: 'MODIFY',
  surface: 'SURFACE',
  pattern: 'PATTERN',
};

export class OpSuggest {
  readonly popup: HTMLDivElement;
  private operations: SuggestOperation[] = [];
  private filtered: SuggestOperation[] = [];
  private highlighted = 0;
  private openState = false;
  private lastQuery: string | null = null;

  constructor(private readonly composer: TokenComposer) {
    this.popup = document.createElement('div');
    this.popup.className = 'absolute bottom-[calc(100%+10px)] left-3.5 right-3.5 z-40 max-h-[300px] overflow-y-auto rounded-[14px] border border-edge bg-panel/95 p-1.5 shadow-2xl shadow-black/60 backdrop-blur-[14px]';
    this.popup.hidden = true;
    this.popup.addEventListener('mousedown', (event) => event.preventDefault());
    this.composer.host.addEventListener('input', () => this.refresh());
    this.composer.host.addEventListener('keyup', (event) => {
      if (!this.openState && event.key === '/') this.refresh();
    });
    this.composer.host.addEventListener('blur', () => window.setTimeout(() => this.close(), 120));
  }

  setOperations(operations: SuggestOperation[]): void {
    this.operations = operations;
  }

  /** Composer key hook: returns true when the key was consumed. */
  handleKeydown(event: KeyboardEvent): boolean {
    if (!this.openState || event.isComposing || event.keyCode === 229) return false;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (this.filtered.length) {
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        this.highlighted = (this.highlighted + delta + this.filtered.length) % this.filtered.length;
        this.render();
      }
      return true;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (this.filtered.length) this.insert(this.filtered[this.highlighted]);
      else this.close();
      return true;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return true;
    }
    return false;
  }

  close(): void {
    this.openState = false;
    this.popup.hidden = true;
    this.popup.replaceChildren();
  }

  // -- internals -------------------------------------------------------------

  private refresh(): void {
    const match = this.slashQuery();
    if (!match || !this.operations.length) {
      this.close();
      return;
    }
    const query = match.lowered;
    // op id substring, or a whole-word label prefix — a bare label substring
    // would match accidents like "fil" inside "sketch profile"
    this.filtered = this.operations.filter((operation) =>
      !query
      || operation.op_id.toLowerCase().includes(query)
      || operation.label.toLowerCase().split(/\s+/).some((word) => word.startsWith(query)));
    if (query !== this.lastQuery) this.highlighted = 0;
    this.lastQuery = query;
    if (!this.filtered.length) {
      // keep the popup open with an explicit empty state — silent closes
      // read as a broken key
      this.filtered = [];
      this.openState = true;
      this.popup.hidden = false;
      this.popup.replaceChildren();
      const empty = document.createElement('div');
      empty.className = 'px-3 py-2.5 text-[11px] text-dim';
      empty.textContent = `no operation matches “${match.raw}”`;
      this.popup.append(empty);
      return;
    }
    this.highlighted = Math.min(this.highlighted, this.filtered.length - 1);
    this.openState = true;
    this.popup.hidden = false;
    this.render();
  }

  private slashQuery(): { raw: string; lowered: string } | null {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const caretNode = range.startContainer;
    if (!(caretNode instanceof Text) || !this.composer.host.contains(caretNode)) return null;
    const lineStart = caretNode.data.lastIndexOf('\n', range.startOffset - 1);
    const text = caretNode.data.slice(lineStart + 1, range.startOffset);
    const slash = text.lastIndexOf('/');
    if (slash < 0 || /\s/.test(text.slice(slash + 1))) return null;
    const raw = text.slice(slash + 1);
    return { raw, lowered: raw.toLowerCase() };
  }

  private slashRange(): SlashRange | null {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const caretNode = range.startContainer;
    if (!(caretNode instanceof Text) || !this.composer.host.contains(caretNode)) return null;
    const before = caretNode.data.slice(0, range.startOffset);
    const slash = before.lastIndexOf('/');
    if (slash < 0) return null;
    return { node: caretNode, offset: slash };
  }

  private insert(operation: SuggestOperation): void {
    const slash = this.slashRange();
    if (slash) {
      const selection = window.getSelection()!;
      const range = selection.getRangeAt(0);
      range.setStart(slash.node, slash.offset);
      range.deleteContents();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    this.composer.insertToken({ token: `op:${operation.op_id}`, label: operation.label, kind: 'op', category: operation.category });
    this.close();
    this.composer.focus();
  }

  private render(): void {
    this.popup.replaceChildren();
    let lastCategory = '';
    this.filtered.forEach((operation, index) => {
      if (operation.category !== lastCategory) {
        lastCategory = operation.category;
        const label = document.createElement('div');
        label.className = 'px-2.5 pb-0.5 pt-1.5 font-mono text-[9px] font-medium tracking-[0.14em] text-faint';
        label.textContent = CATEGORY_LABELS[operation.category] ?? operation.category;
        this.popup.append(label);
      }
      const row = document.createElement('button');
      row.type = 'button';
      row.dataset.highlighted = String(index === this.highlighted);
      row.className = 'group flex w-full items-baseline gap-2.5 rounded-[9px] border-0 bg-transparent px-2.5 py-1.5 text-left text-[11px] text-ink hover:bg-[rgb(179_227_107_/_0.08)] data-[highlighted=true]:bg-[rgb(179_227_107_/_0.08)]';
      const name = document.createElement('span');
      name.className = `font-mono text-[11px] ${operation.category === 'sketch' ? 'text-[#a8e0da]' : operation.category === 'solid' ? 'text-[#b9c8ee]' : operation.category === 'modify' ? 'text-[#eeb9c3]' : operation.category === 'surface' ? 'text-[#d3c4ee]' : operation.category === 'pattern' ? 'text-[#e6bce6]' : operation.category === 'primitive' ? 'text-[#e6d3ab]' : 'text-[#cdd3dd]'}`;
      name.textContent = `/${operation.op_id}`;
      const hint = document.createElement('span');
      hint.className = 'min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[10px] text-dim';
      hint.textContent = operation.hint;
      row.append(name, hint);
      row.addEventListener('mouseenter', () => {
        this.highlighted = index;
        this.render();
      });
      row.addEventListener('click', () => this.insert(operation));
      this.popup.append(row);
    });
    const active = this.popup.querySelector<HTMLElement>('[data-highlighted="true"]');
    active?.scrollIntoView({ block: 'nearest' });
  }
}
