"""
Shared fixtures for the Slackelo test suite.

The environment is configured at import time, before anything imports `app`.
`load_dotenv()` does not override variables that are already set, so these win
over the real `.env` and the tests never touch the production database.
"""

import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_TEST_DIR = Path(tempfile.mkdtemp(prefix="slackelo-tests-"))
TEST_DB_PATH = _TEST_DIR / "test_slackelo.db"

os.environ["DB_PATH"] = str(TEST_DB_PATH)
os.environ["OAUTH_REDIRECT_URI"] = "https://example.test/slackelo/oauth/redirect"
os.environ["REDIRECT_URI_PATH"] = "/oauth/redirect"
os.environ["INSTALL_PATH"] = "/install"
os.environ["PUBLIC_URL"] = "https://example.test/slackelo"
os.environ["SLACK_SIGNING_SECRET"] = "test-signing-secret"
os.environ["SLACK_CLIENT_ID"] = "test-client-id"
os.environ["SLACK_CLIENT_SECRET"] = "test-client-secret"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"

# Tables owned by Slackelo. The `version` table and slack_bolt's OAuth tables
# live in the same database and are deliberately left alone.
DATA_TABLES = (
    "player_games",
    "games",
    "channel_players",
    "channels",
    "players",
)


@pytest.fixture(scope="session", autouse=True)
def _repo_root_cwd():
    """
    Run from the repository root.

    `Migrations` resolves its `migrations/` directory relative to the working
    directory, and `/chart` writes into `static/` the same way.
    """
    previous = os.getcwd()
    os.chdir(REPO_ROOT)
    yield REPO_ROOT
    os.chdir(previous)


@pytest.fixture(scope="session")
def app_module(_repo_root_cwd):
    """
    The imported `app` module.

    Importing it runs the migrations and builds the Flask app, the Bolt app and
    the module-level `Slackelo` instance, so it is done once per session and
    each test gets a clean database instead of a clean import.
    """
    import app

    yield app

    shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture
def slackelo(app_module):
    """A `Slackelo` instance backed by an empty database."""
    instance = app_module.slackelo

    for table in DATA_TABLES:
        instance.db.execute_non_query(f"DELETE FROM {table}")
    # Keep autoincrement ids predictable across tests.
    instance.db.execute_non_query(
        "DELETE FROM sqlite_sequence WHERE name IN ('games')"
    )

    return instance


class FakeClock:
    """
    Stand-in for the `time` module that hands out increasing timestamps.

    `create_game` stamps `int(time.time())`, so several games recorded in the
    same second get identical timestamps and the queries that order by
    timestamp have no tiebreak. Tests need games to be strictly ordered.
    """

    STEP = 60

    def __init__(self, start: int = 1_700_000_000):
        self.now = start

    def time(self) -> int:
        value = self.now
        self.now += self.STEP
        return value


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Give every test deterministic, strictly increasing game timestamps."""
    import slackelo as slackelo_module

    fake = FakeClock()
    monkeypatch.setattr(slackelo_module, "time", fake)
    return fake


@pytest.fixture
def game(slackelo):
    """
    Record a game concisely.

    A bare user ID is a rank of its own; a list or tuple is a group of players
    tied at that rank:

        game(CHANNEL, ALICE, [BOB, CAROL], DAVE)
    """

    def _record(channel_id, *ranks, team_id=None):
        ranked_player_ids = [
            list(rank) if isinstance(rank, (list, tuple, set)) else [rank]
            for rank in ranks
        ]
        return slackelo.create_game(channel_id, ranked_player_ids, team_id)

    return _record


@pytest.fixture
def invoke(app_module):
    """
    Call a Slack command handler and collect what it sent back.

    Handlers are plain functions despite the `@bolt_app.command` decorator, but
    they do not agree on their arguments - some take `say`, some `respond`, and
    `/chart` also takes a `client`. The signature is inspected so callers do
    not have to care which.

    Returns the list of replies: the text for a normal reply, or the keyword
    arguments for a reply built from blocks.
    """

    def _invoke(handler, text="", channel_id=None, user_id=None, team_id=None):
        from helpers import ALICE, CHANNEL, TEAM

        command = {
            "text": text,
            "channel_id": channel_id or CHANNEL,
            "user_id": user_id or ALICE,
            "team_id": team_id or TEAM,
        }

        replies = []

        def collect(text=None, **kwargs):
            replies.append(text if text is not None else kwargs)

        arguments = {}
        for name in inspect.signature(handler).parameters:
            if name == "ack":
                arguments[name] = lambda *args, **kwargs: None
            elif name in ("say", "respond"):
                arguments[name] = collect
            elif name == "client":
                arguments[name] = None
            else:
                # `command`, and `/help`'s unused `_`
                arguments[name] = command

        handler(**arguments)
        return replies

    return _invoke


@pytest.fixture
def reply(invoke):
    """Invoke a handler that is expected to send exactly one reply."""

    def _reply(handler, **kwargs):
        replies = invoke(handler, **kwargs)
        assert len(replies) == 1, f"expected one reply, got {replies}"
        return replies[0]

    return _reply


@pytest.fixture
def flask_client(app_module, slackelo):
    """A Flask test client for the plain HTTP routes."""
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client
