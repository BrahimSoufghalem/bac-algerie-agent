# TokenHarbor free-route acceptance — BLOCKED

This is a real provider compatibility check, not final production acceptance.
Tested source: `47078011b52663e37fd0309efafe6d206ddca7f9`.
The local chat provider, Vision provider, PageDocument schema and extraction prompt were verified byte-for-byte against their Git blob hashes at that commit. The full latest application was not booted in this check.

## Route and constraints

- Base URL: `https://tokenharbor.ai/v1`; OpenAI Chat Completions format (`/chat/completions`).
- Selected model: **`deepseek-v4.1-flash:free`** for every generation request.
- The authenticated `/models` catalog advertises zero input/output prices for this explicit free suffix. No paid model, suffix removal, model fallback, or automatic retry was used. This is the provider's catalog declaration, not an invoice audit.
- Exactly **3 generation requests**: 2 Vision requests and 1 streamed tool-capability request.
- API key was never placed in source files or committed. A private temporary key file was removed after testing.

## Actual results

| Check | Outcome |
|---|---|
| Teaching tool call | Passed: one valid `render_answer` call, exact expected fixture source ID, expected numeric result `24` |
| Vision, 1,600 output-token cap | `OUTPUT_TRUNCATED`; no valid complete page was accepted |
| Vision, separately announced 6,000 cap | `OUTPUT_TRUNCATED`; no valid complete page was accepted |
| Provider regression tests | 4 passed; all mocked, no generation requests |
| Requested DZExams PDF | Blocked: HTTP 403 directly and with browser-session download; Cloudflare verification remained pending |

The image used for compatibility was an existing **synthetic** Arabic/English page with two columns, two diagrams, a table and an equation. It was not the user's requested PDF. Its visual content was checked before use. No extraction-quality claim, original-content preservation claim, real-book publication, or lesson retrieval acceptance is made from these checks.

Truncated Vision responses correctly remained failures, rather than being published as usable knowledge. The cause is not proven: these outcomes alone do not establish that the model lacks vision, nor that a production-sized output budget would succeed. A valid complete structured page and manual source comparison remain required. Increasing limits indefinitely or falling back to a billed route is not acceptable.

Only the successful teaching request exposed saved usage (385 input + 172 output tokens). The provider's early truncation error path does not currently persist usage for failed Vision responses. Total token use across all three calls is therefore **unknown**, not 557 and not zero.

## Remaining acceptance gates

1. Receive the exact requested PDF as a user attachment (or an accessible same-source download).
2. Resolve bounded Vision output completion on the explicitly free DeepSeek route, then inspect transcription, reading order, bboxes, original crops, table values and equation fidelity against the real PDF.
3. Boot the complete current committed app in staging and test review/publication, student teaching, scoped external-agent retrieval, permissions/revocation, restart/resume and backup/restore on that source.
4. Validate the user's actual production host: TLS, trusted origin/cookies, real SMTP if enabled, realistic network load, resource limits and operational/legal release checks.

**Do not mark this report or the release as accepted.** It records blockers honestly and makes no changes to production model configuration.
