"""
Vibecoded Slack bot for tracking Elo ratings in games with more than 2 players.
"""

from datetime import datetime
import os
import re
from flask import Flask, request, redirect
from slack_sdk import WebClient
from slack_bolt import App, Say
from slack_bolt.adapter.flask import SlackRequestHandler
from dotenv import load_dotenv
from slackelo import Slackelo, calculate_group_elo_with_draws

load_dotenv()

# Initialize Flask and load environment variables
app = Flask(__name__)

# Set up Slack client and Bolt app
client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))
bolt_app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)
handler = SlackRequestHandler(bolt_app)

# Initialize Slackelo with database path
slackelo = Slackelo(os.environ.get("DB_PATH", "slackelo.db"), "init.sql")


# Helper function to extract user IDs from mentions
def extract_user_ids(text):
    """Extract user IDs from Slack mentions in the format <@USER_ID|username>"""
    return re.findall(r"<@([A-Z0-9]+)\|?[^>]*>", text)


# Helper function to parse player rankings with ties
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
    # First, normalize by replacing spaces around equals signs
    # This captures ' = ', ' =', and '= ' patterns
    normalized_text = re.sub(r"\s*=\s*", "=", text)

    # Now split by spaces to get individual entries
    parts = normalized_text.split()

    ranked_players = []

    for part in parts:
        if "=" in part:
            # Handle tied players
            tied_players = []
            for tied_part in part.split("="):
                if tied_part:  # Skip empty strings that might result from split
                    user_ids = extract_user_ids(tied_part)
                    tied_players.extend(user_ids)
            if tied_players:
                ranked_players.append(tied_players)
        else:
            # Handle single player
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


def process_game_rankings(text, channel_id, is_simulation=False):
    """
    Process player rankings and calculate rating changes.

    Args:
        text: Command text with player mentions and rankings
        channel_id: Channel ID where the command was called
        is_simulation: Whether this is a simulation (True) or actual game (False)

    Returns:
        A formatted response string with results
    """
    # Parse player rankings with ties
    ranked_player_ids = parse_player_rankings(text)

    if sum(len(group) for group in ranked_player_ids) < 2:
        return "A game must have at least 2 players."

    # Get ratings before the game
    flat_player_ids = [player for rank in ranked_player_ids for player in rank]
    pre_game_ratings = {}
    player_positions = {}
    position = 1

    # Create a map of player_id to position (accounting for ties)
    for rank_group in ranked_player_ids:
        for player_id in rank_group:
            player_positions[player_id] = position
        position += len(rank_group)

    # Get current ratings for all players
    for player_id in flat_player_ids:
        pre_game_ratings[player_id] = slackelo.get_player_channel_rating(
            player_id, channel_id
        )

    if not is_simulation:
        # Create the game in the database
        game_id = slackelo.create_game(channel_id, ranked_player_ids)
        # Get updated ratings from the database
        post_game_ratings = {
            player_id: slackelo.get_player_channel_rating(player_id, channel_id)
            for player_id in flat_player_ids
        }
        response_prefix = "Game recorded! Results:\n"
        response_suffix = ""
    else:
        # Simulate the rating changes without saving to database
        current_ratings = list(pre_game_ratings.values())
        positions_list = [
            player_positions[player_id] for player_id in flat_player_ids
        ]

        # Calculate new ratings using existing function
        new_ratings = calculate_group_elo_with_draws(
            current_ratings, positions_list
        )

        # Create a dictionary of simulated new ratings
        post_game_ratings = {}
        for i, player_id in enumerate(flat_player_ids):
            post_game_ratings[player_id] = new_ratings[i]

        response_prefix = "Simulation results (no changes saved):\n"
        response_suffix = "\n_This is a simulation only. Use `/game` to record an actual game._"

    # Format response with placings and rating changes
    response = response_prefix

    # Determine actual position for each rank group (handling ties correctly)
    position = 1
    for i, rank_group in enumerate(ranked_player_ids):
        # Check if this is the last position group (for poop emoji)
        is_last_position = i == len(ranked_player_ids) - 1

        # Get emoji based on position
        if is_last_position:  # Only show poop emoji for last place
            emoji = "💩 "
        elif position == 1:
            emoji = "🥇 "
        elif position == 2:
            emoji = "🥈 "
        elif position == 3:
            emoji = "🥉 "
        else:
            emoji = ""  # No emoji for positions 4 through second-to-last

        # Format place text
        place_text = f"*{position}{get_ordinal_suffix(position)} place*: "

        # Add all players in this rank group
        for player_id in rank_group:
            old_rating = pre_game_ratings[player_id]
            new_rating = post_game_ratings[player_id]
            change = new_rating - old_rating

            # Format rating change as integer
            if change > 0:
                change_text = f"+{int(change)}"
            else:
                change_text = f"{int(change)}"

            if is_simulation:
                # Format with before and after ratings for simulation
                response += f"{emoji}{place_text}<@{player_id}> - *{int(old_rating)} → {int(new_rating)}* _({change_text})_\n"
            else:
                # Format for actual game (just shows new rating)
                response += f"{emoji}{place_text}<@{player_id}> - *{int(new_rating)}* _({change_text})_\n"

            # We only need to show the place text for the first player in each group
            place_text = ""
            emoji = ""

        # Increase position by the number of players in this rank group
        position += len(rank_group)

    response += response_suffix
    return response


# Basic route for health check
@app.route("/")
def hello():
    return """<a href="https://slack.com/oauth/v2/authorize?client_id=8664928721587.8673368141777&scope=channels:history,chat:write,commands&user_scope="><img alt="Add to Slack" height="40" width="139" src="https://platform.slack-edge.com/img/add_to_slack.png" srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" /></a>"""


# Game creation command
@bolt_app.command("/game")
def create_game(ack, command, say):
    """Create a new game with players and their rankings"""
    ack()

    channel_id = command["channel_id"]
    text = command["text"].strip()

    if not text:
        say(
            "Please provide player information. Format: `/game @player1 @player2 @player3` or `/game @player1=@player2 @player3` for ties."
        )
        return

    try:
        response = process_game_rankings(text, channel_id, is_simulation=False)
        say(response)
    except Exception as e:
        say(f"Error creating game: {str(e)}")


# Simulate game command
@bolt_app.command("/simulate")
def simulate_game(ack, command, say):
    """Simulate a game to see rating changes without saving to the database"""
    ack()

    channel_id = command["channel_id"]
    text = command["text"].strip()

    if not text:
        say(
            "Please provide player information. Format: `/simulate @player1 @player2 @player3` or `/simulate @player1=@player2 @player3` for ties."
        )
        return

    try:
        response = process_game_rankings(text, channel_id, is_simulation=True)
        say(response)
    except Exception as e:
        say(f"Error simulating game: {str(e)}")


# Leaderboard command
@bolt_app.command("/leaderboard")
def show_leaderboard(ack, command, say):
    """Show the channel leaderboard"""
    ack()

    channel_id = command["channel_id"]
    limit = 10

    # Parse optional limit parameter
    text = command["text"].strip()
    if text and text.isdigit():
        limit = min(int(text), 25)  # Cap at 25 to avoid overly long messages

    try:
        leaderboard = slackelo.get_channel_leaderboard(channel_id, limit)

        if not leaderboard:
            say(
                "No ratings found for this channel yet. Start playing games with `/game`!"
            )
            return

        response = "*Channel Leaderboard*\n"
        for i, player in enumerate(leaderboard):
            response += f"{i+1}. <@{player['user_id']}>: {player['rating']} ({player['games_played']} games)\n"

        say(response)

    except Exception as e:
        say(f"Error fetching leaderboard: {str(e)}")


# Undo last game command
@bolt_app.command("/undo")
def undo_last_game(ack, command, say):
    """Undo the last game in the channel"""
    ack()

    channel_id = command["channel_id"]

    try:
        game_timestamp = slackelo.undo_last_game(channel_id)

        # Format the timestamp
        game_time = datetime.utcfromtimestamp(game_timestamp).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        say(
            f"Last game from {game_time} UTC has been undone. All player ratings have been reverted."
        )

    except Exception as e:
        say(f"Error undoing game: {str(e)}")


# Show player rating command
@bolt_app.command("/rating")
def show_rating(ack, command, say):
    """Show a player's rating or your own if no player is specified"""
    ack()

    channel_id = command["channel_id"]
    text = command["text"].strip()
    user_id = command["user_id"]

    try:
        # Check if another player was specified
        mentioned_users = extract_user_ids(text)
        if mentioned_users:
            user_id = mentioned_users[0]

        rating = slackelo.get_player_channel_rating(user_id, channel_id)

        say(f"<@{user_id}>'s current rating in this channel is {rating}.")

    except Exception as e:
        say(f"Error fetching rating: {str(e)}")


# Help command
@bolt_app.command("/help")
def help_command(ack, say):
    """Show available commands and usage"""
    ack()

    help_text = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Slackelo Help"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Available Commands:*"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "• `/game @player1 @player2 @player3` - Record a game with players in order of ranking (winner first)\n• `/game @player1=@player2 @player3` - Record a game with ties (player1 and player2 tied for first)\n• `/simulate @player1 @player2 @player3` - Simulate a game to see rating changes without saving\n• `/leaderboard [limit]` - Show channel leaderboard (optional limit parameter)\n• `/rating [@player]` - Show your rating or another player's rating\n• `/undo` - Undo the last game in the channel\n• `/help` - Show this help message",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Slackelo is an Elo rating system for tracking competitive games in Slack channels.",
                },
            },
        ]
    }

    say(blocks=help_text["blocks"])


# Handle Slack events
@app.route("/events", methods=["POST"])
def slack_events():
    """Route where Slack will post requests"""
    return handler.handle(request)


@app.route("/oauth/redirect", methods=["GET"])
def oauth_redirect():
    # Get the authorization code from the request
    code = request.args.get("code")

    if not code:
        return "Error: No code provided", 400

    try:
        # Exchange the code for an access token
        response = client.oauth_v2_access(
            client_id=os.environ.get("SLACK_CLIENT_ID"),
            client_secret=os.environ.get("SLACK_RANDOM_STRING"),
            code=code,
            redirect_uri=os.environ.get("SLACK_REDIRECT_URI"),
        )

        # Store the tokens (you may want to save these in your database)
        # response will contain access_token, team information, etc.

        # Redirect back to Slack
        return redirect("https://slack.com/"), 302

    except Exception as e:
        return f"Error during OAuth: {str(e)}", 400


@app.route("/install", methods=["GET"])
def install():
    # Create a URL for installing to a workspace
    scope = "channels:history,chat:write,commands"  # Add required scopes
    client_id = os.environ.get("SLACK_CLIENT_ID")
    redirect_uri = os.environ.get("SLACK_REDIRECT_URI")

    # Construct the authorization URL
    auth_url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}"

    # Redirect to Slack's authorization page
    return redirect(auth_url)


@app.route("/success", methods=["GET"])
def success():
    return "Installation successful! You can close this tab."


# Run the Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
