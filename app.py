import os
from flask import Flask, request
from slack_sdk import WebClient
from slack_bolt import App, Say
from slack_bolt.adapter.flask import SlackRequestHandler
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()

client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))

bolt_app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)
handler = SlackRequestHandler(bolt_app)


@app.route("/")
def hello():
    return "slackelo is running 2"


@bolt_app.message("hello slackelo")
def greetings(payload: dict, say: Say):
    """This will check all the message and pass only those which has 'hello slacky' in it"""
    user = payload.get("user")
    say(f"Hi <@{user}>")


@bolt_app.command("/help")
def help_command(say, ack):
    ack()
    text = {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "This is a slash command"},
            }
        ]
    }
    say(text=text)


@app.route("/events", methods=["POST"])
def slack_events():
    """Declaring the route where slack will post a request"""
    return handler.handle(request)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
