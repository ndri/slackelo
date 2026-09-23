"""
Tests for the leaderboard, per-player history and the chart's rating series.
"""

from helpers import (
    ALICE,
    BOB,
    CAROL,
    CHANNEL,
    DAVE,
    OTHER_CHANNEL,
    rating_of,
)


class TestLeaderboard:
    def test_it_is_ordered_by_rating(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        leaderboard = slackelo.get_channel_leaderboard(CHANNEL)

        assert [row["user_id"] for row in leaderboard] == [ALICE, BOB, CAROL]

    def test_it_shows_everyone_by_default(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL, DAVE)
        assert len(slackelo.get_channel_leaderboard(CHANNEL)) == 4

    def test_a_limit_truncates_it(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL, DAVE)
        leaderboard = slackelo.get_channel_leaderboard(CHANNEL, limit=2)

        assert [row["user_id"] for row in leaderboard] == [ALICE, BOB]

    def test_it_counts_games_played(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, CAROL)

        counts = {
            row["user_id"]: row["games_played"]
            for row in slackelo.get_channel_leaderboard(CHANNEL)
        }
        assert counts == {ALICE: 3, BOB: 2, CAROL: 1}

    def test_the_game_count_is_per_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, ALICE, BOB)

        counts = {
            row["user_id"]: row["games_played"]
            for row in slackelo.get_channel_leaderboard(CHANNEL)
        }
        assert counts[ALICE] == 1

    def test_it_only_covers_its_own_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, CAROL, DAVE)

        assert {
            row["user_id"] for row in slackelo.get_channel_leaderboard(CHANNEL)
        } == {ALICE, BOB}

    def test_an_empty_channel_has_an_empty_leaderboard(self, slackelo):
        assert slackelo.get_channel_leaderboard(CHANNEL) == []

    def test_players_on_the_same_rating_both_appear(self, slackelo, game):
        game(CHANNEL, ALICE, [BOB, CAROL])
        leaderboard = slackelo.get_channel_leaderboard(CHANNEL)

        ratings = [row["rating"] for row in leaderboard]
        assert ratings[1] == ratings[2]


class TestPlayerGameHistory:
    def test_it_returns_the_most_recent_games_first(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        history = slackelo.get_player_game_history(ALICE, CHANNEL)
        assert [row["position"] for row in history] == [2, 1]

    def test_it_records_the_ratings_either_side_of_the_game(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        latest = slackelo.get_player_game_history(ALICE, CHANNEL)[0]

        assert latest["rating_before"] == 1000
        assert latest["rating_after"] == 1016

    def test_it_is_limited(self, slackelo, game):
        for _ in range(5):
            game(CHANNEL, ALICE, BOB)

        assert len(slackelo.get_player_game_history(ALICE, CHANNEL, 3)) == 3

    def test_the_limit_takes_the_newest_games(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        latest = slackelo.get_player_game_history(ALICE, CHANNEL, 1)
        assert latest[0]["position"] == 2

    def test_it_marks_gambled_games(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_game_history(ALICE, CHANNEL)[0]["gambled"] == 1

    def test_it_only_covers_its_own_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, ALICE, BOB)

        assert len(slackelo.get_player_game_history(ALICE, CHANNEL)) == 1

    def test_a_player_with_no_games_has_no_history(self, slackelo):
        assert slackelo.get_player_game_history(ALICE, CHANNEL) == []


class TestGameCount:
    def test_it_counts_every_game_in_the_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, CAROL)

        assert slackelo.get_player_game_count(ALICE, CHANNEL) == 2
        assert slackelo.get_player_game_count(BOB, CHANNEL) == 1

    def test_it_is_zero_for_someone_who_has_not_played(self, slackelo):
        assert slackelo.get_player_game_count(ALICE, CHANNEL) == 0

    def test_it_is_per_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, ALICE, BOB)

        assert slackelo.get_player_game_count(ALICE, CHANNEL) == 1


class TestRatingHistoryForTheChart:
    def test_an_empty_channel_has_no_series(self, slackelo):
        assert slackelo.get_player_rating_history(CHANNEL) == {}

    def test_every_player_gets_a_series(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        assert set(slackelo.get_player_rating_history(CHANNEL)) == {ALICE, BOB}

    def test_a_series_starts_from_the_rating_the_player_began_with(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        history = slackelo.get_player_rating_history(CHANNEL)

        assert history[ALICE][0] == (0, 1000, False)

    def test_a_played_game_is_marked_as_played(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        history = slackelo.get_player_rating_history(CHANNEL)

        assert history[ALICE][1] == (1, 1016, True)

    def test_a_game_a_player_sat_out_carries_their_rating_forward(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, CAROL)

        history = slackelo.get_player_rating_history(CHANNEL)
        game_numbers = [point[0] for point in history[ALICE]]
        assert game_numbers == [0, 1, 2]

        sat_out = history[ALICE][2]
        assert sat_out == (2, 1016, False)

    def test_a_late_joiner_is_anchored_just_before_their_first_game(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, CAROL)

        history = slackelo.get_player_rating_history(CHANNEL)
        assert history[CAROL][0] == (1, 1000, False)
        assert [point[0] for point in history[CAROL]] == [1, 2]

    def test_the_last_point_is_the_players_current_rating(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, CAROL)

        history = slackelo.get_player_rating_history(CHANNEL)
        for user_id, points in history.items():
            assert points[-1][1] == rating_of(slackelo, user_id, CHANNEL)

    def test_every_series_covers_the_same_final_game(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, CAROL)
        game(CHANNEL, CAROL, ALICE)

        history = slackelo.get_player_rating_history(CHANNEL)
        assert {points[-1][0] for points in history.values()} == {3}

    def test_it_only_covers_its_own_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, CAROL, DAVE)

        assert set(slackelo.get_player_rating_history(CHANNEL)) == {ALICE, BOB}


class TestLeaderboardLimits:
    def test_a_limit_of_zero_returns_nobody(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        assert slackelo.get_channel_leaderboard(CHANNEL, limit=0) == []

    def test_a_limit_larger_than_the_channel_is_harmless(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        assert len(slackelo.get_channel_leaderboard(CHANNEL, limit=50)) == 2


class TestRatingHistoryWithoutResults:
    def test_games_with_no_recorded_results_produce_no_series(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        slackelo.db.execute_non_query("DELETE FROM player_games")

        assert slackelo.get_player_rating_history(CHANNEL) == {}
