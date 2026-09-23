"""
Tests for the Slack text parsing in `utils.py`.
"""

import pytest

from helpers import ALICE, BOB, CAROL, DAVE, mention
from utils import extract_user_ids, get_ordinal_suffix, parse_player_rankings


class TestExtractUserIds:
    def test_it_reads_a_bare_mention(self):
        assert extract_user_ids(f"<@{ALICE}>") == [ALICE]

    def test_it_reads_a_mention_carrying_a_display_name(self):
        assert extract_user_ids(f"<@{ALICE}|alice>") == [ALICE]

    def test_it_reads_every_mention_in_order(self):
        text = f"{mention(ALICE)} beat {mention(BOB)} and {mention(CAROL)}"
        assert extract_user_ids(text) == [ALICE, BOB, CAROL]

    def test_it_ignores_text_that_is_not_a_mention(self):
        assert extract_user_ids("alice beat bob") == []

    def test_it_ignores_a_plain_at_sign(self):
        assert extract_user_ids("@alice @bob") == []


class TestParsePlayerRankings:
    def test_each_player_gets_their_own_rank(self):
        text = " ".join(mention(u) for u in (ALICE, BOB, CAROL))
        assert parse_player_rankings(text) == [[ALICE], [BOB], [CAROL]]

    @pytest.mark.parametrize(
        "separator",
        ["=", " = ", "= ", " ="],
        ids=["tight", "spaced", "space-after", "space-before"],
    )
    def test_equals_signs_group_players_however_they_are_spaced(
        self, separator
    ):
        text = f"{mention(ALICE)} {mention(BOB)}{separator}{mention(CAROL)}"
        assert parse_player_rankings(text) == [[ALICE], [BOB, CAROL]]

    def test_more_than_two_players_can_share_a_rank(self):
        text = f"{mention(ALICE)} = {mention(BOB)} = {mention(CAROL)}"
        assert parse_player_rankings(text) == [[ALICE, BOB, CAROL]]

    def test_a_tie_can_come_first(self):
        text = f"{mention(ALICE)}={mention(BOB)} {mention(CAROL)}"
        assert parse_player_rankings(text) == [[ALICE, BOB], [CAROL]]

    def test_several_separate_ties(self):
        text = (
            f"{mention(ALICE)}={mention(BOB)} {mention(CAROL)}={mention(DAVE)}"
        )
        assert parse_player_rankings(text) == [[ALICE, BOB], [CAROL, DAVE]]

    def test_empty_text_has_no_ranks(self):
        assert parse_player_rankings("") == []

    def test_words_between_mentions_are_skipped(self):
        text = f"{mention(ALICE)} then {mention(BOB)}"
        assert parse_player_rankings(text) == [[ALICE], [BOB]]

    def test_extra_whitespace_does_not_create_empty_ranks(self):
        text = f"  {mention(ALICE)}    {mention(BOB)}  "
        assert parse_player_rankings(text) == [[ALICE], [BOB]]


class TestOrdinalSuffix:
    @pytest.mark.parametrize(
        "number,suffix",
        [
            (1, "st"),
            (2, "nd"),
            (3, "rd"),
            (4, "th"),
            (10, "th"),
            (21, "st"),
            (22, "nd"),
            (23, "rd"),
            (101, "st"),
        ],
    )
    def test_regular_numbers(self, number, suffix):
        assert get_ordinal_suffix(number) == suffix

    @pytest.mark.parametrize("number", [11, 12, 13, 111, 112, 113])
    def test_the_teens_are_all_th(self, number):
        assert get_ordinal_suffix(number) == "th"
