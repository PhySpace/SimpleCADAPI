# Discipline: Requirement and CAD Brief

Converting prose, reference images, and technical drawings into an actionable
modeling brief. The operational steps live in
`../domains/requirement-refinement.md`; this file carries reasoning and
evidence-handling guidance, not automatic SDK behavior.

**Read when:** Role 1 (or any brief-writing step) starts: prose, images or drawings are being turned into a brief, or
evidence conflicts.

## Every modality funnels into one brief

Prose, images, drawings, and conflicts all reduce to the same artifact: a
note-form brief with units, dimensions, features, positioning intent, paths,
and validation targets. The downstream workflow never changes based on input
modality.

## Evidence precedence

- A dimensioned source beats image proportions, always.
- Two dimensioned sources in conflict (prose says one value, a drawing callout
  another) → flag the conflict to the user; never silently choose.
- An image without dimensions is design intent, not a spec. Establish scale
  from one stated dimension or a known object in frame. If neither exists and
  fit matters, that is the one clarification question worth asking.
- Reproduction ("model this exactly") raises fidelity expectations and
  validation targets; inspiration ("something like this") leaves freedom.
  Record which one the request is.

## Reading a technical drawing

A drawing is a dimensioned contract:

1. Title block and notes first: units, projection convention, revision,
   disclaimers.
2. Map every view to model axes before extracting numbers — trust view labels
   and callouts, not layout conventions.
3. Section views are the source of truth for internal features: bores,
   counterbore/blind-hole depths, wall sections.
4. Every callout becomes a named parameter plus a validation target.
   Multiplicity (`4X`), `TYP.`, thread/counterbore callouts expand into
   features plus checks.
5. Never scale undimensioned geometry off the drawing; derive it from stated
   dimensions when constrained, otherwise assume and report.
6. Cross-check features across views; when views disagree, prefer the
   dimensioned view and flag the disagreement.

Success for a drawing-driven model: every drawing dimension is either verified
by a measurement after generation, or explicitly reported as not verified.

**Unattended:** where this page says to flag or ask the user, record the conflict, the choice and the evidence in the
brief's assumption ledger instead (`discipline/operating-modes.md`); the checks and the brief quality gate are unchanged.

## Assumptions are load-bearing only when reported

An assumption silently applied is a future defect. Each one in the brief
should be one a reviewer would want to see: default wall thickness, assumed
clearance standard, chosen corner treatment. Trivia (an internal helper's
name) is noise.

## The one-question rule

What must be asked or recorded is decided by the blocking-item table in
`domains/requirement-refinement.md` (Ask-or-Record); batch the blocking
set into one question set. A barrage of questions is a failure to apply
defaults; a missing question on a fit-critical dimension is a failure
to ask.

Discretion failed here: an image-only brief with countersunk mounting
holes was modeled for hours without asking, and was rejected twice on
hole orientation alone.

Record load-bearing assumptions as brief fields, not prose: name the
assumption, the features it determines, and the default taken. When
review invalidates an assumption, revisit every feature derived from it
in place — a rebuild that re-encodes the same unchecked assumption
reproduces the same rejection.

**Unattended:** the one question that would be asked is recorded as an assumption (value, evidence, how to change it, the
check that would show it wrong); nothing is asked.

## Brief quality gate

The brief is ready when it defines: source path(s), units, coordinate
convention, named parameters, feature plan, positioning intent, output paths,
and validation targets — and every assumption it carries is worth reporting.
