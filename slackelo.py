from sqlite_connector import SQLiteConnector
from typing import List
import time


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

    def get_player_channel_rating(self, user_id: str, channel_id: str):
        """Get a player's rating for a specific channel."""
        channel_player = self.get_or_create_channel_player(user_id, channel_id)
        return channel_player["rating"]

    def get_channel_leaderboard(self, channel_id: str, limit: int = 10):
        """Get the leaderboard for a specific channel."""
        leaderboard = self.db.execute_query(
            """
            SELECT p.user_id, cp.rating
            FROM channel_players cp
            JOIN players p ON cp.user_id = p.user_id
            WHERE cp.channel_id = ?
            ORDER BY cp.rating DESC
            LIMIT ?
            """,
            (channel_id, limit),
        )
        return leaderboard


def calculate_elo_win(winner_elo: int, loser_elo: int, k_factor: int = 32):
    """
    Calculate the change in ELO for the winner and loser of a game.

    Args:
        winner_elo: ELO rating of the winner
        loser_elo: ELO rating of the loser

    Returns:
        Tuple of the change in ELO for the winner and loser
    """
    expected_win = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_lose = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))

    new_winner_elo = winner_elo + round(k_factor * (1 - expected_win))
    new_loser_elo = loser_elo + round(k_factor * (0 - expected_lose))

    return new_winner_elo, new_loser_elo


def calculate_elo_draw(player1_elo: int, player2_elo: int, k_factor: int = 32):
    """
    Calculate the change in ELO for a draw between two players.

    Args:
        player1_elo: ELO rating of player 1
        player2_elo: ELO rating of player 2

    Returns:
        Tuple of the change in ELO for player 1 and player 2
    """
    expected_p1_score = 1 / (1 + 10 ** ((player2_elo - player1_elo) / 400))
    expected_p2_score = 1 / (1 + 10 ** ((player1_elo - player2_elo) / 400))

    new_player1_elo = player1_elo + round(k_factor * (0.5 - expected_p1_score))
    new_player2_elo = player2_elo + round(k_factor * (0.5 - expected_p2_score))

    return new_player1_elo, new_player2_elo


def calculate_group_elo_with_draws(
    player_elos: List[int], player_positions: List[int], k_factor: int = 32
):
    """
    Calculate the change in ELO for a group of players with support for draws.

    Args:
        player_elos: List of ELO ratings for the players
        player_positions: List of positions for each player (same position means draw)
        k_factor: K-factor for ELO calculation

    Returns:
        List of the new ELO ratings for the players
    """
    new_elos = player_elos.copy()

    # Track ELO changes separately, apply them all at once
    elo_changes = [0] * len(player_elos)

    for i, (elo_i, pos_i) in enumerate(zip(player_elos, player_positions)):
        for j, (elo_j, pos_j) in enumerate(zip(player_elos, player_positions)):
            if i == j:
                continue

            # Handle draws
            if pos_i == pos_j:
                # Calculate ELO changes for a draw
                p1_new, p2_new = calculate_elo_draw(elo_i, elo_j, k_factor)
                # Divide by number of comparisons to avoid over-adjusting
                elo_changes[i] += (p1_new - elo_i) / (len(player_elos) - 1)
                elo_changes[j] += (p2_new - elo_j) / (len(player_elos) - 1)

            # Player i beat player j
            elif pos_i < pos_j:
                # Calculate ELO changes for win/loss
                winner_new, loser_new = calculate_elo_win(
                    elo_i, elo_j, k_factor
                )
                # Divide by number of comparisons to avoid over-adjusting
                elo_changes[i] += (winner_new - elo_i) / (len(player_elos) - 1)
                elo_changes[j] += (loser_new - elo_j) / (len(player_elos) - 1)

    # Apply all changes at once
    for i, change in enumerate(elo_changes):
        new_elos[i] += round(change)

    return new_elos


def calculate_group_elo(player_elos: List[int], k_factor: int = 32):
    """
    Legacy function for backwards compatibility.
    Calculate the change in ELO for a group of players without draws.
    Player 1 wins against player 2, 3 and so on.
    Player 2 loses against player 1, but wins against player 3, 4 and so on.

    Args:
        player_elos: List of ELO ratings for the players
        k_factor: K-factor for ELO calculation

    Returns:
        List of the new ELO ratings for the players
    """
    # Convert to positions format and use new function
    positions = list(range(1, len(player_elos) + 1))
    return calculate_group_elo_with_draws(player_elos, positions, k_factor)
