"""P0 additive authorization retry upgrade; preserves immutable Stage 3.4.5 records.

Run at repository startup after schema creation. Stop all Mission API processes before
upgrading a deployed database: SQLite table rebuild requires an exclusive schema lock.
"""
import sqlite3

LEGACY_ROUTE_UNIQUE = 'UNIQUE(mission_id, route_decision_id)'
VERSIONED_ROUTE_UNIQUE = 'UNIQUE(mission_id, route_decision_id, governance_binding_version)'


def upgrade_sqlite(path):
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='mission_delegation_authorizations'").fetchone()
        if row is None:
            raise RuntimeError('Missing mission_delegation_authorizations table')
        ddl = row[0]
        if LEGACY_ROUTE_UNIQUE not in ddl:
            if VERSIONED_ROUTE_UNIQUE not in ddl:
                raise RuntimeError('Unknown authorization uniqueness layout; migration refuses to continue')
            conn.execute('COMMIT')
            return False
        indexes = [r[0] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='mission_delegation_authorizations' AND sql IS NOT NULL"
        ).fetchall()]
        temp = 'mission_delegation_authorizations_p0_new'
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (temp,)).fetchone():
            raise RuntimeError('Unexpected prior migration table: ' + temp)
        replacement = ddl.replace('CREATE TABLE mission_delegation_authorizations', 'CREATE TABLE ' + temp, 1)
        if replacement == ddl:
            replacement = ddl.replace('CREATE TABLE IF NOT EXISTS mission_delegation_authorizations', 'CREATE TABLE ' + temp, 1)
        if replacement == ddl:
            raise RuntimeError('Unexpected SQLite table declaration')
        replacement = replacement.replace(LEGACY_ROUTE_UNIQUE, VERSIONED_ROUTE_UNIQUE)
        conn.execute(replacement)
        fields = [r[1] for r in conn.execute('PRAGMA table_info(mission_delegation_authorizations)').fetchall()]
        cols = ','.join('"' + value.replace('"','""') + '"' for value in fields)
        before = conn.execute('SELECT COUNT(*) FROM mission_delegation_authorizations').fetchone()[0]
        conn.execute(f'INSERT INTO {temp} ({cols}) SELECT {cols} FROM mission_delegation_authorizations')
        if conn.execute(f'SELECT COUNT(*) FROM {temp}').fetchone()[0] != before:
            raise RuntimeError('Authorization row count mismatch')
        conn.execute('DROP TABLE mission_delegation_authorizations')
        conn.execute(f'ALTER TABLE {temp} RENAME TO mission_delegation_authorizations')
        for sql in indexes:
            conn.execute(sql)
        problems = conn.execute('PRAGMA foreign_key_check').fetchall()
        if problems:
            raise RuntimeError('Foreign key check failed after authorization migration: ' + str(problems[:3]))
        conn.execute('COMMIT')
        return True
    except Exception:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


def upgrade_mysql(connection):
    # MySQL DDL auto-commits; apply while the Mission service is stopped.
    with connection.cursor() as cur:
        cur.execute("""SELECT INDEX_NAME FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='mission_delegation_authorizations'
            AND INDEX_NAME IN ('uq_delegation_authorization_route','uq_delegation_authorization_route_binding')""")
        indexes = {r['INDEX_NAME'] if isinstance(r, dict) else r[0] for r in cur.fetchall()}
        if 'uq_delegation_authorization_route' in indexes:
            cur.execute('''ALTER TABLE mission_delegation_authorizations
                DROP INDEX uq_delegation_authorization_route,
                ADD UNIQUE KEY uq_delegation_authorization_route_binding
                (mission_id, route_decision_id, governance_binding_version)''')
            return True
        if 'uq_delegation_authorization_route_binding' not in indexes:
            raise RuntimeError('Unknown MySQL authorization uniqueness layout')
    return False

if __name__ == '__main__':
    import sys
    import json
    from pathlib import Path
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python delegation_authorization_migration.py <mission_sqlite_path>')
    target = Path(sys.argv[1])
    if not target.is_file():
        raise SystemExit('Database file not found: ' + str(target))
    migrated = upgrade_sqlite(target)
    with sqlite3.connect(target) as connection:
        fk = connection.execute('PRAGMA foreign_key_check').fetchall()
        integrity = connection.execute('PRAGMA quick_check').fetchone()[0]
        count = connection.execute('SELECT COUNT(*) FROM mission_delegation_authorizations').fetchone()[0]
        if fk or integrity != 'ok':
            raise SystemExit('Migration verification failed: ' + str(fk) + ' / ' + integrity)
        print(json.dumps({'migrated': migrated, 'authorization_records': count,
                          'foreign_keys': 'OK', 'sqlite_quick_check': integrity}))
