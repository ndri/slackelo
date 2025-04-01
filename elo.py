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
        Tuple of the Elo changes for the winner and loser
    """
    expected_win = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_lose = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))

    winner_change = round(k_factor * (1 - expected_win))
    loser_change = round(k_factor * (0 - expected_lose))

    return winner_change, loser_change


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
        Tuple of the Elo changes for player 1 and player 2
    """
    expected_p1_score = 1 / (1 + 10 ** ((player2_elo - player1_elo) / 400))
    expected_p2_score = 1 / (1 + 10 ** ((player1_elo - player2_elo) / 400))

    player1_change = round(k_factor * (0.5 - expected_p1_score))
    player2_change = round(k_factor * (0.5 - expected_p2_score))

    return player1_change, player2_change


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
        List of the Elo changes for the players
    """
    # Track Elo changes
    elo_changes = [0] * len(player_elos)

    for i, (elo_i, pos_i) in enumerate(zip(player_elos, player_positions)):
        for j, (elo_j, pos_j) in enumerate(zip(player_elos, player_positions)):
            if i == j:
                continue

            # Handle draws
            if pos_i == pos_j:
                # Calculate Elo changes for a draw
                p1_change, p2_change = calculate_elo_draw(elo_i, elo_j, k_factor)
                # Divide by number of comparisons to avoid over-adjusting
                elo_changes[i] += p1_change / (len(player_elos) - 1)
                elo_changes[j] += p2_change / (len(player_elos) - 1)

            # Player i beat player j
            elif pos_i < pos_j:
                # Calculate Elo changes for win/loss
                winner_change, loser_change = calculate_elo_win(
                    elo_i, elo_j, k_factor
                )
                # Divide by number of comparisons to avoid over-adjusting
                elo_changes[i] += winner_change / (len(player_elos) - 1)
                elo_changes[j] += loser_change / (len(player_elos) - 1)

    # Round all changes
    elo_changes = [round(change) for change in elo_changes]

    return elo_changes


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
        List of the Elo changes for the players
    """
    # Convert to positions format and use new function
    positions: List[int] = list(range(1, len(player_elos) + 1))
    return calculate_group_elo_with_draws(player_elos, positions, k_factor)
