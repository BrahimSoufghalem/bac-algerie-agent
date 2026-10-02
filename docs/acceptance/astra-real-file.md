# Real-provider / real-file acceptance — Astra

**Result: local functional pilot gate passed, with the explicit limits below. This is not an unconditional production-ready verdict.**

Baseline: `47078011b52663e37fd0309efafe6d206ddca7f9`. Credentials, raw provider bodies, source PDF and private full-data backups are excluded from Git. See [sanitized machine-readable evidence](astra-real-file.json).

## Scope and real calls

- Exact user-selected model `ohh/gpt-6-astra` at `https://ohhmyagent.com/v1`.
- Original file: **27 pages**, SHA256 `0f8ae55f3cee1f5387028c13a8269c05d7330c6141fa3598d3dc9914dad8c26e`. Evaluated only the contiguous original PDF pages **1–3**. No claim of whole-book or official-curriculum approval.
- **9 actual generation requests**: one 503, three successful Vision extractions, one concurrent 429, four successful teaching streams. No automatic paid retry loop.
- Gate page 1 success was reused through the original provider/pipeline with an exact rendered-pixel check, without a second paid extraction. Services were closed/reopened at that checkpoint.
- On 429, only failed page 2 was manually retried sequentially; page 1 and page 3 artifact identities stayed unchanged.
- Known Vision usage: **15,429 input + 15,621 output = 31,050 tokens**; **$0.467670** estimate using catalog rates 5/25 USD per million. **Not total cost, not an invoice.** Four SSE teaching calls returned no usage despite requesting it; the two error calls also have unknown usage. Cache usage is unknown, not zero.

## Defects exposed and fixed

1. Repeated top-of-page unit headers created duplicate unit boundaries and doubled the literal label. Coalesce only the still-active, same-kind/title/label ancestor with top-position evidence on both headings; changed parents, TOC targets, labels and mid/same-page headings remain separate. Retain all raw page elements and repeated headings in original content and record evidence. Regression tests cover conservative non-merging cases.
2. Own-content search on non-leaf nodes used only the first populated text field and omitted complex-table cells/headers/footnotes. Index all literal fields while excluding child bodies. Tested synthetically and on the same actual extracted pages packaged hierarchically in an isolated restored-data copy.
3. Source table formulas used `\( … \)` / `\[ … \]`, which CommonMark ate before math rendering. A display-only adapter accepts paired TeX delimiters while leaving code spans/fences, unpaired text and stored source untouched.
4. Inline KaTeX inherited RTL direction. Isolate all math LTR; regression checks `n = m/M` geometric order under Arabic RTL.

## Extraction and retrieval

- Page statuses: SUCCESS / NEEDS_REVIEW / SUCCESS. The page 2 warning is the watermark's `[ILLEGIBLE]`, with original pixels retained; no guessed replacement. Explicit owner acknowledgment was required.
- Visually checked all main table/diagram bounds and selected formulas against source: amount-of-substance/ideal-gas/dilution relations, redox/advancement/titration, reaction-rate and half-time plots. **Not exhaustive character-level OCR certification.**
- Published only an explicit **staging sample**. As a reference, it stays one complete reference node; no invented lessons.
- Additional isolated hierarchical packaging test reused the same cached real extraction with **zero extra model requests**: one original unit spanning PDF pages 1–3, 10 actual sections, 15 tables, 14 figure/image/diagram elements, one standalone equation. Inline/table formulas remain in their original elements; not claimed as standalone equation nodes.
- Both complete reference reads and hierarchical node reads expose original text/assets/structured pages and approved version/source identities. Search of `كمية المادة` reaches the unit's own complex-table cells.
- Service token restricted to the selected publication; other document, owner/config and chat APIs denied. Archive immediately hid search/node/assets; revocation immediately returned 401. `get_lesson` on a reference/unit correctly returned 422: this file has no actual lesson headings. Actual-lesson completeness/parts contracts remain covered by automated regression tests, not falsely attributed to this real file.

## Real teaching flow

One real student prompt completed in four model steps. Actual successful calls: search_library, get_document_metadata, get_table_of_contents, get_section, calculate, verify_calculation. The first render_answer attempted a server-owned image URL, was rejected, and the model corrected it on the next step. No fabricated URL was accepted.

The answer cited the actually read reference, displayed the original half-time graph, and computed the explicitly new user example `8/2 = 4 mol` with separate verification evidence. It distinguished the source's final/maximal progress statement, the new numbers, and the limited numerical scope. It did not claim to have visually inspected pixels through a text retrieval tool.

## Automated and live UI checks

- Backend: **131 passed** (including new running-heading and parent-cell search regressions).
- Production frontend build succeeded. Browser regression: **18 passed**. These automated tests use deterministic fixtures; they are separate from the real-provider evidence above.
- Built UI opened the saved real answer/source at desktop 1440px and mobile 390px: original source images loaded, 183 math renderings in the source reader, zero KaTeX/page errors, no document-level horizontal overflow. Table/cell fallback retains the original raster; it is not claimed as a fully reconstructed merged-table UI.

## Restart, backup and restore

- Actual Uvicorn API + worker processes started/stopped twice with the persistent staging directory; health/login/publication/saved answer/structured page and identical asset SHA256 survived. Idle restarts added no model-usage records. Earlier checkpoint restart resumed pending pages only.
- Stopped all data users before the real full-data backup. Backup/restore included both SQLite databases and both encryption keys: 280 files, 17,461,926-byte archive; integrity/foreign-key checks and decrypted saved model keys passed. Restored login, approved content, answer, structured page and image hash passed. **The archive contains private data and is deliberately not attached or committed.**

## Remaining release gates / operational recommendations

- Evaluate the remaining **24 PDF pages**, and review content before actual student publication. This run does not certify arbitrary books/models.
- For this provider start with `EXTRACTION_WORKERS=1`: a 429 happened at concurrency 2. Availability and limits still depend on the provider. Normal production queue retries remain bounded and respect provider backoff.
- Do not label missing streaming usage/cost as zero. The provider must return usage (or provide a separate trusted billing export) before exact total cost/budget acceptance can be claimed.
- Complete actual-host domain/HTTPS, secure cookies/trusted origins, SMTP verification/recovery and multi-user load/soak testing when the deployment target is available. No Docker runtime was available locally; remote CI container checks are separate.
- Rotate the API key posted in chat before production. Keep model keys server-side; never commit source documents/raw responses/fixture passwords/full-data backups.
