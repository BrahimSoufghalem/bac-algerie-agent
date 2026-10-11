# Mathematics live-audit follow-up

This change addresses failure modes observed in the original 24-question live plan
(21 answers published before a quota error). It does not claim the model's future
answers are mathematically certified. No live generation is part of push/PR CI.

## Implemented safeguards

- The tutor must check the *specific* mathematical claim with ordinary Python,
  identify assumptions/domains, and search counterexamples before generalizing.
  Independence alone does not imply equal conditional probabilities. Numerical
  agreement is not proof; derivative/extremum rules must state their hypotheses.
- Computed values are bound to the current expression; historical examples are
  explicitly historical, not numbers to substitute into the current solution.
- A requested graph already computed in the current run survives a narrow render
  format repair. A unique successful chart can be attached using its actual ID;
  multiple results require an explicit choice. No fabricated data, previous-run
  lookup, wrong ID substitution, or unsolicited graph is allowed. Strict provenance,
  authorization, result validation and privacy checks still apply.
- Double-escaped known TeX commands are normalized only inside math zones/equation
  blocks. Code, unknown macros, matrix row separators and ordinary prose stay literal.
- Partial lesson routing metadata describes the part, not its whole parent. New
  imports store local extractive labels; previously published parts receive an
  in-memory catalogue upgrade. Original files and published snapshots are not rewritten.
  The router still makes a semantic sufficiency decision: there is no blind parent
  replacement, source-body approval call, 60k cap or prompt truncation.
- Agent-managed mastery needs an exact quote plus message ID from an active own-chat
  student message available to that run. Assistant answers, missing/invented quotes,
  another chat, future messages and explicit confusion cannot support it. Notes bind
  to the evidence message and an audit stores digests (not a new copy of the quote).
  Correctness of the student's work still requires the tutor's scoped verification;
  quote presence alone is not proof of mastery. No HTTP note writer was added.
- Benchmark Python/check counters now inspect the scientific result's `output`
  envelope rather than falsely counting successful executions as zero.

## Input pacing and quota failures

`ModelConfig.input_tokens_per_minute` controls **process-local** pacing. `None`
uses a precautionary 200,000/minute budget for official Google endpoints; `0`
disables it; a positive value sets an operator budget. This is NOT a universal
Google quota, context size limit, billing counter, or guarantee against HTTP 429.
The native router and OpenAI-compatible tutor share the same key/model bucket.
Multiple worker processes need operator-managed shared quotas. Reservations survive
separate asyncio loops inside one process and waits are cancellable.

Before sending, UTF-8 request bytes / 2 gives a conservative heuristic reservation.
Provider-reported input counts replace it when available; unknown usage stays
estimated **for pacing only**. Cache hits are not subtracted from this reservation.
Billing/reporting still uses actual provider counters, with unknowns explicitly
unknown. The run deadline includes time spent waiting. An above-budget request waits
until alone and is sent intact; the provider may still reject its own hard limit.

HTTP 429 gets a redacted rate-limit hint and bounded numeric retry delay from
RetryInfo, Retry-After seconds, or a narrow message fallback. The shared bucket
observes that cooldown. Production does **not** silently retry calls, rerun the
conversation, or replay tool side effects. Manual Retry remains explicit.

For a future benchmark on an existing private disposable test root, the explicit
command below authorizes **one** retry of only the last unpublished 429-failed case:

```bash
python benchmarks/run_math_live.py resume-429 24
```

It requires the original latest active student message and existing private database
and configuration. It cannot restore a deleted GitHub runner from public artifacts.
No init/full-conversation rerun is performed. Request/input safety caps remain 128
and 2.5M, including earlier requests. Old failed evidence is preserved under
`previous_attempts`; per-turn tokens include both attempts, and unknown failed-call
usage is not converted to zero. A second resume, published reply, authorization
failure or a changed latest message is rejected. The manual live workflow's defaults
remain preflight; no provider requests are initiated by these edits.

## Validation boundaries

Offline regressions cover counterexamples, trusted fixed Python computations,
format/provenance guards, local metadata, note evidence, rate pacing/cancellation,
redaction, bounded resume and known-only token reconciliation. Passing them verifies
software behavior, not stochastic routing sufficiency or teaching quality. Re-run
the original real-model plan only with explicit authorization and review actual
answers, sources, graphs, student evidence and provider token counters again.
