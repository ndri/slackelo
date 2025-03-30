CREATE TABLE IF NOT EXISTS players (
    user_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    k_factor INTEGER DEFAULT 32
);

CREATE TABLE IF NOT EXISTS channel_players (
    user_id TEXT,
    channel_id TEXT,
    rating INTEGER DEFAULT 1000,
    PRIMARY KEY (user_id, channel_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id),
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT,
    timestamp TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE TABLE IF NOT EXISTS player_games (
    user_id TEXT,
    game_id INTEGER,
    rating_before INTEGER,
    rating_after INTEGER,
    position INTEGER,
    PRIMARY KEY (user_id, game_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id),
    FOREIGN KEY (game_id) REFERENCES games(id)
);
