# Multi-label selector update — compact request accepted; semantic quality FAILED

## Scope

The local coordinator now accepts zero, one, or several references in one selection
request. It uses independent boolean inclusion probabilities, not a single
categorical winner. The default cap is three, configurable from one to eight.
The owner-authorized compact selection policy, version3, is in `config/selector.yaml`.

This change was not pushed to GitHub, installed in the user's Docker, or tested
against the complete uploaded physics book. No alternative model was called.

## Live evidence

Four bounded diagnostic requests used `convaiinnovations/laya` on the existing
Vercel Evaluation endpoint:

| Request shape | Result | What it proves |
| --- | --- | --- |
| Full policy, object state, boolean criteria | HTTP422 | Full request rejected; reason unknown |
| Minimal English string state, no optional criteria | HTTP200; C1=0.9986, C2=0.88, C3=0.0001 | Two independent candidates can pass together in one native request |
| Full policy, object state, shorter question heads, criteria | HTTP422 | Shorter heads did not fix the full request |
| Full policy, JSON string state, no optional criteria | HTTP422 | The previous long policy's wire shape was rejected |

The minimal control does NOT establish Arabic/Darija understanding, book retrieval,
or compliance with the long policy. The full-policy requests contain 3960 policy
characters, with no silent shortening. We cannot determine from the sanitized
errors whether input size, content, or another provider restriction caused rejection.
The request series stopped; there are no automatic paid retries or model switches.

A later read-only `/v1/models` lookup confirmed that the hosted
`convaiinnovations/laya` catalog advertises `context_window=8192` and
`max_tokens=0` (evaluation does not generate free text). This is not proof of the
exact provider tokenizer, internal state/head allocation, or the cause of HTTP422.
The last three-candidate request measured 5295 serialized characters / 5521 UTF-8
bytes. These are NOT token counts. Do not claim that the request exceeded 8k tokens.
Self-hosted checkpoint defaults in the Hugging Face card need not equal hosted
gateway runtime settings.

## Authorized compact-policy follow-up

The owner then requested shortening while preserving the same decision principles.
Version3 reduces the policy from3960 to1529 characters (61.4% fewer characters,
NOT a measured token reduction). It retains multilingual meaning, data/instruction
separation, latest corrected intent, exclusions, context, metadata semantics,
requested-vs-mentioned distinctions, comparisons, sufficient specificity,
non-redundancy, previous coverage, ambiguity/no-match rejection, no invention,
typed-only output and independent multi-selection.

One new request used the same LAYA model, native JSON-string wire shape and Arabic
comparison with three synthetic candidates. **HTTP200**,1494 reported input tokens,
0 output tokens. The request was2486 serialized characters /2712 UTF-8 bytes.

- Nuclear half-life C1:0.9961 — correctly included.
- Chemical half-reaction time C2:0.9974 — correctly included.
- RC charging C3:0.9955 — **incorrectly included**.

The unchanged0.55 confidence /0.10 include-vs-exclude margin gates accepted all
three. Expected C1+C2, actual C2+C1+C3. This is a semantic false positive,
not successful lesson selection. One accepted compact request does not prove that
the previous422 cause was size, that all future requests will be accepted, or that
the model obeyed the compact policy. No threshold change, retry or model fallback
was used. No full-book/teacher/real-Darija test was performed.

## Offline verification

The tests exercise multiple equal-confidence positives, empty decisions, caps,
stable ties, malformed/unknown/missing answers, independent include/exclude margins,
metadata-only requests, actual complete source reads after all decisions, combined
context budget failures without partial read credit, heading-only rejection,
duplicate-read prevention, newest request context, provider isolation and migration008.
These are synthetic fixtures, not live teaching-quality evidence.

The preceding full local backend run: **301 passed, 2 warnings**.
The targeted selector run after shortening: **57 passed**.
TypeScript/Vite build passed before this prompt-only change.
No Docker deployment was executed.

Migration008 copies an active legacy one-reference configuration to a new
three-reference configuration while preserving the encrypted key, old row,
activation flag and queued-run snapshots. It does not activate a disabled selector
or change teaching/extraction settings.

## Release status

Do not enable this selector in production based on the accepted compact request.
The owner-approved shortening was applied; the observed semantic false positive
still fails acceptance. Further changes need representative positive/negative
Arabic/Darija tests; any model/provider switch must be explicit.
Candidate retrieval remains lexical; multi-selection does not fix missing candidates.

## Later bounded prompt-improvement attempt

At the owner's request, two candidate policies of1368 and1342 characters were
prepared, both below the installed1529-character policy. Their total static
instructions were1502 and1478 characters, below the baseline1599. Experimental
question heads referenced each candidate's actual metadata rather than only its
alias. This changes input formulation, not just policy wording.

Three pre-registered development questions were used: the earlier raw Darija
projectile request, the missing black-hole topic, and the nuclear-vs-chemical
half-time comparison. These are synthetic bilingual candidate descriptions, not
the uploaded book's indexed nodes.

| Variant | Answered, exact correct | Answered, wrong set | API rejection | Planned case not run |
| --- | --- | --- | --- | --- |
| Installed policy control | 0 | 1 | 1 HTTP422 | 1 |
| Direct semantic predicate | 0 | 3 | 0 | 0 |
| Negative-first predicate | 0 | 2 | 1 HTTP429 | 0 |

Eight network requests across three distinct questions yielded six answers;
none matched the expected set exactly. Missing concepts or extra unwanted
concepts fail this metric. API refusals are not counted as semantic errors.
The control series stopped at422; different formulations were then explicitly
tested, not the same request retried. At429 every live request stopped, with no
model switch, quota retry or threshold change.

The pre-registered24-case final suite (nine recovered previous questions plus
fifteen unseen cases) was NOT executed. There is no holdout score or evidence of
improvement. Neither new policy was selected for activation; `config/selector.yaml`
remains version3. The prompt-builder refactor preserves the legacy request shape
and supports metadata-grounded experimental heads without private node IDs.