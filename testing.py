from slackelo import Slackelo

slackelo = Slackelo("test.sqlite3", "init.sql")

game_1 = slackelo.create_game(
    "mario_kart", [["player1"], ["player2", "player3"], ["player4"]]
)

print(game_1)
print(slackelo.get_channel_leaderboard("mario_kart"))

game_2 = slackelo.create_game(
    "mario_kart", [["player1", "player2", "player3", "player4"]]
)

print(game_2)
print(slackelo.get_channel_leaderboard("mario_kart"))

game_3 = slackelo.create_game(
    "mario_kart", [["player5"], ["player1"], ["player4"], ["player2"]]
)
print(game_3)
print(slackelo.get_channel_leaderboard("mario_kart"))
