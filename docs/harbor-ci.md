# Harbor Hub CADIR benchmark

The Gitea workflow in `.gitea/workflows/harbor-ci.yaml` evaluates the checked-out CADIR commit against the public Harbor Hub dataset:

```text
au12321ua/cadir-ci-benchmark
```

The runner performs five operations:

1. checks out CADIR and installs `harbor==0.23.0`;
2. builds a content-addressed local runtime image from that checkout, with the
   requested Codex CLI version already installed;
3. runs `harbor run -d au12321ua/cadir-ci-benchmark` on the runner;
4. writes and uploads `.harbor-ci/`, including native Harbor jobs and the summary report;
5. removes the per-run runtime image tag while retaining Docker/BuildKit caches.

The artifact upload explicitly includes hidden files because the complete
benchmark output is rooted at `.harbor-ci/`. A missing output tree is treated as
an upload error instead of being silently ignored. The workflow currently uses
the pinned Node 20 build of the v3 artifact protocol from Gitea's action mirror;
the action source is external, but the runner-provided artifact endpoint keeps
the uploaded data on the CADIR Gitea instance. This avoids v4 `CreateArtifact`
connection resets seen on the self-hosted runner/reverse-proxy path.

Codex is installed while the runtime image is built, rather than during every
Harbor trial. The complete pinned npm installation is copied into the runtime,
including Node.js, the supported `codex` launcher, its platform package,
`codex-code-mode-host`, and bundled resources. Copying only the main native
binary is insufficient: `codex exec --enable unified_exec` needs the matching
Code Mode host, and other Codex features use additional package resources.
Harbor's agent setup has a six-minute default timeout; installing NVM, Node.js,
and Codex separately in each fresh task container can consume that entire
window and produce `AgentSetupTimeoutError` before the task starts. The
launcher resolves the generic `--agent-version` setting into both the image
build and the Harbor agent configuration, so Harbor's setup step only verifies
the matching preinstalled version. The agent name and version are also part of
the runtime image digest.

The runtime image is not pushed to Docker Hub. Harbor downloads the public task packages from Harbor Hub, then Docker executes the agent and separate verifier environments locally on the trusted runner.

## Runner requirements

- trusted Linux host runner labelled `cadir-ci`;
- Gitea Actions runner with the v3 artifact protocol enabled;
- Docker Engine with Compose v2;
- outbound access for uv, Harbor Hub, base images, Codex installation, and the selected model endpoint;
- enough disk for OCC/VTK and task images.

Configure Gitea repository variables. Empty or missing variables fall back to
the values shown here:

- `CADIR_CI_DATASET=au12321ua/cadir-ci-benchmark`;
- `CADIR_CI_AGENT=codex`;
- `CADIR_CI_AGENT_VERSION=0.155.1`;
- `CADIR_CI_N_CONCURRENT=1`: maximum number of trials running at once;
- `CADIR_CI_N_ATTEMPTS=1`: independent attempts per task;
- `CADIR_CI_MAX_RETRIES=0`: retries after a trial raises an exception.

`N_CONCURRENT` controls parallelism, not the total number of runs. Increasing
`N_ATTEMPTS` multiplies the number of trials (and model usage). `MAX_RETRIES`
applies to exceptional failures and does not rerun a completed trial just
because its score was low.

The external configuration uses generic agent names so another Harbor agent can
be added without changing the workflow contract. The runtime currently supports
only `codex`; any other `CADIR_CI_AGENT` value fails explicitly before a runtime
image is built.

Configure the model and endpoint as Gitea repository variables:

- `CADIR_CI_MODEL`;
- optional `CADIR_CI_OPENAI_BASE_URL`.

Configure the credential as a Gitea secret:

- `CADIR_CI_OPENAI_API_KEY`;

The model credential is inherited by Harbor at runtime and is not written to the Job JSON or report. The selected dataset, agent, agent version, concurrency, attempts, and retries are written to the report for traceability. The tracked workflow only runs on the protected `master` and `dev` refs because the checked-out code receives model secrets and controls Docker; do not broaden the trigger to untrusted branches.

If local use supplies `OPENAI_BASE_URL` only through `--env-file`, also pass its non-secret hostname with `--allow-agent-host <hostname>`. Automatic allowlisting can only inspect variables exported to the launcher process.

## Local run

After the dataset has been published, install Harbor. A Codex run uses
`BENCH_MODEL` and `OPENAI_API_KEY` from the environment and accepts the same
generic configuration as CI:

```bash
uv tool install harbor==0.23.0
export BENCH_MODEL='openai/<model-id>'
export OPENAI_API_KEY='...'
python -m tools.harbor_ci.run \
  --dataset au12321ua/cadir-ci-benchmark \
  --agent codex \
  --agent-version 0.155.1 \
  --n-concurrent 1 \
  --n-attempts 1 \
  --max-retries 0
```

Result semantics:

- `PASS`: every completed trial has reward 1;
- `FAIL`: valid scoring completed with at least one reward below 1;
- `ERROR`: missing/partial trials, verifier/agent infrastructure exceptions, or missing rewards.

`FAIL` is report-only by default. Add `--require-pass` after the benchmark is stable if scored failure should fail the workflow. `ERROR` always exits 2.
