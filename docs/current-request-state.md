# Current request, references, attachments and diagnostics

## Reference size and scope

The application no longer applies a 60,000-character context ceiling or any
replacement global character ceiling. Legacy `MAX_CONTEXT_CHARS` environment
values and stored model `max_context_chars` are ignored at execution. Actual
provider context windows and output limits still apply; this is not a promise of
unlimited provider capacity. Selected references are delivered whole, not truncated.
Separate per-tool/Python output, upload, image, wall-time and execution limits remain.

The router is instructed to prefer the **smallest sufficient** indexed reference
for the **current** goal, including a meaningful sufficient part over its larger
parent. It must preserve prerequisites, domains and indispensable complementary
material. It must not choose a tiny unrelated fragment or blindly replace a parent.
No index compression, changed catalogue format, extra verifier or paid summarizer
was added. This is a preference, not a programmatic proof of semantic sufficiency.

## Current versus historical dialogue

The original current message is labeled `CURRENT STUDENT REQUEST`. Earlier turns
are labeled `HISTORICAL`, with attempt status when available. Both router and tutor
are told that failed/interrupted attempts are context, never a backlog. Follow-ups
may still refer to a previous explanation; a switch/correction/exclusion overrides
older goals. Server/tool/attachment messages are data, not new student requests.

A bounded **extractive**, own-conversation summary is stored automatically without
an additional model request. It has at most 12 prior requests and 6,000 characters
of model-visible dialogue excerpts. Each entry links the actual question, answer
and run IDs/status; stored SHA-256 digests allow tracing to the original active
message content. It contains no library body, uploaded pixels or tool arguments.
It is explicitly partial history, not semantic certification, mastery, official
facts, read evidence or policy. COMPLETED means publication, not mathematical truth.

The summary is regenerated from active owned messages before reuse/export rather
than trusting its cached text. Edits/retries exclude inactive messages, other chats
and other users are excluded, and chat deletion cascades to the cache. It is not
cross-conversation learner memory. The personal export includes the same sanitized
own-chat partial dialogue without internal digest records. Migration 011 adds the
summary cache and per-run input manifests; migrations remain serialized/idempotent.

## Student attachments (not textbook images)

At enqueue/retry, the server snapshots the currently available own-chat upload IDs.
It revalidates ownership, conversation, expiry and file presence before inference.
This is an **availability inventory**, not a claim that an upload was sent with a
specific sentence or that pixels have been read. Late uploads require a new message
or retry. Deleted/expired/foreign files cannot be inferred from historical wording.

For explicit references to a missing student image/file, the server returns a short
clarification asking for the attachment or typed data before any router/tutor call.
Ordinary plotting/generation or book-image requests are not treated as proof that
an upload exists. An explicit reference to a student-uploaded textbook photo still
requires a real upload. Available files remain unread until the existing private
page tools actually deliver the needed content/pixels; upload metadata is no evidence.
No new book-image retrieval or display capability is added. Other ambiguous wording
is covered by model instructions and may need clarification; the conservative gate
is not a universal intent classifier. Image count/byte limits remain unchanged.

## Provider HTTP 400 investigation

OpenAI-compatible, native Google router and Anthropic transports now attach bounded,
redacted provider diagnostics. Error bodies are inspected transiently up to 16 KiB.
Only allowlisted protocol vocabulary survives the error message; arbitrary text,
quoted values, identifiers, URLs, keys/signatures and source passages become redacted.
Known error field paths may survive, but arbitrary field names do not. Diagnostics
are re-sanitized when exported to the operator report, including tampered old records.

Request **shape**, not contents, is retained: protocol, role sequence, text lengths,
image/tool-call/reply counts, unmatched reply count, schema property/required counts
and output limit. No endpoint, headers, model name, prompt, code, arguments, source
IDs or thought signatures are stored in these diagnostics. They remain operator-only,
not public activity/chat exports. Hints/redacted vocabulary are evidence for debugging,
not a proved explanation of a provider's rejection.

An offline minimal regression reproduces the unstructured-answer repair branch:
rejected ungrounded prose followed by a forced final request returning HTTP 400.
It verifies sanitized evidence, usage accounting, no published fabricated answer,
failed-attempt memory and **no blind paid retry**. It does not reproduce or resolve
the original live provider rejection's unknown cause. All new tests use scripted
transports; a live conversation is still needed to evaluate model selection/teaching.
