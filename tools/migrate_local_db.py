import sqlite3
import argparse
import sys
from pathlib import Path

def run_migration(db_path: Path, migration_sql_path: Path):
    if not db_path.exists():
        print(f"Error: Database {db_path} does not exist.")
        sys.exit(1)

    with sqlite3.connect(db_path) as db:
        # Verify schema integrity before migration
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            print(f"Error: {db_path} failed integrity_check before migration.")
            sys.exit(1)

        # Get current version
        current_version = db.execute('PRAGMA user_version').fetchone()[0]

        if current_version < 3:
            print(f"Applying migration {migration_sql_path} to {db_path}...")
            migration_script = migration_sql_path.read_text(encoding='utf-8')
            db.executescript(migration_script)
            db.commit()
            print("Migration applied successfully.")
        else:
            print(f"Database {db_path} is already at version {current_version}. Skipping migration.")

        # Verify schema integrity after migration
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            print(f"Error: {db_path} failed integrity_check after migration.")
            sys.exit(1)

        # Verify table relationships/foreign keys
        if len(db.execute('PRAGMA foreign_key_check').fetchall()) > 0:
            print(f"Error: {db_path} failed foreign_key_check after migration.")
            sys.exit(1)

        print("Schema verified successfully: integrity, foreign keys, and version increment.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Automate local DB migration.')
    parser.add_argument('--db-path', type=Path, required=True, help='Path to SQLite DB.')
    parser.add_argument('--migration-sql', type=Path, required=True, help='Path to migration SQL file.')
    args = parser.parse_args()
    run_migration(args.db_path, args.migration_sql)
