import { defaultKeymap } from '@codemirror/commands';
import { python } from '@codemirror/lang-python';
import { defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { Decoration, DecorationSet, EditorView, keymap, lineNumbers } from '@codemirror/view';
import { EditorState, Extension, StateEffect, StateField } from '@codemirror/state';
import { oneDark, oneDarkHighlightStyle } from '@codemirror/theme-one-dark';

export type SourceLocation = {
  path?: string | null;
  line: number;
  end_line: number;
};

type SourceDockOptions = {
  dock: HTMLElement;
  resizer: HTMLElement;
  fileListResizer: HTMLElement;
  fileList: HTMLElement;
  fileCount: HTMLElement;
  activePath: HTMLElement;
  editorHost: HTMLElement;
  emptyState: HTMLElement;
  toggleButton: HTMLButtonElement;
  closeButton: HTMLButtonElement;
  workspace: HTMLElement;
  minHeight?: number;
  maxHeight?: number;
  defaultHeight?: number;
  desktopMedia?: string;
  minFileListWidth?: number;
  maxFileListWidth?: number;
  defaultFileListWidth?: number;
};


type HighlightRange = { startLine: number; endLine: number } | null;

const setHighlight = StateEffect.define<HighlightRange>();
const highlightedLine = Decoration.line({ class: 'cm-source-line-active' });
const highlightField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    value = value.map(transaction.changes);
    for (const effect of transaction.effects) {
      if (!effect.is(setHighlight)) continue;
      if (!effect.value) return Decoration.none;
      const decorations = [];
      const start = Math.max(1, Math.min(effect.value.startLine, transaction.state.doc.lines));
      const end = Math.max(start, Math.min(effect.value.endLine, transaction.state.doc.lines));
      for (let lineNumber = start; lineNumber <= end; lineNumber += 1) {
        decorations.push(highlightedLine.range(transaction.state.doc.line(lineNumber).from));
      }
      return Decoration.set(decorations);
    }
    return value;
  },
  provide: (field) => EditorView.decorations.from(field),
});

const sharedExtensions: Extension[] = [
  lineNumbers(),
  keymap.of(defaultKeymap),
  python(),
  highlightField,
  EditorState.readOnly.of(true),
  EditorView.editable.of(false),
  EditorView.theme({
    '&': { height: '100%' },
    '.cm-scroller': { overflow: 'auto', fontFamily: "'DM Mono', ui-monospace, monospace" },
    '.cm-content': { minHeight: '100%' },
  }),
];

const defaultTheme: Extension[] = [
  syntaxHighlighting(defaultHighlightStyle),
  syntaxHighlighting(oneDarkHighlightStyle),
  oneDark,
];

export type PythonEditorOptions = {
  parent: HTMLElement;
  content?: string;
  /** Replaces the default oneDark pairing; used by the re-studio dock. */
  theme?: Extension[];
};

/** Read-only CodeMirror 6 Python view with line-range highlighting. */
export class PythonEditor {
  readonly view: EditorView;

  constructor(options: PythonEditorOptions) {
    this.view = new EditorView({
      state: EditorState.create({
        doc: options.content ?? '',
        extensions: [...sharedExtensions, ...(options.theme ?? defaultTheme)],
      }),
      parent: options.parent,
    });
  }

  setContent(content: string): void {
    this.view.dispatch({
      changes: { from: 0, to: this.view.state.doc.length, insert: content },
      effects: setHighlight.of(null),
    });
  }

  revealLines(startLine: number, endLine: number): void {
    const start = Math.max(1, Math.min(startLine, this.view.state.doc.lines));
    const end = Math.max(start, Math.min(endLine, this.view.state.doc.lines));
    const effects: StateEffect<unknown>[] = [setHighlight.of({ startLine: start, endLine: end })];
    effects.push(EditorView.scrollIntoView(this.view.state.doc.line(start).from, { y: 'center' }));
    this.view.dispatch({ effects });
  }

  clearHighlight(): void {
    this.view.dispatch({ effects: setHighlight.of(null) });
  }

  requestMeasure(): void {
    this.view.requestMeasure();
  }
}

export class SourceDock {
  private readonly files = new Map<string, string>();
  private readonly rows = new Map<string, HTMLButtonElement>();
  private readonly media: MediaQueryList;
  private readonly editor: PythonEditor;
  private activeFilePath: string | null = null;
  private currentHighlight: HighlightRange = null;
  private dockHeight: number;
  private fileListWidth: number;

  constructor(private readonly options: SourceDockOptions) {
    this.media = window.matchMedia(options.desktopMedia ?? '(min-width: 901px)');
    this.dockHeight = options.defaultHeight ?? 300;
    this.fileListWidth = options.defaultFileListWidth ?? 148;
    this.editor = new PythonEditor({ parent: options.editorHost });
    options.toggleButton.addEventListener('click', () => this.setOpen(options.dock.hidden));
    options.closeButton.addEventListener('click', () => this.setOpen(false));
    this.bindHeightResize();
    this.bindFileListResize();
    this.syncLayout();
  }

  clear(): void {
    this.files.clear();
    this.rows.clear();
    this.activeFilePath = null;
    this.currentHighlight = null;
    this.options.fileList.replaceChildren();
    this.options.fileCount.textContent = '0';
    this.options.activePath.textContent = 'No source file selected';
    this.options.emptyState.hidden = false;
    this.editor.setContent('');
    this.options.toggleButton.disabled = true;
    this.setOpen(false);
  }

  setFiles(files: ReadonlyMap<string, string>): void {
    this.files.clear();
    for (const [path, content] of [...files].sort(([left], [right]) => left.localeCompare(right))) {
      this.files.set(path, content);
    }
    this.renderFiles();
    this.options.fileCount.textContent = String(this.files.size);
    this.options.toggleButton.disabled = this.files.size === 0;
    if (this.files.size === 0) {
      this.activeFilePath = null;
      this.options.activePath.textContent = 'No embedded source files';
      this.options.emptyState.hidden = false;
      this.editor.setContent('');
      this.setOpen(false);
      return;
    }
    this.showFile(this.files.keys().next().value as string);
  }

  reveal(location: SourceLocation): void {
    if (!location.path || !this.files.has(location.path)) return;
    this.setOpen(true);
    this.showFile(location.path, {
      startLine: Math.max(1, location.line),
      endLine: Math.max(location.line, location.end_line),
    });
  }

  private replaceDocument(content: string): void {
    this.editor.setContent(content);
  }

  private showFile(path: string, highlight: HighlightRange = null): void {
    const content = this.files.get(path);
    if (content === undefined) return;
    if (path !== this.activeFilePath) {
      this.activeFilePath = path;
      this.replaceDocument(content);
    }
    this.currentHighlight = highlight;
    if (highlight) {
      this.editor.revealLines(highlight.startLine, highlight.endLine);
    } else {
      this.editor.clearHighlight();
    }
    this.options.activePath.textContent = path;
    this.options.emptyState.hidden = true;
    for (const [rowPath, row] of this.rows) {
      const selected = rowPath === path;
      row.classList.toggle('selected', selected);
      row.setAttribute('aria-selected', String(selected));
    }
  }

  private renderFiles(): void {
    this.rows.clear();
    this.options.fileList.replaceChildren();
    for (const path of this.files.keys()) {
      const row = document.createElement('button');
      row.className = 'source-file-row';
      row.type = 'button';
      row.dataset.sourcePath = path;
      row.setAttribute('role', 'option');
      const basename = path.split('/').pop() || path;
      const directory = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '.';
      row.innerHTML = `<span class="source-file-name">${escapeHtml(basename)}</span><span class="source-file-directory">${escapeHtml(directory)}</span>`;
      row.addEventListener('click', () => this.showFile(path));
      this.options.fileList.append(row);
      this.rows.set(path, row);
    }
  }

  private setOpen(open: boolean): void {
    const available = this.files.size > 0;
    const nextOpen = open && available;
    this.options.dock.hidden = !nextOpen;
    this.options.resizer.hidden = !nextOpen;
    this.options.toggleButton.classList.toggle('active', nextOpen);
    this.options.toggleButton.setAttribute('aria-expanded', String(nextOpen));
    this.syncLayout();
    if (nextOpen) {
      requestAnimationFrame(() => {
        this.editor.requestMeasure();
        if (this.currentHighlight) this.showFile(this.activeFilePath!, this.currentHighlight);
      });
    }
  }

  private syncLayout(): void {
    const open = !this.options.dock.hidden && this.files.size > 0;
    this.options.workspace.classList.toggle('source-dock-open', open);
    this.options.dock.style.setProperty('--source-files-width', `${this.fileListWidth}px`);
    this.options.workspace.style.setProperty('--source-dock-height', open && this.media.matches ? `${this.dockHeight}px` : '0px');
  }

  private bindHeightResize(): void {
    const { resizer, workspace } = this.options;
    resizer.addEventListener('pointerdown', (event) => {
      if (!this.media.matches || resizer.hidden) return;
      event.preventDefault();
      const startY = event.clientY;
      const startHeight = this.options.dock.getBoundingClientRect().height;
      const minHeight = this.options.minHeight ?? 160;
      const maxHeight = Math.min(this.options.maxHeight ?? 620, Math.max(minHeight, workspace.clientHeight - 180));
      resizer.classList.add('dragging');
      document.body.classList.add('resizing-dock');
      resizer.setPointerCapture(event.pointerId);
      const move = (moveEvent: PointerEvent): void => {
        this.dockHeight = Math.max(minHeight, Math.min(maxHeight, startHeight + startY - moveEvent.clientY));
        this.syncLayout();
      };
      const finish = (): void => {
        resizer.classList.remove('dragging');
        document.body.classList.remove('resizing-dock');
        resizer.removeEventListener('pointermove', move);
        resizer.removeEventListener('pointerup', finish);
        resizer.removeEventListener('pointercancel', finish);
        this.editor.requestMeasure();
      };
      resizer.addEventListener('pointermove', move);
      resizer.addEventListener('pointerup', finish);
      resizer.addEventListener('pointercancel', finish);
    });
    const resizeObserver = new ResizeObserver(() => this.syncLayout());
    resizeObserver.observe(workspace);
  }

  private bindFileListResize(): void {
    const { dock, fileListResizer } = this.options;
    fileListResizer.addEventListener('pointerdown', (event) => {
      if (!this.media.matches || dock.hidden) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = this.fileListWidth;
      const minWidth = this.options.minFileListWidth ?? 112;
      const maxWidth = Math.min(this.options.maxFileListWidth ?? 360, Math.max(minWidth, dock.clientWidth - 280));
      fileListResizer.classList.add('dragging');
      document.body.classList.add('resizing-panels');
      fileListResizer.setPointerCapture(event.pointerId);
      const move = (moveEvent: PointerEvent): void => {
        this.fileListWidth = Math.max(minWidth, Math.min(maxWidth, startWidth + moveEvent.clientX - startX));
        dock.style.setProperty('--source-files-width', `${this.fileListWidth}px`);
        this.editor.requestMeasure();
      };
      const finish = (): void => {
        fileListResizer.classList.remove('dragging');
        document.body.classList.remove('resizing-panels');
        fileListResizer.removeEventListener('pointermove', move);
        fileListResizer.removeEventListener('pointerup', finish);
        fileListResizer.removeEventListener('pointercancel', finish);
      };
      fileListResizer.addEventListener('pointermove', move);
      fileListResizer.addEventListener('pointerup', finish);
      fileListResizer.addEventListener('pointercancel', finish);
    });
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character] || character);
}
