CREATE TABLE context_selectors(id TEXT PRIMARY KEY,config TEXT NOT NULL,encrypted_key TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE active_selector(singleton INTEGER PRIMARY KEY CHECK(singleton=1),config_id TEXT NOT NULL REFERENCES context_selectors(id));
ALTER TABLE agent_runs ADD COLUMN selector_config_id TEXT REFERENCES context_selectors(id);
