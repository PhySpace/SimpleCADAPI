# Single-Part Modeling: REQUIREMENTS.md template

The file Role 1 writes (`workflows/single-part-modeling/role-1-requirements.md` step 4).

```markdown
# Requirements: <part name>
- Mode: <interactive | unattended (why)>
- Inputs: <prose | images used | drawings>
- Functional goals: <what the part must do>
- Geometry targets: <confirmed shape description, region by region>
- Units / coordinate convention: <mm; origin, base plane, up axis>
- Named parameters (Var): <name = value | ASSUMED default>
- Fastening & mounting: <fastener, axis, head side, insertion path>
  Envelope math: <head+shaft+wall -> min land / boss / offset>
- Service conditions: <load direction and class | none stated>
- Export targets: .scadpkg always; STEP/STL/OBJ/MJCF/FCStd if requested
- Verification intent: <what the user's words require proving>
- Ask-or-Record ledger: | item | asked/assumed | answer/value |
- Assumption ledger (unattended; interactive runs use the Ask-or-Record ledger above):
  | item | value | evidence | how to change it | the check that would show it wrong |
```

The first line of the file states the mode (`discipline/operating-modes.md`). In unattended mode every field is filled;
a recorded assumption fills a field, an empty field does not.
