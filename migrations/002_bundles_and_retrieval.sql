ALTER TABLE documents ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';
ALTER TABLE versions ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';
ALTER TABLE versions ADD COLUMN edit_revision INTEGER NOT NULL DEFAULT 0;
UPDATE versions SET metadata=(SELECT json_object('title',d.title,'kind',d.kind,'subject',d.subject,'track',d.track,'year',d.year,'source',d.source) FROM documents d WHERE d.id=versions.document_id);
CREATE TABLE version_files(
 id TEXT PRIMARY KEY,version_id TEXT NOT NULL REFERENCES versions(id),bookforge_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('primary','solution')),first_page INTEGER NOT NULL DEFAULT 1,last_page INTEGER,
 metadata TEXT NOT NULL DEFAULT '{}',verification TEXT NOT NULL DEFAULT 'not_applicable' CHECK(verification IN ('not_applicable','pending','owner_verified')),
 bound_identity TEXT,verified_by TEXT REFERENCES users(id),verified_at REAL,evidence TEXT,UNIQUE(version_id,role));
INSERT INTO version_files(id,version_id,bookforge_id,role) SELECT id||':primary',id,bookforge_id,'primary' FROM versions;
ALTER TABLE published_assets ADD COLUMN file_id TEXT;
ALTER TABLE published_assets ADD COLUMN ordinal INTEGER;
UPDATE published_assets SET file_id=version_id||':primary',ordinal=json_extract(metadata,'$.ordinal');
CREATE INDEX assets_scope ON published_assets(version_id,file_id,ordinal);
CREATE TABLE published_pages(
 file_id TEXT NOT NULL,version_id TEXT NOT NULL REFERENCES versions(id),document_id TEXT NOT NULL REFERENCES documents(id),
 pdf_page INTEGER NOT NULL,printed_page TEXT,image_file TEXT,json_file TEXT,content_file TEXT,
 status TEXT NOT NULL,quality TEXT NOT NULL,languages TEXT NOT NULL DEFAULT '[]',PRIMARY KEY(file_id,pdf_page));
CREATE TABLE published_parts(
 id TEXT PRIMARY KEY,node_id TEXT NOT NULL REFERENCES published_nodes(id),version_id TEXT NOT NULL REFERENCES versions(id),
 part_index INTEGER NOT NULL,content_file TEXT NOT NULL,metadata TEXT NOT NULL,UNIQUE(node_id,part_index));
ALTER TABLE loaded_context ADD COLUMN scope TEXT NOT NULL DEFAULT 'full';
ALTER TABLE loaded_context ADD COLUMN scope_id TEXT;
CREATE INDEX parts_node ON published_parts(node_id,part_index);
CREATE TABLE published_files(id TEXT PRIMARY KEY,version_id TEXT NOT NULL REFERENCES versions(id),document_id TEXT NOT NULL REFERENCES documents(id),role TEXT NOT NULL,content_file TEXT NOT NULL,source_pdf TEXT NOT NULL,metadata TEXT NOT NULL);
CREATE TABLE published_elements(id TEXT PRIMARY KEY,version_id TEXT NOT NULL REFERENCES versions(id),file_id TEXT NOT NULL,ordinal INTEGER NOT NULL,type TEXT NOT NULL,pdf_page INTEGER NOT NULL,metadata TEXT NOT NULL,asset_id TEXT);
CREATE INDEX elements_scope ON published_elements(version_id,file_id,ordinal);
