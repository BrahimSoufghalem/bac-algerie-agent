ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;
CREATE TABLE service_tokens(id TEXT PRIMARY KEY,label TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,creator_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,documents TEXT NOT NULL,expires_at REAL NOT NULL,revoked_at REAL,last_used REAL,created_at REAL NOT NULL);
CREATE TABLE auth_links(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,purpose TEXT NOT NULL CHECK(purpose IN ('reset','verify')),token_hash TEXT UNIQUE NOT NULL,expires_at REAL NOT NULL,used_at REAL,created_at REAL NOT NULL);
CREATE TABLE mail_outbox(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,encrypted_message TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',attempts INTEGER NOT NULL DEFAULT 0,available_at REAL NOT NULL,lease_token TEXT,lease_until REAL,error TEXT,created_at REAL NOT NULL);
CREATE INDEX mail_ready ON mail_outbox(status,available_at,lease_until);
