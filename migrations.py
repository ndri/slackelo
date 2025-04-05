"""
Migration manager for SlackElo database schema versioning
"""

import os
import re
import logging
from typing import List, Dict, Any
from sqlite_connector import SQLiteConnector

logger = logging.getLogger(__name__)

class Migrations:
    """
    Handles database migrations for SlackElo schema versioning
    """
    
    def __init__(self, db_path: str, migrations_dir: str = "migrations") -> None:
        """
        Initialize the migrations handler
        
        Args:
            db_path: Path to the SQLite database file
            migrations_dir: Directory containing migration SQL files
        """
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self.connector = SQLiteConnector(db_path)
        
    def _get_current_version(self) -> str:
        """
        Get the current database schema version
        
        Returns:
            Current version as string, or '0.0' if no version found
        """
        # Check if version table exists
        tables = self.connector.execute_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='version'"
        )
        
        if not tables:
            return "0.0"
        
        # Get current version
        versions = self.connector.execute_query(
            "SELECT version FROM version ORDER BY applied_at DESC LIMIT 1"
        )
        
        if not versions:
            return "0.0"
            
        return versions[0]['version']
    
    def _get_available_migrations(self) -> List[str]:
        """
        Get the list of available migration files
        
        Returns:
            List of available migration version numbers in ascending order
        """
        if not os.path.exists(self.migrations_dir):
            logger.warning(f"Migrations directory {self.migrations_dir} does not exist")
            return []
            
        # Get all SQL files in the migrations directory
        migration_files = [f for f in os.listdir(self.migrations_dir) if f.endswith('.sql')]
        
        # Extract version numbers from filenames
        versions = []
        for file in migration_files:
            match = re.match(r'^(\d+\.\d+)\.sql$', file)
            if match:
                versions.append(match.group(1))
                
        # Sort versions
        return sorted(versions, key=lambda v: [int(x) for x in v.split('.')])
    
    def _get_applied_migrations(self) -> List[str]:
        """
        Get the list of migrations that have already been applied
        
        Returns:
            List of applied migration version numbers
        """
        # Check if version table exists
        tables = self.connector.execute_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='version'"
        )
        
        if not tables:
            return []
        
        # Get applied versions
        versions = self.connector.execute_query(
            "SELECT version FROM version ORDER BY applied_at"
        )
        
        return [v['version'] for v in versions]
        
    def migrate_to_version(self, target_version: str) -> None:
        """
        Migrate the database to the specified version
        
        Args:
            target_version: Target version to migrate to
        """
        current_version = self._get_current_version()
        available_migrations = self._get_available_migrations()
        applied_migrations = self._get_applied_migrations()
        
        if not available_migrations:
            logger.warning("No migrations available")
            return
            
        if current_version == target_version:
            logger.info(f"Database already at version {target_version}")
            return
            
        # Make sure target version is available
        if target_version not in available_migrations:
            raise ValueError(f"Target version {target_version} not found in available migrations")
            
        # Get target version index
        target_index = available_migrations.index(target_version)
        
        # Get current version index (if it exists)
        try:
            current_index = available_migrations.index(current_version)
        except ValueError:
            # Current version not in available migrations
            # This can happen if we're starting from 0.0
            current_index = -1
            
        # Check if we're upgrading or downgrading
        if current_index >= target_index:
            logger.warning(f"Current version {current_version} is greater than or equal to target version {target_version}")
            return
            
        # Apply migrations in order from current to target
        for i in range(current_index + 1, target_index + 1):
            version = available_migrations[i]
            
            # Skip migrations that have already been applied
            if version in applied_migrations:
                logger.info(f"Migration {version} already applied, skipping")
                continue
                
            migration_file = os.path.join(self.migrations_dir, f"{version}.sql")
            
            logger.info(f"Applying migration {version}")
            
            try:
                with open(migration_file, 'r') as f:
                    sql = f.read()
                    self.connector.execute_script(sql)
                logger.info(f"Successfully applied migration {version}")
            except Exception as e:
                logger.error(f"Error applying migration {version}: {str(e)}")
                raise
                
        logger.info(f"Database migrated from version {current_version} to {target_version}")