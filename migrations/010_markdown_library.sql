CREATE TABLE library_cleanup(path TEXT PRIMARY KEY,created_at REAL NOT NULL);
-- Retire extraction activation, preserving old config records for migration history.
DELETE FROM active_models WHERE slot='extraction';
