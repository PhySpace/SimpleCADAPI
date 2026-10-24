# SimpleCAD Product Viewer

This browser-only viewer opens canonical `.scadpkg` product packages (package
schema 3.0) without importing SimpleCAD, Python, or OpenCascade. The loader
validates `package.json`, the exact member closure (`definitions/`,
`occurrences/root.json`, `blobs/`, `projections/scene/scene.json`), and the
embedded evaluated scene before parsing GLB or entity assets. It rejects older
package schemas, standalone Scene ZIPs, and any package with missing, extra,
length-mismatched, or hash-mismatched members. Product definition ZIPs and
feature-graph archives are integrity-checked as package blobs but never
re-packed, because the viewer renders exclusively from the scene projection.

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:5173/`, click **Open .scadpkg**, and select a package
written directly by the functional capture API:

```python
scad.capture(result, "out/product.scadpkg")
```

The same file can be dropped directly into the viewport.

The file picker accepts local `.scadpkg` product packages only. The viewer does
not load packages from URL query parameters or require a built-in case registry.

## Reverse-Engineering Studio (`re.html`)

The second entry, `re.html`, is the interactive reconstruction studio: a human
annotates a STEP target, an agent reconstructs from those annotations, and the
studio displays the rebuilt result next to the original. See
`docs/skill/references/workflows/reverse-engineering-studio.md` for the full
agent-side loop.

```bash
# from the repo root — binds 127.0.0.1:7170 and opens the studio
uv run python -m viewer.server <case_dir> --daemon
```

The case directory must contain the STEP target (`*.step`/`*.stp`); the server
synthesizes the same GLB + entity-sidecar scene projection packages carry, so
face/edge/vertex picking works identically on both sides. The rebuilt side
loads the agent's captured v3 `rebuilt.scadpkg` through the normal package
loader. During development, `npm run dev` proxies `/api` to the server port.

Annotation happens in a free-form composer: picked entities and operations land
as inline color-coded chips (serialized as `[face:12](face:12)` /
`[fillet](op:fillet)`) alongside plain text; type `/` for an operation
autocomplete. The operation registry is markdown — one file per tip in
`viewer/server/operations/` (frontmatter `label/category/api/reads/doc_refs` +
hint body), editable without code changes; referenced tips travel inside the
submission as `operation_context`. The rebuilt panel shows the package's feature
DAG and the syntax-highlighted, self-contained rebuild source with
feature-to-source line reveal.

Governance: the studio UI only selects and describes — it never edits geometry.
Only the browser writes `re_work/submission.json`; the agent waits on it via
`uv run python -m viewer.server <case_dir> --wait-only` and writes artifacts
(`rebuild.py`, `rebuilt.step`, `rebuilt.scadpkg`, `comparison.png`,
`evaluation.json`) that the UI polls. Every event lands in
`re_work/session.ndjson` as the training record.

## BRep Renderer Component (`src/renderer/`)

The presentation layer is a standalone component: `BRepRenderer` renders a
scene-2.0 package (the GLB faces + line edges + entity sidecars that both the
original STEP side and captured `.scadpkg` packages carry) with no dependency
on any host page. It provides image-based studio lighting (PMREM
`RoomEnvironment` + one key light), GTAO ambient occlusion (tuned to the
model's world scale on every fit), a free trackball camera (no rotational
poles, `FIT` restores the canonical Z-up and kills inertia), and CAD-style
edge display — edges tessellate tighter than faces, and seam/degenerate edges
are split into their own visuals and hidden by default.

```ts
import { BRepRenderer } from './renderer';

const viewer = new BRepRenderer(hostElement, { ssao: true, seams: false });
await viewer.loadScene(files);     // scene-2.0 files from a .scadpkg or the re-studio server
viewer.setSeamsVisible(false);     // toggle seam/degenerate edges
viewer.setEdgesVisible(true);
viewer.setSSAO(true);
viewer.frame();                    // canonical fit
```

Selection and annotation are deliberately out of scope: `src/scene-view.ts`
composes `BRepRenderer` and adds raycast picking (face/edge/vertex), selection
modes, and annotation marks. Embed `BRepRenderer` alone for read-only display;
build interaction layers on top of it.

## Inspecting A Product

The **Components** tab shows the evaluated occurrence hierarchy. Select an
occurrence to inspect its definition, visibility, and evaluated body data. The
visibility control on each row hides or shows that occurrence.

The **Features** tab federates the immutable feature DAGs embedded by every part
and nested assembly definition. Selecting a feature shows its operation,
definition-local identity, inputs, outputs, parameters, source spans, and linked
geometry. Connector and joint selections resolve through the package indexes to
the exact producing feature when that evidence exists.

The source panel lists the content-addressed source snapshots embedded by the
definition closure. Selecting a mapped feature opens the exact source asset,
scrolls to its recorded line range, and highlights that range without reading
files from the local machine.

Select components, solids, faces, edges, or vertices in the viewport to inspect
evaluated geometry and measurements. Geometry selections link back to the
feature DAG through stable definition, node, output-slot, and topology evidence.
