# Task Domain: Requirement Refinement

Convert a user request — prose, reference images, technical drawings, or a
combination — into an actionable modeling brief before any geometry is written.

**Read when:** every task starts here: any modeling, assembly, reconstruction, or export request is refined into a brief
first, and whenever inputs conflict, are ambiguous, or mix modalities.

## Use when

- Every task starts here: any modeling, assembly, reconstruction, or export
  request is refined into a brief first.
- Inputs conflict, are ambiguous, or mix modalities.

## Do not use

- As a user-facing form: the brief is internal Markdown notes; never ask the
  user to fill out a schema.
- As a substitute for asking the one focused question that actually blocks the
  work.

## The brief must answer

- What is being modeled: part, assembly, modification, inspection, or export
  task.
- Units and coordinate convention (SDK evaluates lengths in millimeters and
  angles in degrees while preserving declared units in model JSON).
- Overall dimensions and which missing dimensions are inferable.
- Required features: holes, slots, bosses, ribs, pockets, shells, threads,
  patterns.
- Positioning control: faces, axes, origins, connectors, constraints,
  interfaces.
- Output files requested: package, STEP, STL, OBJ, MJCF, FCStd, scripts.
- Mounting and service conditions when the part fastens to anything or
  carries load: fastener type/size, head side and insertion direction,
  mounting face, and the load direction with a magnitude class.
- Validation targets: bounding box, solid count, labels/tags, dimensions,
  mesh relations, replay count.

## Brief format

```text
CAD brief:
- Mode: <interactive | unattended (why)>   (first line; see `discipline/operating-modes.md`)
- Model: <name>, <part | assembly | modification | inspection | export>
- Inputs: <prose | reference images | drawing views used>
- Units: <explicit or assumed>
- Coordinate convention: <origin, base plane, up axis>
- Overall dimensions: <W x D x H or equivalent>
- Functional features: <list>
- Positioning/mating: <interfaces, datums, connectors, constraints>
- Parameters: <named parameters that must be Var-exposed>
- Paths: <source file(s), package/export targets>
- Validation targets: <measurable checks>
- Assumptions: <meaningful inferred choices only>
- Assumption ledger (unattended): | item | value | evidence | how to change it | the check that would show it wrong |
```

## Input precedence

- Dimensioned sources win over image proportions.
- When two dimensioned sources conflict, flag the conflict; never silently
  choose.
- An image without stated dimensions is design intent, not a spec: establish
  scale from one stated dimension or a known object, or ask the one scaling
  question when fit matters.
- Distinguish reproduction ("model this part") from inspiration ("something
  like this"): reproduction raises fidelity expectations.
- A single perspective reference is a floor, not a spec: when fidelity
  matters, request an orthographic view or one key dimension rather than
  inferring hidden geometry.
- If an input image contains a reference structure, you MUST describe the
  interpreted shape (overall form, visible features and locations,
  orientation, anything hidden or uncertain) and confirm with the user
  before any geometry. You MUST NOT satisfy this with a recorded assumption;
  only dimension-level defaults may be assumed once a scale anchor exists.

## Technical drawings

A drawing is a dimensioned contract:

- Read the title block first: units, projection convention, revision.
- Identify each view and its model axes before extracting numbers; section
  views are the source of truth for internal features.
- Convert every callout into a named parameter and a validation target;
  expand `4X`, `TYP.`, thread/counterbore callouts into features plus checks.
- Never scale undimensioned geometry off the image.
- Cross-check features across views; prefer the dimensioned view and flag
  disagreements.

## Clarification policy (Ask-or-Record)

When any blocking item below is missing, it is either asked (batched
into one question set before any geometry) or recorded in the brief as
a reported assumption. Proceeding with neither — a silent default — is
the failure mode, not the asking.

Blocking items:

| Missing item | Blocks when |
| --- | --- |
| One overall dimension / scale anchor | reference is images only and any physical fit matters |
| Fastener axis and head side | holes, counterbores, or countersinks are present |
| Mounting face / mating interface | the part attaches to anything |
| Load direction and magnitude class | the part carries load (structural role) |
| Interpreted shape of a reference image | always — you MUST describe and confirm before geometry; never a recorded assumption |

Batch all blocking questions into one ask; four one-question round
trips are worse than one four-question ask. Ask when: no dimensions and
no scale reference for a physical object; a mating interface is
described but unspecified; the part is load-critical; output depends on
a missing source file. Do not ask when a default clearance or cosmetic
radius suffices, or the user asked for a first-pass concept.

The brief is complete only when its validation targets name the checks that will run: every blocking answer and every user-stated requirement maps to a targeted measurement or a rendered view, written down before the first modeling call. Modeling never precedes the acceptance set; volume and face counts alone have never distinguished a correct part from a rejected one.

Own the methods, ask about the requirements: how a claim will be verified (an insertion-envelope sweep, a highlight render, a comparison view) is yours to propose in the plan — do not wait for the user to invent the test. What counts as success (fit, load direction, finish) is the user's call and belongs in the Ask-or-Record set.

**Unattended:** the clarification policy and the "confirm with the user" rule above change who decides, not what is
checked (`discipline/operating-modes.md`). Nothing is asked: every blocking item is recorded in the brief's assumption
ledger with its evidence and the check that would show it wrong. The interpreted shape of a reference image is still
described region by region before any geometry, checked against the measured evidence, and its confidence recorded; it is
not skipped. Conflicting dimensioned sources: record the conflict and the choice (measured over prose over inference)
instead of flagging it to a person.

## Success criteria

The brief is ready when it defines source path(s), units, coordinate system,
named parameters, feature plan, positioning intent, output paths, and
validation targets — and every assumption it carries is one worth reporting.

Read `discipline/requirement-and-cad-brief.md` for the full discipline.
