"""Durable enumeration outbox/projection, separate from execution authority."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3


class EnumerationDeliveryRepository:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv('APTS_ENUMERATION_DELIVERY_DB') or
                         Path(__file__).resolve().parents[1] / 'data' / 'enumeration_delivery.db').resolve()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('''CREATE TABLE IF NOT EXISTS enumeration_deliveries (
            intake_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS enumeration_delivery_events (
            event_id INTEGER PRIMARY KEY, intake_id TEXT NOT NULL, state_json TEXT NOT NULL,
            created_at TEXT NOT NULL)''')
        return conn

    def save(self, request, state):
        encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        body, status = encode(request), encode(state)
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn, conn:
            prior = conn.execute('SELECT * FROM enumeration_deliveries WHERE intake_id=?', (request['intake_id'],)).fetchone()
            if prior and prior['request_json'] != body:
                raise ValueError('Enumeration delivery identity has conflicting content')
            if prior and prior['state_json'] == status:
                return
            conn.execute('INSERT INTO enumeration_deliveries VALUES(?,?,?,?) ON CONFLICT(intake_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at',
                         (request['intake_id'], body, status, now))
            conn.execute('INSERT INTO enumeration_delivery_events(intake_id,state_json,created_at) VALUES(?,?,?)',
                         (request['intake_id'], status, now))

    def list(self):
        # A GET must neither create the outbox nor write to it.
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM enumeration_deliveries ORDER BY updated_at DESC LIMIT 500').fetchall()
        return [{'request': json.loads(row['request_json']), 'state': json.loads(row['state_json']),
                 'updated_at': row['updated_at']} for row in rows]
