-- Upgrade only the active one-source configuration. Preserve old immutable
-- rows (including queued-run snapshots) and encrypted keys. Do not enable a
-- disabled selector or touch teaching/extraction settings.
CREATE TEMP TABLE selector_multi_upgrade(old_id TEXT PRIMARY KEY,new_id TEXT NOT NULL);
INSERT INTO selector_multi_upgrade
SELECT c.id,'selector_multi_' || lower(hex(randomblob(16)))
FROM context_selectors c JOIN active_selector a ON a.config_id=c.id
WHERE COALESCE(json_extract(c.config,'$.selector_max_sources'),1)=1;
INSERT INTO context_selectors(id,config,encrypted_key,created_at)
SELECT u.new_id,json_set(c.config,'$.selector_max_sources',3),
       c.encrypted_key,CAST(strftime('%s','now') AS REAL)
FROM context_selectors c JOIN selector_multi_upgrade u ON u.old_id=c.id;
UPDATE active_selector
SET config_id=(SELECT new_id FROM selector_multi_upgrade WHERE old_id=active_selector.config_id)
WHERE config_id IN (SELECT old_id FROM selector_multi_upgrade);
DROP TABLE selector_multi_upgrade;