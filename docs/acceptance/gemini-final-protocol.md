# Gemini multi-round/final request protocol and private error diagnostics

## Operator evidence, not a guessed cause

After the previous compatibility patch, the operator reported that a plain greeting succeeded. Ordinary Darija projectile-motion teaching and a follow-up still failed. The latest scrubbed report showed `FAILED / HTTP_400`, **8 model requests / 7 executed tool calls**, current configuration true, no newer run, and two private review diagnostics (`OTHER_FAILURE`, `TOOL_INPUT_OR_SOURCE_ERROR`).

This is not a fixed model-round cap. It confirms a rejected provider request after tool work, but does **not** establish the provider's reason, whether the last request was forced-final, which source was read, or topic relevance. The previous diagnostic intentionally omitted the raw provider error. The operator has not yet confirmed an approved reference covering projectile motion. Greeting/listing success is not full tool/vision acceptance.

No Google credential is present in development. This patch uses explicit offline HTTP/SSE fixtures; it does not claim to reproduce or fix the exact live rejection without a new deployment result.

## Changes

1. **Stable Google tool manifest.** For the exact official Google HTTPS OpenAI endpoint only, the original role-scoped declarations remain on later requests, including forced-final and paused-search requests. Prior function-call history is no longer paired with a pruned declaration list. The transient final policy, forced `render_answer` choice and server-side only-terminal-call rule remain. Keeping a declaration does not grant permission to execute it. Other providers keep their existing pruning. Received opaque continuity tokens remain exact and private.
2. **Contiguous parallel responses.** All tool replies in an assistant batch precede any separately delivered user image messages. Model-only pixels cannot split a tool-response turn. Existing image size/count limits remain; source scans are still forbidden in the answer/UI.
3. **Seen evidence, not same-batch credit.** A newly read source is eligible only after a subsequent valid model response to the request that contains its actual tool result/pixels. `render_answer` is a sole terminal call, never parallel with reads/calculations/saves. Same-batch read+save cannot pre-credit a teacher material. Restored, freshly validated source context remains reusable. Prompt/tool descriptions explain these requirements. This enforces structural delivery, **not semantic relevance or correctness certification**.
4. **Honest progress and source diagnostics.** Paused search receives a paired unavailable outcome without execution. Size/image-budget checks happen before successful public outcomes. Fixed source-size/atomic-bundle/access/not-ready/kind-mismatch codes replace ambiguous categories where identifiable. Oversized corrective feedback retains its root private code plus a result-budget code; no reading credit or truncated reference is invented.
5. **Private provider hints and topology.** A non-200 error body is inspected transiently with a 16 KiB bound; embedded JSON/SSE errors use the same safe classifier. Only fixed hint/status enums and request-shape counts are retained, never the raw message, payload, field paths, key, model thought text, file/source IDs, function names or arguments. A `provider_diagnostic` event is written only in the fenced terminal transaction and is excluded from public SSE, per-answer drawers, history and privacy exports. The local operator CLI re-sanitizes stored payloads.

No migration, model substitution, native fallback, automatic paid retry, lifted read gate or fixed total-step limit was added. Existing time/context/account/no-progress guards remain. Finalizing early enough is still important.

## Interpreting the local report

`docker compose exec -T api python -m bac.cli diagnose-run` adds `provider_diagnostics`, up to 40 entries (tool diagnostics also remain bounded to 40). Each entry contains:

- `http_status`, an allowed numeric HTTP error status, and `status`, a fixed provider-status enum or `UNKNOWN`;
- `hint`, a fixed error-message classification such as signature, declaration/history/schema/choice, role, context or media rejection, otherwise `REQUEST_INVALID_UNKNOWN`;
- `forced_final` (boolean), `declared_tool_count`, `prior_tool_calls`, `missing_declaration_count`, `signed_prior_tool_calls` (counts only).

A hint is **not proof of cause**; it does not automatically change execution or retry. Non-JSON/oversized/unrecognized error bodies remain unknown, not printed. Old failed runs have no retrospectively invented hints. `uses_current_model_config` and `newer_run_exists` must still be checked. Do not share raw logs, a database, Google error bodies, book content or a key.

## Verification

Local verification on the final code:

- **217 backend tests passed**, including **33 new offline protocol/diagnostic regressions**; two existing dependency/test warnings.
- **20 browser tests passed**, including independent drawers/retries/reload/mobile/privacy flows.
- TypeScript/Vite build and Ruff F passed.
- **Zero live Google generation requests** were made for this patch. Actual operator deployment acceptance remains pending.

GitHub verification/container checks must pass before merge. New regressions use the real AgentEngine, OpenAI HTTP/SSE adapter and reviewed/published synthetic source pipeline, with explicit MockTransport. They cover stable final declaration/history pairing, forced-final execution restrictions, other-provider isolation, same-batch read/render and read/material prevention, parallel image ordering, paired paused-search outcomes, bounded private error handling across non-200/JSON/SSE, tampered stored diagnostics, and source-budget failure without credit. The fake provider rejection is an explicit fixture, not evidence about the operator's live Google error. Browser fixtures remain offline and test presentation/privacy/history persistence, not educational quality.

## Deploy and one fresh acceptance attempt

Back up the persistent data volume **and encryption keys**. Keep the same Compose project, env and volumes; update API and worker together:

```bash
git pull --ff-only
docker compose up -d --build api worker
```

Hard-refresh and start a fresh attempt. Keep the configured Google endpoint/model/key unchanged; do not reuse raw paid probes or loop on the failure. Confirm that a reviewed/published internal reference covers nonvertical projectile motion. Ask an ordinary student question without tool instructions, then request a generated velocity/acceleration explanation graph only if teaching succeeds. A missing relevant source must produce a brief honest clarification, not memory-only teaching. Original reference files/images remain confidential.

If the fresh run fails, share only the local `diagnose-run` output. The new hints/topology plus fixed source failures allow the next change to address observed evidence rather than blindly increase limits or relax grounding. Actual live Google tool/vision compatibility and educational interpretation remain pending operator acceptance.
