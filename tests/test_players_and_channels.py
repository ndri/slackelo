"""
Tests for player, channel and k-factor bookkeeping in `slackelo.py`.
"""

import pytest

from helpers import ALICE, BOB, CHANNEL, OTHER_CHANNEL, TEAM, channel_player_ids
from slackelo import DEFAULT_K_FACTOR, DEFAULT_RATING


class TestPlayers:
    def test_a_player_is_created_once(self, slackelo):
        slackelo.get_or_create_player(ALICE)
        slackelo.get_or_create_player(ALICE)

        rows = slackelo.db.execute_query(
            "SELECT * FROM players WHERE user_id = ?", (ALICE,)
        )
        assert len(rows) == 1


class TestChannels:
    def test_a_new_channel_gets_the_default_k_factor(self, slackelo):
        channel = slackelo.get_or_create_channel(CHANNEL)
        assert channel["k_factor"] == DEFAULT_K_FACTOR

    def test_the_team_id_is_stored(self, slackelo):
        channel = slackelo.get_or_create_channel(CHANNEL, TEAM)
        assert channel["team_id"] == TEAM

    def test_a_missing_team_id_is_filled_in_later(self, slackelo):
        slackelo.get_or_create_channel(CHANNEL)
        channel = slackelo.get_or_create_channel(CHANNEL, TEAM)
        assert channel["team_id"] == TEAM

    def test_an_existing_team_id_is_not_overwritten(self, slackelo):
        slackelo.get_or_create_channel(CHANNEL, TEAM)
        channel = slackelo.get_or_create_channel(CHANNEL, "T99OTHER")
        assert channel["team_id"] == TEAM


class TestChannelPlayers:
    def test_a_new_channel_player_starts_at_the_default_rating(self, slackelo):
        channel_player = slackelo.get_or_create_channel_player(ALICE, CHANNEL)

        assert channel_player["rating"] == DEFAULT_RATING
        assert channel_player["gambling"] == 0

    def test_creating_a_channel_player_creates_the_player_and_channel(
        self, slackelo
    ):
        slackelo.get_or_create_channel_player(ALICE, CHANNEL)

        assert slackelo.db.execute_query(
            "SELECT 1 FROM players WHERE user_id = ?", (ALICE,)
        )
        assert slackelo.db.execute_query(
            "SELECT 1 FROM channels WHERE channel_id = ?", (CHANNEL,)
        )

    def test_ratings_are_per_channel(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) > DEFAULT_RATING
        assert (
            slackelo.get_player_channel_rating(ALICE, OTHER_CHANNEL)
            == DEFAULT_RATING
        )


class TestReadOnlyLookups:
    """
    Reading a player must never put them on the leaderboard. This is the bug
    class behind `/rating` and `/simulate` adding players to `/leaderboard`.
    """

    def test_get_channel_player_returns_nothing_for_a_stranger(self, slackelo):
        assert slackelo.get_channel_player(ALICE, CHANNEL) is None

    def test_get_channel_player_does_not_create_a_row(self, slackelo):
        slackelo.get_channel_player(ALICE, CHANNEL)
        assert channel_player_ids(slackelo, CHANNEL) == set()

    def test_reading_a_rating_reports_the_default_without_storing_it(
        self, slackelo
    ):
        assert (
            slackelo.get_player_channel_rating(ALICE, CHANNEL) == DEFAULT_RATING
        )
        assert channel_player_ids(slackelo, CHANNEL) == set()

    def test_reading_gambling_status_does_not_create_a_row(self, slackelo):
        assert slackelo.is_player_gambling(ALICE, CHANNEL) is False
        assert channel_player_ids(slackelo, CHANNEL) == set()


class TestKFactor:
    def test_an_unconfigured_channel_uses_the_default(self, slackelo):
        assert slackelo.get_channel_k_factor(CHANNEL) == DEFAULT_K_FACTOR

    def test_setting_and_reading_it_back(self, slackelo):
        slackelo.set_channel_k_factor(CHANNEL, 64)
        assert slackelo.get_channel_k_factor(CHANNEL) == 64

    def test_it_is_per_channel(self, slackelo):
        slackelo.set_channel_k_factor(CHANNEL, 64)
        assert slackelo.get_channel_k_factor(OTHER_CHANNEL) == DEFAULT_K_FACTOR

    @pytest.mark.parametrize("invalid", [0, -1, -32])
    def test_it_must_be_positive(self, slackelo, invalid):
        with pytest.raises(ValueError):
            slackelo.set_channel_k_factor(CHANNEL, invalid)

    def test_a_rejected_value_leaves_the_old_one_in_place(self, slackelo):
        slackelo.set_channel_k_factor(CHANNEL, 16)

        with pytest.raises(ValueError):
            slackelo.set_channel_k_factor(CHANNEL, 0)

        assert slackelo.get_channel_k_factor(CHANNEL) == 16

    def test_it_changes_how_far_ratings_move(self, slackelo, game):
        slackelo.set_channel_k_factor(CHANNEL, 16)
        game(CHANNEL, ALICE, BOB)

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1008
