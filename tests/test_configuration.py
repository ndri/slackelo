"""
Tests for how `app.py` reads its configuration at import time.

These import `app.py` again under a throwaway module name so the environment
can be varied. `load_dotenv` is stubbed out first, so the real `.env` cannot
leak in and supply a value the test meant to leave unset.
"""

import importlib.util

import pytest

from conftest import REPO_ROOT

REQUIRED = {
    "OAUTH_REDIRECT_URI": "https://games.example/slackelo/oauth/redirect",
    "SLACK_SIGNING_SECRET": "signing-secret",
    "SLACK_CLIENT_ID": "client-id",
    "SLACK_CLIENT_SECRET": "client-secret",
}

OPTIONAL = ("PUBLIC_URL", "INSTALL_PATH", "REDIRECT_URI_PATH", "SUCCESS_URL")


@pytest.fixture
def import_app(monkeypatch, tmp_path):
    """Import `app.py` afresh with exactly the environment given."""

    def _import(**overrides):
        import dotenv

        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

        for name in list(REQUIRED) + list(OPTIONAL):
            monkeypatch.delenv(name, raising=False)

        monkeypatch.setenv("DB_PATH", str(tmp_path / "configured.db"))
        for name, value in {**REQUIRED, **overrides}.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

        spec = importlib.util.spec_from_file_location(
            "app_under_test", REPO_ROOT / "app.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _import


class TestPublicUrl:
    def test_it_uses_public_url_when_one_is_configured(self, import_app):
        module = import_app(PUBLIC_URL="https://games.example/slackelo")
        assert module.public_url == "https://games.example/slackelo"

    def test_a_trailing_slash_is_dropped(self, import_app):
        module = import_app(PUBLIC_URL="https://games.example/slackelo/")
        assert module.public_url == "https://games.example/slackelo"

    def test_without_one_it_is_derived_from_the_oauth_redirect(
        self, import_app
    ):
        """
        Regression: `/chart` posted a localhost link because `PUBLIC_URL` was
        simply not set in the deployed environment, and the fallback was a
        hardcoded localhost address.
        """
        module = import_app(PUBLIC_URL=None)

        assert module.public_url == "https://games.example/slackelo"
        assert "localhost" not in module.public_url

    def test_the_derived_url_does_not_keep_the_redirect_path(self, import_app):
        module = import_app(PUBLIC_URL=None)
        assert not module.public_url.endswith("/oauth/redirect")

    def test_it_honours_a_custom_redirect_path(self, import_app):
        module = import_app(
            PUBLIC_URL=None,
            OAUTH_REDIRECT_URI="https://games.example/slackelo/auth/cb",
            REDIRECT_URI_PATH="/auth/cb",
        )
        assert module.public_url == "https://games.example/slackelo"

    def test_an_empty_value_is_treated_as_unset(self, import_app):
        module = import_app(PUBLIC_URL="")
        assert module.public_url == "https://games.example/slackelo"


class TestRequiredSettings:
    @pytest.mark.parametrize("name", sorted(REQUIRED))
    def test_a_missing_setting_stops_the_app_starting(self, import_app, name):
        with pytest.raises(ValueError, match=name):
            import_app(**{name: None})


class TestStartupMigrations:
    def test_a_database_that_cannot_be_migrated_stops_startup(
        self, import_app, tmp_path
    ):
        """A deploy against an unwritable database must fail loudly."""
        unreachable = str(tmp_path / "no-such-directory" / "slackelo.db")

        with pytest.raises(Exception, match="Error connecting to database"):
            import_app(DB_PATH=unreachable)
