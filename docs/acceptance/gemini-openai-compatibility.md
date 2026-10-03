# Gemini OpenAI compatibility: confirmed defects and unresolved live acceptance

## Evidence and boundaries

The operator reported `HTTP_404`, one model request and zero executed tools for the latest failed run. A subsequent explicit local metadata check reported list HTTP 200, the saved model listed after normalizing Google's `models/` prefix, and `gemini-3.5-flash-lite` metadata HTTP 200. This proves metadata availability/authentication for that check, **not** successful generation or the root cause of the earlier failed run. Run configurations are immutable enqueue snapshots; a failed run may have used a different configuration than the currently saved one.

No Google key was sent to the development environment. Real Google generation acceptance is pending the operator's separately confirmed one-request greeting probe. Do not claim that metadata listing, offline tests or these compatibility changes fix the earlier 404 without a new live result. The earlier six-stage greeting failure and the latest zero-tool 404 report may describe different attempts.

## Follow-up

The operator later reported greeting success but a multi-round lesson failure (`HTTP_400`, 8 model requests, 7 tool calls). This historical report describes the preceding patch only; see [the later final-request protocol and diagnostic work](gemini-final-protocol.md) for current evidence and remaining live acceptance.

## Narrow fixes

1. Model identity normalization is restricted to Google's official HTTPS OpenAI endpoint. `models/NAME` is equivalent to `NAME` for listing comparison; requests use the documented bare name. Other provider namespaces are unchanged; no fuzzy name matching, model substitution, native-API fallback or hidden retry was added.
2. A pure greeting/thanks that omits the optional `response_kind` can be inferred as `conversation` from the actual known simple user question. Existing short-one-text/no-math/no-source/no-warning requirements still apply. Lesson or numeric requests cannot enter this route; greetings containing numbers/math operators are not treated as purely social. Teaching still requires actual delivered read evidence.
3. Gemini's received `extra_content.google.thought_signature` continuity token is preserved across SSE fragments and JSON responses and forwarded with its exact originating function call on the next model round. It is opaque, not decrypted, synthesized or displayed. Arbitrary extra data and reasoning text are dropped. No bypass/dummy signature is invented. Per-token and aggregate metadata limits fail explicitly rather than silently discard required context. Existing total-context/response limits still apply.
4. OpenAI-compatible error objects inside an HTTP-200 SSE/JSON response are handled fail-closed by an allowlisted numeric HTTP code; raw provider error text is not exposed.
5. The operator-only `diagnose-run` report states whether the failed run used the current saved model configuration and whether a newer run exists. It prints no configuration IDs, model keys, prompts, source data or internal thought text. UI connection feedback uses clear human wording rather than a raw true/false suffix, while retaining the warning that GET /models is not a generation/tool/vision test.

Private sources, source-image restrictions, agent-owned read-only notes and independent per-answer attempt drawers are unchanged. No migration, fixed round cap or paid automatic retry was added.

## Verification

- Local backend: **184 passed**, two existing dependency/test warnings.
- Local browser: **20 passed**, covering UI/history/retry/work summaries/science/privacy flows.
- TypeScript/Vite build and Ruff F passed.
- New transport/engine/mode regressions: **16 tests**, no live Google calls.
- Actual Google generation, full tool and vision acceptance remain pending; there is no live-success claim.

Regression fixtures use the real HTTP/SSE parser and AgentEngine with explicit `httpx.MockTransport`, actual publication/read evidence and tool-round continuity. The two-round fixture requires the exact received opaque token on the next request and verifies that it is absent from messages/events persisted in the database. Tests also check namespace isolation, missing-mode greeting acceptance, lesson/numeric/large/math-block rejection, non-streaming privacy, embedded errors, metadata limits and immutable-run configuration diagnostics. These are protocol and privacy tests, **not a live Google or educational-quality certification**.

## Deploy and live acceptance

Back up data and encryption keys, update API and worker together using the same Compose project/env, then hard-refresh:

```bash
git pull --ff-only
docker compose up -d --build api worker
```

Use `https://generativelanguage.googleapis.com/v1beta/openai/` and `gemini-3.5-flash-lite` only if actually available to the project. Set Google's recommended Gemini 3 temperature 1.0; do not silently change the saved provider/model. A new run/retry uses the active saved configuration; an already queued/running run keeps its original snapshot.

The separately supplied operator probe sends one explicit real greeting request with no reference input/tools, reports only safe status/length, records actual observed usage, and requires `--confirm-cost`. It does not establish full tool/vision compatibility. Next acceptance must test an ordinary lesson with an approved relevant reference and then a generated graph on the actual deployment. Keep any failure and its scrubbed diagnostic; no fake success or invented drawer stages.

## Official references

- https://ai.google.dev/gemini-api/docs/openai
- https://ai.google.dev/gemini-api/docs/gemini-3
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
