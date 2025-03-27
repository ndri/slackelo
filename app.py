"""
Vibecoded Slack bot for tracking Elo ratings in games with more than 2 players.
"""

from datetime import datetime
import os
import re
from flask import Flask, request
from slack_sdk import WebClient
from slack_bolt import App, Say
from slack_bolt.adapter.flask import SlackRequestHandler
from dotenv import load_dotenv
from slackelo import Slackelo

# Initialize Flask and load environment variables
app = Flask(__name__)
load_dotenv()

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
    Format: @player1 @player2=@player3 @player4
    Returns a list of lists, where each inner list contains players tied at that position.
    """
    ranked_players = []
    parts = text.split()

    for part in parts:
        if "=" in part:
            # Handle tied players
            tied_players = []
            for tied_part in part.split("="):
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


# Basic route for health check
@app.route("/")
def hello():
    return "Slackelo is running!"


# Greeting message
@bolt_app.message("hello slackelo")
def greetings(payload: dict, say: Say):
    """Respond to 'hello slackelo' messages"""
    user = payload.get("user")
    say(
        f"Hi <@{user}>! I'm Slackelo, your friendly Elo rating bot. Use `/help` to see available commands."
    )


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
        # Parse player rankings with ties
        ranked_player_ids = parse_player_rankings(text)

        if (
            len(ranked_player_ids) < 2
            or sum(len(group) for group in ranked_player_ids) < 2
        ):
            say("A game must have at least 2 players.")
            return

        # Create the game
        game_id = slackelo.create_game(channel_id, ranked_player_ids)

        # Get updated ratings for all players
        player_data = []
        for rank_group in ranked_player_ids:
            for player_id in rank_group:
                rating = slackelo.get_player_channel_rating(
                    player_id, channel_id
                )
                player_data.append((player_id, rating))

        # Format response
        response = "Game recorded! Current ratings:\n"
        for player_id, rating in player_data:
            response += f"• <@{player_id}>: {rating}\n"

        say(response)

    except Exception as e:
        say(f"Error creating game: {str(e)}")


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
        game_time = datetime.fromtimestamp(game_timestamp).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        say(
            f"Last game from {game_time} has been undone. All player ratings have been reverted."
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
                    "text": "• `/game @player1 @player2 @player3` - Record a game with players in order of ranking (winner first)\n• `/game @player1=@player2 @player3` - Record a game with ties (player1 and player2 tied for first)\n• `/leaderboard [limit]` - Show channel leaderboard (optional limit parameter)\n• `/rating [@player]` - Show your rating or another player's rating\n• `/undo` - Undo the last game in the channel\n• `/help` - Show this help message",
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


# Run the Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
