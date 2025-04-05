-- Update version
INSERT OR REPLACE INTO version (version, applied_at) VALUES ('1.2', CURRENT_TIMESTAMP);

-- Add gambling field to channel_players table
ALTER TABLE channel_players ADD COLUMN gambling INTEGER DEFAULT 0;

-- Add gambled field to player_games table to track if a game was played with double rating change
ALTER TABLE player_games ADD COLUMN gambled INTEGER DEFAULT 0;