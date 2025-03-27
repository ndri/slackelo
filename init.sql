CREATE TABLE IF NOT EXISTS players (
    user_id TEXT PRIMARY KEY,
    rating INTEGER DEFAULT 1000
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT,
    timestamp TIMESTAMP
);

CREATE TABLE IF NOT EXISTS player_games (
    user_id TEXT,
    game_id INTEGER,
    rating_before INTEGER,
    rating_after INTEGER,
    position INTEGER,
    PRIMARY KEY (user_id, game_id)
);
