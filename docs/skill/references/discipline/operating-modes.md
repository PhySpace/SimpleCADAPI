# Discipline: Operating Modes

**Read when:** at the start of every task (the router sends you here), and again whenever a gate says to ask or to wait
for a person.

Every workflow runs in one of two modes. The mode changes who decides, never what is checked.

## The two modes

- **Interactive.** A person is in the loop (a conversation, or the editor open). You may ask questions, and a consent
  gate waits for them.
- **Unattended.** No person will answer (a service, a batch run, a job queue). You never ask and never wait. Everything
  a person would have decided, you decide from evidence and record.

## Which mode am I in

Decide once, at the start. The first line that matches wins:

1. The task or the runtime instructions say the run is unattended, forbid questions, or say nobody will answer
   ("unattended", "do not ask questions", "make evidence-based assumptions instead of asking") → **unattended**.
2. A person is talking to you, or has the editor open (`sca edit`) → **interactive**.
3. You have no tool for asking a question → **unattended**.
4. Otherwise → **interactive**.

Write the result as the first line of the brief: `Mode: unattended (the task says the run is unattended)`.
Do not switch to interactive because a step is hard. In unattended mode the only way to reach a person is the report.

## What never changes

- A gate binds an artifact: it passes only when the artifact exists (printed facts, measurements, named views, filled
  brief fields). A feeling of success is not a gate result, in either mode.
- A failed check closes by changing the design, or by redefining the check in the open. Never by weakening or deleting it.
- No claim of strength, fatigue, thermal behaviour, tolerance compliance or regulatory fitness without the analysis run.
- Every modelling rule (feature tree, QL selection, keyword arguments, cells and `Var`) is the same.
- Host-specific blocks about asking tools and plan tools are for interactive runs; in unattended mode skip the ones that
  ask a person.

## What changes: each gate and its replacement

| In interactive mode | In unattended mode |
| --- | --- |
| An **Ask-or-Record** item: ask once, batched | **Record it.** Choose the value the evidence supports and write it in the brief's assumption ledger: `value / evidence / how to change it / the check that would show it wrong` |
| A **consent gate** (⛔: the person approves the brief or the plan) | A **self-review gate.** Re-read the brief against the request and the evidence, write one paragraph of decision with the open risks, and go on only when every required field is filled (a recorded assumption fills a field; an empty field does not) |
| A choice between design directions | Take the one that meets the stated requirements and is easier to change later; record the other in the plan |
| A missing prerequisite (file, tool, input): name it and stop that route | Record the blocker in the report, do the strongest work the available evidence supports (say which parts it supports), and go on. Never invent the missing input |
| An independent review (isolated reviewer, second pair of eyes) | A fresh-context check of your own against a written checklist, quoting what you observed; use a subagent if the host offers one. If neither is possible, the report says the review was not independent |
| Asking the person to look at a render | Look at it yourself: name the views, what you looked for, and quote the observation |
| Conflicting information | Measured evidence over prose, prose over inference; record the conflict and the choice |
| A closing message to the person | The report (below) |

## The report (unattended)

The deliverable that replaces every conversation. Name and place come from the task; the default is `report.md` next to
the source. It lists:

- the assumptions, each as in the ledger above;
- what was reconstructed, what was omitted, and what is uncertain (with the evidence tier of each statement);
- the checks that ran with their results, and the checks that were not run, with the reason;
- any review that was not independent;
- the commands that reproduce the result.

## Stopping

End the run only after the source runs and you have inspected its result and written the report. The service that
receives the run validates independently; your closing text approves nothing.

If the same check fails twice for the same cause, change the design or redefine the check in the report: do not retry the
same thing (`failure-and-repair.md`).
