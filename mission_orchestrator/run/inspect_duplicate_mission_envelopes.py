import sqlite3
import hashlib
from mission_orchestrator.repository import MissionRepository

MISSION_ID = "mission-gmo-e672e544-c49e-4ece-a08c-f3a9f8c972d7"

repo = MissionRepository()
print("driver:", repo.driver)
print("sqlite_path:", repo.sqlite_path)

conn = sqlite3.connect(repo.sqlite_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def short(v, limit=500):
    if v is None:
        return "NULL"
    if isinstance(v, bytes):
        return f"<bytes len={len(v)} sha256={hashlib.sha256(v).hexdigest()}>"
    s = str(v)
    return s if len(s) <= limit else s[:limit] + "...<truncated>"

print("\n=== A. mission_envelopes schema ===")
for row in cur.execute("PRAGMA table_info(mission_envelopes)"):
    print(dict(row))

print("\n=== B. mission_envelopes indexes ===")
for row in cur.execute("PRAGMA index_list(mission_envelopes)"):
    print(dict(row))

print("\n=== C. duplicate mission_envelopes by mission_id ===")
for row in cur.execute("""
    SELECT mission_id, COUNT(*) AS count
    FROM mission_envelopes
    GROUP BY mission_id
    HAVING COUNT(*) > 1
    ORDER BY count DESC
"""):
    print(dict(row))

print("\n=== D. envelope rows for target mission ===")
rows = cur.execute("""
    SELECT rowid, *
    FROM mission_envelopes
    WHERE mission_id = ?
    ORDER BY rowid
""", (MISSION_ID,)).fetchall()

for row in rows:
    print("\n--- row ---")
    for key in row.keys():
        print(f"{key}: {short(row[key])}")

print("\nROW COUNT:", len(rows))
