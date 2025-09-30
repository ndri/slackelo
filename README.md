# Slackelo

Slackelo is a Slack bot that tracks Elo ratings for competitive games played within your Slack channels. Whether you're tracking ping pong matches, chess games, Mario Kart races, or any other competitive activity with two or more players, Slackelo makes it easy to record results and maintain a leaderboard.

![banner that shows a bunch of example commands and responses](/static/banner.png)

## Features

- 📊 **Track Elo Ratings**: Automatically calculate and update Elo ratings based on game results
- 🎮 **Multi-Player Support**: Works with any game format, from 1v1 duels to multi-player competitions like Mario Kart
- 🏆 **Channel Leaderboards**: View rankings for all players in a channel
- 🤝 **Support for Ties**: Record games where multiple players tie for a position
- 🔢 **Customizable K-Factor**: Adjust how quickly ratings change based on your preferences
- 📜 **Game History**: View past games and rating changes for any player
- 🧪 **Simulation Mode**: Preview rating changes without recording actual games
- ↩️ **Undo Functionality**: Easily revert the most recent game if needed
- 🎲 **Gambling**: Option to double the rating change of your next game (win big or lose big)
- 📊 **Channel Statistics**: View fun statistics like highest rating, biggest comebacks, win streaks, and more
- 📈 **Rating Charts**: Visualize rating history over time with interactive charts

## Installation

### Option 1: Add the Official Slackelo Bot to Your Workspace

1. Visit [https://andri.io/slackelo](https://andri.io/slackelo)
2. Click "Add to Slack"
3. Authorize the app for your workspace
4. Invite @Slackelo to any channels where you want to use it

Do note that the official Slackelo bot relies on my server, which might not be available someday. If you want to ensure that the bot is always available, consider self-hosting it.

### Option 2: Self-Host Slackelo

#### Prerequisites

- Python 3.8+
- SQLite 3
- A publicly accessible URL for OAuth redirects (can use ngrok for testing)

#### Step 1: Create a Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click "Create New App"
3. Choose "From scratch"
4. Name your app (e.g., "Slackelo") and select your workspace
5. Click "Create App"

#### Step 2: Configure Slack App Settings

1. Under "Basic Information", note your Signing Secret
2. Under "OAuth & Permissions":

   - Add the following Bot Token Scopes:
     - `channels:history`
     - `chat:write`
     - `commands`
   - Set your Redirect URL: `https://your-domain.com/oauth/redirect`

3. Under "Slash Commands", create the following commands:

   - `/game`
   - `/simulate`
   - `/leaderboard`
   - `/rating`
   - `/history`
   - `/kfactor`
   - `/gamble`
   - `/stats`
   - `/chart`
   - `/undo`
   - `/help`

   For each command, use `https://your-domain.com/slack/commands` as the Request URL

4. Under "Interactivity & Shortcuts":

   - Set the Request URL to `https://your-domain.com/events`

5. Install the app to your workspace from the "Install App" section

#### Step 3: Clone and Configure Slackelo

1. Clone the repository:

   ```bash
   git clone https://github.com/ndri/slackelo.git
   cd slackelo
   ```

2. Create a virtual environment and install dependencies:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Create a `.env` file based on the provided example:

   ```bash
   cp .env.example .env
   ```

4. Edit the `.env` file with your Slack app credentials and configuration:

   ```
   # Database configuration
   DB_PATH=slackelo.db
   INIT_SQL_FILE=init.sql

   # Slack API credentials
   SLACK_SIGNING_SECRET=your_slack_signing_secret
   SLACK_CLIENT_ID=your_slack_client_id
   SLACK_CLIENT_SECRET=your_slack_client_secret

   # OAuth and installation settings
   OAUTH_REDIRECT_URI=https://your-domain.com/oauth/redirect
   INSTALL_PATH=/install
   REDIRECT_URI_PATH=/oauth/redirect
   SUCCESS_URL=/slackelo/success
   INSTALL_SUCCESS_URL=

   # Server settings
   HOST=0.0.0.0
   PORT=8080
   ```

#### Step 4: Run the Application

1. Start the server:

   ```bash
   python app.py
   ```

2. Your Slackelo bot should now be running and accessible at `https://your-domain.com`

#### Deployment Options

For production deployment, consider serving Slackelo using a WSGI server like Gunicorn and a reverse proxy like Nginx.

Here is the guide I followed to deploy it: https://www.digitalocean.com/community/tutorials/how-to-serve-flask-applications-with-uwsgi-and-nginx-on-ubuntu-20-04

## Usage

Once installed, you can use the following commands in any channel where Slackelo is present:

- `/game @player1 @player2 @player3` - Record a game with players in ranking order (winner first)
- `/game @player1=@player2 @player3` - Record a game with ties (player1 and player2 tied for first)
- `/game @player1 @player2=@player3 @player4` - Record complex rankings (player1 first, player2 and player3 tied for second, player4 fourth)
- `/simulate @player1 @player2 @player3` - Simulate a game without saving
- `/leaderboard [limit]` - Show channel leaderboard (optional limit parameter)
- `/rating [@player]` - Show your rating or another player's rating
- `/history [@player]` - View your game history or another player's history
- `/kfactor [value]` - View or set the k-factor for this channel
- `/gamble` - Double the rating change of your next game (win big or lose big)
- `/stats` - Show channel statistics
- `/chart` - Show a rating history chart for all players
- `/undo` - Undo the last game in the channel
- `/help` - Show a help message with available commands

## How Elo Ratings Work

The Elo rating system is a method for calculating the relative skill levels of players in zero-sum games. After every game, the winning player takes points from the losing player. The number of points exchanged depends on the rating difference between players:

- When a higher-rated player beats a lower-rated player, relatively few points are exchanged
- When a lower-rated player beats a higher-rated player, more points are exchanged

The K-factor determines how dramatically ratings change after each game:

- Higher K-factor (e.g., 64): Ratings change more quickly
- Lower K-factor (e.g., 16): Ratings change more slowly
- Default K-factor: 32

Read more about the Elo rating system on [Wikipedia](https://en.wikipedia.org/wiki/Elo_rating_system).

## Contributing

Contributions are welcome! Feel free to submit a pull request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
