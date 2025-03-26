""" Basic operations using Slack_sdk """

import os
import json
from slack_sdk import WebClient

# We need to pass the 'Bot User OAuth Token'
slack_token = os.environ.get("SLACK_BOT_TOKEN")

# Creating an instance of the Webclient class
client = WebClient(token=slack_token)

print("Client", client)

# Posting a message in #random channel
response = client.chat_postMessage(
    channel="elo-bot-testing", text="Bot's first message"
)

# Sending a message to a particular user
# response = client.chat_postEphemeral(
#     channel="elo-bot-testing", text="Hello USERID0000", user="USERID0000"
# )

# Get basic information of the channel where our Bot has access
# response = client.conversations_info(channel="CHNLID0000")

# Get a list of conversations
response = client.conversations_list()
# print(json.dumps(response["channels"], indent=2))
print(dir(response))
