"""
Elo rating system functions.
"""

from typing import List, Tuple


def calculate_elo_win(
    winner_elo: int, loser_elo: int, k_factor: int = 32
) -> Tuple[int, int]:
    """
    Calculate the change in Elo for the winner and loser of a game.

    Args:
        winner_elo: Elo rating of the winner
        loser_elo: Elo rating of the loser
        k_factor: K-factor for Elo calculation

    Returns:
        Tuple of the new Elo ratings for the winner and loser
    """
    expected_win = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_lose = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))

    new_winner_elo = winner_elo + round(k_factor * (1 - expected_win))
    new_loser_elo = loser_elo + round(k_factor * (0 - expected_lose))

    return new_winner_elo, new_loser_elo


def calculate_elo_draw(
    player1_elo: int, player2_elo: int, k_factor: int = 32
) -> Tuple[int, int]:
    """
    Calculate the change in Elo for a draw between two players.

    Args:
        player1_elo: Elo rating of player 1
        player2_elo: Elo rating of player 2
        k_factor: K-factor for Elo calculation

    Returns:
        Tuple of the change in Elo for player 1 and player 2
    """
    expected_p1_score = 1 / (1 + 10 ** ((player2_elo - player1_elo) / 400))
    expected_p2_score = 1 / (1 + 10 ** ((player1_elo - player2_elo) / 400))

    new_player1_elo = player1_elo + round(k_factor * (0.5 - expected_p1_score))
    new_player2_elo = player2_elo + round(k_factor * (0.5 - expected_p2_score))

    return new_player1_elo, new_player2_elo


def calculate_group_elo_with_draws(
    player_elos: List[int], player_positions: List[int], k_factor: int = 32
) -> List[int]:
    """
    Calculate the change in Elo for a group of players with support for draws.

    Args:
        player_elos: List of Elo ratings for the players
        player_positions: List of positions for each player (same position means draw)
        k_factor: K-factor for Elo calculation

    Returns:
        List of the new Elo ratings for the players
    """
    new_elos = player_elos.copy()

    # Track Elo changes separately, apply them all at once
    elo_changes = [0] * len(player_elos)

    for i, (elo_i, pos_i) in enumerate(zip(player_elos, player_positions)):
        for j, (elo_j, pos_j) in enumerate(zip(player_elos, player_positions)):
            if i == j:
                continue

            # Handle draws
            if pos_i == pos_j:
                # Calculate Elo changes for a draw
                p1_new, p2_new = calculate_elo_draw(elo_i, elo_j, k_factor)
                # Divide by number of comparisons to avoid over-adjusting
                elo_changes[i] += (p1_new - elo_i) / (len(player_elos) - 1)
                elo_changes[j] += (p2_new - elo_j) / (len(player_elos) - 1)

            # Player i beat player j
            elif pos_i < pos_j:
                # Calculate Elo changes for win/loss
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


def calculate_group_elo(
    player_elos: List[int], k_factor: int = 32
) -> List[int]:
    """
    Legacy function for backwards compatibility.
    Calculate the change in Elo for a group of players without draws.
    Player 1 wins against player 2, 3 and so on.
    Player 2 loses against player 1, but wins against player 3, 4 and so on.

    Args:
        player_elos: List of Elo ratings for the players
        k_factor: K-factor for Elo calculation

    Returns:
        List of the new Elo ratings for the players
    """
    # Convert to positions format and use new function
    positions: List[int] = list(range(1, len(player_elos) + 1))
    return calculate_group_elo_with_draws(player_elos, positions, k_factor)
