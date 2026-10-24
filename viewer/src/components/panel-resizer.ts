type PanelSide = 'navigator' | 'inspector';

type ResizablePanelsOptions = {
  workspace: HTMLElement;
  navigatorPanel: HTMLElement;
  inspectorPanel: HTMLElement;
  navigatorResizer: HTMLElement;
  inspectorResizer: HTMLElement;
  minNavigatorWidth?: number;
  maxNavigatorWidth?: number;
  minInspectorWidth?: number;
  maxInspectorWidth?: number;
  minCenterWidth?: number;
  gutterWidth?: number;
  desktopMedia?: string;
};

export function bindResizablePanels(options: ResizablePanelsOptions): () => void {
  const {
    workspace,
    navigatorPanel,
    inspectorPanel,
    navigatorResizer,
    inspectorResizer,
    minNavigatorWidth = 180,
    maxNavigatorWidth = 520,
    minInspectorWidth = 230,
    maxInspectorWidth = 620,
    minCenterWidth = 320,
    gutterWidth = 14,
    desktopMedia = '(min-width: 901px)',
  } = options;
  const media = window.matchMedia(desktopMedia);
  const cleanups: Array<() => void> = [];

  const panelFor = (side: PanelSide): HTMLElement => side === 'navigator' ? navigatorPanel : inspectorPanel;
  const otherPanelFor = (side: PanelSide): HTMLElement => side === 'navigator' ? inspectorPanel : navigatorPanel;
  const resizerFor = (side: PanelSide): HTMLElement => side === 'navigator' ? navigatorResizer : inspectorResizer;

  const setWidth = (side: PanelSide, requestedWidth: number): void => {
    if (!media.matches) return;
    const minimum = side === 'navigator' ? minNavigatorWidth : minInspectorWidth;
    const configuredMaximum = side === 'navigator' ? maxNavigatorWidth : maxInspectorWidth;
    const available = workspace.getBoundingClientRect().width
      - otherPanelFor(side).getBoundingClientRect().width
      - minCenterWidth
      - gutterWidth;
    const maximum = Math.max(minimum, Math.min(configuredMaximum, available));
    const width = Math.round(Math.max(minimum, Math.min(maximum, requestedWidth)));
    workspace.style.setProperty(side === 'navigator' ? '--navigator-width' : '--inspector-width', `${width}px`);
    const resizer = resizerFor(side);
    resizer.setAttribute('aria-valuemin', String(minimum));
    resizer.setAttribute('aria-valuemax', String(maximum));
    resizer.setAttribute('aria-valuenow', String(width));
  };

  const bind = (side: PanelSide): void => {
    const resizer = resizerFor(side);
    const onPointerDown = (event: PointerEvent): void => {
      if (event.button !== 0 || !media.matches) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = panelFor(side).getBoundingClientRect().width;
      resizer.setPointerCapture(event.pointerId);
      resizer.classList.add('dragging');
      document.body.classList.add('resizing-panels');

      const onPointerMove = (moveEvent: PointerEvent): void => {
        const delta = moveEvent.clientX - startX;
        setWidth(side, startWidth + (side === 'navigator' ? delta : -delta));
      };
      const finish = (): void => {
        resizer.classList.remove('dragging');
        document.body.classList.remove('resizing-panels');
        resizer.removeEventListener('pointermove', onPointerMove);
        resizer.removeEventListener('pointerup', finish);
        resizer.removeEventListener('pointercancel', finish);
      };
      resizer.addEventListener('pointermove', onPointerMove);
      resizer.addEventListener('pointerup', finish);
      resizer.addEventListener('pointercancel', finish);
    };
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const currentWidth = panelFor(side).getBoundingClientRect().width;
      setWidth(side, currentWidth + direction * (side === 'navigator' ? 12 : -12));
    };
    resizer.addEventListener('pointerdown', onPointerDown);
    resizer.addEventListener('keydown', onKeyDown);
    cleanups.push(() => resizer.removeEventListener('pointerdown', onPointerDown));
    cleanups.push(() => resizer.removeEventListener('keydown', onKeyDown));
  };

  bind('navigator');
  bind('inspector');
  setWidth('navigator', navigatorPanel.getBoundingClientRect().width);
  setWidth('inspector', inspectorPanel.getBoundingClientRect().width);

  const resizeObserver = new ResizeObserver(() => {
    if (!media.matches) return;
    setWidth('navigator', navigatorPanel.getBoundingClientRect().width);
    setWidth('inspector', inspectorPanel.getBoundingClientRect().width);
  });
  resizeObserver.observe(workspace);
  cleanups.push(() => resizeObserver.disconnect());

  return () => cleanups.forEach((cleanup) => cleanup());
}
