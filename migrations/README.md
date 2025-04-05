# SlackElo Database Migrations

This directory contains migration files used to manage the SlackElo database schema.

## How It Works

1. Migration files are named according to their version number (e.g., `1.0.sql`, `1.1.sql`)
2. Each migration file contains SQL statements to update the database schema from the previous version
3. When the application starts, it runs all necessary migrations to bring the database up to the version specified in `app.py`

## Adding a New Migration

To add a new migration:

1. Increment the `VERSION` constant in `app.py`
2. Create a new migration file in this directory with the version number (e.g., `1.2.sql`)
3. Include the following at the beginning of the file to update the version tracking:

```sql
-- Update version
INSERT OR REPLACE INTO version (version, applied_at) VALUES ('1.2', CURRENT_TIMESTAMP);
```

4. Add your schema changes after the version update statement

## Migration File Example

Here's an example of a migration file that adds a new column:

```sql
-- Update version
INSERT OR REPLACE INTO version (version, applied_at) VALUES ('1.2', CURRENT_TIMESTAMP);

-- Add a new column to the games table
ALTER TABLE games ADD COLUMN game_type TEXT DEFAULT 'standard';
```