from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from .event_bus import CtiEventBus


class CtiEventDispatcher:
    """Dispatch queued CTI events to registered subscribers.

    The dispatcher can be drained synchronously (useful for deterministic tests
    and the legacy blocking enrichment endpoint) or can run as a background
    worker for asynchronous mission/event APIs.
    """

    def __init__(self, bus: CtiEventBus, poll_interval: float = 0.05):
        self.bus = bus
        self.poll_interval = max(0.005, float(poll_interval))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dispatch_lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="cti-event-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        self._thread = None

    def dispatch_one(self) -> bool:
        with self._dispatch_lock:
            event = self.bus.pop()
            if event is None:
                return False
            subscribers = self.bus.subscribers_for(event.get("event_type") or "UNKNOWN")
            for subscriber_id, handler in subscribers:
                try:
                    handler(event)
                    self.bus.mark_delivery(event, subscriber_id, "DELIVERED")
                except Exception as exc:
                    self.bus.mark_delivery(event, subscriber_id, "FAILED", str(exc))
                    # Convert handler failure into a typed infrastructure event.
                    # CTI-A01 subscribes to this and terminates the affected
                    # mission deterministically instead of leaving it hanging.
                    if str(event.get("event_type") or "").upper() != "EVENT_HANDLER_FAILED":
                        self.bus.publish(
                            "EVENT_HANDLER_FAILED",
                            source_component="CTI-INF03",
                            mission_id=event.get("mission_id"),
                            payload={
                                "failed_event_id": event.get("event_id"),
                                "failed_event_type": event.get("event_type"),
                                "subscriber_id": subscriber_id,
                                "error": str(exc),
                            },
                            severity="ERROR",
                            state_version=event.get("state_version"),
                            plan_version=event.get("plan_version"),
                            policy_version=event.get("policy_version"),
                        )
            return True

    def dispatch_pending(self, max_events: int = 1000) -> int:
        processed = 0
        while processed < max(1, int(max_events)) and self.dispatch_one():
            processed += 1
        return processed

    def run_until(
        self,
        predicate: Callable[[], bool],
        *,
        timeout_seconds: float = 300.0,
        max_events_per_tick: int = 100,
    ) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while time.monotonic() < deadline:
            if predicate():
                return True
            processed = self.dispatch_pending(max_events=max_events_per_tick)
            if processed == 0:
                time.sleep(self.poll_interval)
        return bool(predicate())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.dispatch_pending(max_events=100)
            except Exception:
                # Mission handlers are responsible for turning errors into typed
                # failure events. Keep the dispatcher alive for other missions.
                processed = 0
            if processed == 0:
                self._stop.wait(self.poll_interval)
