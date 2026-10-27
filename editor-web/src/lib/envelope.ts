/** Live event socket: server-pushed model envelopes over /ws.
 *
 * Envelope types (workspace_server.replay order): params.schema,
 * params.values, geometry, tree, notebook.cells, notebook.features,
 * package, selection, status, hello.
 */

export type Envelope = Record<string, unknown> & { type: string };

/** A binary frame is a `preview` envelope and the preview itself: `<u32 big-endian N><N bytes JSON><preview bytes>`
 *  (`simplecadapi.editor.ws.preview_frame`).  The envelope handed to handlers carries the preview as `bytes`. */
function decodeFrame(buffer: ArrayBuffer): Envelope | null {
  if (buffer.byteLength < 4) return null;
  const length = new DataView(buffer).getUint32(0, false);
  if (buffer.byteLength < 4 + length) return null;
  try {
    const envelope = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, length))) as Envelope;
    envelope["bytes"] = buffer.slice(4 + length);
    return envelope;
  } catch {
    return null;
  }
}
type Handler = (envelope: Envelope) => void;

export class EnvelopeSocket {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private backoffMs = 500;
  private closed = false;

  constructor(private readonly url: string) {}

  on(type: string, handler: Handler): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler);
    return () => set!.delete(handler);
  }

  connect(): void {
    this.closed = false;
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.backoffMs = 500;
    };
    ws.onmessage = (event) => {
      let envelope: Envelope | null;
      if (event.data instanceof ArrayBuffer) {
        envelope = decodeFrame(event.data);
      } else {
        try {
          envelope = JSON.parse(String(event.data));
        } catch {
          return;
        }
      }
      if (!envelope) return;
      const set = this.handlers.get(envelope.type);
      if (set) for (const handler of set) handler(envelope);
      const anySet = this.handlers.get("*");
      if (anySet) for (const handler of anySet) handler(envelope);
    };
    ws.onclose = () => {
      if (this.closed) return;
      // Kernel/server restarts must transparently re-attach the UI.
      setTimeout(() => this.connect(), this.backoffMs);
      this.backoffMs = Math.min(this.backoffMs * 2, 8000);
    };
  }

  /** Send one ui command (param.set / export.request / code.edit / rerun.request). */
  send(message: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
