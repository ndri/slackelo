"""
Tests for the awards behind `/stats`.

Each test builds the smallest channel history that makes one award
unambiguous, rather than one shared fixture where several players could
plausibly win.
"""

import pytest

from helpers import ALICE, BOB, CAROL, CHANNEL, DAVE, ERIN, OTHER_CHANNEL


@pytest.fixture
def swingy(slackelo):
    """
    A channel with a large k-factor.

    Several awards only trigger on movements of more than 100 points, which
    would otherwise take a dozen games to build up.
    """
    slackelo.set_channel_k_factor(CHANNEL, 200)
    return slackelo


class TestEmptyChannel:
    def test_there_are_no_awards_without_games(self, slackelo):
        assert slackelo.get_channel_statistics(CHANNEL) == {"total_games": 0}

    def test_games_elsewhere_do_not_count(self, slackelo, game):
        game(OTHER_CHANNEL, ALICE, BOB)
        assert slackelo.get_channel_statistics(CHANNEL) == {"total_games": 0}


class TestGameCount:
    def test_it_counts_the_channels_games(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(OTHER_CHANNEL, ALICE, BOB)

        assert slackelo.get_channel_statistics(CHANNEL)["total_games"] == 2


class TestRatingExtremes:
    def test_the_highest_rating_ever_reached(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["highest_rating"]["user_id"] == ALICE
        # Alice peaked before losing the last game, and the peak is what counts.
        assert stats["highest_rating"]["rating"] > slackelo.get_player_channel_rating(
            ALICE, CHANNEL
        )

    def test_the_lowest_rating_ever_reached(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["lowest_rating"]["user_id"] == BOB
        assert stats["lowest_rating"]["rating"] == (
            slackelo.get_player_channel_rating(BOB, CHANNEL)
        )

    def test_the_biggest_gain_and_loss_in_a_single_game(self, swingy, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, CAROL, DAVE)

        stats = swingy.get_channel_statistics(CHANNEL)
        assert stats["biggest_increase"]["change"] == 100
        assert stats["biggest_decrease"]["change"] == -100

    def test_a_channel_where_nothing_ever_moved_has_no_gain_or_loss(
        self, slackelo, game
    ):
        game(CHANNEL, [ALICE, BOB])

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert "biggest_increase" not in stats
        assert "biggest_decrease" not in stats


class TestFinishingPositions:
    def test_most_first_places(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_wins"] == {"user_id": ALICE, "wins": 2}

    def test_most_last_places(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, ALICE, BOB, CAROL)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_losses"] == {"user_id": CAROL, "losses": 2}

    def test_last_place_is_relative_to_the_size_of_the_game(
        self, slackelo, game
    ):
        # Carol is 3rd of 3 here, which is last; Alice is 3rd of 4 there, which
        # is not.
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, BOB, CAROL, ALICE, DAVE)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_losses"]["user_id"] in (CAROL, DAVE)
        assert stats["most_losses"]["losses"] == 1

    def test_most_games_played(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, CAROL)
        game(CHANNEL, ALICE, DAVE)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_games"] == {"user_id": ALICE, "games": 3}

    def test_the_perennial_runner_up(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, ALICE, BOB, CAROL)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_second_places"] == {
            "user_id": BOB,
            "second_places": 2,
        }

    def test_a_single_second_place_is_not_an_award(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        assert "most_second_places" not in slackelo.get_channel_statistics(
            CHANNEL
        )


class TestPerfectlyBalanced:
    def test_repeatedly_ending_level_is_an_award(self, slackelo, game):
        game(CHANNEL, [ALICE, BOB])
        game(CHANNEL, [ALICE, BOB])

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_zero_changes"]["user_id"] in (ALICE, BOB)
        assert stats["most_zero_changes"]["zero_changes"] == 2

    def test_a_single_flat_game_is_not_an_award(self, slackelo, game):
        game(CHANNEL, [ALICE, BOB])
        assert "most_zero_changes" not in slackelo.get_channel_statistics(
            CHANNEL
        )


class TestStreaks:
    def test_consecutive_wins(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["longest_win_streak"] == {"user_id": ALICE, "streak": 3}

    def test_a_streak_is_broken_by_a_loss(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["longest_win_streak"]["streak"] == 2

    def test_a_single_win_is_not_a_streak(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        assert "longest_win_streak" not in slackelo.get_channel_statistics(
            CHANNEL
        )

    def test_consecutive_last_places(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, CAROL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["longest_losing_streak"] == {"user_id": CAROL, "streak": 2}

    def test_a_single_last_place_is_not_a_streak(self, slackelo, game):
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, CAROL, ALICE, BOB)

        assert "longest_losing_streak" not in slackelo.get_channel_statistics(
            CHANNEL
        )

    def test_games_sat_out_do_not_break_a_streak(self, slackelo, game):
        # A streak is over a player's own games, not over the channel's.
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, CAROL, DAVE)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["longest_win_streak"] == {"user_id": ALICE, "streak": 2}


class TestComebacksAndCollapses:
    def test_a_rise_after_a_low_point(self, swingy, game):
        game(CHANNEL, BOB, ALICE)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)

        stats = swingy.get_channel_statistics(CHANNEL)
        comeback = stats["biggest_comeback"]
        assert comeback["user_id"] == ALICE
        assert comeback["to"] - comeback["from"] == comeback["comeback"]
        assert comeback["comeback"] > 100

    def test_a_fall_after_a_high_point(self, swingy, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)
        game(CHANNEL, BOB, ALICE)

        stats = swingy.get_channel_statistics(CHANNEL)
        collapse = stats["biggest_collapse"]
        assert collapse["user_id"] == ALICE
        assert collapse["from"] - collapse["to"] == collapse["collapse"]
        assert collapse["collapse"] > 100

    def test_small_swings_are_not_worth_reporting(self, slackelo, game):
        game(CHANNEL, BOB, ALICE)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert "biggest_comeback" not in stats
        assert "biggest_collapse" not in stats

    def test_both_awards_only_look_forwards_in_time(self, swingy, game):
        # Alice peaks first and then only falls; Bob bottoms out first and then
        # only climbs. Alice's high is a collapse and Bob's low is a comeback,
        # never the other way round.
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)
        game(CHANNEL, BOB, ALICE)

        stats = swingy.get_channel_statistics(CHANNEL)
        assert stats["biggest_comeback"]["user_id"] == BOB
        assert stats["biggest_collapse"]["user_id"] == ALICE


class TestGiantSlayer:
    def test_it_finds_the_biggest_upset(self, swingy, game):
        # Bob climbs well clear of the field, then Carol beats him.
        game(CHANNEL, BOB, DAVE)
        game(CHANNEL, BOB, DAVE)
        game(CHANNEL, CAROL, BOB)

        stats = swingy.get_channel_statistics(CHANNEL)
        assert stats["giant_slayer"]["user_id"] == CAROL
        assert stats["giant_slayer"]["beaten_user_id"] == BOB
        assert stats["giant_slayer"]["gap"] > 0

    def test_the_gap_is_measured_before_the_game(self, swingy, game):
        game(CHANNEL, BOB, DAVE)
        game(CHANNEL, CAROL, BOB)

        stats = swingy.get_channel_statistics(CHANNEL)
        history = swingy.get_player_game_history(CAROL, CHANNEL, 1)
        bob_history = swingy.get_player_game_history(BOB, CHANNEL, 1)

        assert stats["giant_slayer"]["gap"] == (
            bob_history[0]["rating_before"] - history[0]["rating_before"]
        )

    def test_beating_an_equal_is_not_an_upset(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        assert "giant_slayer" not in slackelo.get_channel_statistics(CHANNEL)


class TestVolatility:
    def test_the_swingiest_and_steadiest_players(self, slackelo, game):
        # Alice alternates wins and losses against a mixed field; Dave and Erin
        # only ever draw, so they never move at all.
        for _ in range(3):
            game(CHANNEL, ALICE, BOB)
            game(CHANNEL, BOB, ALICE)
            game(CHANNEL, [DAVE, ERIN])

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["most_volatile"]["user_id"] in (ALICE, BOB)
        assert stats["most_volatile"]["volatility"] > 0
        assert stats["most_consistent"]["user_id"] in (DAVE, ERIN)
        assert stats["most_consistent"]["volatility"] == 0

    def test_two_games_are_not_enough_to_judge(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert "most_volatile" not in stats
        assert "most_consistent" not in stats


class TestGambling:
    def test_a_winning_gambler_is_credited_with_half_the_swing(
        self, slackelo, game
    ):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        # The whole change was 32 because it was doubled; 16 of that was the
        # gamble.
        assert stats["best_gambler"] == {"user_id": ALICE, "total": 16}

    def test_a_losing_gambler_is_recorded_as_a_negative_total(
        self, slackelo, game
    ):
        slackelo.toggle_player_gambling(BOB, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["worst_gambler"] == {"user_id": BOB, "total": -16}

    def test_only_gambled_games_count(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert "best_gambler" not in stats
        assert "worst_gambler" not in stats

    def test_the_addict_is_whoever_gambles_most_often(self, slackelo, game):
        # Alice gambles in all three of her games, Bob in one of three.
        for _ in range(3):
            slackelo.toggle_player_gambling(ALICE, CHANNEL)
            game(CHANNEL, ALICE, BOB)
        slackelo.toggle_player_gambling(BOB, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        stats = slackelo.get_channel_statistics(CHANNEL)
        assert stats["gambling_addict"]["user_id"] == ALICE
        assert stats["gambling_addict"]["gambles"] == 3
        assert stats["gambling_addict"]["games"] == 4
        assert stats["gambling_addict"]["rate"] == 75

    def test_the_award_needs_a_few_games_behind_it(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        assert "gambling_addict" not in slackelo.get_channel_statistics(CHANNEL)

    def test_never_gambling_wins_nothing(self, slackelo, game):
        for _ in range(3):
            game(CHANNEL, ALICE, BOB)

        assert "gambling_addict" not in slackelo.get_channel_statistics(CHANNEL)


class TestGamblingLeaderboard:
    def test_it_ranks_gamblers_by_net_points(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        slackelo.toggle_player_gambling(BOB, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        leaderboard = slackelo.get_gambling_leaderboard(CHANNEL)
        assert [row["user_id"] for row in leaderboard] == [ALICE, BOB]
        assert leaderboard[0]["net_gambling"] == 16
        assert leaderboard[1]["net_gambling"] == -16

    def test_it_counts_how_many_times_each_player_gambled(self, slackelo, game):
        for _ in range(2):
            slackelo.toggle_player_gambling(ALICE, CHANNEL)
            game(CHANNEL, ALICE, BOB)

        leaderboard = slackelo.get_gambling_leaderboard(CHANNEL)
        assert leaderboard[0]["gambles"] == 2

    def test_players_who_never_gambled_are_left_out(self, slackelo, game):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)

        leaderboard = slackelo.get_gambling_leaderboard(CHANNEL)
        assert [row["user_id"] for row in leaderboard] == [ALICE]

    def test_a_channel_with_no_gambling_has_an_empty_board(self, slackelo, game):
        game(CHANNEL, ALICE, BOB)
        assert slackelo.get_gambling_leaderboard(CHANNEL) == []
