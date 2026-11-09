# Single-Part Modeling: Role 1, Requirement Confirmer

Outline, role map and standing discipline: `workflows/single-part-modeling.md`.

## Role 1 — Requirement Confirmer ⛔

Convert the request into `REQUIREMENTS.md`. No geometry, no probe builds,
no source-file writes before this role's gate closes.

Procedure:

1. Classify inputs (prose / reference images / drawings / mesh models ,etc.). For any image
   containing reference structure: write the interpreted shape region by
   region — overall form, visible features and locations, symmetry and
   orientation, anything hidden or uncertain. **Describing is not
   confirming:** the interpretation ends as part of ONE batched ask round
   that also covers the Ask-or-Record blocking table
   (`domains/requirement-refinement.md`). Shape-level facts are always
   confirmed; only dimension-level defaults may be assumed once a scale
   anchor exists.
   For provided models(most cases are mesh), use python code to render and inspect geometry information through something like sampling / fitting, which may provide useful geometry information for you to build similar stucture / rebuild same struction in brep through simplecadapi.
2. For undetermined parameters / geometry / function / performance, propose
   recommended assumptions as ask options (default first) so the user can
   accept or override in one round.


**Unattended:** the gate is a self-review gate, and Ask-or-Record items are recorded in the assumption ledger, not asked
(`discipline/operating-modes.md`). Shape-level facts are still described region by region in `REQUIREMENTS.md`; the
interpretation is checked against the evidence (measured mesh / drawing facts first) and its confidence is recorded. It is
never skipped.

**Interactive host bindings** for the batched ask round (the `ask` / `question` / `AskUserQuestion` payload design, or the
plain-text fallback) are in `workflows/single-part-modeling/role-1-ask-bindings.md`; read it when you are about to ask.

3. Fastened or load-bearing parts: the requirements contain the envelope
   arithmetic, not just values — head diameter + shaft + wall/clearance →
   minimum land diameter, boss thickness, edge distance, and lateral
   offset along the insertion path.
4. Write `REQUIREMENTS.md`:
(the template is in `workflows/single-part-modeling/requirements-template.md`; fill every field, record an assumption for any field not answered)

Gate: the ask round returned answers, consent is recorded in the ledger, and
`REQUIREMENTS.md` exists. Entering Role 2 without this gate is the cardinal
violation.

**Unattended:** the gate passes when `REQUIREMENTS.md` exists with `Mode: unattended`, every field filled (an assumption
recorded in the ledger fills a field; an empty field does not), and one paragraph of decision with the open risks written
under the ledger. The self-review is a re-read of the brief against the request and the evidence. Entering Role 2 without
this artifact is still the cardinal violation.
