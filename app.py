"""
Vibecoded Slack bot for tracking Elo ratings in games with more than 2 players.
"""

import os
import re
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_flow import OAuthFlow
from dotenv import load_dotenv
from slackelo import Slackelo, calculate_group_elo_with_draws

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

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
    ranked_player_ids = parse_player_rankings(text)

    if sum(len(group) for group in ranked_player_ids) < 2:
        return "A game must have at least 2 players."

    flat_player_ids = [player for rank in ranked_player_ids for player in rank]
    pre_game_ratings = {}
    player_positions = {}
    position = 1

    for rank_group in ranked_player_ids:
        for player_id in rank_group:
            player_positions[player_id] = position
        position += len(rank_group)

    for player_id in flat_player_ids:
        pre_game_ratings[player_id] = slackelo.get_player_channel_rating(
            player_id, channel_id
        )

    if not is_simulation:
        game_id = slackelo.create_game(channel_id, ranked_player_ids)
        post_game_ratings = {
            player_id: slackelo.get_player_channel_rating(player_id, channel_id)
            for player_id in flat_player_ids
        }
        response_prefix = "Game recorded! Results:\n"
        response_suffix = ""
    else:
        current_ratings = list(pre_game_ratings.values())
        positions_list = [
            player_positions[player_id] for player_id in flat_player_ids
        ]

        new_ratings = calculate_group_elo_with_draws(
            current_ratings, positions_list
        )

        post_game_ratings = {}
        for i, player_id in enumerate(flat_player_ids):
            post_game_ratings[player_id] = new_ratings[i]

        response_prefix = "Simulation results (no changes saved):\n"
        response_suffix = "\n_This is a simulation only. Use `/game` to record an actual game._"

    response = response_prefix

    position = 1
    for i, rank_group in enumerate(ranked_player_ids):
        is_last_position = i == len(ranked_player_ids) - 1

        if is_last_position:
            emoji = "💩 "
        elif position == 1:
            emoji = "🥇 "
        elif position == 2:
            emoji = "🥈 "
        elif position == 3:
            emoji = "🥉 "
        else:
            emoji = ""

        place_text = f"*{position}{get_ordinal_suffix(position)} place*: "

        for player_id in rank_group:
            old_rating = pre_game_ratings[player_id]
            new_rating = post_game_ratings[player_id]
            change = new_rating - old_rating

            if change > 0:
                change_text = f"+{int(change)}"
            else:
                change_text = f"{int(change)}"

            if is_simulation:
                response += f"{emoji}{place_text}<@{player_id}> - *{int(old_rating)} → {int(new_rating)}* _({change_text})_\n"
            else:
                response += f"{emoji}{place_text}<@{player_id}> - *{int(new_rating)}* _({change_text})_\n"

            place_text = ""
            emoji = ""

        position += len(rank_group)

    response += response_suffix
    return response


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


@bolt_app.command("/leaderboard")
def show_leaderboard(ack, command, say):
    """Show the channel leaderboard"""
    ack()

    channel_id = command["channel_id"]
    limit = 10

    text = command["text"].strip()
    if text and text.isdigit():
        limit = min(int(text), 25)

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


@bolt_app.command("/undo")
def undo_last_game(ack, command, say):
    """Undo the last game in the channel"""
    ack()

    channel_id = command["channel_id"]

    try:
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
def show_rating(ack, command, say):
    """Show a player's rating or your own if no player is specified"""
    ack()

    channel_id = command["channel_id"]
    text = command["text"].strip()
    user_id = command["user_id"]

    try:
        mentioned_users = extract_user_ids(text)
        if mentioned_users:
            user_id = mentioned_users[0]

        rating = slackelo.get_player_channel_rating(user_id, channel_id)

        say(f"<@{user_id}>'s current rating in this channel is {rating}.")

    except Exception as e:
        logger.error(f"Error in show_rating: {str(e)}")
        say(f"Error fetching rating: {str(e)}")


@bolt_app.command("/history")
def show_history(ack, command, say):
    """Show a player's game history or your own if no player is specified"""
    ack()

    channel_id = command["channel_id"]
    text = command["text"].strip()
    user_id = command["user_id"]

    try:
        mentioned_users = extract_user_ids(text)

        if mentioned_users:
            user_id = mentioned_users[0]
            player_name = f"<@{user_id}>"

        player_name = f"<@{user_id}>"

        history = slackelo.get_player_game_history(user_id, channel_id)

        if not history:
            say(f"No game history found for {player_name} in this channel.")
            return

        response = f"*Game history for {player_name}:*\n"

        for game in history:
            # Format the timestamp
            game_time = datetime.utcfromtimestamp(game["timestamp"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            # Format the position with ordinal suffix
            position = game["position"]
            suffix = get_ordinal_suffix(position)

            # Calculate and format rating change
            rating_change = game["rating_after"] - game["rating_before"]
            if rating_change > 0:
                change_text = f"+{int(rating_change)}"
            else:
                change_text = f"{int(rating_change)}"

            response += f"• {game_time} UTC: {position}{suffix} place - *{int(game['rating_before'])} → {int(game['rating_after'])}* _({change_text})_\n"

        say(response)

    except Exception as e:
        logger.error(f"Error in show_history: {str(e)}")
        say(f"Error fetching history: {str(e)}")


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
                    "text": "• `/game @player1 @player2 @player3` - Record a game with players in order of ranking (winner first)\n• `/game @player1=@player2 @player3` - Record a game with ties (player1 and player2 tied for first)\n• `/simulate @player1 @player2 @player3` - Simulate a game to see rating changes without saving\n• `/leaderboard [limit]` - Show channel leaderboard (optional limit parameter)\n• `/rating [@player]` - Show your rating or another player's rating\n• `/history [@player]` - View your game history or another player's history\n• `/undo` - Undo the last game in the channel\n• `/help` - Show this help message",
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


@app.route("/")
def hello():
    base_url = request.url_root.rstrip("/")
    install_url = f"{base_url}/install"
    return render_template("index.html", install_url=install_url)


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
        success_url = f"{base_url}/success"
        bolt_app.oauth_flow.settings.success_url = success_url
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
    logger.info("Starting Slackelo app...")
    app.run(host="0.0.0.0", port=8080)
