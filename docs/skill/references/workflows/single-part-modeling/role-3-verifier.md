# Single-Part Modeling: Role 3, Verifier Planner

Outline: `workflows/single-part-modeling.md`. Check patterns and the isolated image review: `workflows/single-part-modeling/verifier-contract-patterns.md`.
The per-host loop and TODO state machine for this role: `workflows/single-part-modeling/role-3-host-bindings.md` (read it when Role 3 starts).

## Role 3 — Verifier Planner

Role 3 runs before every stage's modeling work and owns the stage's
verification contract. It is the modeling equivalent of writing tests before
implementation.

For the current `S` stage, in order:

1. Identify the stage output: name the substructure that must be complete,
   its datum/coordinate relationship, and the existing geometry it may touch.
   State what is deliberately out of scope until later stages.
2. Translate the requirements into acceptance criteria for that output:
   dimensions and tolerances; required faces, holes, axes, or features;
   interfaces and fit with already-built geometry; collision and clearance;
   fastener insertion and tool access; assembly reachability; demolding or
   manufacturing access when relevant; absence of unintended interference;
   BREP validity and single-solid expectations. Include visual criteria when
3. Turn every criterion into a deterministic check. Iterate through small
   hypothesis code snippets or probes in the available execution environment:
   deliberately good and bad probes must show that the proposed measurement,
   collision test, topology query, or visual review contract distinguishes pass
   from fail. Reject a check that merely prints a plausible value without
   testing the requirement.
4. Produce the executable verification script or function for this stage,
   including explicit pass/fail assertions, named measurements, and small
   evidence prints. Append to `BUILD_PLAN.md`:
   `Verifier contract: <output> / Criteria: <...> / Script: <path or symbol>`
   plus the hypothesis results and known-bad proof.
5. Update TODO before modeling: complete the current `plan verifier` item
   after the contract, executable check, hypothesis evidence, and known-bad
   proof are recorded. The `model` item may then start. After Role 4 produces
   the stage result, start `run verifier` and execute the exact prepared
   function or script against that result; only its passing output closes the
   stage.

Role 3 may prepare visual verification here. It defines named render views,
close-ups, comparison regions, and the structured verdict required from an
isolated reviewer. It does not treat a render it produced as its own visual
acceptance.
**Unattended:** the visual contract is still written before Role 4 builds (views, close-ups, regions, verdict fields). The
review is a fresh-context check against that written contract (a subagent if the host offers one), quoting what was
observed; if neither is possible the report says the review was not independent. A visual verdict still comes from outside
the context that produced the render, or is reported as not independent; it never comes from the model's own say-so.

