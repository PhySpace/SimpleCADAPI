# Single-Part Modeling: Role 1 ask bindings

**Read when:** Role 1 (interactive mode) is about to send its batched ask round.

**Unattended:** skip this page. Nothing is asked; every item that would be asked is recorded in the assumption ledger of
`REQUIREMENTS.md` (`value / evidence / how to change it / the check that would show it wrong`).

<!-- skill:if omp -->

### Host binding: designing the Role 1 `ask` payload (omp)

OMP already provides and executes the `ask` tool. This block defines only how
to design its input for the Requirement Confirmer. After writing the
region-by-region interpretation and the Ask-or-Record ledger, make one batched
call for all unresolved items that can block `REQUIREMENTS.md`.

Design each question so its answer can be copied into one ledger row:

- Ask about one decision, not one vague topic. Name the affected region,
  feature, axis, or interface and state the evidence or ambiguity.
- Ask shape-level interpretation explicitly. Do not hide a disputed region in
  a general "does this look right?" question.
- Separate independent decisions such as overall orientation, hole axis,
  thread representation, and mounting intent. Use `multi: true` only when the
  user may independently select several items from the same set.
- Make options mutually exclusive and operational: each option must say what
  will be recorded and what modeling consequence follows. Do not offer
  imaginary precision that the source does not support.
- Put the conservative, clearly labeled assumption first and set
  `recommended: 0`; this is a recommendation, never consent. Include a
  concrete correction path in the options so the user can reject or amend the
  interpretation.
- Ask only blocking decisions in this round. Record inferable dimensions and
  low-risk defaults as assumptions with their basis; do not burden the user
  with API or verification choices owned by later roles.

Example payload shape (the actual labels and questions must be derived from the
current part, not copied literally):

```ts
ask({
  questions: [
    {
      id: "region_c_flange_location",
      question: "The drawing leaves the C-view flange location ambiguous. Which region is the C flange?",
      options: [
        { label: "The -Y horizontal-port end", description: "Record C as the long rounded flange on the -Y end; model its axis along Y." },
        { label: "The top vertical-bore end", description: "Record C as the flange around the top vertical bore; revise the region map before modeling." }
      ],
      recommended: 0
    },
    {
      id: "thread_representation",
      question: "The drawing calls out M36-6H, but does not establish whether thread faces are needed for this deliverable. How should it be represented?",
      options: [
        { label: "Nominal bore", description: "Record the callout and model the nominal bore; do not create helical faces." },
        { label: "Explicit thread geometry", description: "Record modeled thread geometry as required and plan a thread-specific verification." }
      ],
      recommended: 0
    },
    {
      id: "mounting_intent",
      question: "What mounting intent should the base holes represent?",
      options: [
        { label: "Through-bolted to a flat base", description: "Record insertion along Z and verify the fastener envelope and underside clearance." },
        { label: "Tapped or blind mounting", description: "Record the hole termination and thread requirement; do not assume through holes." }
      ],
      recommended: 0
    }
  ]
})
```

Use stable machine-readable `id` values that match ledger rows. After the call,
copy the returned selected options, custom answers, notes, and any timeout
status into `REQUIREMENTS.md`; preserve the user's wording for corrections.
The gate closes only when every blocking row has an explicit answer or an
explicitly recorded assumption permitted by the requirement discipline. A
recommendation or timeout is not user consent. On cancellation, incomplete
answers, or unavailable interactive UI, keep the gate blocked and stop; never
continue by silently selecting the recommended option.

When a question has no valid answer among the proposed options, its wording
must make clear what correction or missing requirement the user should supply.
Do not ask the user to choose an implementation detail owned by a later role;
ask only for the requirement that changes the model or its acceptance criteria.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: designing the Role 1 `question` payload (opencode)

opencode provides and executes the native `question` tool, which batches all
questions in one call. This block defines only how to design its input for
the Requirement Confirmer. After writing the region-by-region interpretation
and the Ask-or-Record ledger, make one batched call for all unresolved items
that can block `REQUIREMENTS.md`.

The tool schema differs from a generic ask; design around the differences:

- There is no `id` field. Key each ledger row to the `header` (max 30
  characters): derive it from the stable identifier you would otherwise use
  as an id, e.g. `C-flange location`, `thread representation`.
- There is no `recommended` index. Express the recommendation by putting the
  conservative, clearly labeled option first and suffixing its label with
  `(Recommended)`; this is a recommendation, never consent.
- A free-text "type your own answer" choice is offered automatically; do not
  add your own catch-all option. Answers return as the selected option
  labels (arrays when `multiple: true`). Use `multiple: true` only when the
  user may independently select several items from the same set.
- Keep each `label` to a few words and put the operational consequence —
  what will be recorded and what modeling follows — in `description`.

The shared design rules still apply: one decision per question, shape-level
interpretation asked explicitly, independent decisions separated into their
own questions, mutually exclusive and operational options, a concrete
correction path in the options, and only blocking decisions in this round.

Example payload shape (the actual labels and questions must be derived from
the current part, not copied literally):

```ts
question({
  questions: [
    {
      header: "C-flange location",
      question: "The drawing leaves the C-view flange location ambiguous. Which region is the C flange?",
      options: [
        { label: "-Y horizontal-port end (Recommended)", description: "Record C as the long rounded flange on the -Y end; model its axis along Y." },
        { label: "Top vertical-bore end", description: "Record C as the flange around the top vertical bore; revise the region map before modeling." }
      ]
    },
    {
      header: "Thread representation",
      question: "The drawing calls out M36-6H but does not establish whether thread faces are needed for this deliverable. How should it be represented?",
      options: [
        { label: "Nominal bore (Recommended)", description: "Record the callout and model the nominal bore; do not create helical faces." },
        { label: "Explicit thread geometry", description: "Record modeled thread geometry as required and plan a thread-specific verification." }
      ]
    }
  ]
})
```

After the call, copy the selected labels, any typed custom answers, and the
questions' headers into `REQUIREMENTS.md` keyed by header; preserve the
user's wording for corrections. A dismissed or skipped question is an
unanswered blocking row: keep the gate blocked and stop; never continue by
silently selecting the recommended option. The gate closes only when every
blocking row has an explicit answer or an explicitly recorded assumption
permitted by the requirement discipline.

When a question has no valid answer among the proposed options, its wording
must make clear what correction or missing requirement the user should type
as the free-text answer. Do not ask the user to choose an implementation
detail owned by a later role; ask only for the requirement that changes the
model or its acceptance criteria.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode -->

### Host binding: designing the Role 1 `AskUserQuestion` payload (Claude Code / ZCode)

The host provides and executes the `AskUserQuestion` tool. This block defines
only how to design its input for the Requirement Confirmer. After writing the
region-by-region interpretation and the Ask-or-Record ledger, make one batched
call for all unresolved items that can block `REQUIREMENTS.md`.

The schema differs from a generic ask; design around the differences:

- At most 4 questions per call. If more blocking rows remain, send the
  remaining rows as further batched calls in the same turn and say why.
- `header` (max 12 characters, shown as a chip) is the ledger key: derive it
  from the stable identifier you would otherwise use as an id, e.g.
  `C flange`, `thread`.
- There is no `recommended` index. Put the conservative, clearly labeled
  option first and suffix its label with `(Recommended)`; this is a
  recommendation, never consent.
- 2–4 options per question; each option is a short `label` plus an
  operational `description` saying what will be recorded and what modeling
  follows. A free-text "Other" choice is offered automatically; do not add
  your own catch-all option. Answers return as the selected labels plus any
  typed notes.
- `multiSelect: true` only when the user may independently select several
  items from the same set.

The shared design rules still apply: one decision per question, shape-level
interpretation asked explicitly, independent decisions separated into their
own questions, mutually exclusive and operational options, a concrete
correction path in the options, and only blocking decisions in this round.
Example payload shape (the actual labels and questions must be derived from
the current part, not copied literally):

```ts
AskUserQuestion({
  questions: [
    {
      question: "The drawing leaves the C-view flange location ambiguous. Which region is the C flange?",
      header: "C flange",
      multiSelect: false,
      options: [
        { label: "-Y port end (Recommended)", description: "Record C as the long rounded flange on the -Y end; model its axis along Y." },
        { label: "Top bore end", description: "Record C as the flange around the top vertical bore; revise the region map before modeling." }
      ]
    }
  ]
})
```

After the call, copy the selected labels, any typed custom answers, and notes
into `REQUIREMENTS.md` keyed by header; preserve the user's wording for
corrections. A skipped question or an empty answer is an unanswered blocking
row: keep the gate blocked and stop; never continue by silently selecting the
recommended option. The gate closes only when every blocking row has an
explicit answer or an explicitly recorded assumption permitted by the
requirement discipline.

<!-- skill:endif -->

<!-- skill:if codex -->

### Host binding: Role 1 blocking questions without a native ask tool (codex)

codex provides no structured interactive-question tool. Keep the ledger
discipline in plain conversation: after writing the region-by-region
interpretation and the Ask-or-Record ledger, send ONE message listing every
unresolved item that can block `REQUIREMENTS.md` — one numbered question per
decision, lettered mutually exclusive options each stating the operational
consequence, the conservative interpretation first and marked
`(recommended)`, and an explicit invitation to correct or type a different
answer. Then stop: make no further tool call until the user replies. Record
the reply verbatim in `REQUIREMENTS.md` under the same ledger keys, preserving
the user's wording for corrections. A partial answer or a general "sounds
good" does not answer the open rows: re-ask exactly those rows and keep the
gate blocked; never continue by silently selecting the recommended option.
The gate closes only when every blocking row has an explicit answer or an
explicitly recorded assumption permitted by the requirement discipline.

<!-- skill:endif -->

<!-- skill:if dsh,kimicode -->

### Host binding: Role 1 blocking questions, conservative fallback (dsh / kimicode)

No native interactive-question tool is assumed for this host, so use the
plain-text ledger discipline: after writing the region-by-region
interpretation and the Ask-or-Record ledger, send ONE message listing every
unresolved item that can block `REQUIREMENTS.md` — one numbered question per
decision, lettered mutually exclusive options each stating the operational
consequence, the conservative interpretation first and marked
`(recommended)`, and an explicit invitation to correct or type a different
answer. Then stop and wait for the user's reply; record it verbatim in
`REQUIREMENTS.md` under the same ledger keys. A partial answer does not
answer the open rows: re-ask them and keep the gate blocked; never continue
by silently selecting the recommended option. If this host does provide a
native ask/question tool, map this block onto it and keep the same gate
semantics: one batched round, blocking decisions only, and a recommendation
that is never consent.

<!-- skill:endif -->
