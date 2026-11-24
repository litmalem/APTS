from __future__ import annotations

from typing import Any, Optional

from .db import to_json
from .repositories import GovernanceRepository
from .utils import new_id, sha256_json


class AuditService:
    def __init__(self, repo: GovernanceRepository):
        self.repo = repo

    def record(self, *args, **kwargs):
        database = getattr(self.repo, "db", None)
        if database is None:
            return self._record_transaction(*args, **kwargs)
        with database.connect():
            return self._record_transaction(*args, **kwargs)

    def _record_transaction(
        self,
        event_type: str,
        *,
        actor_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        payload: Any = None,
    ) -> str:
        previous_hash = self.repo.last_audit_hash()
        audit_id = new_id("gaudit")
        body = {
            "audit_id": audit_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "mission_id": mission_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload or {},
            "previous_hash": previous_hash,
        }
        record_hash = sha256_json(body)
        self.repo.insert_audit({
            "audit_id": audit_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "mission_id": mission_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload_json": to_json(payload or {}),
            "previous_hash": previous_hash,
            "record_hash": record_hash,
        })
        return audit_id
