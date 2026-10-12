# Subject-neutral task/evidence and cache prefixes

This change leaves the full published catalogue, source hierarchy/body, providers,
model names, prices, current Python isolation and router validation unchanged.

## Contracts and message flow

- The server identifies the CURRENT request and separates authenticated student
  message IDs/givens from reference examples and previous assistant explanations.
  Goal hints (explanation/calculation/plot/follow-up/history/mixed history) are
  scheduling/negative hints, **not** evidence of correctness or sufficiency.
- The isolated tutor assessment declares goal/rule/condition/prerequisite
  requirements and maps EVERY declared requirement to exact allowlisted server
  passage IDs. The server checks aliases, delivery, body hashes, source membership,
  requirement closure, current-goal support, obvious topic mismatches and existing
  condition checks. Missing closure recovers to uncertain; no memory teaching.
- All configured subjects use this same schema/prompt. Closed topic hints cover
  several disciplines but are incomplete negative filters, never a curriculum or
  semantic entailment oracle. Unknown concepts still rely on the model's actual-
  body assessment. Claiming a requirement exists does not prove it covers all
  implicit dependencies: that remains an empirical quality limit.
- The router is unchanged: full catalogue only when needed, validated source
  selection, one initial route plus at most one essential repair, at most three
  assessments. Private page/pixel delivery, permissions and final result-ID checks
  are unchanged. No new unbounded loop or additional model verifier call exists.
- Plain greetings/thanks/help retain the closed server whitelist. A PURE requested
  own-dialogue summary uses history_summary and needs own active public history;
  a mixed summary plus exercise/explanation still uses the reference gate for the
  educational part. History is not curricular source evidence or mastery.

## Computation/claim checks

Ordinary isolated Python remains the only exposed computation tool. check() now
optionally emits bounded comparison evidence (observed, expected, relation,
tolerance); its declared status must match the emitted comparison. render_answer
can link the exact claim text/block to the actual current-run result/check index.
Computational/plot tasks with Python results, and calculation responses, require
such bindings. A printed OK, an invented/stale result, wrong check label, a failed
check or a check without comparison evidence cannot count as a checked assertion.
This is **not** independent certification of model-written code: constant/tautological
comparisons can still be authored, and the server cannot prove every natural-
language assertion is correctly expressed as a check. Independent derivations,
applicability/domain/units and universal-claim restraint are generic prompt policy;
paid answer review is still necessary. No AST restrictions or host fallback were
introduced, and no provider output is executed outside the existing container.

## Traceable history

The bounded extractive summary keeps early confusion candidates plus recent
exchanges, marks itself incomplete and does not infer mastery. Authorized
read_conversation_history pages only active PUBLIC dialogue in the current owner's
conversation (student-only by default). Cursors, account activity, quote membership,
actual delivery and message digests are checked; edited/inactive messages cannot
be cited. A completed scan requires contiguous pages in the same scan mode and no
truncation; otherwise the server adds an explicit partial-summary warning.
Each student observation needs genuine student quote evidence, never an assistant
or book example. No reference text is added to measurement logs.

## Cache topology and measurements

1. Fixed isolated assessment policy and authenticated scope.
2. Sorted complete authorized actual bodies and stable aliases/passages.
3. Volatile current request, recent history, session summary, attachments and stage.

The live assessment tool schema no longer contains dynamic source/passage enums;
choices stay in DATA while exact server allowlists remain authoritative. The main
tutor's initial/restored source envelope is identical for the same immutable
source set/versions and precedes settings/history/current state. Source changes,
withdrawn permissions or new versions correctly change the prefix. Working rounds
still append tool messages; no mid-round prefix mutation is introduced.

Owner-only context_prefix_shape records phase/source count/fixed-prefix character
count/hash, and context_requirements_accepted records counts and source IDs, never
student text, source passages or hidden reasoning. Existing usage records preserve
provider-reported input/output/cache values and distinguish unknown cache from zero.

Direct DeepSeek/OpenAI automatic caching can reuse matching prefixes where the
provider supports it; threshold, persistence, routing and cache hits are provider-
specific and best-effort. No unsupported prompt_cache_key/TTL/breakpoint options
are sent to Gemini, DeepSeek or other endpoints. Matching schemas/order is a
necessary optimization, NOT measured proof of a particular cache hit or saving.

## Validation and remaining empirical limits

Deterministic tests include all authenticated configured subjects, actual body
mismatches in six disciplines, dependency closure, stable source/tool prefixes,
plot vs old analysis goals, traceable paginated history, inactive/foreign history,
failed comparison/result bindings and fixed trusted regression computations.
The unchanged 24-turn mathematics harness is an empirical stress test, not a
math-specific production prompt. Its paid run must be evaluated by actual answer
content as well as publication/errors/calls/tokens/cache. Local Docker-only tests
are skipped where Docker is unavailable; CI runs them in the existing broker.
