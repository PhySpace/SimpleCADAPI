/** REST surface of the runtime server (`sca edit <workspace>`).
 *
 * The WebSocket (`lib/envelope.ts`) carries live model events; these calls
 * cover discovery, control, and the agent-facing selection contract.
 */

export type NotebookRow = {
  name: string;
  path: string;
  entry: boolean;
  kind: "part" | "assembly" | "helper";
  current: boolean;
  /** Definition id from the notebook header. */
  id?: string;
  /** Notebooks this one runs with use(...), workspace-relative. */
  uses?: string[];
  error?: string | null;
};

export type SelectedInfo = {
  selected: Record<string, unknown>;
  notebook: string | null;
};

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}: ${body.slice(0, 200)}`);
  }
  return (await response.json()) as T;
}

/** Notebooks in the workspace with entry/helper classification. */
export function getWorkspace(): Promise<{ notebooks: NotebookRow[] }> {
  return fetch("/api/workspace").then((response) => json<{ notebooks: NotebookRow[] }>(response));
}

/** Switch the active entry notebook (server restarts the kernel). */
export function openNotebook(path: string): Promise<{ ok: boolean }> {
  return fetch("/api/workspace/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  }).then((response) => json<{ ok: boolean }>(response));
}

/** Provision a new entry notebook from the server template and open it. */
export function newNotebook(name: string, kind: "part" | "assembly"): Promise<{ created: string }> {
  return fetch("/api/workspace/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, kind }),
  }).then((response) => json<{ created: string }>(response));
}

/** Latest in-memory scadpkg bytes (rule 4: never a disk read). */
export async function fetchPackage(): Promise<Uint8Array> {
  const response = await fetch("/api/package/latest");
  if (!response.ok) throw new Error("no package published yet");
  return new Uint8Array(await response.arrayBuffer());
}

/** Publish the viewport selection so agents can read it. */
export function select(selection: Record<string, unknown>): Promise<{ ok: boolean }> {
  return fetch("/api/studio/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(selection),
  }).then((response) => json<{ ok: boolean }>(response));
}

/** Agent-facing read: what the human has selected right now. */
export function getSelected(): Promise<SelectedInfo> {
  return fetch("/api/studio/selected").then((response) => json<SelectedInfo>(response));
}
