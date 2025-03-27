from sqlite_connector import SQLiteConnector
from typing import List
import time


class Slackelo:
    def __init__(self, db_path: str, init_sql_file: str = None):
        self.db = SQLiteConnector(db_path, init_sql_file)

    def get_or_create_player(self, user_id: str):
        player = self.db.execute_query(
            "SELECT * FROM players WHERE user_id = ?", (user_id,)
        )

        if not player:
            self.db.execute_non_query(
                "INSERT INTO players (user_id, rating) VALUES (?, ?)",
                (user_id, 1000),
            )
            player = self.db.execute_query(
                "SELECT * FROM players WHERE user_id = ?", (user_id,)
            )

        return player[0]

    def create_game(self, channel_id: str, player_ids: List[str]):
        if len(player_ids) < 2:
            raise Exception("A game must have at least 2 players")

        insert_output = self.db.execute_non_query(
            "INSERT INTO games (channel_id, timestamp) VALUES (?, ?)",
            (channel_id, int(time.time())),
        )

        game_id = insert_output["lastrowid"]

        players = []

        for player_id in player_ids:
            player = self.get_or_create_player(player_id)
            players.append(player)

        old_ratings = [player["rating"] for player in players]
        new_ratings = calculate_group_elo(old_ratings)

        for i, player in enumerate(players):
            print(
                player["user_id"],
                game_id,
                old_ratings[i],
                new_ratings[i],
                i + 1,
            )
            self.db.execute_non_query(
                "INSERT INTO player_games "
                "(user_id, game_id, rating_before, rating_after, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    player["user_id"],
                    game_id,
                    old_ratings[i],
                    new_ratings[i],
                    i + 1,
                ),
            )
            self.db.execute_non_query(
                "UPDATE players SET rating = ? WHERE user_id = ?",
                (new_ratings[i], player["user_id"]),
            )

        return game_id


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
    expected_draw = 1 / (1 + 10 ** ((player2_elo - player1_elo) / 400))

    new_player1_elo = player1_elo + round(k_factor * (0.5 - expected_draw))
    new_player2_elo = player2_elo + round(k_factor * (0.5 - expected_draw))

    return new_player1_elo, new_player2_elo


def calculate_group_elo(player_elo: List[int], k_factor: int = 32):
    """
    Calculate the change in ELO for a group of players.
    Player 1 wins against player 2, 3 and so on.
    Player 2 loses against player 1, but wins against player 3, 4 and so on.

    Args:
        player_elo: List of ELO ratings for the players
        k_factor: K-factor for ELO calculation

    Returns:
        List of the new ELO ratings for the players
    """
    new_elos = player_elo.copy()

    # Track ELO changes separately, apply them all at once
    elo_changes = [0] * len(player_elo)

    for i, player_i_elo in enumerate(player_elo):
        for j, player_j_elo in enumerate(player_elo):
            if i == j:
                continue

            # Player with lower index beats player with higher index
            if i < j:
                # Calculate ELO change for winner and loser
                winner_change, loser_change = calculate_elo_win(
                    player_i_elo, player_j_elo, k_factor
                )
                elo_changes[i] += winner_change - player_i_elo
                elo_changes[j] += loser_change - player_j_elo

    # Apply all changes at once
    for i, change in enumerate(elo_changes):
        new_elos[i] += change

    return new_elos
