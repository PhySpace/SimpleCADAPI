import type { AgentClient, RpcError } from './client';

type RpcResponse<T> = { jsonrpc: '2.0'; id: number; result?: T; error?: RpcError };

export class AgentSessionError extends Error {
  readonly code: number;
  readonly data: unknown;

  constructor(error: RpcError) {
    super(error.message);
    this.name = 'AgentSessionError';
    this.code = error.code;
    this.data = error.data;
  }
}

/** Browser transport for the Web Editor session.
 *
 * HTTP JSON-RPC is the current adapter. The UI only depends on AgentClient,
 * so a WebSocket or ACP bridge can replace this transport later.
 */
export class AgentSession implements AgentClient {
  private nextId = 1;

  constructor(private readonly endpoint = '/rpc') {}

  async call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: this.nextId++, method, params }),
    });
    const payload = (await response.json()) as RpcResponse<T>;
    if (!response.ok || payload.error) {
      throw new AgentSessionError(payload.error ?? { code: response.status, message: response.statusText });
    }
    return payload.result as T;
  }

  getSession<T>(): Promise<T> {
    return this.call<T>('session.get');
  }

  listOperations<T>(): Promise<T> {
    return this.call<T>('operations.list');
  }

  getScene<T>(): Promise<T> {
    return this.call<T>('scene.original');
  }

  describeEntity<T>(id: string): Promise<T> {
    return this.call<T>('entity.describe', { id });
  }

  resolveRegion<T>(camera: unknown, polygon: unknown): Promise<T> {
    return this.call<T>('region.resolve', { camera, polygon });
  }

  getSubmission<T>(): Promise<T> {
    return this.call<T>('submission.get');
  }

  createSubmission<T>(params: Record<string, unknown>): Promise<T> {
    return this.call<T>('submission.create', params);
  }

  recordAnnotation<T>(params: Record<string, unknown>): Promise<T> {
    return this.call<T>('annotation.record', params);
  }

  recordEvent<T>(params: Record<string, unknown>): Promise<T> {
    return this.call<T>('event.record', params);
  }
}
