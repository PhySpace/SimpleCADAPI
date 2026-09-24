// Free-form annotation composer: a contenteditable input where picked
// entities and operation tips appear as inline chips, peers of plain text.
//
// Serialized form (what annotations.jsonl / submission.json carry):
//     "extrude [face:34](face:34) then [fillet](op:fillet) the seam"
// i.e. every chip renders as `[label](token)`; tokens are canonical entity
// ids (`face:6`) or operation ids (`op:fillet`).
//
// IME safety: Enter during composition (isComposing / keyCode 229) commits
// the candidate, never the annotation — the classic CJK-input submit bug.

export type ComposerTokenKind = 'face' | 'edge' | 'vertex' | 'body' | 'op';

export type ComposerToken = {
  token: string;
  label: string;
  kind: ComposerTokenKind;
  category?: string;
};

export type TokenComposerOptions = {
  placeholder?: string;
  /** Replaces the default `re-composer-input` host class (keep that class
   *  name when styling externally — the empty-state placeholder targets it). */
  hostClassName?: string;
  onChange?: () => void;
  onCommit?: () => void;
  /** Runs before built-in key handling; return true to consume the key. */
  onKeydown?: (event: KeyboardEvent) => boolean;
};

const KIND_GLYPH: Record<ComposerTokenKind, string> = {
  face: 'F',
  edge: 'E',
  vertex: 'V',
  body: 'B',
  op: 'OP',
};

function escapeAttributeValue(value: string): string {
  return value.replace(/["\\]/g, '\\$&');
}

export class TokenComposer {
  readonly host: HTMLDivElement;
  private composing = false;
  private readonly options: TokenComposerOptions;

  constructor(options: TokenComposerOptions = {}) {
    this.options = options;
    this.host = document.createElement('div');
    this.host.className = options.hostClassName ?? 're-composer-input';
    this.host.contentEditable = 'true';
    this.host.role = 'textbox';
    this.host.ariaMultiLine = 'true';
    this.host.ariaLabel = options.placeholder ?? 'annotation composer';
    this.host.dataset.placeholder = options.placeholder ?? '';
    this.host.dataset.empty = 'true';
    this.host.addEventListener('compositionstart', () => {
      this.composing = true;
    });
    this.host.addEventListener('compositionend', () => {
      this.composing = false;
      this.notifyChange();
    });
    this.host.addEventListener('input', () => this.notifyChange());
    this.host.addEventListener('keydown', (event) => this.handleKeydown(event));
    this.host.addEventListener('paste', (event) => this.handlePaste(event));
  }

  focus(): void {
    this.host.focus();
  }

  /** Runs the commit callback (Enter behavior) — for external submit buttons. */
  commit(): void {
    this.options.onCommit?.();
  }

  // Chips may repeat — an annotation can cite the same operation tip twice
  // ("[fillet] before [chamfer], but keep [fillet] at R2"). Entity chips stay
  // unique because the click path dedupes through its selection draft before
  // calling here; this class is a dumb chip editor, not a semantics police.

  insertToken(token: ComposerToken): void {
    if (!token.token) return;
    const chip = this.buildChip(token);
    const space = document.createTextNode(' ');
    const range = this.caretRange();
    if (range) {
      range.deleteContents();
      range.insertNode(space);
      this.host.insertBefore(chip, space);
      const after = document.createRange();
      after.setStartAfter(space);
      after.collapse(true);
      this.placeRange(after);
    } else {
      this.host.append(chip, space);
    }
    this.notifyChange();
  }

  removeToken(token: string): boolean {
    if (!token) return false;
    const chip = this.host.querySelector<HTMLElement>(`[data-token="${escapeAttributeValue(token)}"]`);
    if (!chip) return false;
    return this.removeChip(chip);
  }

  listTokens(): ComposerToken[] {
    return Array.from(this.host.querySelectorAll<HTMLElement>('span.re-token')).map((chip) => ({
      token: chip.dataset.token ?? '',
      label: chip.dataset.label ?? chip.dataset.token ?? '',
      kind: (chip.dataset.kind as ComposerTokenKind | undefined) ?? 'face',
      category: chip.dataset.category || undefined,
    }));
  }

  /** Serialized content: plain text with every chip as `[label](token)`. */

  value(): string {
    const parts: string[] = [];
    const walk = (node: Node): void => {
      if (node instanceof Text) {
        parts.push(node.data);
        return;
      }
      if (node instanceof HTMLBRElement) {
        parts.push('\n');
        return;
      }
      if (node instanceof HTMLElement && node.classList.contains('re-token')) {
        const token = node.dataset.token ?? '';
        parts.push(`[${node.dataset.label ?? token}](${token})`);
        return;
      }
      node.childNodes.forEach(walk);
    };
    this.host.childNodes.forEach(walk);
    return parts.join('');
  }

  isEmpty(): boolean {
    return this.value().trim() === '';
  }

  clear(): void {
    this.host.replaceChildren();
    this.notifyChange();
  }

  // -- internals -------------------------------------------------------------

  private buildChip(token: ComposerToken): HTMLSpanElement {
    const chip = document.createElement('span');
    const kindClasses: Record<ComposerTokenKind, string> = {
      face: 'text-[#a8cdf5] border-[#33587e] bg-[rgb(79_156_240_/_0.13)]',
      edge: 'text-[#a9e2bd] border-[#2f5c42] bg-[rgb(79_197_122_/_0.13)]',
      vertex: 'text-[#f2c4a3] border-[#7c5232] bg-[rgb(224_129_79_/_0.13)]',
      body: 'text-[#e7d5a8] border-[#79622f] bg-[rgb(201_162_79_/_0.13)]',
      op: ({
        sketch: 'text-[#a8e0da] border-[#2f5c57] bg-[rgb(69_184_173_/_0.12)]',
        boolean: 'text-[#cdd3dd] border-[#4a5462] bg-[rgb(148_163_184_/_0.13)]',
        solid: 'text-[#b9c8ee] border-[#3c4d7e] bg-[rgb(122_148_212_/_0.12)]',
        primitive: 'text-[#e6d3ab] border-[#6f5c33] bg-[rgb(206_170_96_/_0.13)]',
        modify: 'text-[#eeb9c3] border-[#7e3c4a] bg-[rgb(212_122_138_/_0.13)]',
        surface: 'text-[#d3c4ee] border-[#4c3a7e] bg-[rgb(157_122_212_/_0.12)]',
        pattern: 'text-[#e6bce6] border-[#6b3a6b] bg-[rgb(196_111_196_/_0.12)]',
      }[token.category ?? ''] ?? 'text-ink border-edge bg-inset'),
    };
    chip.className = `inline-flex items-center gap-1 mx-px rounded-full border px-[7px] text-[9px] leading-[1.7] align-baseline select-all whitespace-nowrap ${kindClasses[token.kind]}`;
    chip.contentEditable = 'false';
    chip.dataset.token = token.token;
    chip.dataset.label = token.label;
    chip.dataset.kind = token.kind;
    if (token.category) chip.dataset.category = token.category;
    chip.title = token.token;
    const glyph = document.createElement('span');
    glyph.className = 'font-mono text-[8px] font-bold leading-none tracking-[0.04em] opacity-85';
    glyph.textContent = KIND_GLYPH[token.kind];
    const label = document.createElement('span');
    label.className = 'font-mono';
    label.textContent = token.label;
    chip.append(glyph, label);
    return chip;
  }

  private handleKeydown(event: KeyboardEvent): void {
    if (this.options.onKeydown?.(event)) return;
    if (this.composing || event.isComposing || event.keyCode === 229) return;
    if (event.key === 'Enter') {
      event.preventDefault();
      if (event.shiftKey) this.insertText('\n');
      else this.options.onCommit?.();
      return;
    }
    if (event.key === 'Backspace' && this.deleteChipBeforeCaret()) event.preventDefault();
  }

  private handlePaste(event: ClipboardEvent): void {
    event.preventDefault();
    const text = event.clipboardData?.getData('text/plain') ?? '';
    this.insertText(text.replace(/\r\n?/g, '\n'));
  }

  private insertText(text: string): void {
    if (!text) return;
    if (!this.caretRange()) this.placeCaretAtEnd();
    document.execCommand('insertText', false, text);
    this.notifyChange();
  }

  /** Delete the whole chip when backspacing right after it (atomic chips).
   *  Removes the exact element before the caret — with duplicate chips
   *  allowed, a token-keyed lookup could delete the wrong occurrence. */

  private deleteChipBeforeCaret(): boolean {
    const selection = window.getSelection();
    if (!selection || !selection.isCollapsed || selection.rangeCount === 0) return false;
    const range = selection.getRangeAt(0);
    if (range.startContainer === this.host) {
      const previous = this.host.childNodes[range.startOffset - 1];
      if (previous instanceof HTMLElement && previous.classList.contains('re-token')) {
        return this.removeChip(previous);
      }
      return false;
    }
    if (range.startContainer instanceof Text && range.startOffset === 0) {
      const previous = range.startContainer.previousSibling;
      if (previous instanceof HTMLElement && previous.classList.contains('re-token')) {
        return this.removeChip(previous);
      }
    }
    return false;
  }

  private removeChip(chip: Element): boolean {
    const next = chip.nextSibling;
    chip.remove();
    if (next instanceof Text && next.data.startsWith(' ')) {
      next.data = next.data.slice(1);
      if (!next.data) next.remove();
    }
    this.notifyChange();
    return true;
  }

  private caretRange(): Range | null {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;
    const range = selection.getRangeAt(0);
    if (this.host.contains(range.commonAncestorContainer)) return range;
    return null;
  }

  private placeCaretAtEnd(): void {
    const range = document.createRange();
    range.selectNodeContents(this.host);
    range.collapse(false);
    this.placeRange(range);
  }

  private placeRange(range: Range): void {
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }

  private notifyChange(): void {
    this.host.dataset.empty = this.isEmpty() ? 'true' : 'false';
    this.options.onChange?.();
  }
}
