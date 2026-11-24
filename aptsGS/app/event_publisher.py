from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

import requests

from .config import settings
from .db import to_json
from .repositories import GovernanceRepository
from .utils import new_id

log = logging.getLogger(__name__)


class GovernanceEventPublisher:
    """Transactional-outbox publisher to the VulnDesk CTI event endpoint.

    Governance remains authoritative even when CTI is temporarily unavailable.
    Decisions are persisted first, then delivery is retried asynchronously.
    """

    SOURCE_COMPONENT = "GOV-PLANE"

    def __init__(self, repo: GovernanceRepository):
        self.repo = repo
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def publish(
        self,
        event_type: str,
        *,
        mission_id: Optional[str],
        payload: Dict[str, Any],
        severity: str = "INFO",
    ) -> str:
        event_id = new_id("gevent")
        event_payload = dict(payload or {})
        # Stage 2.7: preserve the authoritative outbox event identity inside the
        # delivered payload. VulnDesk uses this as an idempotency/correlation key
        # when projecting granular PolicyDecision revocations.
        event_payload.setdefault("governance_event_id", event_id)
        self.repo.insert_outbox({
            "event_id": event_id,
            "mission_id": mission_id,
            "event_type": event_type.upper(),
            "source_component": self.SOURCE_COMPONENT,
            "severity": severity.upper(),
            "payload_json": to_json(event_payload),
        })
        return event_id

    def deliver_pending(self, limit: int = 50) -> int:
        delivered = 0
        for row in self.repo.pending_outbox(limit=limit):
            try:
                if not row.get("mission_id"):
                    self.repo.mark_outbox_delivered(row["event_id"])
                    delivered += 1
                    continue

                response = requests.post(
                    settings.cti_event_api_url,
                    json={
                        "mission_id": row["mission_id"],
                        "event_type": row["event_type"],
                        "source_component": self.SOURCE_COMPONENT,
                        "severity": row.get("severity") or "INFO",
                        "payload": row.get("payload") or {},
                    },
                    timeout=settings.cti_event_api_timeout_seconds,
                )
                if 200 <= response.status_code < 300:
                    self.repo.mark_outbox_delivered(row["event_id"])
                    delivered += 1
                else:
                    self.repo.mark_outbox_failed(
                        row["event_id"],
                        f"HTTP {response.status_code}: {response.text[:1000]}",
                    )
            except Exception as exc:
                self.repo.mark_outbox_failed(row["event_id"], str(exc))
        return delivered

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gov-outbox-publisher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.deliver_pending(limit=100)
            except Exception:
                log.exception("Governance event outbox delivery failed")
            self._stop.wait(max(0.25, settings.outbox_poll_seconds))
