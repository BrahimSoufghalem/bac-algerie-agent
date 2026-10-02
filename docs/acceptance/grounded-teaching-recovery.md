# Actual-read teaching gate, graph correction and retry history

## Incident and scope

A student reported a lesson reply without a visible reference read after a retry, followed by a failed velocity/acceleration graph. The former policy explicitly allowed general teaching when no reference was found; unstructured model text could also finish a run without selecting read evidence. This was a confirmed policy/runtime gap. A drawer cannot repair it by inventing a retrieval step.

The exact final graph failure on the user's Docker installation was **not reproduced** locally. Before this change, the same ordinary Darija lesson question completed after one search and no full read. Its graph follow-up also completed with two graphs after a failed numeric-program call. This is evidence of an ungrounded teaching path and a recoverable tool error, not proof of the cause of the user's terminal graph failure.

## Implemented behavior

- `response_kind=teaching` is the default. Actual runs require nonempty selected `source_ids` already delivered to the model context, in addition to current-source/ownership/publication validation. Search, metadata, TOC and registered-but-not-delivered sources do not satisfy the gate.
- A lesson reply cannot finish as unstructured prose. Rejection is fed back privately so the model can read a matching complete lesson/section/part/bundle/private page and call `render_answer` correctly. If no relevant reference exists, it must ask a short clarification, not deliver a memory-only lecture.
- Simple greetings/thanks have a bounded conversation route; clarification/refusal are one short plain-text block, without math, sources or extra warnings. Standalone numeric tasks have a calculation route requiring actual computed results. This is **structural evidence enforcement**, not automatic proof that every sentence is entailed by the selected reference. Topic relevance, faithful teaching and correct mode selection still require model evaluation.
- Retry retains source locators, but reload revalidates current publication/private ownership/expiry and actually delivers bounded content again. A deterministic **مراجعة المعلومات السابقة** stage records that real reload. Expired/archived sources do not gain fresh credit.
- Failed attempts remain distinct from the later successful reply in history and both export paths. A retry action is available on the latest failed request. Prior drawers remain independent, above their own reply, through follow-up, reload and mobile layouts.
- Previous real equation/table blocks are restored as model conversation context. A graph follow-up no longer loses prior equations simply because only prose was stored in the context projection. Old graph/result IDs do not become current-run computation evidence.
- `plot_function` accepts bounded explicit numeric constants through `values`, including constant acceleration. Domain holes remain excluded after substitution. Tool contracts provide exact field names and restricted-code examples; validation failures give bounded actionable correction instructions, not a false result. Graphs use actual scientific-result IDs, with units and clearly labelled illustrative values. Speed/velocity and acceleration must not share a physical-value axis with incompatible units.
- Local `python -m bac.cli diagnose-run` produces a bounded operator report with allowlisted failure codes and validation root-fields/types only. No question, model text, raw arguments, source IDs/files, keys, identities or raw tool names are included. Detailed diagnostics are not in public SSE, drawer projections or exports. Older failed runs may have no tool diagnostics.

No fixed model-round or total tool-call cap was added. Existing wall-time, context, per-call calculation limits, cancellation, allowance checks and repeated-identical-no-progress protection remain. No hidden paid retries were added. Source originals/pixels remain confidential model-only context; no student library, self-practice feature or editable student learning notes was reintroduced. There is no new migration.

## Verification

Local final test totals and live-provider results are recorded below after completion. Browser integration uses explicit test-only model/Vision fixtures and real PDF publication, actual read/cached reload, scientific runner, API/SSE/history/export and UI paths. A controlled projectile reference is synthetic, not an official curriculum or the user's actual projectile book.

- Final local backend: **168 passed**, with two existing dependency/test warnings.
- Final local browser: **20 passed**, including independent failed/successful drawers, actual cached reload, corrected graph, desktop/mobile, reload and no overflow/JS errors.
- Typecheck/Vite build and Ruff F checks passed. Local fixture screenshots are test-only illustrations, not live-provider success proof.
- Before-change live run with `ohh/gpt-6-astra`: teaching completed after search alone; graph follow-up completed with two actual graph blocks after a failed numeric-program call (five provider requests across those two turns).
- Post-change live attempts with the same endpoint/model did **not** complete: first attempt received EMPTY_MODEL_RESPONSE and HTTP_503; a manual second attempt received NETWORK_OR_TIMEOUT and then HTTP_503 after one successful search. A final ordinary greeting without any tools also returned EMPTY_MODEL_RESPONSE. **Eleven actual provider requests total** including the baseline, failed attempts and probe. No live success after the new read gate is claimed. A controlled published projectile reference was present in the post-change test database; its extraction/publication used an explicitly known fixture transcription, not a paid Vision quality test.
- First post-change attempt used an output limit of 4000; the second restored 6000, matching the baseline; the minimal greeting also used 6000. These few noncontrolled attempts are not a causal performance benchmark. Provider failures occurred even without tools; they must not be reported as confirmed causes of the user's earlier graph failure. Paid testing was stopped rather than hidden retrying.

New regression coverage rejects memory-only teaching, search-only credit, clipped/undelivered credit and non-teaching mode payload bypasses; corrects a malformed graph call; preserves prior equations; checks constant acceleration and domain holes; keeps failed/read retries in both exports and browser reload; and proves diagnostics are scrubbed and not public.

These tests are not certification of educational quality, complete source relevance, provider reliability, security of every possible model output, production load or the user's Docker environment. CI builds/tests its own container. Update and acceptance on the actual deployment remain necessary.

## Deploy

Back up the existing data volume and encryption keys first. From the same repository, Compose project and `.env`, update **both** API and worker:

```bash
git pull --ff-only
docker compose up -d --build api worker
docker compose ps
```

Use the same production `-f` flags if applicable; never `down -v`. Hard-refresh the browser. Ensure a relevant reviewed reference is actually published for a lesson; a secret file existing only as a draft is not evidence available to teaching. If a new request fails, run the local operator diagnostic described in [OPERATIONS.md](../OPERATIONS.md), rather than sharing raw logs/database/model traces or a provider key.
