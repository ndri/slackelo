"""
Utility functions for Slackelo.
"""

import re


def extract_user_ids(text):
    """Extract user IDs from Slack mentions in the format <@USER_ID|username>"""
    return re.findall(r"<@([A-Z0-9]+)\|?[^>]*>", text)


def parse_player_rankings(text):
    """
    Parse player rankings with support for ties.
    Format:
    - @player1 @player2=@player3 @player4 (original format)
    - @player1 @player2 = @player3 @player4 (spaces around equals)
    - @player1 @player2= @player3 @player4 (space after equals)
    - @player1 @player2 =@player3 @player4 (space before equals)
    - @player1 @player2 = @player3 = @player4 (multi-way ties with spaces)

    Returns a list of lists, where each inner list contains players tied at that position.
    """
    normalized_text = re.sub(r"\s*=\s*", "=", text)
    parts = normalized_text.split()
    ranked_players = []

    for part in parts:
        if "=" in part:
            tied_players = []
            for tied_part in part.split("="):
                if tied_part:
                    user_ids = extract_user_ids(tied_part)
                    tied_players.extend(user_ids)
            if tied_players:
                ranked_players.append(tied_players)
        else:
            user_ids = extract_user_ids(part)
            if user_ids:
                ranked_players.append([user_ids[0]])

    return ranked_players


def get_ordinal_suffix(num):
    """Return the ordinal suffix for a number (1st, 2nd, 3rd, etc.)"""
    if 10 <= num % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(num % 10, "th")
    return suffix
