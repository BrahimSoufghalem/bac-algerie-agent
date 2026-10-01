# Initial architecture decisions

- Modular Python monolith, FastAPI, explicit SQLite migrations for the self-hosted MVP, protected local storage and durable workers. Single-host only until PostgreSQL/shared storage are implemented.
- Reuse and namespace BookForge; do not substitute traditional OCR for its Vision structured JSON pipeline. Keep a source-hash reuse manifest and licensing notices (PyMuPDF AGPL/commercial).
- Separate extraction revisions from owner-approved published snapshots. Students/tools can retrieve only published snapshots, never draft/archived content.
- Owner-only durable-library writes. Student chat attachments remain private and temporary.
- One provider/model per agent run. Real tool events, bounded context/steps/timeout, durable SSE replay and cancellation. No model reasoning trace is exposed.
- Examination question set and verified associated solution are a logical retrieval bundle; exercise collections are whole bundles. No inferred official solution linkage.
- Password-based accounts, hashed server-side sessions, CSRF/RBAC/ownership checks. No API keys in browser code.
- BM25 first. Caching keys include publication revision, permissions and filters. No shared cache of personal answers.
- Repository research: OpenCode and OpenAI Agents SDK are maintained MIT projects inspected for patterns; Claude Code repository license states all rights reserved/commercial terms, so no implementation code is copied from it. Full security auditing of upstream projects is not claimed.
