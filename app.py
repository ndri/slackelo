"""
Vibecoded Slack bot for tracking Elo ratings in games with 2 or more players.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any
from flask import Flask, request, jsonify, render_template
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_flow import OAuthFlow
from dotenv import load_dotenv
from slackelo import Slackelo
from utils import (
    extract_user_ids,
    parse_player_rankings,
    get_ordinal_suffix,
)
from migrations import Migrations

# Application version - update this when schema changes
VERSION = "1.2"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

# Configuration from .env
db_path: str = os.environ.get("DB_PATH", "slackelo.db")

# OAuth URLs
oauth_redirect_uri: str = os.environ.get("OAUTH_REDIRECT_URI")
install_path: str = os.environ.get("INSTALL_PATH", "/install")
redirect_uri_path: str = os.environ.get("REDIRECT_URI_PATH", "/oauth/redirect")
success_url: str = os.environ.get("SUCCESS_URL", "/slackelo/success")

# Slack app credentials
signing_secret = os.environ.get("SLACK_SIGNING_SECRET")
client_id = os.environ.get("SLACK_CLIENT_ID")
client_secret = os.environ.get("SLACK_CLIENT_SECRET")

if not oauth_redirect_uri:
    raise ValueError(
        "Missing required environment variable: OAUTH_REDIRECT_URI"
    )

if not signing_secret:
    raise ValueError(
        "Missing required environment variable: SLACK_SIGNING_SECRET"
    )

if not client_id:
    raise ValueError("Missing required environment variable: SLACK_CLIENT_ID")

if not client_secret:
    raise ValueError(
        "Missing required environment variable: SLACK_CLIENT_SECRET"
    )

# Run database migrations before initializing app
migrations = Migrations(db_path)
try:
    logger.info(f"Running database migrations to version {VERSION}...")
    migrations.migrate_to_version(VERSION)
    logger.info(f"Database schema upgraded to version {VERSION}")
except Exception as e:
    logger.error(f"Error running migrations: {str(e)}")
    raise

# Initialize application after migrations
slackelo = Slackelo(db_path)

bolt_app = App(
    signing_secret=signing_secret,
    oauth_flow=OAuthFlow.sqlite3(
        database=db_path,
        client_id=client_id,
        client_secret=client_secret,
        scopes=["channels:history", "chat:write", "commands"],
        redirect_uri=oauth_redirect_uri,
        install_path=install_path,
        redirect_uri_path=redirect_uri_path,
        success_url=success_url,
    ),
)

handler = SlackRequestHandler(bolt_app)


def process_game_rankings(
    text: str, channel_id: str, team_id: str = None, is_simulation: bool = False
) -> str:
    """
    Process player rankings and calculate rating changes.

    Args:
        text: Command text with player mentions and rankings
        channel_id: Channel ID where the command was called
        team_id: Team ID where the command was called
        is_simulation: Whether this is a simulation (True) or actual game (False)

    Returns:
        A formatted response string with results
    """
    ranked_player_ids = parse_player_rankings(text)

    if sum(len(group) for group in ranked_player_ids) < 2:
        return "A game must have at least 2 players."

    if not is_simulation:
        slackelo.create_game(channel_id, ranked_player_ids, team_id)

        # Get flat list of player IDs
        flat_player_ids = [
            player for rank in ranked_player_ids for player in rank
        ]

        # Get pre-game ratings (have to reconstruct from player_games)
        pre_game_ratings = {}
        post_game_ratings = {}
        player_positions = {}

        for player_id in flat_player_ids:
            post_game_ratings[player_id] = slackelo.get_player_channel_rating(
                player_id, channel_id
            )

            # Get player's game history to find the most recent game (which should be the one we just created)
            history = slackelo.get_player_game_history(player_id, channel_id, 1)
            if history:
                pre_game_ratings[player_id] = history[0]["rating_before"]
                player_positions[player_id] = history[0]["position"]

        response_prefix = "Game recorded! Results:\n"
        response_suffix = ""
    else:
        pre_game_ratings, post_game_ratings, player_positions = (
            slackelo.simulate_game(channel_id, ranked_player_ids)
        )

        response_prefix = "Simulation results (no changes saved):\n"
        response_suffix = "\n_This is a simulation only. Use `/game` to record an actual game._"

    response = response_prefix

    position = 1
    for i, rank_group in enumerate(ranked_player_ids):
        is_last_position = i == len(ranked_player_ids) - 1

        if is_last_position:
            position_emoji = "💩 "
        elif position == 1:
            position_emoji = "🥇 "
        elif position == 2:
            position_emoji = "🥈 "
        elif position == 3:
            position_emoji = "🥉 "
        else:
            position_emoji = ""

        position_text = f"*{position}{get_ordinal_suffix(position)} place*: "

        for player_id in rank_group:
            old_rating = pre_game_ratings[player_id]
            new_rating = post_game_ratings[player_id]
            change = new_rating - old_rating

            # Check if player was gambling
            was_gambling = False
            if not is_simulation:
                # For actual games, check player_games record
                player_game = slackelo.get_player_game_history(
                    player_id, channel_id, 1
                )
                if player_game and player_game[0].get("gambled", 0) == 1:
                    was_gambling = True
            else:
                # For simulations, check current gambling status
                was_gambling = slackelo.is_player_gambling(
                    player_id, channel_id
                )

            if change > 0:
                change_text = f"+{int(change)}"
            else:
                change_text = f"{int(change)}"

            # Add gambling indicator if player was gambling
            gambling_indicator = " (🎲 2x!)" if was_gambling else ""

            response += f"{position_emoji}{position_text}<@{player_id}> - *{int(old_rating)} → {int(new_rating)}* _({change_text})_{gambling_indicator}\n"

        position += len(rank_group)

    response += response_suffix
    return response


@bolt_app.command("/game")
def create_game(ack: callable, command: Dict[str, Any], say: callable):
    """Create a new game with players and their rankings"""
    ack()
    channel_id = command["channel_id"]
    team_id = command["team_id"]
    text = command["text"].strip()

    if not text:
        say(
            "Please provide player information. Format: `/game @player1 @player2 @player3` or `/game @player1=@player2 @player3` for ties."
        )
        return

    try:
        response = process_game_rankings(
            text, channel_id, team_id, is_simulation=False
        )
        say(response)
    except Exception as e:
        logger.error(f"Error in create_game: {str(e)}")
        say(f"Error creating game: {str(e)}")


@bolt_app.command("/simulate")
def simulate_game(ack: callable, command: Dict[str, Any], respond: callable):
    """Simulate a game to see rating changes without saving to the database"""
    ack()

    channel_id = command["channel_id"]
    team_id = command["team_id"]
    text = command["text"].strip()

    if not text:
        respond(
            "Please provide player information. Format: `/simulate @player1 @player2 @player3` or `/simulate @player1=@player2 @player3` for ties."
        )
        return

    try:
        response = process_game_rankings(
            text, channel_id, team_id, is_simulation=True
        )
        respond(response)
    except Exception as e:
        logger.error(f"Error in simulate_game: {str(e)}")
        respond(f"Error simulating game: {str(e)}")


@bolt_app.command("/leaderboard")
def show_leaderboard(ack: callable, command: Dict[str, Any], say: callable):
    """Show the channel leaderboard"""
    ack()

    channel_id = command["channel_id"]
    team_id = command["team_id"]
    limit = 10

    text = command["text"].strip()
    if text and text.isdigit():
        limit = min(int(text), 25)

    try:
        # Make sure channel exists with team_id set
        slackelo.get_or_create_channel(channel_id, team_id)
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


@bolt_app.command("/undo")
def undo_last_game(ack: callable, command: Dict[str, Any], say: callable):
    """Undo the last game in the channel"""
    ack()

    channel_id = command["channel_id"]
    team_id = command["team_id"]

    try:
        # Make sure channel exists with team_id set
        slackelo.get_or_create_channel(channel_id, team_id)

        game_timestamp = slackelo.undo_last_game(channel_id)
        game_time = datetime.utcfromtimestamp(game_timestamp).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        say(
            f"Last game from {game_time} UTC has been undone. All player ratings have been reverted."
        )

    except Exception as e:
        logger.error(f"Error in undo_last_game: {str(e)}")
        say(f"Error undoing game: {str(e)}")


@bolt_app.command("/rating")
def show_rating(ack: callable, command: Dict[str, Any], respond: callable):
    """Show a player's rating or your own if no player is specified"""
    ack()

    channel_id = command["channel_id"]
    team_id = command["team_id"]
    text = command["text"].strip()
    user_id = command["user_id"]

    try:
        # Make sure channel exists with team_id set
        slackelo.get_or_create_channel(channel_id, team_id)

        mentioned_users = extract_user_ids(text)
        if mentioned_users:
            user_id = mentioned_users[0]

        rating = slackelo.get_player_channel_rating(user_id, channel_id)

        respond(f"<@{user_id}>'s current rating in this channel is {rating}.")

    except Exception as e:
        logger.error(f"Error in show_rating: {str(e)}")
        respond(f"Error fetching rating: {str(e)}")


@bolt_app.command("/history")
def show_history(ack: callable, command: Dict[str, Any], respond: callable):
    """Show a player's game history or your own if no player is specified"""
    ack()

    games_to_show = 10

    channel_id = command["channel_id"]
    team_id = command["team_id"]
    text = command["text"].strip()
    user_id = command["user_id"]

    try:
        # Make sure channel exists with team_id set
        slackelo.get_or_create_channel(channel_id, team_id)

        mentioned_users = extract_user_ids(text)

        if mentioned_users:
            user_id = mentioned_users[0]
            player_name = f"<@{user_id}>"
        else:
            player_name = f"<@{user_id}>"

        latest_games = slackelo.get_player_game_history(
            user_id, channel_id, games_to_show
        )

        if not latest_games:
            respond(f"No game history found for {player_name} in this channel.")
            return

        total_games = slackelo.get_player_game_count(user_id, channel_id)

        response = f"*Game history for {player_name}:*\n"

        if total_games > games_to_show:
            previous_games = total_games - games_to_show
            response += f"• _+{previous_games} previous games_\n"

        for game in latest_games[::-1]:
            game_time = datetime.utcfromtimestamp(game["timestamp"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            position = game["position"]
            suffix = get_ordinal_suffix(position)

            rating_change = game["rating_after"] - game["rating_before"]
            if rating_change > 0:
                change_text = f"+{int(rating_change)}"
            else:
                change_text = f"{int(rating_change)}"

            # Add gambling indicator if player gambled in this game
            gambling_indicator = (
                " (🎲 2x!)" if game.get("gambled", 0) == 1 else ""
            )

            response += f"• {game_time} UTC: {position}{suffix} place - *{int(game['rating_before'])} → {int(game['rating_after'])}* _({change_text})_{gambling_indicator}\n"

        respond(response)

    except Exception as e:
        logger.error(f"Error in show_history: {str(e)}")
        respond(f"Error fetching history: {str(e)}")


@bolt_app.command("/kfactor")
def set_k_factor(ack: callable, command: Dict[str, Any], say: callable):
    """Set or view the k-factor for the current channel"""
    ack()

    channel_id = command["channel_id"]
    team_id = command["team_id"]
    text = command["text"].strip()

    try:
        # Make sure channel exists with team_id set
        slackelo.get_or_create_channel(channel_id, team_id)

        old_k_factor = slackelo.get_channel_k_factor(channel_id)

        # If no value provided, show current k-factor
        if not text:
            say(
                f"The current k-factor for this channel is *{old_k_factor}*.\n"
                f"This affects how quickly ratings change after games.\n"
                f"• The standard value is 32\n"
                f"• Higher values (e.g., 64): Ratings change more quickly\n"
                f"• Lower values (e.g., 16): Ratings change more slowly\n"
                f"Use `/kfactor [value]` to set a new value."
            )
            return

        # Try to parse the provided value
        if not text.isdigit() or int(text) <= 0:
            say(
                "The k-factor must be a positive integer.\n"
                "Recommended values: 16 (slow changes), 32 (standard), 64 (rapid changes)"
            )
            return

        new_k_factor = int(text)
        slackelo.set_channel_k_factor(channel_id, new_k_factor)

        say(
            f"The k-factor for this channel has been set from {old_k_factor} to *{new_k_factor}*."
        )

    except ValueError as ve:
        say(f"Error: {str(ve)}")
    except Exception as e:
        logger.error(f"Error in set_k_factor: {str(e)}")
        say(f"Error setting k-factor: {str(e)}")


@bolt_app.command("/gamble")
def toggle_gambling(ack: callable, command: Dict[str, Any], say: callable):
    """Toggle the gambling status for the player"""
    ack()

    channel_id = command["channel_id"]
    team_id = command["team_id"]
    user_id = command["user_id"]

    try:
        # Toggle gambling status
        is_gambling = slackelo.toggle_player_gambling(user_id, channel_id)

        if is_gambling:
            say(
                f"<@{user_id}> is now gambling! 🎲\nTheir next rating change in this channel will be doubled (win big or lose big)!"
            )
        else:
            say(
                f"<@{user_id}> is no longer gambling.\nTheir next rating change will be normal."
            )

    except Exception as e:
        logger.error(f"Error in toggle_gambling: {str(e)}")
        say(f"Error toggling gambling status: {str(e)}")


@bolt_app.command("/help")
def help_command(ack: callable, _, respond: callable) -> None:
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
                "text": {
                    "type": "mrkdwn",
                    "text": "Slackelo is an Elo rating bot for tracking competitive games with two or more players in Slack channels.",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Available Commands:*"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(
                        [
                            "• `/game @player1 @player2 @player3` - Record a game with players in order of ranking (winner first)",
                            "• `/game @player1=@player2 @player3` - Record a game with ties (player1 and player2 tied for first)",
                            "• `/simulate @player1 @player2 @player3` - Simulate a game to see rating changes without saving",
                            "• `/leaderboard [limit]` - Show channel leaderboard (optional limit parameter)",
                            "• `/rating [@player]` - Show your rating or another player's rating",
                            "• `/history [@player]` - View your game history or another player's history",
                            "• `/kfactor [value]` - View or set the k-factor for this channel",
                            "• `/gamble` - Toggle doubling your next rating change (win big or lose big)",
                            "• `/undo` - Undo the last game in the channel",
                            "• `/help` - Show this help message",
                        ]
                    ),
                },
            },
        ]
    }

    respond(blocks=help_text["blocks"])


@app.route("/")
def hello():
    base_url = request.url_root.rstrip("/")
    install_url = f"{base_url}{install_path}"
    return render_template("index.html", install_url=install_url)


@app.route("/privacy")
def privacy_policy():
    """Render the privacy policy page"""
    return render_template("privacy.html")


@app.route("/events", methods=["POST"])
def slack_events():
    try:
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error handling Slack event: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/slack/commands", methods=["POST"])
def slack_commands():
    try:
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error handling slash command: {str(e)}")
        return (
            jsonify({"text": f"Error processing command: {str(e)}"}),
            200,
        )


@app.route("/oauth/redirect", methods=["GET"])
def oauth_redirect():
    try:
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error in OAuth redirect: {str(e)}")
        return render_template("error.html", error=str(e)), 500


@app.route("/install", methods=["GET"])
def install():
    try:
        base_url = request.url_root.rstrip("/")
        install_success_url = (
            os.environ.get("INSTALL_SUCCESS_URL") or f"{base_url}/success"
        )
        bolt_app.oauth_flow.settings.success_url = install_success_url
        return handler.handle(request)
    except Exception as e:
        logger.error(f"Error in install: {str(e)}")
        return render_template("error.html", error=str(e)), 500


@app.route("/success", methods=["GET"])
def success():
    return render_template("success.html")


@app.before_request
def handle_content_type():
    if request.path.startswith("/slack/commands"):
        if hasattr(request, "_cached_data"):
            delattr(request, "_cached_data")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting Slackelo app on {host}:{port}...")
    app.run(host=host, port=port)
