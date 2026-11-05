/** The mouse wheel scrolls a `scroll-row` (a one-line row of buttons, see index.css) sideways: a vertical wheel turn over
 * a row that overflows moves it left and right, as a trackpad's sideways swipe already does. */
export function installScrollRows(root: Document = document): () => void {
  const onWheel = (event: WheelEvent) => {
    if (event.ctrlKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    const row = (event.target as Element | null)?.closest?.(".scroll-row") as HTMLElement | null;
    if (!row || row.scrollWidth <= row.clientWidth) return;
    const before = row.scrollLeft;
    row.scrollLeft += event.deltaY;
    if (row.scrollLeft !== before) event.preventDefault();
  };
  root.addEventListener("wheel", onWheel, { passive: false });
  return () => root.removeEventListener("wheel", onWheel);
}
