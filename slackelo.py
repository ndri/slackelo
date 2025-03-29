"""
API for interacting with the Slackelo database.
"""

from typing import List
import time
from sqlite_connector import SQLiteConnector
from elo import calculate_group_elo_with_draws


class Slackelo:
    def __init__(self, db_path: str, init_sql_file: str = None):
        self.db = SQLiteConnector(db_path, init_sql_file)

    def get_or_create_player(self, user_id: str):
        """Get or create a player in the players table."""
        player = self.db.execute_query(
            "SELECT * FROM players WHERE user_id = ?", (user_id,)
        )

        if not player:
            self.db.execute_non_query(
                "INSERT INTO players (user_id) VALUES (?)",
                (user_id,),
            )
            player = self.db.execute_query(
                "SELECT * FROM players WHERE user_id = ?", (user_id,)
            )

        return player[0]

    def get_or_create_channel(self, channel_id: str):
        """Get or create a channel in the channels table."""
        channel = self.db.execute_query(
            "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
        )

        if not channel:
            self.db.execute_non_query(
                "INSERT INTO channels (channel_id) VALUES (?)",
                (channel_id,),
            )
            channel = self.db.execute_query(
                "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
            )

        return channel[0]

    def get_or_create_channel_player(self, user_id: str, channel_id: str):
        """Get or create a player's rating for a specific channel."""
        # Ensure player and channel exist
        self.get_or_create_player(user_id)
        self.get_or_create_channel(channel_id)

        channel_player = self.db.execute_query(
            "SELECT * FROM channel_players WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )

        if not channel_player:
            self.db.execute_non_query(
                "INSERT INTO channel_players (user_id, channel_id, rating) VALUES (?, ?, ?)",
                (user_id, channel_id, 1000),
            )
            channel_player = self.db.execute_query(
                "SELECT * FROM channel_players WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            )

        return channel_player[0]

    def create_game(self, channel_id: str, ranked_player_ids: List[List[str]]):
        """
        Create a new game with players in a specific channel.

        Args:
            channel_id: Channel ID where the game took place
            ranked_player_ids: List of lists of player IDs, where each inner list
                               represents players that tied at that position.
                               For example: [["player1"], ["player2", "player3"], ["player4"]]
                               means player1 won, player2 and player3 tied for second,
                               and player4 came in third.
        """
        # Flatten the list to count total players
        flat_player_ids = [
            player for rank in ranked_player_ids for player in rank
        ]

        if len(flat_player_ids) < 2:
            raise Exception("A game must have at least 2 players")

        # Check for duplicate players
        if len(flat_player_ids) != len(set(flat_player_ids)):
            raise Exception("A player cannot be in multiple positions")

        insert_output = self.db.execute_non_query(
            "INSERT INTO games (channel_id, timestamp) VALUES (?, ?)",
            (channel_id, int(time.time())),
        )

        game_id = insert_output["lastrowid"]

        channel_players = []
        player_positions = {}
        position = 1

        # Create a map of player_id to position (accounting for ties)
        for rank_group in ranked_player_ids:
            for player_id in rank_group:
                player_positions[player_id] = position
            position += len(rank_group)

        # Get all channel players
        for player_id in flat_player_ids:
            channel_player = self.get_or_create_channel_player(
                player_id, channel_id
            )
            channel_players.append(channel_player)

        old_ratings = [player["rating"] for player in channel_players]
        new_ratings = calculate_group_elo_with_draws(
            old_ratings,
            [player_positions[player["user_id"]] for player in channel_players],
        )

        # Update ratings for each player
        for i, player in enumerate(channel_players):
            self.db.execute_non_query(
                "INSERT INTO player_games "
                "(user_id, game_id, rating_before, rating_after, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    player["user_id"],
                    game_id,
                    old_ratings[i],
                    new_ratings[i],
                    player_positions[player["user_id"]],
                ),
            )
            self.db.execute_non_query(
                "UPDATE channel_players SET rating = ? WHERE user_id = ? AND channel_id = ?",
                (new_ratings[i], player["user_id"], channel_id),
            )

        return game_id

    def undo_last_game(self, channel_id: str):
        """
        Undo the last game in a specific channel.

        Args:
            channel_id: Channel ID where the game took place
        """
        last_game = self.db.execute_query(
            """
            SELECT g.id, g.timestamp
            FROM games g
            WHERE g.channel_id = ?
            ORDER BY g.timestamp DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if not last_game:
            raise Exception("No games to undo")

        game_id = last_game[0]["id"]
        game_timestamp = last_game[0]["timestamp"]

        # Get all players in the game
        player_games = self.db.execute_query(
            "SELECT * FROM player_games WHERE game_id = ?", (game_id,)
        )

        # Update ratings for each player
        for player_game in player_games:
            self.db.execute_non_query(
                "UPDATE channel_players SET rating = ? WHERE user_id = ? AND channel_id = ?",
                (
                    player_game["rating_before"],
                    player_game["user_id"],
                    channel_id,
                ),
            )

        # Delete the game and player_games
        self.db.execute_non_query("DELETE FROM games WHERE id = ?", (game_id,))
        self.db.execute_non_query(
            "DELETE FROM player_games WHERE game_id = ?", (game_id,)
        )

        return game_timestamp

    def get_player_channel_rating(self, user_id: str, channel_id: str):
        """Get a player's rating for a specific channel."""
        channel_player = self.get_or_create_channel_player(user_id, channel_id)
        return channel_player["rating"]

    def get_channel_leaderboard(self, channel_id: str, limit: int = 10):
        """
        Get the leaderboard for a specific channel.

        Returns player ratings along with the number of games played in the channel.
        """
        leaderboard = self.db.execute_query(
            """
            SELECT p.user_id, cp.rating, COUNT(pg.game_id) as games_played
            FROM channel_players cp
            JOIN players p ON cp.user_id = p.user_id
            LEFT JOIN player_games pg ON p.user_id = pg.user_id
            LEFT JOIN games g ON pg.game_id = g.id
            WHERE cp.channel_id = ?
            AND (g.channel_id = ? OR g.channel_id IS NULL)
            GROUP BY p.user_id, cp.rating
            ORDER BY cp.rating DESC
            LIMIT ?
            """,
            (channel_id, channel_id, limit),
        )
        return leaderboard

    def get_player_game_history(
        self, user_id: str, channel_id: str, limit: int = 10
    ):
        """
        Get the game history for a specific player in a specific channel.

        Args:
            user_id: The user ID to get history for
            channel_id: The channel ID to get history for
            limit: Maximum number of games to return (default: 10)

        Returns:
            List of dictionaries containing game history
        """
        history = self.db.execute_query(
            """
            SELECT
                pg.game_id,
                pg.rating_before,
                pg.rating_after,
                pg.position,
                g.timestamp
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE pg.user_id = ?
            AND g.channel_id = ?
            ORDER BY g.timestamp DESC
            LIMIT ?
            """,
            (user_id, channel_id, limit),
        )

        return history

    def get_player_game_count(self, user_id: str, channel_id: str):
        """
        Get the total number of games a player has participated in within a channel.

        Args:
            user_id: The user ID to count games for
            channel_id: The channel ID to count games in

        Returns:
            Integer count of games
        """
        result = self.db.execute_query(
            """
            SELECT
                COUNT(*) as game_count
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE pg.user_id = ?
            AND g.channel_id = ?
            """,
            (user_id, channel_id),
        )

        if result and "game_count" in result[0]:
            return result[0]["game_count"]
        return 0
