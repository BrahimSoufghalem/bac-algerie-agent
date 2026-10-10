# Markdown library transition — local acceptance

## Scope

Based on PR26 head `995bef437385dcf9f62b7047440202d3447ca957`, retaining the shared 6000-token minimums and safe answer/router contracts. No main merge, production deployment, production deletion, full attached-book inspection/import, or paid generation call was performed.

Owner library uploads are Markdown-only. Trailing owner metadata feeds the router catalogue; actual bodies go directly to the tutor after authorization/version/budget checks, without a second semantic-verification model request. Retired owner PDF-processing/re-extraction/model endpoints and runtime worker are removed. Already-published legacy snapshots remain readable; raw legacy drafts require Markdown reupload.

All predefined track/subject pairs appear in inventory, including zero-file rows. Counts are distinct current primary source documents, not versions, sections, or attached solutions. The owner can remove one file, one subject's contents in a track, or the same subject across all tracks, with category scope and fresh explicit confirmation. Track-only removal preserves shared files elsewhere and subject definitions remain.

## Regressions exercised

- Fenced YAML, unlabeled fences, unfenced/missing-opening-fence metadata; source fidelity, formulas and table/proof atomicity; invalid encoding, ambiguous trailing content, bodyless/incomplete metadata and aliases rejected.
- No extraction service/database/model usage on fresh startup or import/review/publish; PDF uploads and retired APIs refused; existing private library authorization and CSRF rules retained.
- Frozen reviewed snapshots, stale edit revisions, immutable approved metadata, reclassification requiring reupload, distinct-document counts, zero-file curriculum coverage.
- Category/file/global deletion, preview-fingerprint conflict, shared-track retention, loaded-context authorization, run cancellation and durable owned-file cleanup.
- Metadata-only catalogue; no second source-body verification call, including mixed existing/new sources. Router malformed-response and honest clarification/budget/graph authorization tests retained.
- Browser upload, math preview, review and publish; desktop, 390px mobile and dark mode; category/track scope, cancel and exact remove-request intent. Native select/checkbox states are preserved in local QA snapshots; password values excluded.

## Verification

- Backend: **318 passed**, with two known warnings (Starlette TestClient deprecation and deliberately duplicated ZIP entry in a restore rejection test).
- Exact CI `ruff --select F` scope: **passed**.
- `npm run build` (TypeScript + Vite): **passed**.
- Complete browser suite: **31 passed**. An additional delayed-preview cancellation regression was then added; the focused Markdown suite **4 passed**, including that new case. No production provider is used by these tests.
- Visual QA: inspected inventory desktop/mobile/dark, source and KaTeX preview, upload and explicit scoped-delete dialog. Forms and wide-table scroll behavior verified at delivery sizes. Browser uses synthetic sources and a test-only fake teacher; no claim about teaching quality, unseen books, third-party model accuracy, production concurrency or Docker deployment.

GitHub Advanced Security secret scanning was unavailable for this repository. A local targeted credential-pattern and file-path review found no matches; this is not an exhaustive secret-security certification. No data directory, encryption keys, source books, real credentials, raw traces, screenshots or dependency symlink are included.

## Operational limits

Back up data and encryption keys, test restore, then update API and worker together. Migration010 removes only active extraction-slot selection and adds cleanup queue; encrypted historical settings/keys and prior migrations are retained. Shared vendor storage/contracts remain, but the old extraction engine is not initialized by the platform.

Deletion preserves subject definitions, prior conversations and external backups. Legacy raw extraction files may remain physically stored; authorization is revoked and owned snapshots/new Markdown files are cleaned. Cleanup failure remains queued and is retried on startup. No automatic production-data purge.

Router summaries are owner-supplied routing hints, not proof that a body is sufficient. The tutor receives actual content; unsupported/oversized atomic sources are not silently truncated. No model validates or repairs uploaded Markdown. Large real-book/provider-quality and Docker/HTTPS tests were not run in this task.
