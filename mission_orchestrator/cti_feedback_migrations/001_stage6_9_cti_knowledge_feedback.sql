CREATE TABLE cti_feedback_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    schema_version TEXT NOT NULL,
    migration_level INTEGER NOT NULL CHECK(migration_level=1)
);
CREATE TABLE cti_knowledge_revisions (
    revision_id TEXT PRIMARY KEY,
    knowledge_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 1000),
    previous_revision_sha256 TEXT,
    feedback_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL CHECK(json_valid(record_json) AND length(CAST(record_json AS BLOB))<=65536),
    feedback_export_json TEXT NOT NULL CHECK(json_valid(feedback_export_json) AND length(CAST(feedback_export_json AS BLOB))<=16777216),
    updated_at TEXT NOT NULL,
    UNIQUE(knowledge_id,revision)
);
CREATE INDEX cti_knowledge_mission ON cti_knowledge_revisions(mission_id,knowledge_id,revision);
CREATE TRIGGER cti_knowledge_no_update BEFORE UPDATE ON cti_knowledge_revisions BEGIN
    SELECT RAISE(ABORT,'CTI knowledge revisions are immutable');
END;
CREATE TRIGGER cti_knowledge_no_delete BEFORE DELETE ON cti_knowledge_revisions BEGIN
    SELECT RAISE(ABORT,'CTI knowledge revisions are append-only');
END;
CREATE TRIGGER cti_knowledge_chain BEFORE INSERT ON cti_knowledge_revisions
WHEN NEW.revision != (SELECT count(*)+1 FROM cti_knowledge_revisions WHERE knowledge_id=NEW.knowledge_id)
OR (NEW.revision=1 AND NEW.previous_revision_sha256 IS NOT NULL)
OR (NEW.revision>1 AND NOT EXISTS (
    SELECT 1 FROM cti_knowledge_revisions p WHERE p.knowledge_id=NEW.knowledge_id
    AND p.revision=NEW.revision-1 AND p.record_sha256=NEW.previous_revision_sha256 AND p.mission_id=NEW.mission_id
)) BEGIN
    SELECT RAISE(ABORT,'CTI knowledge requires exact sequential head');
END;
