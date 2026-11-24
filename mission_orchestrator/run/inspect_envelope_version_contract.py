import sqlite3, json, hashlib
from mission_orchestrator.repository import MissionRepository

MISSION_ID = "mission-gmo-e672e544-c49e-4ece-a08c-f3a9f8c972d7"

repo = MissionRepository()
conn = sqlite3.connect(repo.sqlite_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== A. mission_envelopes SQL contract ===")
for row in cur.execute("""
    SELECT type, name, sql
    FROM sqlite_master
    WHERE tbl_name = 'mission_envelopes'
    ORDER BY type, name
"""):
    print(dict(row))

print("\n=== B. envelope version summary ===")
rows = cur.execute("""
    SELECT id, envelope_id, mission_id, envelope_version,
           canonical_sha256, canonical_json, created_at
    FROM mission_envelopes
    WHERE mission_id = ?
    ORDER BY envelope_version, id
""", (MISSION_ID,)).fetchall()

for row in rows:
    data = json.loads(row["canonical_json"])
    bindings = data.get("bindings", {})
    identity = data.get("identity", {})
    raw_sha = hashlib.sha256(row["canonical_json"].encode("utf-8")).hexdigest()

    print("\n--- envelope ---")
    print("db_id:", row["id"])
    print("envelope_id:", row["envelope_id"])
    print("envelope_version:", row["envelope_version"])
    print("created_at:", row["created_at"])
    print("identity.envelope_version:", identity.get("envelope_version"))
    print("pip:", bindings.get("pip"))
    print("scope:", bindings.get("scope"))
    print("canonical_sha256:", row["canonical_sha256"])
    print("raw_json_sha256:", raw_sha)
    print("sha_matches_raw_json:", raw_sha == row["canonical_sha256"])

print("\n=== C. mission events around this mission ===")
for row in cur.execute("""
    SELECT rowid, *
    FROM mission_events
    WHERE mission_id = ?
    ORDER BY rowid
""", (MISSION_ID,)):
    d = dict(row)
    compact = {}
    for k, v in d.items():
        s = str(v)
        compact[k] = s if len(s) <= 250 else s[:250] + "...<truncated>"
    print(compact)
