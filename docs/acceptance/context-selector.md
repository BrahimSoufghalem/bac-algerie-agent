# Context selector acceptance — experimental, quality gate NOT passed

## Honest verdict

The independent source-selection architecture and provider presets have offline contract coverage. **The hosted `convaiinnovations/laya` selector has NOT passed a source-selection quality gate for Arabic/Darija.** It is opt-in and disabled by default. Do not interpret a successful HTTP response, source read, or green offline CI as a language/teaching quality certificate.

Only Vercel LAYA was called live. No live OpenAI, Google, Claude teaching/vision, or alternative chat-based selector was tested; no corresponding keys were available. Teaching, diagrams, extraction fixtures and full-engine integration tests here use explicit synthetic/scripted providers. No user runtime data, real curriculum acceptance dataset, credentials, or raw responses are committed.

## Live observations

1. Initial shared-state batch with four **unrelated** query cases: HTTP200, approximately857ms,1033 reported input tokens,0 output tokens. Selected the chemistry option for every case;1/4 matched the expected choice. This request formulation was rejected.
2. Six single-query probes against bilingual metadata: English controlHTTP422; raw Darija chose none (~0.481) instead of projectile; plain Arabic projectile chose the matching option (~0.608); French Newton chose the matching option (~0.809); greeting chose none (~0.644); missing-topic requestHTTP429. We stopped on429. A saved model list was not treated as evaluation acceptance. The422 cause is not established by the sanitized evidence.
3. An initial pipeline harness aborted because it tried to enqueue a second concurrent run. One evaluation occurred before the harness error, but no usable persisted case result was recovered. It is excluded from quality scoring, not counted as success.
4. Corrected real coordinator pipeline with synthetic sources created through extraction/review/publication (known transcription, no paid OCR):
   - Focused literal Darija projectile request,2candidate titles including vertical and oblique: no accepted selection; full content not fetched. **Failed.**
   - Chemistry half-reaction request,1candidate: correct full read. **Passed, low discrimination.**
   - A missing black-hole concept with2lexically overlapping motion candidates: rejected all; no full read. **Passed.**
   - Reported source-selection input usage180/135/182 tokens; output0 for each. Latencies~718/369/465ms.
5. Compact natural metadata formulation,2candidate titles: **selected the wrong vertical source** for an oblique request. Reportedconfidence0.5513,margin0.2837; it passed the numerical thresholds and caused a full read. This is direct evidence that numerical confidence gates are not semantic correctness checks. One197-input-token evaluation,~460ms.
6. An explicit opposite-motion-title filter was then added with offline Arabic/English/negation tests. This narrow backend guard must not be described as LAYA independently understanding the raw question or as universal retrieval quality.

Subsequent guarded pipeline:1 remaining candidate, matching choice confidence0.7208,margin0.4416, actual full read,160reported input tokens/0output tokens,~540ms. **Passed only this narrow, backend-filtered case.** A one-candidate success after this guard does **not** reverse the failed general quality verdict. Multi-source sufficient/stop decisions currently have offline tests only.

## Offline contract checks

Tests cover metadata-only selection, alias validation and uncertainty, actual full reads before teaching, snapshot isolation, greetings with no paid selector call, full context beyond the old tool-result budget, no unadvertised library bypass, a single essential addition, final-answer round reservation, explicit overflow/no silent truncation, no implicit paid connection test, API provider/key forwarding protection, native Claude streaming/tool-result grouping, Claude vision schema calls, public chat/SSE/export source privacy, all decisions preceding all full reads, no duplicate selections, and stopping when the decision model says enough.

Browser test covers independent provider/slot/protocol presets, cleared secret fields, explicit opt-in, no auto-generation, Custom provider switching, and mobile overflow. Browser evidence uses offline fixtures only. **Final local results:254 backend tests and21 browser tests passed; Ruff F checks and TypeScript/Vite build passed.** Native provider and teacher paths in these tests remain offline fixtures; no raw private provider data are present in artifacts.

## Production gate still needed

- A reviewed, private, representative dataset of Arabic/Darija/French questions with several plausible positive/negative candidates; greetings, clarification/follow-ups, exams/exercise bundles, and multi-source requests.
- Measure candidate recall separately from choice accuracy, insufficient-context rejection and wrongly accepted choices. Current title/keyword retrieval is not semantic search.
- Choose a selector that meets the gate; use the same replaceable slot rather than accepting unreliable LAYA choices blindly. Do not silently swap models or bill retries.
- Live test the deployment's selected main model with ordinary student wording, grounded follow-ups, a corrected graph, explicit stop/retry, concurrent users and provider quotas. This change does not prove that these paid teaching tests passed.
- Docker backup/migration7 and API/worker version parity; confirm keys configured in the user's deployment. The provided test key was never pushed or silently installed in their local Docker.
