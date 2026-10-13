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

/** A local module some notebook imports (shared dimensions, helpers). */
export type ModuleRow = { name: string; path: string; used_by: string[] };

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
export function getWorkspace(): Promise<{ notebooks: NotebookRow[]; modules: ModuleRow[] }> {
  return fetch("/api/workspace").then((response) => json<{ notebooks: NotebookRow[]; modules: ModuleRow[] }>(response));
}

/** Switch the active entry notebook (server restarts the kernel). */
export function openNotebook(path: string): Promise<{ ok: boolean }> {
  return fetch("/api/workspace/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  }).then((response) => json<{ ok: boolean }>(response));
}

/** Provision a new entry notebook from the server template and open it. Rejects with the server's reason (a bad or taken name). */
export async function newNotebook(name: string, kind: "part" | "assembly"): Promise<{ created: string }> {
  const response = await fetch("/api/workspace/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, kind }),
  });
  const body = (await response.json().catch(() => null)) as { created?: string; error?: string } | null;
  if (!response.ok || !body?.created) throw new Error(body?.error ?? `${response.status} ${response.statusText}`);
  return { created: body.created };
}

/** What the viewport shows (PNG data URL), for coding agents to look at. */
export async function postViewport(dataUrl: string): Promise<void> {
  const blob = await (await fetch(dataUrl)).blob();
  await fetch("/api/studio/viewport", { method: "POST", headers: { "Content-Type": "image/png" }, body: blob });
}

/** The latest preview of the model (`simplecadapi.scene.preview`). */
export async function fetchPreview(): Promise<ArrayBuffer> {
  const response = await fetch("/api/preview/latest");
  if (!response.ok) throw new Error("no preview published yet");
  return response.arrayBuffer();
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
