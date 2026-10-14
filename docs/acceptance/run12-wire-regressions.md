# Run12: evidence and answer wire repair (offline)

Base: `4d85c667d14119936bccdd8390e1c5db391cc26a` (PR37). Evidence: [recorded Run12](https://github.com/BrahimSoufghalem/bac-algerie-agent/actions/runs/38611837906). No live API trial, merge or deployment is authorized by this change. Fixtures contain only small recorded contracts/schema-field lists, not books, full conversations, secrets or hidden reasoning.

## Verified causes and changes

- **M01 and similar unlinked objectives:** the old wire required named goals/rules plus a separate coverage link list. A declared but unlinked goal remained rejected, with no useful format-repair category. The live wire now attaches `supports: [{source_id, evidence_id}]` directly to every requirement. The server normalizes only those explicit pairs into the existing internal coverage contract and derives quotes from actual loaded passages. It does not invent support, infer IDs, auto-select cited sources or trust copied quotations.
- **Legacy missing-goal links:** one format repair is allowed within the existing three assessment calls. Explicit empty nested support, missing prerequisites/conditions, unknown spans, mismatched aliases and reported semantic gaps remain rejections, not automatic sufficiency. Recorded/internal legacy contracts remain supported and fully validated.
- **M19:** a `clarify` plan had an empty question. The server substitutes a bounded neutral clarification and revalidates the entire plan. Valid alternative IDs are discarded, not executed. Invalid IDs/fields/goals still fail closed. No extra router request. Owner audit stores a fixed reason code; reported usage is recorded even for a safely recovered invalid clarification (`safe_clarification`, counted as a non-`ok` request by existing usage reports).
- **M24:** the actual Google-compatible render manifest omitted `history_evidence`, `checked_claims` and the `history_summary` response kind. Google block flattening now derives from `PresentedAnswer`, preserving every top-level field, bounds and provenance subcontracts. Only the block union is flattened; strict server block/provenance/result validation remains authoritative. OpenAI-compatible and native Anthropic manifests share the canonical contract. Native Google is a **router-only** transport in this project, not a teaching adapter.
- **History review:** pure or mixed requested history review is read-only for learning observations. Note mutations are omitted from that turn's advertised tools and denied by the executor as defense in depth. Mixed review plus new teaching still requires both actual student-history evidence and curricular source support. No change to account ownership, teacher/private-upload permissions or note management outside review turns.
- **M03:** a correct computation/counterexample did not justify converting a sufficient condition into a necessary condition. A fixed authored counterexample test pins that diagnostic. Assessment/teaching policy explicitly checks logical direction before publication, across subjects. **This is not a universal deterministic prose validator, and no claim is made that a real model can no longer repeat this error.** Computational comparisons certify only their explicitly bound claims, not the whole explanation.

## Boundaries

Reference files/catalogue, providers, model names, prices, context prefix ordering, source ledger, Python sandbox/security, attachment guards, graph/result IDs and private permissions are unchanged. There is no extra provider call type: format repair stays once per run within three assessments; working rounds/final reserve and the one existing essential-context addition remain unchanged. Router choice prompt is unchanged.

Offline tests include same-contract examples across six subjects; exact recorded M01/M19 contract shapes; Google/OpenAI/DeepSeek/Anthropic outgoing manifests; unknown/empty/mismatched evidence; bounded repair followed by N-turn reuse; no reads after clarification; mixed history plus teaching through an actual mocked Google HTTP transport; actual claimed-result binding through the mocked transport; note-mutation rejection. Model Python is mocked, never executed on the host. Existing tests cover permissions, missing images, graphs, sandbox and loop caps.

## Remaining validation

No new provider-reported token/cache/cost measurements exist for this patch. Mocked fixture usage is only a test of plumbing, not a savings estimate. Live structured-call acceptance, whether the model supplies complete supports, reference choices and pedagogical accuracy need a separately approved paid run. A green workflow is not an answer-quality certificate. No automatic paid workflow was dispatched.

## Executed local checks

- Latest full `pytest -q`: **637 passed, 6 skipped, 2 warnings**, 85.04 seconds. The six skips are Docker-gated sandbox cases; Docker is not installed in the local agent workspace. The warnings are the existing Starlette test-client deprecation and an intentionally duplicated ZIP entry used in a corruption test.
- Focused evidence/assessment/audit tests: **109 passed**. New regression module contributes **31 tests** to the full suite.
- Earlier full run had two failures because old schema assertions expected `BodySupport` in the live manifest and a Google-only source-ID description. The former assertion now tests the nested support schema; the latter description is canonical for all providers. Both pass in the final full run.
- Ruff F checks excluding unchanged vendored code, bytecode compilation and `git diff --check`: passed. An exploratory lint including vendor files found two pre-existing unused imports in `bac/vendor/bookforge`; those unrelated files were not changed.
- No real model/paid requests were made. Local tests used HTTP fixtures and mocked model-Python execution; they do not replace live semantic review. Container/browser CI results are separate and are not claimed here before the workflow finishes.
