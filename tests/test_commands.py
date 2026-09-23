"""
End-to-end tests for the Slack slash commands in `app.py`.

Handlers are driven directly through the `invoke`/`reply` fixtures, which fake
Slack's `ack`, `say` and `respond` callbacks and collect whatever is posted.
"""

import re

import pytest

from helpers import (
    ALICE,
    BOB,
    CAROL,
    CHANNEL,
    DAVE,
    ERIN,
    channel_player_ids,
    mention,
    mentions,
)


class TestGameCommand:
    def test_it_records_the_game(self, slackelo, app_module, reply):
        reply(app_module.create_game, text=mentions(ALICE, BOB))

        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1016
        assert slackelo.get_player_channel_rating(BOB, CHANNEL) == 984

    def test_it_reports_each_players_before_and_after(
        self, slackelo, app_module, reply
    ):
        response = reply(app_module.create_game, text=mentions(ALICE, BOB))

        assert "Game recorded!" in response
        assert f"<@{ALICE}> - *1000 → 1016* _(+16)_" in response
        assert f"<@{BOB}> - *1000 → 984* _(-16)_" in response

    def test_it_marks_the_podium_and_the_wooden_spoon(
        self, slackelo, app_module, reply
    ):
        response = reply(
            app_module.create_game, text=mentions(ALICE, BOB, CAROL, DAVE)
        )

        assert "🥇 *1st place*" in response
        assert "🥈 *2nd place*" in response
        assert "🥉 *3rd place*" in response
        assert "💩 *4th place*" in response

    def test_last_place_is_never_also_a_medal(self, slackelo, app_module, reply):
        response = reply(app_module.create_game, text=mentions(ALICE, BOB))

        assert "🥈" not in response
        assert "💩 *2nd place*" in response

    def test_it_reports_a_tie_at_a_shared_position(
        self, slackelo, app_module, reply
    ):
        text = f"{mention(ALICE)} {mention(BOB)}={mention(CAROL)}"
        response = reply(app_module.create_game, text=text)

        assert response.count("*2nd place*") == 2
        assert "*3rd place*" not in response

    def test_it_flags_a_gambled_result(self, slackelo, app_module, reply):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        response = reply(app_module.create_game, text=mentions(ALICE, BOB))

        assert f"<@{ALICE}> - *1000 → 1032* _(+32)_ (🎲 2x!)" in response
        assert f"<@{BOB}> - *1000 → 984* _(-16)_\n" in response

    def test_it_asks_for_players_when_given_none(self, app_module, reply):
        response = reply(app_module.create_game, text="")
        assert "Please provide player information" in response

    def test_one_player_is_not_a_game(self, slackelo, app_module, reply):
        response = reply(app_module.create_game, text=mention(ALICE))

        assert "at least 2 players" in response
        assert slackelo.db.execute_query("SELECT * FROM games") == []

    def test_naming_the_same_player_twice_is_reported(
        self, slackelo, app_module, reply
    ):
        text = f"{mention(ALICE)} {mention(ALICE)}"
        response = reply(app_module.create_game, text=text)

        assert "Error creating game" in response
        assert slackelo.db.execute_query("SELECT * FROM games") == []


class TestSimulateCommand:
    def test_it_does_not_add_anyone_to_the_leaderboard(
        self, slackelo, app_module, reply
    ):
        """Regression: `/simulate` used to quietly create rating rows."""
        reply(app_module.simulate_game, text=mentions(ALICE, BOB))

        assert channel_player_ids(slackelo, CHANNEL) == set()

    def test_it_does_not_record_a_game(self, slackelo, app_module, reply):
        reply(app_module.simulate_game, text=mentions(ALICE, BOB))
        assert slackelo.db.execute_query("SELECT * FROM games") == []

    def test_it_says_that_nothing_was_saved(self, app_module, reply):
        response = reply(app_module.simulate_game, text=mentions(ALICE, BOB))

        assert "Simulation results (no changes saved)" in response
        assert "This is a simulation only" in response

    def test_it_shows_the_same_numbers_a_real_game_would(
        self, slackelo, app_module, reply
    ):
        simulated = reply(app_module.simulate_game, text=mentions(ALICE, BOB))
        recorded = reply(app_module.create_game, text=mentions(ALICE, BOB))

        assert f"<@{ALICE}> - *1000 → 1016* _(+16)_" in simulated
        assert f"<@{ALICE}> - *1000 → 1016* _(+16)_" in recorded

    def test_it_accounts_for_a_pending_gamble(
        self, slackelo, app_module, reply
    ):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        response = reply(app_module.simulate_game, text=mentions(ALICE, BOB))

        assert "(🎲 2x!)" in response

    def test_it_asks_for_players_when_given_none(self, app_module, reply):
        response = reply(app_module.simulate_game, text="")
        assert "Please provide player information" in response


class TestLeaderboardCommand:
    def test_it_shows_everyone_by_default(self, slackelo, app_module, game, reply):
        game(CHANNEL, ALICE, BOB, CAROL, DAVE)
        response = reply(app_module.show_leaderboard)

        for user_id in (ALICE, BOB, CAROL, DAVE):
            assert f"<@{user_id}>" in response

    def test_a_number_limits_it(self, slackelo, app_module, game, reply):
        game(CHANNEL, ALICE, BOB, CAROL, DAVE)
        response = reply(app_module.show_leaderboard, text="2")

        assert f"<@{ALICE}>" in response
        assert f"<@{DAVE}>" not in response

    def test_a_limit_of_zero_still_shows_someone(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_leaderboard, text="0")

        assert f"<@{ALICE}>" in response

    def test_text_that_is_not_a_number_is_ignored(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB, CAROL)
        response = reply(app_module.show_leaderboard, text="everyone please")

        assert f"<@{CAROL}>" in response

    def test_tied_players_share_a_rank_and_the_next_rank_skips(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, [BOB, CAROL], DAVE)
        response = reply(app_module.show_leaderboard)

        ranks = re.findall(r"^(\d+)\. <@(U\w+)>", response, re.MULTILINE)
        assert [rank for rank, _ in ranks] == ["1", "2", "2", "4"]
        assert ranks[0][1] == ALICE
        assert ranks[3][1] == DAVE

    def test_it_counts_games_played(self, slackelo, app_module, game, reply):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_leaderboard)

        assert "(2 games)" in response

    def test_a_single_game_is_not_pluralised(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_leaderboard)

        assert "(1 game)" in response
        assert "(1 games)" not in response

    def test_an_empty_channel_says_so(self, slackelo, app_module, reply):
        response = reply(app_module.show_leaderboard)
        assert "No ratings found for this channel yet" in response


class TestRatingCommand:
    def test_it_shows_your_own_rating(self, slackelo, app_module, game, reply):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_rating, user_id=ALICE)

        assert f"<@{ALICE}>'s current rating in this channel is 1016." == response

    def test_it_shows_a_mentioned_players_rating(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(
            app_module.show_rating, text=mention(BOB), user_id=ALICE
        )

        assert f"<@{BOB}>" in response
        assert "984" in response

    def test_an_unknown_player_is_reported_at_the_starting_rating(
        self, slackelo, app_module, reply
    ):
        response = reply(app_module.show_rating, user_id=CAROL)
        assert "1000" in response

    def test_looking_someone_up_does_not_add_them_to_the_leaderboard(
        self, slackelo, app_module, reply
    ):
        """Regression: `/rating` used to quietly create a rating row."""
        reply(app_module.show_rating, text=mention(CAROL), user_id=ALICE)

        assert channel_player_ids(slackelo, CHANNEL) == set()


class TestHistoryCommand:
    def test_it_lists_games_oldest_first(
        self, slackelo, app_module, game, reply
    ):
        # Alice wins, then loses. The reply reads oldest first, so her win
        # must appear above her loss.
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)
        response = reply(app_module.show_history, user_id=ALICE)

        assert response.index("1st place") < response.index("2nd place")

    def test_it_shows_the_rating_change(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_history, user_id=ALICE)

        assert "*1000 → 1016* _(+16)_" in response

    def test_it_can_show_someone_else(self, slackelo, app_module, game, reply):
        game(CHANNEL, ALICE, BOB)
        response = reply(
            app_module.show_history, text=mention(BOB), user_id=ALICE
        )

        assert f"Game history for <@{BOB}>" in response
        assert "_(-16)_" in response

    def test_it_flags_gambled_games(self, slackelo, app_module, game, reply):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_history, user_id=ALICE)

        assert "(🎲 2x!)" in response

    def test_older_games_beyond_the_limit_are_summarised(
        self, slackelo, app_module, game, reply
    ):
        for _ in range(12):
            game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_history, user_id=ALICE)

        assert "_+2 previous games_" in response

    def test_a_player_with_no_games_is_told_so(self, slackelo, app_module, reply):
        response = reply(app_module.show_history, user_id=ALICE)
        assert "No game history found" in response


class TestUndoCommand:
    def test_it_reverts_the_last_game(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.undo_last_game)

        assert "has been undone" in response
        assert slackelo.get_player_channel_rating(ALICE, CHANNEL) == 1000

    def test_it_reports_when_there_is_nothing_to_undo(
        self, slackelo, app_module, reply
    ):
        response = reply(app_module.undo_last_game)
        assert "No games to undo" in response


class TestKFactorCommand:
    def test_it_reports_the_current_value(self, slackelo, app_module, reply):
        response = reply(app_module.set_k_factor)

        assert "current k-factor for this channel is *32*" in response

    def test_it_sets_a_new_value(self, slackelo, app_module, reply):
        response = reply(app_module.set_k_factor, text="64")

        assert "from 32 to *64*" in response
        assert slackelo.get_channel_k_factor(CHANNEL) == 64

    @pytest.mark.parametrize("text", ["0", "-16", "abc", "32.5"])
    def test_it_rejects_anything_that_is_not_a_positive_integer(
        self, slackelo, app_module, reply, text
    ):
        response = reply(app_module.set_k_factor, text=text)

        assert "must be a positive integer" in response
        assert slackelo.get_channel_k_factor(CHANNEL) == 32


class TestGambleCommand:
    def test_it_turns_gambling_on(self, slackelo, app_module, reply):
        response = reply(app_module.toggle_gambling, user_id=ALICE)

        assert "is now gambling! 🎲" in response
        assert slackelo.is_player_gambling(ALICE, CHANNEL) is True

    def test_it_turns_gambling_off_again(self, slackelo, app_module, reply):
        reply(app_module.toggle_gambling, user_id=ALICE)
        response = reply(app_module.toggle_gambling, user_id=ALICE)

        assert "no longer gambling" in response
        assert slackelo.is_player_gambling(ALICE, CHANNEL) is False


class TestStatsCommand:
    def test_an_empty_channel_says_so(self, slackelo, app_module, reply):
        response = reply(app_module.show_statistics)
        assert "No games found for this channel yet" in response

    def test_it_reports_the_headline_awards(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_statistics)

        assert "*Channel Statistics* (2 games played)" in response
        assert "🏆 *All-time highest rating:*" in response
        assert "📛 *All-time lowest rating:*" in response
        assert "🥇 *Most 1st place finishes:*" in response
        assert "🔥 *Longest win streak:*" in response

    def test_losses_through_gambling_are_shown_as_a_positive_number(
        self, slackelo, app_module, game, reply
    ):
        """The stored total is negative, but "lost" already carries the sign."""
        slackelo.toggle_player_gambling(BOB, CHANNEL)
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_statistics)

        assert "16 points lost through gambling" in response
        assert "-16 points lost" not in response

    def test_it_names_the_gambling_addict(
        self, slackelo, app_module, game, reply
    ):
        for _ in range(3):
            slackelo.toggle_player_gambling(ALICE, CHANNEL)
            game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_statistics)

        assert f"🃏 *Gambling addict:* <@{ALICE}> - gambled in 3 of 3 games (100%)" in response

    def test_it_names_the_giant_slayer(
        self, slackelo, app_module, game, reply
    ):
        slackelo.set_channel_k_factor(CHANNEL, 200)
        game(CHANNEL, BOB, DAVE)
        game(CHANNEL, BOB, DAVE)
        game(CHANNEL, CAROL, BOB)
        response = reply(app_module.show_statistics)

        assert f"🗡️ *Giant slayer:* <@{CAROL}> - beat <@{BOB}>" in response

    def test_it_reports_a_losing_streak(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB, CAROL)
        game(CHANNEL, ALICE, BOB, CAROL)
        response = reply(app_module.show_statistics)

        assert f"🧊 *Longest losing streak:* <@{CAROL}> - 2" in response

    def test_it_reports_a_collapse(self, slackelo, app_module, game, reply):
        slackelo.set_channel_k_factor(CHANNEL, 200)
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, BOB, ALICE)
        game(CHANNEL, BOB, ALICE)
        response = reply(app_module.show_statistics)

        assert f"🪂 *Biggest collapse:* <@{ALICE}>" in response


class TestGamblersCommand:
    def test_a_channel_with_no_gambling_says_so(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_gamblers)

        assert "No one has gambled in this channel yet" in response

    def test_it_ranks_gamblers(self, slackelo, app_module, game, reply):
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        slackelo.toggle_player_gambling(BOB, CHANNEL)
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_gamblers)

        assert f"🥇 1. <@{ALICE}> - +16 points (1 gamble)" in response
        assert f"📉 2. <@{BOB}> - -16 points (1 gamble)" in response

    def test_it_pluralises_the_gamble_count(
        self, slackelo, app_module, game, reply
    ):
        for _ in range(2):
            slackelo.toggle_player_gambling(ALICE, CHANNEL)
            game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_gamblers)

        assert "(2 gambles)" in response


class TestChartCommand:
    @pytest.fixture(autouse=True)
    def _isolated_static_dir(self, monkeypatch, tmp_path):
        """`/chart` writes into `static/` relative to the working directory."""
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def test_an_empty_channel_says_so(self, slackelo, app_module, reply):
        response = reply(app_module.show_chart)
        assert "No games found for this channel yet" in response

    def test_it_writes_a_chart_image(
        self, slackelo, app_module, game, reply, _isolated_static_dir
    ):
        game(CHANNEL, ALICE, BOB)
        reply(app_module.show_chart)

        charts = list((_isolated_static_dir / "static").glob("*.png"))
        assert len(charts) == 1
        assert charts[0].stat().st_size > 0

    def test_it_links_to_the_public_url(
        self, slackelo, app_module, game, reply
    ):
        """Regression: the link used to point at localhost."""
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_chart)

        assert "localhost" not in response
        assert re.search(
            r"<https://example\.test/slackelo/static/rating_chart_"
            r"\d{8}_\d{6}\.png\|View Chart>",
            response,
        )

    def test_the_link_points_at_the_file_that_was_written(
        self, slackelo, app_module, game, reply, _isolated_static_dir
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_chart)

        written = next((_isolated_static_dir / "static").glob("*.png"))
        assert written.name in response

    def test_the_legend_runs_from_the_highest_rating_down(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB, CAROL)
        response = reply(app_module.show_chart)

        order = re.findall(r"<@(U\w+)>", response)
        assert order == [ALICE, BOB, CAROL]

    def test_every_legend_entry_is_a_bare_hex_colour(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_chart)

        entries = [
            line for line in response.splitlines() if line.startswith("#")
        ]
        assert len(entries) == 2
        for line in entries:
            assert re.fullmatch(r"#[0-9a-f]{6} <@U\w+>", line)

    def test_it_has_an_entry_for_every_player(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        game(CHANNEL, CAROL, DAVE)
        response = reply(app_module.show_chart)

        assert len(re.findall(r"^#[0-9a-f]{6} ", response, re.MULTILINE)) == 4


class TestHelpCommand:
    def test_it_replies_with_blocks(self, app_module, reply):
        response = reply(app_module.help_command)
        assert "blocks" in response

    def test_it_lists_every_command(self, app_module, reply):
        response = reply(app_module.help_command)
        text = str(response["blocks"])

        for command in (
            "/game",
            "/simulate",
            "/leaderboard",
            "/rating",
            "/history",
            "/kfactor",
            "/gamble",
            "/gamblers",
            "/stats",
            "/chart",
            "/undo",
            "/help",
        ):
            assert f"`{command}" in text


class TestPositionsBeyondThePodium:
    def test_middle_places_get_no_emoji(self, slackelo, app_module, reply):
        response = reply(
            app_module.create_game,
            text=mentions(ALICE, BOB, CAROL, DAVE, ERIN),
        )

        assert "🥉 *3rd place*" in response
        assert "*4th place*: " in response
        assert "🏅" not in response
        # Fourth of five is neither a medal nor last.
        fourth = next(
            line for line in response.splitlines() if "*4th place*" in line
        )
        assert fourth.startswith("*4th place*")

    def test_only_the_final_position_gets_the_wooden_spoon(
        self, slackelo, app_module, reply
    ):
        response = reply(
            app_module.create_game,
            text=mentions(ALICE, BOB, CAROL, DAVE, ERIN),
        )

        assert response.count("💩") == 1
        assert "💩 *5th place*" in response


class TestLeaderboardTieEdges:
    def test_a_three_way_tie_shares_one_rank(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, [ALICE, BOB, CAROL], DAVE)
        response = reply(app_module.show_leaderboard)

        ranks = [rank for rank, _ in re.findall(r"^(\d+)\. <@(U\w+)>", response, re.MULTILINE)]
        assert ranks == ["1", "1", "1", "4"]

    def test_toggling_gambling_alone_puts_you_on_the_board(
        self, slackelo, app_module, reply
    ):
        """
        `/gamble` has to store the flag somewhere, and the only place is the
        rating row - so it lists a player who has never played a game.
        """
        reply(app_module.toggle_gambling, user_id=ALICE)
        response = reply(app_module.show_leaderboard)

        assert f"1. <@{ALICE}>: 1000 (0 games)" in response


class TestHistoryLength:
    def test_exactly_ten_games_needs_no_summary_line(
        self, slackelo, app_module, game, reply
    ):
        for _ in range(10):
            game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_history, user_id=ALICE)

        assert "previous games" not in response
        assert response.count("place -") == 10

    def test_the_eleventh_game_starts_the_summary_line(
        self, slackelo, app_module, game, reply
    ):
        for _ in range(11):
            game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_history, user_id=ALICE)

        assert "_+1 previous games_" in response


class TestGamblersLeaderboardRanking:
    def test_the_top_three_winners_get_medals_and_the_rest_a_moneybag(
        self, slackelo, app_module, game, reply
    ):
        # Four players each gamble once and beat Erin, who never gambles.
        for winner in (ALICE, BOB, CAROL, DAVE):
            slackelo.toggle_player_gambling(winner, CHANNEL)
            game(CHANNEL, winner, ERIN)

        response = reply(app_module.show_gamblers)

        assert "🥇 1." in response
        assert "🥈 2." in response
        assert "🥉 3." in response
        assert "💰 4." in response
        assert f"<@{ERIN}>" not in response

    def test_breaking_even_is_marked_separately(
        self, slackelo, app_module, game, reply
    ):
        # A gambled draw doubles a change of zero, which is still zero.
        slackelo.toggle_player_gambling(ALICE, CHANNEL)
        game(CHANNEL, [ALICE, BOB])

        response = reply(app_module.show_gamblers)
        assert f"➖ 1. <@{ALICE}> - 0 points (1 gamble)" in response


class TestChartColours:
    @pytest.fixture(autouse=True)
    def _isolated_static_dir(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def test_colours_are_converted_when_matplotlib_gives_rgb_tuples(
        self, slackelo, app_module, game, reply, monkeypatch
    ):
        """The legend must render a hex code whatever form the colour takes."""
        from cycler import cycler
        import matplotlib.pyplot as plt

        monkeypatch.setitem(
            plt.rcParams,
            "axes.prop_cycle",
            cycler(color=[(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)]),
        )

        game(CHANNEL, ALICE, BOB)
        response = reply(app_module.show_chart)

        # Which player gets which colour is not fixed - the histories are
        # collected through a set, so the order changes between processes.
        assert set(re.findall(r"^(#[0-9a-f]{6}) ", response, re.MULTILINE)) == {
            "#19334c",
            "#667f99",
        }


class TestErrorsAreReportedNotRaised:
    """
    Every handler catches its own failures and says something in the channel.
    A handler that raised instead would leave Slack showing a dispatch error.
    """

    @pytest.mark.parametrize(
        "handler_name,broken_method,expected",
        [
            ("show_leaderboard", "get_or_create_channel", "Error fetching leaderboard"),
            ("undo_last_game", "get_or_create_channel", "Error undoing game"),
            ("show_rating", "get_or_create_channel", "Error fetching rating"),
            ("show_history", "get_or_create_channel", "Error fetching history"),
            ("set_k_factor", "get_or_create_channel", "Error setting k-factor"),
            ("show_statistics", "get_or_create_channel", "Error fetching statistics"),
            ("show_gamblers", "get_or_create_channel", "Error fetching gambling leaderboard"),
            ("show_chart", "get_or_create_channel", "Error generating chart"),
            ("toggle_gambling", "toggle_player_gambling", "Error toggling gambling status"),
        ],
    )
    def test_a_failing_lookup_is_reported(
        self,
        slackelo,
        app_module,
        reply,
        monkeypatch,
        handler_name,
        broken_method,
        expected,
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("database is on fire")

        monkeypatch.setattr(app_module.slackelo, broken_method, boom)
        response = reply(getattr(app_module, handler_name))

        assert expected in response
        assert "database is on fire" in response

    def test_a_failing_simulation_is_reported(
        self, slackelo, app_module, reply, monkeypatch
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("database is on fire")

        monkeypatch.setattr(app_module.slackelo, "simulate_game", boom)
        response = reply(app_module.simulate_game, text=mentions(ALICE, BOB))

        assert "Error simulating game" in response


class TestChartColourStability:
    """
    A player's line should keep its colour, so charts posted weeks apart can
    be read against each other.
    """

    @pytest.fixture(autouse=True)
    def _isolated_static_dir(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        return tmp_path

    @staticmethod
    def legend(response):
        """The legend as a {user_id: colour} mapping."""
        return {
            user_id: colour
            for colour, user_id in re.findall(
                r"^(#[0-9a-f]{6}) <@(U\w+)>$", response, re.MULTILINE
            )
        }

    def test_colours_follow_the_order_players_joined(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, CAROL, DAVE)
        game(CHANNEL, ALICE, BOB)

        colours = self.legend(reply(app_module.show_chart))
        # Whatever the palette is, the first pair to play takes the first two
        # colours and the next pair the two after that.
        assert len({*colours.values()}) == 4
        assert colours[CAROL] != colours[ALICE]

    def test_a_new_player_does_not_change_anyone_elses_colour(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB)
        before = self.legend(reply(app_module.show_chart))

        game(CHANNEL, CAROL, DAVE)
        after = self.legend(reply(app_module.show_chart))

        assert after[ALICE] == before[ALICE]
        assert after[BOB] == before[BOB]

    def test_playing_more_games_does_not_change_colours(
        self, slackelo, app_module, game, reply
    ):
        game(CHANNEL, ALICE, BOB, CAROL)
        before = self.legend(reply(app_module.show_chart))

        # Reverse the standings entirely; the legend reorders but the colours
        # belong to the players, not to their rank.
        for _ in range(3):
            game(CHANNEL, CAROL, BOB, ALICE)
        after = self.legend(reply(app_module.show_chart))

        assert after == before
