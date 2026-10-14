# Context contract compatibility after PR36/run10

The run10 publication counts hid an end-to-end failure: 21 identical insufficient
clarifications, one correct missing-attachment clarification, and two failed turns.
The model returned `sufficient` 27 times, but only one passed the server gate.
23 assessment attempts omitted a `goal` requirement and two omitted a `rule`.
The exposed generic array did not make those required categories explicit.

## Small wire-only change

Live `assess_context.requirements` is now an object with four mandatory arrays:
`goals`, `rules`, `conditions`, `prerequisites`. Each item has a unique `id` and a
short `description`; its group supplies its kind. `sufficient` still needs nonempty
goals/rules and actual passage links for every goal, rule, condition and prerequisite.
Non-sufficient choices can use empty arrays. All groups together retain the
existing maximum of 16 items. The canonical internal decision/ledger is unchanged;
old recorded array callers remain compatible. Production prompts and field
descriptions state the same contract as the server. No subject-specific worked
example or new educational allowlist was added.

The stable live schema keeps the same shape across initial, restored and new source
sets. Source/passages choices remain server-owned DATA; unknown aliases, changed
bodies, wrong passages, topic mismatches and unsupported dependencies cannot grant
read credit. Neither an empty group nor merely valid IDs proves sufficiency.

## Bounded format repair is not reference retrieval

The engine distinguishes a malformed/duplicate wire contract or missing structural
goal/rule classification from a genuine body-support gap. It can send one private
format-correction request per run, using the same bodies and fixed tool schema.
Only safe reason codes and generic format instructions are added to the volatile
server context; no hidden reasoning or student/source text enters the audit log.

This repair consumes the **existing maximum of THREE assessment requests**, not a
new independent allowance. It creates no new router loop. If formatting remains
invalid or the assessment budget is exhausted, the decision remains uncertain,
coverage is revoked, and the existing safe no-teaching path applies. The router
and its initial-plus-one-essential-repair limit are unchanged. A successful grouped
decision adds no extra model call.

Actual missing rules/conditions are not treated as a format fault. The full catalogue,
library bodies/hierarchy, provider/model/prices, ownership, attachments, isolation
and final source/result/graph validation are unchanged. In particular this change
does not solve every prerequisite selection problem seen in M01/M13, and must not
be reported as semantic certification of declared requirements.

## Computation feedback before the final round

For coordinated computational/plot requests, a successful `run_python` result
without emitted comparison evidence now carries private answer-contract feedback.
It explains that successful execution/printing is not verification, asks for
genuine comparison evidence and exact `checked_claims` bindings, and reminds the
model to reserve a render round. The execution remains successful and its actual
output is persisted unchanged. The server never manufactures checks or grants
whole-answer verification. Existing working-round ceilings and Python isolation
are unchanged.

## Deterministic regressions and empirical limits

`tests/fixtures/pr36_contract_replay.json` contains only ten scripted benchmark
assessment contracts and provenance: no reference bodies, real student identifiers,
keys or model reasoning. Tests replay their failure shapes against synthetic
passages (not a public copy of the private book). Integration tests cover missing
goal classification, duplicate references, one bounded repair, repeated failure,
current/N-th-turn reuse without default routing, exhausted budgets, semantic gaps,
unknown source/passage rejection, and early Python feedback followed by an actual
mocked comparison/result binding. Six subjects use the same grouped schema.

Mocked provider/Python results test server contracts and orchestration, not live
pedagogical accuracy or container execution. Existing CI container checks and one
separately authorized paid 24-turn trial must be reported distinctly. The paid trial
must review actual answers, actual graphs, dependencies, history, token usage and
unknown cache coverage; Workflow success alone is not a quality score.