"""
Tests for the thin database wrapper in `sqlite_connector.py`.
"""

import pytest

from sqlite_connector import SQLiteConnector


@pytest.fixture
def connector(tmp_path):
    connector = SQLiteConnector(str(tmp_path / "connector.db"))
    connector.execute_non_query(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT, size INTEGER)"
    )
    return connector


class TestQueries:
    def test_rows_come_back_as_plain_dictionaries(self, connector):
        connector.execute_non_query(
            "INSERT INTO widgets (name, size) VALUES (?, ?)", ("bolt", 3)
        )
        rows = connector.execute_query("SELECT * FROM widgets")

        assert rows == [{"id": 1, "name": "bolt", "size": 3}]
        # Callers use `.get()` on these, which `sqlite3.Row` does not support.
        assert rows[0].get("missing", "fallback") == "fallback"

    def test_a_query_with_no_matches_returns_an_empty_list(self, connector):
        assert connector.execute_query("SELECT * FROM widgets") == []

    def test_parameters_are_bound_not_interpolated(self, connector):
        connector.execute_non_query(
            "INSERT INTO widgets (name) VALUES (?)", ("'; DROP TABLE widgets--",)
        )
        rows = connector.execute_query("SELECT name FROM widgets")

        assert rows[0]["name"] == "'; DROP TABLE widgets--"

    def test_a_query_can_run_without_parameters(self, connector):
        assert connector.execute_query("SELECT 1 AS one") == [{"one": 1}]


class TestWrites:
    def test_an_insert_reports_the_new_row_id(self, connector):
        result = connector.execute_non_query(
            "INSERT INTO widgets (name) VALUES (?)", ("nut",)
        )
        assert result["lastrowid"] == 1

    def test_an_update_reports_how_many_rows_changed(self, connector):
        for name in ("bolt", "nut"):
            connector.execute_non_query(
                "INSERT INTO widgets (name, size) VALUES (?, 1)", (name,)
            )

        result = connector.execute_non_query("UPDATE widgets SET size = 2")
        assert result["rowcount"] == 2

    def test_writes_are_committed(self, tmp_path):
        db_path = str(tmp_path / "committed.db")
        SQLiteConnector(db_path).execute_non_query(
            "CREATE TABLE things (id INTEGER PRIMARY KEY)"
        )
        SQLiteConnector(db_path).execute_non_query(
            "INSERT INTO things (id) VALUES (1)"
        )

        # A brand new connector sees the data, so nothing was left uncommitted.
        assert SQLiteConnector(db_path).execute_query("SELECT * FROM things") == [
            {"id": 1}
        ]


class TestScripts:
    def test_a_script_runs_several_statements(self, connector):
        connector.execute_script(
            """
            INSERT INTO widgets (name) VALUES ('one');
            INSERT INTO widgets (name) VALUES ('two');
            """
        )
        assert len(connector.execute_query("SELECT * FROM widgets")) == 2


class TestInitFile:
    def test_it_runs_the_schema_file_it_is_given(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE seeded (id INTEGER PRIMARY KEY);")

        connector = SQLiteConnector(
            str(tmp_path / "seeded.db"), init_sql_file=str(schema)
        )
        assert connector.execute_query("SELECT * FROM seeded") == []

    def test_a_missing_schema_file_is_an_error(self, tmp_path):
        with pytest.raises(Exception, match="Error reading SQL"):
            SQLiteConnector(
                str(tmp_path / "db.db"),
                init_sql_file=str(tmp_path / "nowhere.sql"),
            )

    def test_the_projects_own_init_sql_applies_cleanly(self, tmp_path):
        connector = SQLiteConnector(
            str(tmp_path / "init.db"), init_sql_file="init.sql"
        )
        names = {
            row["name"]
            for row in connector.execute_query(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "players",
            "channels",
            "channel_players",
            "games",
            "player_games",
        } <= names


class TestConnectionFailures:
    def test_an_unreachable_database_path_is_reported(self, tmp_path):
        unreachable = str(tmp_path / "no-such-directory" / "db.db")

        with pytest.raises(Exception, match="Error connecting to database"):
            SQLiteConnector(unreachable).execute_query("SELECT 1")

    def test_a_write_to_an_unreachable_path_is_reported(self, tmp_path):
        unreachable = str(tmp_path / "no-such-directory" / "db.db")

        with pytest.raises(Exception, match="Error connecting to database"):
            SQLiteConnector(unreachable).execute_non_query("CREATE TABLE t (a)")
