"""
vibecoded using claude 3.7 sonnet
"""

import sqlite3
from typing import Optional, Union, List, Dict, Any


class SQLiteConnector:
    """
    A class to handle SQLite database connections and operations.
    Connects and disconnects with each query for clean connections.
    """

    def __init__(self, db_path: str, init_sql_file: Optional[str] = None):
        """
        Initialize the connector with the database path and optionally execute an init SQL file.

        Args:
            db_path: Path to the SQLite database file
            init_sql_file: Optional path to an SQL file containing initialization commands
                          (e.g., CREATE TABLE statements)
        """
        self.db_path = db_path

        # If an initialization SQL file is provided, execute it
        if init_sql_file:
            self._execute_init_sql_file(init_sql_file)

    def _get_connection(self) -> sqlite3.Connection:
        """
        Create a new connection to the SQLite database.

        Returns:
            A new SQLite connection
        """
        try:
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as e:
            raise Exception(f"Error connecting to database: {e}")

    def execute_query(
        self, query: str, params: Optional[Union[tuple, dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return the results.
        Opens a new connection for each query and closes it after completion.

        Args:
            query: SQL query to execute
            params: Parameters to substitute into the query

        Returns:
            List of dictionaries representing the rows
        """
        # Create a new connection for this query
        connection = self._get_connection()
        cursor = connection.cursor()

        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Convert results to dictionaries
            results = [dict(row) for row in cursor.fetchall()]

            return results
        finally:
            cursor.close()
            connection.close()

    def execute_non_query(
        self, query: str, params: Optional[Union[tuple, dict]] = None
    ) -> dict:
        """
        Execute an INSERT, UPDATE, or DELETE query and return a dictionary with result info.
        Opens a new connection for each query and closes it after completion.

        Args:
            query: SQL query to execute
            params: Parameters to substitute into the query

        Returns:
            Dictionary containing:
                - 'rowcount': Number of affected rows
                - 'lastrowid': ID of the last inserted row (for INSERT statements)
        """
        # Create a new connection for this query
        connection = self._get_connection()
        cursor = connection.cursor()

        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            connection.commit()

            return {"rowcount": cursor.rowcount, "lastrowid": cursor.lastrowid}
        finally:
            cursor.close()
            connection.close()

    def execute_script(self, script: str) -> None:
        """
        Execute a SQL script that may contain multiple statements.
        Opens a new connection and closes it after completion.

        Args:
            script: SQL script to execute
        """
        # Create a new connection for this script
        connection = self._get_connection()

        try:
            connection.executescript(script)
            connection.commit()
        finally:
            connection.close()

    def _execute_init_sql_file(self, sql_file_path: str) -> None:
        """
        Execute initialization SQL from a file.

        Args:
            sql_file_path: Path to the SQL file
        """
        try:
            with open(sql_file_path, "r") as f:
                sql_script = f.read()
                self.execute_script(sql_script)
        except IOError as e:
            raise Exception(f"Error reading SQL initialization file: {e}")


# Example usage
if __name__ == "__main__":
    # Create a global API instance
    # You can optionally pass an initialization SQL file path
    api = SQLiteConnector("database.db", init_sql_file="schema.sql")

    # Create a table
    api.execute_non_query(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER
        )
    """
    )

    # Insert data
    api.execute_non_query(
        "INSERT INTO users (name, age) VALUES (?, ?)", ("John Doe", 30)
    )

    # Query data
    users = api.execute_query("SELECT * FROM users")
    for user in users:
        print(
            f"User ID: {user['id']}, Name: {user['name']}, Age: {user['age']}"
        )

    # Execute multiple statements with a script
    api.execute_script(
        """
        BEGIN;
        CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price REAL);
        INSERT INTO products (name, price) VALUES ('Widget', 19.99);
        INSERT INTO products (name, price) VALUES ('Gadget', 24.99);
        COMMIT;
    """
    )
