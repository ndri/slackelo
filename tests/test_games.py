"""
Tests for recording, gambling on and undoing games.
"""

import pytest

from helpers import (
    ALICE,
    BOB,
    CAROL,
    CHANNEL,
    DAVE,
    OTHER_CHANNEL,
    TEAM,
    channel_player_ids,
    rating_of,
)
from slackelo import DEFAULT_RATING


def player_games(slackelo, game_id):
    """The stored result rows for one game, keyed by user."""
    rows = slackelo.db.execute_query(
        "SELECT * FROM player_games WHERE game_id = ?", (game_id,)
    )
    return {row["user_id"]: row for row in rows}


class TestRecordingAGame:
    def test_the_winner_gains_and_the_loser_drops(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1016
        assert slackelo.get_player_channel_rating(BOB, CHANNEL) == 984

    def test_everyone_who_played_joins_the_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        assert channel_player_ids(slackelo, CHANNEL) == {ALICE, BOB, CAROL}

    def test_the_result_is_stored_for_each_player(self, slackelo, game):
        game_id = game(CHANNEL, ALICE, BOB)
        rows = player_games(slackelo, game_id)

        assert rows[ALICE]["position"] == 1
        assert rows[ALICE]["rating_before"] == DEFAULT_RATING
        assert rows[ALICE]["rating_after"] == 1016
        assert rows[BOB]["position"] == 2
        assert rows[BOB]["rating_after"] == 984

    def test_the_stored_rating_matches_the_players_new_rating(
        self, slackelo, game
    ):
        game_id = game(CHANNEL, ALICE, BOB)
        rows = player_games(slackelo, game_id)

        assert rows[ALICE]["rating_after"] == rating_of(slackelo, ALICE, CHANNEL)

    def test_the_game_is_tied_to_the_channel_and_team(self, slackelo, game):
        game_id = game(CHANNEL, ALICE, BOB, team_id=TEAM)

        stored = slackelo.db.execute_query(
            "SELECT channel_id FROM games WHERE id = ?", (game_id,)
        )
        assert stored[0]["channel_id"] == CHANNEL

        channel = slackelo.get_or_create_channel(CHANNEL)
        assert channel["team_id"] == TEAM

    def test_ratings_carry_over_between_games(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) > 1016

    def test_games_in_another_channel_do_not_interfere(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, BOB, ALICE)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1016
        assert slackelo.get_player_channel_rating(ALICE, OTHER_CHANNEL) == 984


class TestTies:
    def test_tied_players_share_a_position_and_the_next_rank_skips(
        self, slackelo, game
    ):
        game_id = game(CHANNEL, ALICE, [BOB, CAROL], DAVE)
        rows = player_games(slackelo, game_id)

        assert rows[ALICE]["position"] == 1
        assert rows[BOB]["position"] == 2
        assert rows[CAROL]["position"] == 2
        assert rows[DAVE]["position"] == 4

    def test_tied_players_end_on_the_same_rating(self, slackelo, game):
        game(CHANNEL, ALICE, [BOB, CAROL], DAVE)

        assert rating_of(slackelo, BOB, CHANNEL) == rating_of(
            slackelo, CAROL, CHANNEL
        )

    def test_an_all_play_all_draw_changes_nothing(self, slackelo, game):
        game(CHANNEL, [ALICE, BOB, CAROL])

        for user_id in (ALICE, BOB, CAROL):
            assert rating_of(slackelo, user_id, CHANNEL) == DEFAULT_RATING


class TestValidation:
    def test_a_game_needs_at_least_two_players(self, slackelo):
        with pytest.raises(Exception, match="at least 2 players"):
            slackelo.create_game(CHANNEL, [[ALICE]])

    def test_no_players_at_all_is_rejected(self, slackelo):
        with pytest.raises(Exception, match="at least 2 players"):
            slackelo.create_game(CHANNEL, [])

    def test_a_player_cannot_appear_twice(self, slackelo):
        with pytest.raises(Exception, match="multiple positions"):
            slackelo.create_game(CHANNEL, [[ALICE], [ALICE]])

    def test_a_player_cannot_be_tied_with_themselves(self, slackelo):
        with pytest.raises(Exception, match="multiple positions"):
            slackelo.create_game(CHANNEL, [[ALICE, ALICE], [BOB]])

    def test_a_rejected_game_is_not_recorded(self, slackelo):
        with pytest.raises(Exception):
            slackelo.create_game(CHANNEL, [[ALICE], [ALICE]])

        assert slackelo.db.execute_query("SELECT * FROM games") == []


class TestGambling:
    def test_toggling_reports_the_new_state(self, slackelo):
        assert slackelo.toggle_player_gambling(ALICE, CHANNEL) is True
        assert slackelo.toggle_player_gambling(ALICE, CHANNEL) is False

    def test_the_state_is_readable(self, slackelo):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        assert slackelo.is_player_gambling(ALICE, CHANNEL) is True

    def test_it_is_per_channel(self, slackelo):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        assert slackelo.is_player_gambling(ALICE, OTHER_CHANNEL) is False

    def test_a_gambler_moves_twice_as_far(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1032

    def test_a_losing_gambler_drops_twice_as_far(self, slackelo, game):
        slackelo.toggle_player_gambling(BOB, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(BOB, CHANNEL) == 968

    def test_the_other_players_are_unaffected(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(BOB, CHANNEL) == 984

    def test_the_game_records_who_gambled(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game_id = game(CHANNEL, ALICE, BOB)
        rows = player_games(slackelo, game_id)

        assert rows[ALICE]["gambled"] == 1
        assert rows[BOB]["gambled"] == 0

    def test_gambling_only_lasts_one_game(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.is_player_gambling(ALICE, CHANNEL) is False

        game_id = game(CHANNEL, ALICE, BOB)
        assert player_games(slackelo, game_id)[ALICE]["gambled"] == 0


class TestUndo:
    def test_ratings_go_back_to_what_they_were(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)
        slackelo.undo_last_game(CHANNEL)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1016
        assert slackelo.get_player_channel_rating(BOB, CHANNEL) == 984

    def test_the_game_and_its_results_are_deleted(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game_id = game(CHANNEL, BOB, ALICE)
        slackelo.undo_last_game(CHANNEL)

        assert slackelo.db.execute_query(
            "SELECT * FROM games WHERE id = ?", (game_id,)
        ) == []
        assert player_games(slackelo, game_id) == {}

    def test_it_returns_the_timestamp_of_the_undone_game(self, slackelo, game):
        game_id = game(CHANNEL, ALICE, BOB)
        stored = slackelo.db.execute_query(
            "SELECT timestamp FROM games WHERE id = ?", (game_id,)
        )

        assert slackelo.undo_last_game(CHANNEL) == stored[0]["timestamp"]

    def test_undoing_the_only_game_returns_players_to_the_default(
        self, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB)
        slackelo.undo_last_game(CHANNEL)

        assert rating_of(slackelo, ALICE, CHANNEL) == DEFAULT_RATING

    def test_it_undoes_one_game_at_a_time(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        slackelo.undo_last_game(CHANNEL)

        assert len(slackelo.db.execute_query("SELECT * FROM games")) == 1

    def test_it_only_looks_at_its_own_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, ALICE, BOB)
        slackelo.undo_last_game(CHANNEL)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1000
        assert slackelo.get_player_channel_rating(ALICE, OTHER_CHANNEL) == 1016

    def test_undoing_with_no_games_fails(self, slackelo):
        with pytest.raises(Exception, match="No games to undo"):
            slackelo.undo_last_game(CHANNEL)

    def test_a_gambled_game_is_fully_reverted(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)
        slackelo.undo_last_game(CHANNEL)

        assert rating_of(slackelo, ALICE, CHANNEL) == DEFAULT_RATING


class TestResetChannel:
    def test_it_removes_games_players_and_ratings(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.reset_channel(CHANNEL) == 2
        assert slackelo.db.execute_query(
            "SELECT * FROM games WHERE channel_id = ?", (CHANNEL,)
        ) == []
        assert slackelo.db.execute_query("SELECT * FROM player_games") == []
        assert channel_player_ids(slackelo, CHANNEL) == set()

    def test_it_leaves_other_channels_alone(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, ALICE, BOB)
        slackelo.reset_channel(CHANNEL)

        assert slackelo.get_player_channel_rating(ALICE, OTHER_CHANNEL) == 1016
        assert channel_player_ids(slackelo, OTHER_CHANNEL) == {ALICE, BOB}

    def test_resetting_an_empty_channel_is_harmless(self, slackelo):
        assert slackelo.reset_channel(CHANNEL) == 0
