"""
Tests for the Elo maths in `elo.py`.
"""

import pytest

from elo import (
    calculate_elo_draw,
    calculate_elo_win,
    calculate_group_elo,
    calculate_group_elo_with_draws,
)


class TestHeadToHead:
    def test_evenly_matched_players_swing_by_half_the_k_factor(self):
        assert calculate_elo_win(1000, 1000) == (16, -16)

    def test_the_winner_gains_exactly_what_the_loser_drops(self):
        winner_change, loser_change = calculate_elo_win(1350, 1120)
        assert winner_change == -loser_change

    def test_beating_a_stronger_player_is_worth_more(self):
        upset, _ = calculate_elo_win(1000, 1200)
        expected, _ = calculate_elo_win(1200, 1000)
        assert upset > 16 > expected

    def test_k_factor_scales_the_swing(self):
        assert calculate_elo_win(1000, 1000, k_factor=16) == (8, -8)
        assert calculate_elo_win(1000, 1000, k_factor=64) == (32, -32)


class TestDraws:
    def test_a_draw_between_equals_changes_nothing(self):
        assert calculate_elo_draw(1000, 1000) == (0, 0)

    def test_the_underdog_gains_from_a_draw(self):
        underdog_change, favourite_change = calculate_elo_draw(1000, 1200)
        assert underdog_change > 0
        assert favourite_change == -underdog_change


class TestGroups:
    def test_ranked_group_of_equals_is_symmetric(self):
        assert calculate_group_elo_with_draws(
            [1000, 1000, 1000], [1, 2, 3]
        ) == [16, 0, -16]

    def test_changes_decrease_with_position(self):
        changes = calculate_group_elo_with_draws(
            [1000, 1000, 1000, 1000], [1, 2, 3, 4]
        )
        assert changes == sorted(changes, reverse=True)
        assert changes[0] > 0 > changes[-1]

    def test_a_group_is_roughly_zero_sum(self):
        changes = calculate_group_elo_with_draws(
            [1400, 1200, 1000, 900, 800], [1, 2, 3, 4, 5]
        )
        # Every change is rounded independently, so the total is only zero to
        # within the accumulated rounding error.
        assert abs(sum(changes)) <= len(changes)

    def test_everyone_tied_means_nobody_moves(self):
        assert calculate_group_elo_with_draws(
            [1000, 1000, 1000], [1, 1, 1]
        ) == [0, 0, 0]

    def test_tied_players_get_identical_changes(self):
        first, second, third, fourth = calculate_group_elo_with_draws(
            [1000, 1000, 1000, 1000], [1, 2, 2, 4]
        )
        assert second == third
        assert first > second > fourth

    def test_a_tie_between_unequal_players_favours_the_underdog(self):
        stronger, weaker = calculate_group_elo_with_draws(
            [1200, 1000], [1, 1]
        )
        assert weaker > 0 > stronger

    def test_position_numbers_only_matter_in_relative_order(self):
        # Positions after a tie skip, e.g. 1, 2, 2, 4 - the gap must not change
        # the maths compared to consecutive positions.
        assert calculate_group_elo_with_draws(
            [1000, 1100, 1200], [1, 5, 9]
        ) == calculate_group_elo_with_draws([1000, 1100, 1200], [1, 2, 3])


class TestLegacyGroupHelper:
    def test_it_ranks_players_in_the_order_given(self):
        elos = [1000, 1100, 1200]
        assert calculate_group_elo(elos) == calculate_group_elo_with_draws(
            elos, [1, 2, 3]
        )

    @pytest.mark.parametrize("k_factor", [16, 32, 64])
    def test_it_passes_the_k_factor_through(self, k_factor):
        elos = [1000, 1000, 1000]
        assert calculate_group_elo(elos, k_factor) == (
            calculate_group_elo_with_draws(elos, [1, 2, 3], k_factor)
        )
