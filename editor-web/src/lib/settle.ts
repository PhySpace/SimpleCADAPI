/** How long a drag has to pause before its value is sent (ms). */
export const SETTLE_MS = 250;

/** Collect changes and send them once they settle.
 *
 * A slider reports every step of a drag, and each step the server is given
 * is a rebuild of the model.  `push` records the latest value of a key and
 * restarts the wait; the values go out together when `delay` ms pass without
 * another change (the drag paused), or at once on `flush` (the pointer was
 * released, a toggle was clicked).  Not a throttle: a drag that never pauses
 * sends nothing until it ends.
 */
export function createSettler<V>(delay: number, send: (values: Record<string, V>) => void) {
  const pending = new Map<string, V>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  const stop = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const flush = () => {
    stop();
    if (pending.size === 0) return;
    const values = Object.fromEntries(pending);
    pending.clear();
    send(values);
  };

  return {
    push(key: string, value: V) {
      pending.set(key, value);
      stop();
      timer = setTimeout(flush, delay);
    },
    flush,
    cancel() {
      stop();
      pending.clear();
    },
  };
}
