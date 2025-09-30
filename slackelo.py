"""
API for interacting with the Slackelo database.
"""

from typing import List, Dict, Tuple, Any, Optional, cast
import time
from sqlite_connector import SQLiteConnector
from elo import calculate_group_elo_with_draws

DEFAULT_K_FACTOR = 32


class Slackelo:

    def __init__(
        self,
        db_path: str,
    ):
        self.db: SQLiteConnector = SQLiteConnector(db_path)

    def get_or_create_player(self, user_id: str) -> Dict[str, Any]:
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

    def get_or_create_channel(self, channel_id: str, team_id: str = None) -> Dict[str, Any]:
        """Get or create a channel in the channels table."""
        channel = self.db.execute_query(
            "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
        )

        if not channel:
            self.db.execute_non_query(
                "INSERT INTO channels (channel_id, k_factor, team_id) VALUES (?, ?, ?)",
                (channel_id, DEFAULT_K_FACTOR, team_id),
            )
            channel = self.db.execute_query(
                "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
            )
        elif team_id and channel[0]["team_id"] is None:
            # Update team_id if it's provided and currently null
            self.db.execute_non_query(
                "UPDATE channels SET team_id = ? WHERE channel_id = ? AND team_id IS NULL",
                (team_id, channel_id),
            )
            channel = self.db.execute_query(
                "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
            )

        return channel[0]

    def get_or_create_channel_player(
        self, user_id: str, channel_id: str
    ) -> Dict[str, Any]:
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
                "INSERT INTO channel_players (user_id, channel_id, rating, gambling) VALUES (?, ?, ?, ?)",
                (user_id, channel_id, 1000, 0),
            )
            channel_player = self.db.execute_query(
                "SELECT * FROM channel_players WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            )

        return channel_player[0]
        
    def toggle_player_gambling(self, user_id: str, channel_id: str) -> bool:
        """
        Toggle a player's gambling status for the next game.
        
        Args:
            user_id: The player's user ID
            channel_id: The channel ID
            
        Returns:
            The new gambling status (True if gambling, False if not)
        """
        # Make sure the player exists in the channel
        channel_player = self.get_or_create_channel_player(user_id, channel_id)
        
        # Toggle gambling status
        current_status = bool(channel_player.get("gambling", 0))
        new_status = not current_status
        
        self.db.execute_non_query(
            "UPDATE channel_players SET gambling = ? WHERE user_id = ? AND channel_id = ?",
            (1 if new_status else 0, user_id, channel_id),
        )
        
        return new_status
        
    def is_player_gambling(self, user_id: str, channel_id: str) -> bool:
        """
        Check if a player is gambling for the next game.
        
        Args:
            user_id: The player's user ID
            channel_id: The channel ID
            
        Returns:
            True if the player is gambling, False otherwise
        """
        channel_player = self.get_or_create_channel_player(user_id, channel_id)
        return bool(channel_player.get("gambling", 0))

    def get_channel_k_factor(self, channel_id: str) -> int:
        """Get the k-factor for a specific channel."""
        channel = self.get_or_create_channel(channel_id)
        return (
            channel["k_factor"]
            if channel["k_factor"] is not None
            else DEFAULT_K_FACTOR
        )

    def set_channel_k_factor(self, channel_id: str, k_factor: int) -> bool:
        """
        Set the k-factor for a specific channel.

        Args:
            channel_id: Channel ID to update
            k_factor: New k-factor value (must be a positive integer)

        Returns:
            True if successful, False otherwise
        """
        if k_factor <= 0:
            raise ValueError("K-factor must be a positive integer")

        # Ensure channel exists
        self.get_or_create_channel(channel_id)

        # Update the k-factor
        self.db.execute_non_query(
            "UPDATE channels SET k_factor = ? WHERE channel_id = ?",
            (k_factor, channel_id),
        )

        return True

    def create_game(
        self, channel_id: str, ranked_player_ids: List[List[str]], team_id: str = None
    ) -> int:
        """
        Create a new game with players in a specific channel.

        Args:
            channel_id: Channel ID where the game took place
            ranked_player_ids: List of lists of player IDs, where each inner list
                               represents players that tied at that position.
                               For example: [["player1"], ["player2", "player3"], ["player4"]]
                               means player1 won, player2 and player3 tied for second,
                               and player4 came in third.
            team_id: Team ID where the game took place

        Returns:
            The ID of the newly created game
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

        # Make sure channel exists and has team_id set
        self.get_or_create_channel(channel_id, team_id)

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

        # Get channel-specific k-factor
        k_factor = self.get_channel_k_factor(channel_id)

        old_ratings = [int(player["rating"]) for player in channel_players]
        rating_changes = calculate_group_elo_with_draws(
            old_ratings,
            [player_positions[player["user_id"]] for player in channel_players],
            k_factor=k_factor,
        )

        # Update ratings for each player, accounting for gambling
        for i, player in enumerate(channel_players):
            is_gambling = bool(player.get("gambling", 0))
            
            # Apply gambling multiplier if player is gambling
            multiplier = 2 if is_gambling else 1
            adjusted_change = rating_changes[i] * multiplier
            new_rating = old_ratings[i] + adjusted_change
            
            self.db.execute_non_query(
                "INSERT INTO player_games "
                "(user_id, game_id, rating_before, rating_after, position, gambled) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    player["user_id"],
                    game_id,
                    old_ratings[i],
                    new_rating,
                    player_positions[player["user_id"]],
                    1 if is_gambling else 0,
                ),
            )
            
            # Reset gambling status if player was gambling
            if is_gambling:
                self.db.execute_non_query(
                    "UPDATE channel_players SET rating = ?, gambling = 0 WHERE user_id = ? AND channel_id = ?",
                    (new_rating, player["user_id"], channel_id),
                )
            else:
                self.db.execute_non_query(
                    "UPDATE channel_players SET rating = ? WHERE user_id = ? AND channel_id = ?",
                    (new_rating, player["user_id"], channel_id),
                )

        return game_id

    def simulate_game(
        self, channel_id: str, ranked_player_ids: List[List[str]], team_id: str = None
    ) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, int]]:
        """
        Simulate a game to calculate rating changes without saving to the database.

        Args:
            channel_id: Channel ID where the simulation is taking place
            ranked_player_ids: List of lists of player IDs, where each inner list
                              represents players that tied at that position.
            team_id: Team ID where the simulation is taking place

        Returns:
            Tuple containing:
            - pre_game_ratings: Dictionary mapping player_id to current rating
            - post_game_ratings: Dictionary mapping player_id to simulated new rating
            - player_positions: Dictionary mapping player_id to position in the game
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
            
        # Make sure channel exists and has team_id set
        self.get_or_create_channel(channel_id, team_id)

        # Get player positions
        player_positions = {}
        position = 1

        for rank_group in ranked_player_ids:
            for player_id in rank_group:
                player_positions[player_id] = position
            position += len(rank_group)

        # Get pre-game ratings
        pre_game_ratings = {}
        for player_id in flat_player_ids:
            pre_game_ratings[player_id] = self.get_player_channel_rating(
                player_id, channel_id
            )

        # Get channel-specific k-factor
        k_factor = self.get_channel_k_factor(channel_id)

        # Calculate rating changes
        current_ratings = list(pre_game_ratings.values())
        positions_list = [
            player_positions[player_id] for player_id in flat_player_ids
        ]

        rating_changes = calculate_group_elo_with_draws(
            current_ratings, positions_list, k_factor=k_factor
        )

        # Map new ratings to player IDs, accounting for gambling
        post_game_ratings = {}
        for i, player_id in enumerate(flat_player_ids):
            # Check if player is gambling
            player_gambling = self.is_player_gambling(player_id, channel_id)
            
            # Apply gambling multiplier if player is gambling
            multiplier = 2 if player_gambling else 1
            adjusted_change = rating_changes[i] * multiplier
            
            post_game_ratings[player_id] = current_ratings[i] + adjusted_change

        return pre_game_ratings, post_game_ratings, player_positions

    def undo_last_game(self, channel_id: str) -> int:
        """
        Undo the last game in a specific channel.

        Args:
            channel_id: Channel ID where the game took place

        Returns:
            The timestamp of the undone game
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

    def get_player_channel_rating(self, user_id: str, channel_id: str) -> int:
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
    ) -> List[Dict[str, Any]]:
        """
        Get the game history for a specific player in a specific channel.

        Args:
            user_id: The user ID to get history for
            channel_id: The channel ID to get history for
            limit: Maximum number of games to return (default: 10)

        Returns:
            List of dictionaries containing game history
        """
        history: List[Dict[str, Any]] = self.db.execute_query(
            """
            SELECT
                pg.game_id,
                pg.rating_before,
                pg.rating_after,
                pg.position,
                g.timestamp,
                pg.gambled
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

    def get_player_game_count(self, user_id: str, channel_id: str) -> int:
        """
        Get the total number of games a player has participated in within a channel.

        Args:
            user_id: The user ID to count games for
            channel_id: The channel ID to count games in

        Returns:
            Integer count of games
        """
        result: List[Dict[str, Any]] = self.db.execute_query(
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
            return int(result[0]["game_count"])
        return 0

    def get_channel_statistics(self, channel_id: str) -> Dict[str, Any]:
        """
        Get various statistics for a channel.

        Args:
            channel_id: The channel ID to get statistics for

        Returns:
            Dictionary containing channel statistics
        """
        stats = {}

        # Highest rating ever achieved
        highest_rating = self.db.execute_query(
            """
            SELECT pg.user_id, MAX(pg.rating_after) as highest_rating
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            GROUP BY pg.user_id
            ORDER BY highest_rating DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if highest_rating:
            stats["highest_rating"] = {
                "user_id": highest_rating[0]["user_id"],
                "rating": int(highest_rating[0]["highest_rating"])
            }

        # Lowest rating ever achieved
        lowest_rating = self.db.execute_query(
            """
            SELECT pg.user_id, MIN(pg.rating_after) as lowest_rating
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            GROUP BY pg.user_id
            ORDER BY lowest_rating ASC
            LIMIT 1
            """,
            (channel_id,),
        )

        if lowest_rating:
            stats["lowest_rating"] = {
                "user_id": lowest_rating[0]["user_id"],
                "rating": int(lowest_rating[0]["lowest_rating"])
            }

        # Biggest rating increase in one game
        biggest_increase = self.db.execute_query(
            """
            SELECT pg.user_id, pg.rating_after - pg.rating_before as rating_change, g.timestamp
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            ORDER BY rating_change DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if biggest_increase and biggest_increase[0]["rating_change"] > 0:
            stats["biggest_increase"] = {
                "user_id": biggest_increase[0]["user_id"],
                "change": int(biggest_increase[0]["rating_change"])
            }

        # Biggest rating decrease in one game
        biggest_decrease = self.db.execute_query(
            """
            SELECT pg.user_id, pg.rating_after - pg.rating_before as rating_change, g.timestamp
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            ORDER BY rating_change ASC
            LIMIT 1
            """,
            (channel_id,),
        )

        if biggest_decrease and biggest_decrease[0]["rating_change"] < 0:
            stats["biggest_decrease"] = {
                "user_id": biggest_decrease[0]["user_id"],
                "change": int(biggest_decrease[0]["rating_change"])
            }

        # Most wins (1st place finishes)
        most_wins = self.db.execute_query(
            """
            SELECT pg.user_id, COUNT(*) as win_count
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ? AND pg.position = 1
            GROUP BY pg.user_id
            ORDER BY win_count DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if most_wins:
            stats["most_wins"] = {
                "user_id": most_wins[0]["user_id"],
                "wins": int(most_wins[0]["win_count"])
            }

        # Most losses (last place finishes)
        most_losses = self.db.execute_query(
            """
            SELECT pg.user_id, COUNT(*) as loss_count
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            AND pg.position = (
                SELECT MAX(position)
                FROM player_games
                WHERE game_id = pg.game_id
            )
            GROUP BY pg.user_id
            ORDER BY loss_count DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if most_losses:
            stats["most_losses"] = {
                "user_id": most_losses[0]["user_id"],
                "losses": int(most_losses[0]["loss_count"])
            }

        # Most games played
        most_games = self.db.execute_query(
            """
            SELECT pg.user_id, COUNT(*) as game_count
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            GROUP BY pg.user_id
            ORDER BY game_count DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if most_games:
            stats["most_games"] = {
                "user_id": most_games[0]["user_id"],
                "games": int(most_games[0]["game_count"])
            }

        # Most volatile player (highest standard deviation in rating changes)
        most_volatile = self.db.execute_query(
            """
            SELECT
                pg.user_id,
                AVG((pg.rating_after - pg.rating_before) * (pg.rating_after - pg.rating_before)) as variance,
                COUNT(*) as game_count
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            GROUP BY pg.user_id
            HAVING game_count >= 3
            ORDER BY variance DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if most_volatile:
            stats["most_volatile"] = {
                "user_id": most_volatile[0]["user_id"],
                "volatility": round(most_volatile[0]["variance"] ** 0.5, 2)
            }

        # Most consistent player (lowest standard deviation in rating changes, min 3 games)
        most_consistent = self.db.execute_query(
            """
            SELECT
                pg.user_id,
                AVG((pg.rating_after - pg.rating_before) * (pg.rating_after - pg.rating_before)) as variance,
                COUNT(*) as game_count
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            GROUP BY pg.user_id
            HAVING game_count >= 3
            ORDER BY variance ASC
            LIMIT 1
            """,
            (channel_id,),
        )

        if most_consistent:
            stats["most_consistent"] = {
                "user_id": most_consistent[0]["user_id"],
                "volatility": round(most_consistent[0]["variance"] ** 0.5, 2)
            }

        # Longest win streak (consecutive 1st place finishes)
        # This requires more complex logic, so we'll fetch all games for players and calculate
        all_games = self.db.execute_query(
            """
            SELECT pg.user_id, pg.position, g.timestamp
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            ORDER BY pg.user_id, g.timestamp
            """,
            (channel_id,),
        )

        if all_games:
            # Calculate win streaks
            current_streak = 0
            max_streak = 0
            max_streak_user = None
            current_user = None

            for game in all_games:
                if game["user_id"] != current_user:
                    current_user = game["user_id"]
                    current_streak = 0

                if game["position"] == 1:
                    current_streak += 1
                    if current_streak > max_streak:
                        max_streak = current_streak
                        max_streak_user = game["user_id"]
                else:
                    current_streak = 0

            if max_streak > 1:
                stats["longest_win_streak"] = {
                    "user_id": max_streak_user,
                    "streak": max_streak
                }

        # Biggest comeback (lowest rating to highest rating)
        biggest_comeback = self.db.execute_query(
            """
            SELECT
                pg.user_id,
                MIN(pg.rating_after) as lowest_rating,
                MAX(pg.rating_after) as highest_rating,
                MAX(pg.rating_after) - MIN(pg.rating_after) as comeback
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            GROUP BY pg.user_id
            HAVING comeback > 0
            ORDER BY comeback DESC
            LIMIT 1
            """,
            (channel_id,),
        )

        if biggest_comeback and biggest_comeback[0]["comeback"] > 100:
            stats["biggest_comeback"] = {
                "user_id": biggest_comeback[0]["user_id"],
                "comeback": int(biggest_comeback[0]["comeback"]),
                "from": int(biggest_comeback[0]["lowest_rating"]),
                "to": int(biggest_comeback[0]["highest_rating"])
            }

        # Total games played in channel
        total_games = self.db.execute_query(
            """
            SELECT COUNT(*) as total_games
            FROM games
            WHERE channel_id = ?
            """,
            (channel_id,),
        )

        if total_games:
            stats["total_games"] = int(total_games[0]["total_games"])

        return stats

    def reset_channel(self, channel_id: str) -> int:
        """
        Reset all data for a channel, including games and channel players.

        Args:
            channel_id: The channel ID to reset

        Returns:
            The number of games that were deleted
        """
        # Get count of games before deletion
        games = self.db.execute_query(
            "SELECT COUNT(*) as game_count FROM games WHERE channel_id = ?",
            (channel_id,),
        )
        game_count = games[0]["game_count"] if games else 0

        # Delete all player_games records for games in this channel
        self.db.execute_non_query(
            """
            DELETE FROM player_games
            WHERE game_id IN (
                SELECT id FROM games WHERE channel_id = ?
            )
            """,
            (channel_id,),
        )

        # Delete all games in this channel
        self.db.execute_non_query(
            "DELETE FROM games WHERE channel_id = ?",
            (channel_id,),
        )

        # Delete all channel_players for this channel
        self.db.execute_non_query(
            "DELETE FROM channel_players WHERE channel_id = ?",
            (channel_id,),
        )

        return game_count

    def get_player_rating_history(self, channel_id: str) -> Dict[str, List[Tuple[int, int]]]:
        """
        Get rating history for all players in a channel, chronologically by game number.

        Args:
            channel_id: The channel ID to get history for

        Returns:
            Dictionary mapping user_id to list of (game_number, rating) tuples
            where game_number is the chronological game number in the channel
        """
        # Get all games in chronological order with a game number
        all_games = self.db.execute_query(
            """
            SELECT DISTINCT g.id, g.timestamp
            FROM games g
            WHERE g.channel_id = ?
            ORDER BY g.timestamp ASC
            """,
            (channel_id,),
        )

        if not all_games:
            return {}

        # Create mapping of game_id to chronological game number
        game_id_to_number = {game["id"]: idx + 1 for idx, game in enumerate(all_games)}

        # Get all player games with their ratings
        player_games = self.db.execute_query(
            """
            SELECT
                pg.user_id,
                pg.rating_after,
                g.id as game_id
            FROM player_games pg
            JOIN games g ON pg.game_id = g.id
            WHERE g.channel_id = ?
            ORDER BY g.timestamp ASC
            """,
            (channel_id,),
        )

        if not player_games:
            return {}

        # Build rating history for each player
        player_histories = {}
        player_current_rating = {}
        player_first_game = {}

        # Get all unique players and their first game
        all_players = set(pg["user_id"] for pg in player_games)

        for user_id in all_players:
            player_histories[user_id] = []
            player_current_rating[user_id] = 1000
            # Find first game this player participated in
            first_game = min(
                game_id_to_number[pg["game_id"]]
                for pg in player_games
                if pg["user_id"] == user_id
            )
            player_first_game[user_id] = first_game

        # Process each game chronologically
        for game_number in range(1, len(all_games) + 1):
            # Find which game_id this is
            game_id = next(gid for gid, gnum in game_id_to_number.items() if gnum == game_number)

            # Get players who participated in this game
            players_in_game = {
                pg["user_id"]: pg["rating_after"]
                for pg in player_games
                if pg["game_id"] == game_id
            }

            # Update rating for all players
            for user_id in all_players:
                # Only add data points if player has started playing
                if game_number >= player_first_game[user_id]:
                    if user_id in players_in_game:
                        # Player participated, update their rating
                        new_rating = int(players_in_game[user_id])
                        player_current_rating[user_id] = new_rating
                        player_histories[user_id].append((game_number, new_rating))
                    else:
                        # Player didn't participate, keep same rating
                        player_histories[user_id].append((game_number, player_current_rating[user_id]))

        return player_histories
