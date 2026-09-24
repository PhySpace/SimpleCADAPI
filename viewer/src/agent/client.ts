export type RpcError = { code: number; message: string; data?: unknown };

export interface AgentClient {
  call<T>(method: string, params?: Record<string, unknown>): Promise<T>;
  getSession<T>(): Promise<T>;
  getScene<T>(): Promise<T>;
  describeEntity<T>(id: string): Promise<T>;
  resolveRegion<T>(camera: unknown, polygon: unknown): Promise<T>;
  listOperations<T>(): Promise<T>;
  getSubmission<T>(): Promise<T>;
  createSubmission<T>(params: Record<string, unknown>): Promise<T>;
  recordAnnotation<T>(params: Record<string, unknown>): Promise<T>;
  recordEvent<T>(params: Record<string, unknown>): Promise<T>;
}
