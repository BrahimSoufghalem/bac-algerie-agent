-- Reference bodies remain in the library, never in this ID-only ledger.
ALTER TABLE loaded_context ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1));
-- The old read ledger cannot establish an active set. Preserve its IDs as dormant
-- and reselect once on upgrade instead of loading the entire historical library.
UPDATE loaded_context SET active=0;
CREATE TABLE run_reference_state(
 run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL,node_id TEXT NOT NULL,version_id TEXT NOT NULL,
 scope TEXT NOT NULL,scope_id TEXT NOT NULL,
 selected INTEGER NOT NULL DEFAULT 0,loaded INTEGER NOT NULL DEFAULT 0,
 delivered INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 0,used INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,source_id));
CREATE TABLE context_decisions(
 run_id TEXT PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL,decision TEXT,router_requests INTEGER NOT NULL DEFAULT 0,
 essential_requests INTEGER NOT NULL DEFAULT 0,reused_current INTEGER NOT NULL DEFAULT 0,
 sufficiency_gap INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,
 started_at REAL NOT NULL,duration_ms REAL,status TEXT NOT NULL DEFAULT 'running');
