"""
Vibecoded Slack bot for tracking Elo ratings in games with more than 2 players.
"""

import os
import re
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_flow import OAuthFlow
from dotenv import load_dotenv
from slackelo import Slackelo, calculate_group_elo_with_draws

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

db_path = os.environ.get("DB_PATH", "slackelo.db")
slackelo = Slackelo(db_path, "init.sql")

bolt_app = App(
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    oauth_flow=OAuthFlow.sqlite3(
        database=db_path,
        client_id=os.environ.get("SLACK_CLIENT_ID"),
        client_secret=os.environ.get("SLACK_RANDOM_STRING"),
        scopes=["channels:history", "chat:write", "commands"],
        redirect_uri="https://andri.io/slackelo/oauth/redirect",
        install_path="/install",
        redirect_uri_path="/oauth/redirect",
        success_url="/slackelo/success",
    ),
)

handler = SlackRequestHandler(bolt_app)


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
        logger.error(f"Error in create_game: {str(e)}")
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
        logger.error(f"Error in simulate_game: {str(e)}")
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
        logger.error(f"Error in show_leaderboard: {str(e)}")
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
        logger.error(f"Error in undo_last_game: {str(e)}")
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
        logger.error(f"Error in show_rating: {str(e)}")
        say(f"Error fetching rating: {str(e)}")


# Help command
@bolt_app.command("/help")
def help_command(ack, command, say):
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


# Basic route for health check
@app.route("/")
def hello():
    # Get the absolute URL for the installation
    base_url = request.url_root.rstrip("/")
    install_url = f"{base_url}/install"

    return f"""
    <html>
    <head>
        <title>Slackelo - Elo Rating System for Slack</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
            h1 {{ color: #4A154B; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .btn {{ display: inline-block; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Slackelo</h1>
            <p>An Elo rating system for tracking competitive games in Slack channels.</p>
            <div class="btn">
                <a href="{install_url}"><img alt="Add to Slack" height="40" width="139" src="https://platform.slack-edge.com/img/add_to_slack.png" srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" /></a>
            </div>
        </div>
    </body>
    </html>
    """


# Route for Slack events with better error handling
@app.route("/events", methods=["POST"])
def slack_events():
    # Add detailed logging of the request
    logger.debug(
        f"Received request: content-type={request.headers.get('Content-Type')}"
    )
    try:
        # Log raw request data for debugging
        request_data = request.get_data(as_text=True)
        logger.debug(f"Request body: {request_data}")
        logger.debug(f"Request form: {request.form}")
        logger.debug(f"Request args: {request.args}")

        # Process the request through the Slack handler
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error handling Slack event: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Dedicated route for slash commands
@app.route("/slack/commands", methods=["POST"])
def slack_commands():
    logger.debug(
        f"Received slash command: content-type={request.headers.get('Content-Type')}"
    )
    logger.debug(f"Form data: {request.form}")

    try:
        # Slack sends slash commands as form data
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error handling slash command: {str(e)}")
        return (
            jsonify({"text": f"Error processing command: {str(e)}"}),
            200,
        )  # Return 200 so Slack shows the error


# Handle OAuth installation and redirect
@app.route("/oauth/redirect", methods=["GET"])
def oauth_redirect():
    logger.debug(f"Received OAuth redirect with args: {str(request.args)}")
    logger.debug(f"Full request URL: {request.url}")
    try:
        # Get the state from the request
        state = request.args.get("state", "")
        logger.debug(f"State parameter: {state}")

        # Process the OAuth callback
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error in OAuth redirect: {str(e)}")
        return (
            f"""
        <html>
        <head>
            <title>Slackelo - Installation Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                h1 {{ color: #E01E5A; }}
                .container {{ max-width: 800px; margin: 0 auto; text-align: center; }}
                .error {{ color: #E01E5A; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Installation Error</h1>
                <p class="error">{str(e)}</p>
                <p>Please try again from the <a href="/">homepage</a> or contact the app owner.</p>
            </div>
        </body>
        </html>
        """,
            500,
        )


@app.route("/install", methods=["GET"])
def install():
    try:
        # Get the base URL for the success redirect
        base_url = request.url_root.rstrip("/")
        success_url = f"{base_url}/success"

        # Configure the OAuth settings for this specific request
        bolt_app.oauth_flow.settings.success_url = success_url

        # Process the installation request without manually handling state
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error in install: {str(e)}")
        return (
            f"""
        <html>
        <head>
            <title>Slackelo - Installation Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                h1 {{ color: #E01E5A; }}
                .container {{ max-width: 800px; margin: 0 auto; text-align: center; }}
                .error {{ color: #E01E5A; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Installation Error</h1>
                <p class="error">{str(e)}</p>
                <p>Please try again from the <a href="/">homepage</a> or contact the app owner.</p>
            </div>
        </body>
        </html>
        """,
            500,
        )


@app.route("/success", methods=["GET"])
def success():
    return """
    <html>
    <head>
        <title>Slackelo - Installation Successful</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
            h1 { color: #2EB67D; }
            .container { max-width: 800px; margin: 0 auto; text-align: center; }
            .success { color: #2EB67D; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Installation Successful!</h1>
            <p class="success">Slackelo has been successfully installed to your workspace.</p>
            <p>You can now use the following slash commands in your Slack channels:</p>
            <ul style="display: inline-block; text-align: left;">
                <li><code>/game @player1 @player2 @player3</code> - Record a game with players in order of ranking</li>
                <li><code>/simulate @player1 @player2 @player3</code> - Simulate a game without saving</li>
                <li><code>/leaderboard</code> - View channel leaderboard</li>
                <li><code>/rating</code> - Check your rating</li>
                <li><code>/help</code> - View all available commands</li>
            </ul>
            <p>You can close this tab and return to Slack.</p>
        </div>
    </body>
    </html>
    """


# Add a middleware to handle content type issues
@app.before_request
def handle_content_type():
    # Only apply to Slack command endpoints
    if request.path.startswith("/slack/commands"):
        logger.debug(
            f"Handling content type for Slack command: content-type={request.headers.get('Content-Type')}"
        )
        # Force Flask to treat it as form data
        if hasattr(request, "_cached_data"):
            delattr(request, "_cached_data")


# Run the Flask app
if __name__ == "__main__":
    logger.info("Starting Slackelo app...")
    logger.info(f"Database path: {db_path}")

    logger.info("Available routes:")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.endpoint}: {rule}")

    app.run(host="0.0.0.0", port=8080, debug=True)
