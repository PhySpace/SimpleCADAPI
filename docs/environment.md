# Environment switches

The SDK reads these variables. The first group are kill switches for the editor's speed-ups: each turns one of them
off, to tell a speed-up from a bug (a result that differs with the switch set is a bug; please report it).

| Variable | Effect |
|---|---|
| `SCA_NO_CELL_MEMORY=1` | The editor kernel does not keep what its cells made; every restore reads the disk cache. |
| `SCA_NO_USE_MEMO=1` | `use()` runs the child notebook each time instead of handing out the product of its last run. |
| `SCA_NO_PREVIEW_WARM=1` | Parts are not tessellated in the background while the next cell computes. |
| `SCA_NO_KERNEL_CACHE=1` | The editor kernel's cells are not cached. |
| `SCA_NO_DIAGNOSTIC_RENDER=1` | A failed operation does not render its diagnostic picture. |

| Variable | Effect |
|---|---|
| `SCA_WRAPPED=native\|ocp` | What `shape.wrapped` returns. Default: an OCP shape when OCP is installed (the `verify` extra), else the SDK's own OCCT shape. Read on each access. |
| `SCA_EDITOR_TRACE=1` | The editor prints how long each step of a settle takes, and what the cache did with each cell. |
| `SCA_EDITOR_TRACE_FILE=<path>` | With `SCA_EDITOR_TRACE`, write the trace there instead of stderr. |
| `SCA_EDITOR_CALL_TIMEOUT`, `SCA_EDITOR_OPEN_WAIT` | Seconds the editor waits for a kernel call / for the page to open. |
| `SCA_JOBS` | Worker processes for building child notebooks ahead of `use()`. |
| `SCA_DIAGNOSTIC_RENDER_BUDGET` | Seconds a failure's diagnostic render may take. |
| `SCA_RUNTIME_DIR`, `SCA_ADDON_DIR`, `SCA_ADDON_HOME`, `SCA_SKILLS_DIR`, `SCA_TARGET` | Where the runtime state, add-ons, skills and the install target live. |

A handled failure that must still be seen prints a `[sca] ...` line on stderr; nothing is swallowed silently.
