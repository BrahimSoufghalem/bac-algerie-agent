ALTER TABLE learning_notes ADD COLUMN origin TEXT NOT NULL DEFAULT 'legacy_user';
-- Do not silently promote old user-edited notes to agent-owned memory.
DELETE FROM teaching_materials WHERE kind='self_practice';
-- Private sources are no longer exposed through previously issued read credentials.
UPDATE service_tokens SET revoked_at=strftime('%s','now') WHERE revoked_at IS NULL;
