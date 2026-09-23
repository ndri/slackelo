"""
Tests for `/simulate`, which must predict a game without changing anything.
"""

import pytest

from helpers import ALICE, BOB, CAROL, CHANNEL, channel_player_ids, rating_of
from slackelo import DEFAULT_RATING


class TestSimulationLeavesNoTrace:
    """
    Regression tests: simulating a game used to add every player named to the
    channel, so they turned up on `/leaderboard` without having played.
    """

    def test_it_does_not_add_players_to_the_channel(self, slackelo):
        slackelo.simulate_game(CHANNEL, [[ALICE], [BOB]])
        assert channel_player_ids(slackelo, CHANNEL) == set()

    def test_it_does_not_record_a_game(self, slackelo):
        slackelo.simulate_game(CHANNEL, [[ALICE], [BOB]])

        assert slackelo.db.execute_query("SELECT * FROM games") == []
        assert slackelo.db.execute_query("SELECT * FROM player_games") == []

    def test_it_does_not_move_the_ratings_of_existing_players(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        before = rating_of(slackelo, ALICE, CHANNEL)

        slackelo.simulate_game(CHANNEL, [[BOB], [ALICE]])

        assert rating_of(slackelo, ALICE, CHANNEL) == before

    def test_it_does_not_consume_a_gambling_flag(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        slackelo.toggle_player_gambling(ALICE, CHANNEL)

        slackelo.simulate_game(CHANNEL, [[ALICE], [BOB]])

        assert slackelo.is_player_gambling(ALICE, CHANNEL) is True


class TestSimulatedNumbers:
    def test_unknown_players_are_treated_as_starting_out(self, slackelo):
        pre, post, _ = slackelo.simulate_game(CHANNEL, [[ALICE], [BOB]])

        assert pre == {ALICE: DEFAULT_RATING, BOB: DEFAULT_RATING}
        assert post == {ALICE: 1016, BOB: 984}

    def test_it_uses_the_ratings_players_actually_have(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        pre, _, _ = slackelo.simulate_game(CHANNEL, [[BOB], [ALICE]])

        assert pre == {BOB: 984, ALICE: 1016}

    def test_it_predicts_exactly_what_recording_the_game_would_do(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB, CAROL)

        _, predicted, _ = slackelo.simulate_game(
            CHANNEL, [[CAROL], [ALICE], [BOB]]
        )
        game(CHANNEL, CAROL, ALICE, BOB)

        actual = {
            user_id: rating_of(slackelo, user_id, CHANNEL)
            for user_id in (ALICE, BOB, CAROL)
        }
        assert predicted == actual

    def test_it_reports_positions_including_ties(self, slackelo):
        _, _, positions = slackelo.simulate_game(
            CHANNEL, [[ALICE], [BOB, CAROL]]
        )
        assert positions == {ALICE: 1, BOB: 2, CAROL: 2}

    def test_it_honours_the_channel_k_factor(self, slackelo):
        slackelo.set_channel_k_factor(CHANNEL, 64)
        _, post, _ = slackelo.simulate_game(CHANNEL, [[ALICE], [BOB]])

        assert post[ALICE] == 1032

    def test_it_doubles_the_change_for_a_gambler(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        slackelo.toggle_player_gambling(BOB, CHANNEL)

        pre, post, _ = slackelo.simulate_game(CHANNEL, [[BOB], [ALICE]])

        assert (post[BOB] - pre[BOB]) == 2 * (pre[ALICE] - post[ALICE])


class TestValidation:
    def test_a_simulation_needs_at_least_two_players(self, slackelo):
        with pytest.raises(Exception, match="at least 2 players"):
            slackelo.simulate_game(CHANNEL, [[ALICE]])

    def test_a_player_cannot_appear_twice(self, slackelo):
        with pytest.raises(Exception, match="multiple positions"):
            slackelo.simulate_game(CHANNEL, [[ALICE], [ALICE]])
