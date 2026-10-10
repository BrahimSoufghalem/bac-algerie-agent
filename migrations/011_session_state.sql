-- Availability at enqueue time, NOT an assertion that bytes/pixels were read.
-- IDs are deliberately not foreign keys: expiry/deletion must remain detectable.
CREATE TABLE run_input_manifests(
 run_id TEXT PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
 attachment_ids TEXT NOT NULL DEFAULT '[]'
);
-- Own-conversation extractive cache, never cross-chat learner facts or read evidence.
CREATE TABLE conversation_summaries(
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 payload TEXT NOT NULL,
 updated_at REAL NOT NULL
);
