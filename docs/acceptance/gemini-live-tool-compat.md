# Gemini live tool-protocol acceptance

Base: `95ef1d8e9d34ef9cc26c95ab1754d9a994410899`. Model: `gemini-3.5-flash-lite`, official Google AI Studio.

## Failures reproduced against the real API

- Parallel streamed calls carried distinct real `id` values but `index: null`. The old assembler collapsed them into index zero, concatenating names such as five repeated `calculate` calls. The resulting history was rejected with HTTP 400. This was an adapter defect, not evidence of incorrect physics reasoning.
- Forced `render_answer` with the full Pydantic discriminated-union schema returned HTTP 400. A plain answer schema returned HTTP 200, including when sent with the entire coordinated 19-tool manifest. The plain schema keeps block fields explicit; strict `PresentedAnswer`, source-grounding, graph-result authorization and all size limits remain server-side and unchanged.
- Requiring *all* tools in working rounds was rejected by Google for this manifest. That experiment was reverted. Working rounds retain automatic tool choice; the final round still explicitly forces `render_answer`.

## Changes

- Google-only streamed ID fallback when an index is null/missing; reject ambiguous unsigned/unidentified fragments instead of inventing call identity. Forward only actually received opaque continuity signatures.
- Google-only plain `render_answer` wire schema, without modifying callers' manifests or changing strict execution contracts.
- Explicitly state the existing six-call-per-turn bound in teacher instructions.
- Safe error hints recognize a single-item Google error envelope; topology tolerates a string tool-choice value. Provider text, keys and reasoning are never persisted in diagnostics.

## Local checks

321 backend tests passed on the final automatic-working-round version. New tests cover null and omitted indices, independent calls, preserved real signature placement, ambiguous fragments, non-mutating schema conversion and unchanged strict server validation.

The live educational benchmark uses the previously extracted 321-page physics book in an isolated database, not the user's production Docker data. The book still has 28 unresolved detailed TOC matches from its earlier draft review. Educational accuracy and first-pass failures are reported separately from transport/unit acceptance; a successful HTTP response is not an educational accuracy score.

Cache is a subset of input. Missing provider counters are unknown, not zero. Native Google total output includes candidate and thinking tokens as reported by UsageMetadata; internal thought text is never collected. Earlier diagnostic attempts are charged to a separate ledger, not erased from the test's accounting.
