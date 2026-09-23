"""
Tests for the schema versioning in `migrations.py`.

These build their own throwaway databases from the repository's real migration
files, so a migration that does not apply cleanly fails here.
"""

import pytest

from migrations import Migrations
from sqlite_connector import SQLiteConnector

LATEST = "1.2"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "migrations.db")


def columns(connector, table):
    return {
        row["name"]
        for row in connector.execute_query(f"PRAGMA table_info({table})")
    }


def tables(connector):
    return {
        row["name"]
        for row in connector.execute_query(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


class TestMigratingFromScratch:
    def test_it_creates_every_table(self, db_path):
        Migrations(db_path).migrate_to_version(LATEST)

        assert {
            "players",
            "channels",
            "channel_players",
            "games",
            "player_games",
            "version",
        } <= tables(SQLiteConnector(db_path))

    def test_it_records_every_migration_it_ran(self, db_path):
        # `_get_current_version` reads the newest row by `applied_at`, which is
        # only accurate to the second, so a run that applies several migrations
        # at once cannot be ordered by it. The applied list is the reliable
        # record of what ran.
        migrations = Migrations(db_path)
        migrations.migrate_to_version(LATEST)

        assert migrations._get_applied_migrations() == ["1.0", "1.1", LATEST]

    def test_it_adds_the_columns_the_app_relies_on(self, db_path):
        Migrations(db_path).migrate_to_version(LATEST)
        connector = SQLiteConnector(db_path)

        # `init.sql` alone does not produce these - they only exist after 1.1
        # and 1.2 have run.
        assert "team_id" in columns(connector, "channels")
        assert "gambling" in columns(connector, "channel_players")
        assert "gambled" in columns(connector, "player_games")

    def test_it_applies_the_intermediate_migrations_on_the_way(self, db_path):
        migrations = Migrations(db_path)
        migrations.migrate_to_version(LATEST)

        assert set(migrations._get_applied_migrations()) >= {"1.0", "1.1", "1.2"}


class TestMigratingInSteps:
    def test_stopping_short_leaves_later_changes_unapplied(self, db_path):
        Migrations(db_path).migrate_to_version("1.1")
        connector = SQLiteConnector(db_path)

        assert "team_id" in columns(connector, "channels")
        assert "gambling" not in columns(connector, "channel_players")

    def test_the_rest_can_be_applied_afterwards(self, db_path):
        migrations = Migrations(db_path)
        migrations.migrate_to_version("1.1")
        migrations.migrate_to_version(LATEST)

        assert LATEST in migrations._get_applied_migrations()
        assert "gambling" in columns(
            SQLiteConnector(db_path), "channel_players"
        )


class TestRepeatedAndInvalidMigrations:
    def test_migrating_again_changes_nothing(self, db_path):
        migrations = Migrations(db_path)
        migrations.migrate_to_version(LATEST)
        before = migrations._get_applied_migrations()

        migrations.migrate_to_version(LATEST)

        assert migrations._get_applied_migrations() == before

    def test_asking_for_an_older_version_does_not_undo_anything(self, db_path):
        migrations = Migrations(db_path)
        migrations.migrate_to_version(LATEST)

        migrations.migrate_to_version("1.0")

        assert "gambling" in columns(
            SQLiteConnector(db_path), "channel_players"
        )

    def test_an_unknown_version_is_rejected(self, db_path):
        with pytest.raises(ValueError, match="9.9"):
            Migrations(db_path).migrate_to_version("9.9")

    def test_a_fresh_database_reports_no_version(self, db_path):
        assert Migrations(db_path)._get_current_version() == "0.0"

    def test_a_missing_migrations_directory_is_survivable(
        self, db_path, tmp_path
    ):
        migrations = Migrations(db_path, str(tmp_path / "nowhere"))
        migrations.migrate_to_version(LATEST)

        assert migrations._get_current_version() == "0.0"


class TestAvailableMigrations:
    def test_it_finds_the_repositorys_migrations_in_order(self, db_path):
        available = Migrations(db_path)._get_available_migrations()

        assert available == sorted(
            available, key=lambda v: [int(part) for part in v.split(".")]
        )
        assert LATEST in available

    def test_it_ignores_files_that_are_not_versioned_sql(
        self, db_path, tmp_path
    ):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "1.0.sql").write_text("SELECT 1;")
        (migrations_dir / "README.md").write_text("not a migration")
        (migrations_dir / "notes.sql").write_text("SELECT 1;")

        migrations = Migrations(db_path, str(migrations_dir))
        assert migrations._get_available_migrations() == ["1.0"]


class TestBrokenMigrations:
    @pytest.fixture
    def broken_dir(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "1.0.sql").write_text(
            "CREATE TABLE version (version TEXT NOT NULL PRIMARY KEY, "
            "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);\n"
            "INSERT OR IGNORE INTO version (version) VALUES ('1.0');"
        )
        (migrations_dir / "1.1.sql").write_text("THIS IS NOT SQL;")
        return str(migrations_dir)

    def test_a_migration_that_fails_stops_the_upgrade(
        self, db_path, broken_dir
    ):
        with pytest.raises(Exception):
            Migrations(db_path, broken_dir).migrate_to_version("1.1")

    def test_the_failed_version_is_not_recorded_as_applied(
        self, db_path, broken_dir
    ):
        migrations = Migrations(db_path, broken_dir)
        with pytest.raises(Exception):
            migrations.migrate_to_version("1.1")

        assert migrations._get_applied_migrations() == ["1.0"]


class TestVersionReporting:
    def test_an_empty_version_table_reads_as_unversioned(self, db_path):
        SQLiteConnector(db_path).execute_non_query(
            "CREATE TABLE version (version TEXT NOT NULL PRIMARY KEY, "
            "applied_at TIMESTAMP)"
        )

        assert Migrations(db_path)._get_current_version() == "0.0"
