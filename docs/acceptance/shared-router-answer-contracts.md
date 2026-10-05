# Shared router and answer contract corrections

## Scope

These are provider-independent configuration and tool-contract corrections following the real-book DeepSeek/TokenHarbor benchmark. They are not a new 24-question benchmark or a claim that low temperature guarantees correct physics.

The changes apply to the router/verifier and teaching agent. Extraction configuration, private reference permissions, source provenance, result authorization and strict server validation are not relaxed. No production database, Docker volume or deployed service was changed during this work.

## Changes

- **Output budget:** the effective teaching and router/verifier limit is at least **6,000 tokens**, retaining any higher configured limit. Old saved configurations with 1,000/1,500-token limits receive the compatibility floor without rewriting historical database rows. New saves and the owner UI advertise the same minimum. This is a ceiling per generation request, not an instruction to generate 6,000 tokens or a 6,000-token ceiling for the entire conversation.
- **Goal contract:** a goal can contain **1–400 characters**. This limit is advertised in the router's function schema and instruction, and checked by the parser. Clarification remains single-line and at most 280 characters. Function declarations advertise the configured goal/source limits without mutating shared declarations. The total distinct selected-source limit is still enforced by the server.
- **Graph contract:** generation manifests for OpenAI-compatible and native Anthropic providers no longer advertise the server-owned `result` property in graph/verification blocks. A graph uses only its `type` and returned `result_id`. The server resolves the authorized scientific result and supplies display data. Google's existing compatible answer-schema adapter uses this same cleanup before its provider-specific simplification. Responses are not silently stripped: fabricated result data and unauthorized IDs still fail strict validation.
- **Answer discipline:** the owner can enable or disable **نمط الإجابة المنضبطة**. This is a local policy limiting the teaching temperature to 0.1 or lower, not a provider `focus`/`reasoning_effort` option and not increased reasoning capacity. It defaults on; disabling it preserves and restores the owner's configured temperature for a model with special temperature requirements. Router/verifier temperature is 0. The local flag is never sent as an unknown API option. Extraction settings are unchanged.
- **Current intent:** the teaching prompt prioritizes the newest request and corrections/exclusions, rather than resuming older unsuccessful questions without permission. It discourages unsolicited plots and lengthy numerical demonstrations for a short conceptual request and explicitly forbids embedding chart arrays/data in a graph block.

## Automated evidence

- Backend suite: **333 passed**, two existing warnings.
- Exact CI lint scope (`ruff`, F rules): passed. Vendored BookForge code is outside that scope and was not changed.
- TypeScript/Vite build: passed.
- Local-only Playwright suite: **29 passed**. Includes the discipline checkbox, recommended 6,000-token setting, disabled router temperature, source/result safeguards, charts and desktop/mobile settings.
- New focused regression module: **12 passed** after formatting. Covers immutable configuration versions, advertised bounds, legacy-budget compatibility, optional local focus and provider request manifests. Anthropic manifest coverage uses a mocked native SSE response, not a live Anthropic call.

## Limited live evidence

### Minimal router probes

Two synthetic catalogue probes used actual API calls:

| Provider path | Requests | HTTP | Effective output ceiling | Temperature |
| --- | ---: | --- | ---: | ---: |
| TokenHarbor `deepseek-v4.1-flash:free`, OpenAI-compatible | 1 | 200 | 6,000 | 0 |
| Official Google `gemini-3.5-flash-lite`, native router | 1 | 200 | 6,000 | 0 |

Both returned the requested catalogue ID. The native Google request accepted the advertised string/array bounds. This tests schema/budget compatibility, not educational quality or all supported model variants.

### Two consecutive real-book messages

An isolated copy of the previously extracted 321-page physics book was used, without new OCR. The old saved router budget was 1,500 and teaching temperature was 1; runtime normalization actually sent a 6,000-token ceiling with router temperature 0 and teaching temperature 0.1.

Only the frozen benchmark's questions **11 and 12** were replayed, consecutively in a new RL conversation, using TokenHarbor's free model for both roles:

1. For L = 0.2 H, R = 40 ohms and E = 6 V: calculate tau, final current and current at tau, and check units.
2. Plot that same current from 0 to 0.025 s and calculate final stored inductive energy.

Both requests completed and delivered final answers. Actual scientific results gave tau = 0.005 s, final current = 0.15 A, current at tau approximately 0.0948180838 A, and stored energy = 0.00225 J. The second request generated a 51-point current plot over the requested interval; its sampled values match `0.15 * (1 - exp(-t / 0.005))` within ordinary floating-point error (maximum absolute error below 3e-17 A). Both model-generated graph blocks contained **only `type` and `result_id`**; the stored/public graph's additional result data came from the server.

These two messages used 12 generation requests: 268,105 reported input tokens, 9,297 output tokens and 152,320 known cached input tokens. Cache usage was unavailable on three requests, not assumed zero. No rate-limit/billing error or paid fallback occurred in this limited probe.

**Remaining quality issues:** question 11 included an unsolicited plot and a replacement-character text artifact. Question 12 added an unsupported general comparison with capacitor energy and did not complete automated dimensional verification of the energy expression; it did not claim that check had succeeded. Correct numerical values and successful tool delivery do not certify every explanatory sentence. Temperature changes and prompt rules are controls, not guarantees.

The original 24-question scores remain historical, unchanged. A fresh complete benchmark is still necessary for a new comparative score, provider/model selection or a claim that the earlier context-switch failures are resolved in live conversations.

## Deployment and privacy

Normal deployment of the GitHub source update applies the compatibility settings; no manual dataset ZIP is required for these code changes. No API keys, private book content, model traces, database files, account identifiers or scientific-result IDs are committed in this report. Provider limits/prices/model identity are not inferred from the model's marketing name. A larger output ceiling can increase cost only when the model actually generates more billed output.
