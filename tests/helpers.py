"""
Shared constants and helpers for the test suite.
"""

# Slack-shaped user IDs. `extract_user_ids` only matches [A-Z0-9]+, so made-up
# IDs like "U_alice" get silently mangled - always use IDs of this shape.
ALICE = "U01ALICE"
BOB = "U02BOB"
CAROL = "U03CAROL"
DAVE = "U04DAVE"
ERIN = "U05ERIN"

CHANNEL = "C01CHANNEL"
OTHER_CHANNEL = "C02OTHER"
TEAM = "T01TEAM"

NAMES = {
    ALICE: "alice",
    BOB: "bob",
    CAROL: "carol",
    DAVE: "dave",
    ERIN: "erin",
}


def mention(user_id: str, with_name: bool = True) -> str:
    """Render a user ID the way Slack sends it in a slash command's text."""
    if with_name:
        return f"<@{user_id}|{NAMES.get(user_id, 'someone')}>"
    return f"<@{user_id}>"


def mentions(*user_ids: str) -> str:
    """Render several mentions as a space-separated command text."""
    return " ".join(mention(user_id) for user_id in user_ids)


def rating_of(slackelo, user_id: str, channel_id: str):
    """Read a rating straight from the database, bypassing the API."""
    rows = slackelo.db.execute_query(
        "SELECT rating FROM channel_players WHERE user_id = ? AND channel_id = ?",
        (user_id, channel_id),
    )
    return rows[0]["rating"] if rows else None


def channel_player_ids(slackelo, channel_id: str):
    """Every user that has a rating row in the channel, i.e. the leaderboard."""
    rows = slackelo.db.execute_query(
        "SELECT user_id FROM channel_players WHERE channel_id = ?",
        (channel_id,),
    )
    return {row["user_id"] for row in rows}
