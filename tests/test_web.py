"""
Tests for the plain HTTP routes in `app.py`.

The Slack-facing routes (`/events`, `/slack/commands`, `/oauth/redirect`) are
thin wrappers around Bolt's request handler and are exercised through the
command handlers instead.
"""

import pytest

from helpers import ALICE, BOB, CHANNEL, TEAM, channel_player_ids

PASSWORD = "test-admin-password"


class TestPages:
    def test_the_landing_page_renders(self, flask_client):
        response = flask_client.get("/")
        assert response.status_code == 200

    def test_the_landing_page_links_to_the_installer(self, flask_client):
        response = flask_client.get("/")
        assert b"/install" in response.data

    def test_the_privacy_policy_renders(self, flask_client):
        assert flask_client.get("/privacy").status_code == 200

    def test_the_success_page_renders(self, flask_client):
        assert flask_client.get("/success").status_code == 200


class TestResetEndpoint:
    def test_it_rejects_a_request_with_no_password(self, flask_client):
        response = flask_client.post("/reset", json={"channel_id": CHANNEL})

        assert response.status_code == 400
        assert "required" in response.get_json()["error"]

    def test_it_rejects_a_request_with_no_channel(self, flask_client):
        response = flask_client.post("/reset", json={"password": PASSWORD})

        assert response.status_code == 400

    def test_it_rejects_an_empty_body(self, flask_client):
        response = flask_client.post("/reset", json={})

        assert response.status_code == 400
        assert "JSON" in response.get_json()["error"]

    def test_it_rejects_the_wrong_password(self, flask_client, game):
        game(CHANNEL, ALICE, BOB, team_id=TEAM)
        response = flask_client.post(
            "/reset", json={"password": "wrong", "channel_id": CHANNEL}
        )

        assert response.status_code == 401

    def test_the_wrong_password_deletes_nothing(
        self, flask_client, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB, team_id=TEAM)
        flask_client.post(
            "/reset", json={"password": "wrong", "channel_id": CHANNEL}
        )

        assert channel_player_ids(slackelo, CHANNEL) == {ALICE, BOB}

    def test_it_reports_an_unknown_channel(self, flask_client):
        response = flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": "C99NOPE"}
        )

        assert response.status_code == 404

    def test_a_channel_with_no_team_cannot_be_reset(
        self, flask_client, slackelo, game
    ):
        # Without a team_id there is no workspace to announce the reset in.
        game(CHANNEL, ALICE, BOB)
        response = flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": CHANNEL}
        )

        assert response.status_code == 404
        assert channel_player_ids(slackelo, CHANNEL) == {ALICE, BOB}

    def test_it_is_disabled_when_no_password_is_configured(
        self, flask_client, app_module, monkeypatch
    ):
        monkeypatch.setattr(app_module, "admin_password", None)
        response = flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": CHANNEL}
        )

        assert response.status_code == 503

    def test_the_right_password_clears_the_channel(
        self, flask_client, slackelo, game
    ):
        game(CHANNEL, ALICE, BOB, team_id=TEAM)
        game(CHANNEL, ALICE, BOB, team_id=TEAM)

        response = flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": CHANNEL}
        )

        assert response.status_code == 200
        assert response.get_json()["games_deleted"] == 2
        assert channel_player_ids(slackelo, CHANNEL) == set()
        assert slackelo.db.execute_query("SELECT * FROM games") == []


class TestResetAnnouncement:
    """
    The success path posts a message back to the channel. It needs an OAuth
    installation to find a bot token, which the test database does not have,
    so both the lookup and the Slack client are stubbed.
    """

    @pytest.fixture
    def slack(self, app_module, monkeypatch):
        import slack_sdk

        posted = []

        class FakeInstallation:
            bot_token = "xoxb-test-token"

        class FakeWebClient:
            def __init__(self, token):
                self.token = token

            def chat_postMessage(self, **kwargs):
                posted.append({"token": self.token, **kwargs})

        monkeypatch.setattr(
            app_module.bolt_app.installation_store,
            "find_installation",
            lambda **kwargs: FakeInstallation(),
        )
        monkeypatch.setattr(slack_sdk, "WebClient", FakeWebClient)
        return posted

    def test_it_announces_the_reset_in_the_channel(
        self, flask_client, slack, game
    ):
        game(CHANNEL, ALICE, BOB, team_id=TEAM)

        response = flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": CHANNEL}
        )

        assert response.status_code == 200
        assert response.get_json()["message"] == "Channel reset successfully"
        assert len(slack) == 1
        assert slack[0]["channel"] == CHANNEL
        assert slack[0]["token"] == "xoxb-test-token"
        assert "All 1 games have been deleted" in slack[0]["text"]

    def test_the_data_is_gone_as_well_as_announced(
        self, flask_client, slackelo, slack, game
    ):
        game(CHANNEL, ALICE, BOB, team_id=TEAM)
        flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": CHANNEL}
        )

        assert channel_player_ids(slackelo, CHANNEL) == set()

    def test_a_failure_while_posting_is_reported_as_a_server_error(
        self, flask_client, app_module, monkeypatch, game
    ):
        game(CHANNEL, ALICE, BOB, team_id=TEAM)
        monkeypatch.setattr(
            app_module.bolt_app.installation_store,
            "find_installation",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("slack is down")),
        )

        response = flask_client.post(
            "/reset", json={"password": PASSWORD, "channel_id": CHANNEL}
        )

        assert response.status_code == 500
        assert "slack is down" in response.get_json()["error"]


class TestSlackFacingRoutes:
    """
    These routes just hand the request to Bolt. What matters here is how they
    behave when that fails, which differs by route.
    """

    @pytest.fixture
    def broken_handler(self, app_module, monkeypatch):
        def boom(request):
            raise RuntimeError("bolt exploded")

        monkeypatch.setattr(app_module.handler, "handle", boom)

    def test_a_failing_slash_command_still_answers_slack_with_200(
        self, flask_client, broken_handler
    ):
        """
        Slack shows the user a dispatch failure for any non-2xx reply, so the
        error has to come back as a normal message instead.
        """
        response = flask_client.post("/slack/commands", data={"text": ""})

        assert response.status_code == 200
        assert "bolt exploded" in response.get_json()["text"]

    def test_a_failing_event_is_a_server_error(
        self, flask_client, broken_handler
    ):
        response = flask_client.post("/events", json={})

        assert response.status_code == 500
        assert "bolt exploded" in response.get_json()["error"]

    def test_a_failing_oauth_redirect_renders_the_error_page(
        self, flask_client, broken_handler
    ):
        response = flask_client.get("/oauth/redirect")

        assert response.status_code == 500
        assert b"bolt exploded" in response.data

    def test_a_failing_install_renders_the_error_page(
        self, flask_client, broken_handler
    ):
        response = flask_client.get("/install")

        assert response.status_code == 500
        assert b"bolt exploded" in response.data

    def test_install_points_the_success_url_at_this_host(
        self, flask_client, app_module, monkeypatch
    ):
        monkeypatch.setattr(app_module.handler, "handle", lambda request: "ok")
        settings = app_module.bolt_app.oauth_flow.settings
        # The route assigns to this shared object, so put it back afterwards.
        monkeypatch.setattr(settings, "success_url", settings.success_url)

        flask_client.get("/install")

        assert settings.success_url.endswith("/success")
