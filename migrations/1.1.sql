INSERT OR REPLACE INTO version (version, applied_at) VALUES ('1.1', CURRENT_TIMESTAMP);

ALTER TABLE channels ADD COLUMN team_id TEXT;
