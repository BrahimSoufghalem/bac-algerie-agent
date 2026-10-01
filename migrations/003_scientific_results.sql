CREATE TABLE scientific_results (
 id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 run_id TEXT REFERENCES agent_runs(id) ON DELETE CASCADE,
 tool TEXT NOT NULL,
 inputs TEXT NOT NULL,
 output TEXT NOT NULL,
 output_sha256 TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX science_conversation ON scientific_results(conversation_id,created_at);
CREATE INDEX science_run ON scientific_results(run_id);
