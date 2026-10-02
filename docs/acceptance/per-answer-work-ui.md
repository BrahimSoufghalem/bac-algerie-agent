# Per-answer work drawers and refined Masar utilities

## Scope

- Collapsible work summary between each question and its answer, with independent run identity and saved entries.
- Follow-up, reload, own chat export and personal export preserve earlier summaries. Failed/cancelled requests keep a summary under their question.
- Calm reveal/close animation, bounded timeline, keyboard controls and reduced motion.
- Refined sidebar history and account/settings card/menu; custom private attachment panel with drag/drop, download/delete, privacy/expiry information and inline validation. File actions do not clear or send the draft.
- No new migration. Owner references remain private; original pixels are not displayed or linked. Notes stay agent-managed/read-only; self-practice stays retired.

## Public summary, not chain of thought

The server projects queued/model-start/finalizing/tool-start/tool-end/answer/error event facts into fixed allowlisted labels, generic categories and states. Model text/deltas/reasoning, original event labels, raw tool names, arguments/results, source titles/paths/IDs and internal error codes are excluded.

The drawer is a brief execution/progress summary, not an internal reasoning transcript. Invocation completion does not guarantee the whole explanation is correct. Failed verification is not shown as successful. Legacy messages without saved events receive no invented trace. Opening state can reset on reload; the underlying summary remains.

## Local verification

- **153 backend tests passed**, including five new projection/history/export/replay/cancellation tests.
- **19 browser integration tests passed**, including two new drawer and attachment/settings scenarios.
- TypeScript check, production frontend build and CI-scope Ruff F checks passed.
- Browser scenarios use explicit no-network model fixtures with actual APIs, persistence and scientific tools: wiring/interaction evidence, not model educational-quality certification.
- Follow-up/reload retains each drawer's original identity/entries; drawer precedes answer; light/dark and 360/390px fit; reduced-motion disables transitions; keyboard/Escape/focus restoration work.
- Attachment tests cover over-limit rejection without upload, valid drop, safe deletion, draft preservation and mobile bounds.
- Initial full-suite failure came from test-account concurrency interference after retry. The retry test now waits for actual completion; drawer tests use a dedicated fixture account. The final complete suite passed, not just isolated tests.

No new paid provider requests were made for this UI task. Reopening saved real-provider replies for shell previews is not a fresh provider test. Automated browser screenshots are fixture-based; saved-real-chat previews are separately identified and do not rewrite answers.

## Docker handoff

Back up data and keys first, following [OPERATIONS.md](../OPERATIONS.md). Use the same repository, Compose project, `.env` and production `-f` options if configured:

```bash
git pull --ff-only
docker compose up -d --build api worker
docker compose ps
```

Hard-refresh the browser. Never `docker compose down -v`. Nothing installs automatically on the user's localhost. Updates from older releases also carry migration006's token/self-practice retirement; keep a pre-upgrade backup.

Container build/runtime checks belong to GitHub CI; Docker is not installed in this sandbox. This is not an independent security audit, semantic-confidentiality guarantee or completion of production launch gates.