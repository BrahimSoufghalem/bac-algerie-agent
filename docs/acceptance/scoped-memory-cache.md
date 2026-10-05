# Scoped conversation memory and cost-aware prompt layout

Baseline: `b6bfa224c478dfe92a2a6bcfa3e9f4def00a80b1`.

## What changed

- Router input now includes a bounded chronological dialogue: up to four previous messages / 6,000 serialized characters, including public assistant equations/tables. The current student message is supplied separately, not duplicated as the latest history entry. No paid summarizer is introduced. Overlong history is omitted as whole messages rather than presented as complete when cut.
- Prior complete reads are remembered using the existing conversation-local `loaded_context` node IDs, version IDs and read scopes. Temporary catalogue aliases are rebuilt for each scoped catalogue, not persisted as identity.
- Only references actually selected for the current request are loaded/delivered. Their bodies are read again through the authorized publication reader; metadata itself never grants evidence credit. An unchanged complete already-read selection can avoid the extra post-read verification LLM call. The router must select `read` for a learning follow-up, not discard it as "already covered".
- New or mixed selections still get full post-read verification. Atomic exams/exercise bundles also retain verification, including supplied solutions. Parts, navigation headings, stale versions, archived documents, excluded documents and foreign study scopes cannot use the bypass.
- The teaching model still checks the actual delivered evidence for relevance/sufficiency, and may request one essential missing reference or ask a clarification. Skipping a repeated body-verification call is NOT proof that an LLM's new intent decision is correct; real-model multi-turn regression testing remains necessary.
- Essential repair includes the original current question as context for the narrowly requested missing reference.
- Older whole dialogue turns may be evicted when the text context fills; the current request, source bodies and policy are never silently truncated. Image transport bytes have separate image/byte guards and are not treated as text tokens.

## Cache/cost design

The full authorized index precedes dynamic state/question in router requests. Actual reference bodies precede changing goals in verification requests. Source payload order is deterministic. Untrusted source text stays user data, never system policy.

Built-in adapters omit the duplicated per-round timer message during working rounds. The server still enforces deadlines, final reserve, final tool choice, source grounding, budgets and tool authorization. A short final execution signal is appended as user scheduling data, not inserted into the stable system prefix. Native Anthropic does not hoist that signal into its system field. Custom adapters retain their prior topology unless they opt into the prefix capability.

Stable declarations are **not blindly forced for every intermediary**:

- Google OpenAI protocol continuity requires them.
- Known direct automatic prefix-cache endpoints (DeepSeek / OpenAI) retain role-scoped declarations.
- A built-in adapter receiving valid provider-reported cache hits may retain them for subsequent rounds.
- An unknown intermediary without measured cache benefit keeps the smaller final manifest to avoid unnecessary cold input cost.

The usage recorder accepts both nested `prompt_tokens_details.cached_tokens` and DeepSeek `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`. Invalid, inconsistent or missing measurements remain unknown, never fabricated zero. Owner-configured price estimates remain estimates, not invoices. No model/provider/prices/keys were changed.

Official cache reference: https://api-docs.deepseek.com/guides/kv_cache
Caching is automatic/best-effort, requires persisted matching prefix units, and is neither durable conversation memory nor an answer cache. No paid cache warm-up calls were added.

## Offline before/after experiment

A controlled 24-turn local replay was run against baseline and updated engine/coordinator code, with the same scripted selections, known synthetic approved source and one teaching response per turn. This is **not** the earlier 24-question real-model accuracy benchmark.

| Actual mocked transport requests | Baseline | Updated |
| --- | ---: | ---: |
| Route selection | 24 | 24 |
| Post-read verification | 24 | 1 |
| Teaching | 24 | 24 |
| Total | 72 | 49 |

These counts demonstrate removed repeated calls in this scenario; they do NOT establish a percentage reduction in real token charges or a universally optimal provider configuration. The additional bounded assistant history has an input cost; the net result depends on real hit/miss rates, model prices, source size and how often the topic changes. Serialized character-prefix proxies in the companion JSON are not tokens or measured cache hits; they are not monetary evidence.

## Regression evidence and scope

The two original memory failures were reproduced before fixing them: follow-ups repeated verification, and router context omitted the preceding assistant answer. New tests cover persistence across fresh Tools objects, alias renumbering, stale/archived/foreign/partial references, other conversations, no-new metadata without source credit, mixed-new verification, essential-repair context, whole-turn eviction, large image transport, safe endpoint detection, real cache field normalization and final protocol enforcement. Existing paired tool replies, private images, thought signatures, publication scope and final-round restrictions remain covered.

No production Docker volumes, source PDFs, published data, user accounts or API secrets were touched. No migration, provider switch, shared final-answer cache, paid model request or new OCR run was performed. This does not make the existing adapter ready for DeepSeek default thinking mode; that separate provider/tool-choice compatibility task remains pending.
