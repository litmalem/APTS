"""Adaptive external-CTI source monitoring for Vulndesk Web.

The scheduler only performs lightweight read-only probes. When a change is
confirmed and autonomous update is enabled, it starts the existing governed CTI
mission route; it never calls SourceSyncConnector directly and never bypasses GSS.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend import AppError, json_default

TERMINAL_MISSION_STATES = {"COMPLETED", "QUALITY_REVIEW", "FAILED", "CANCELLED"}


def utcnow():
    return datetime.now(timezone.utc)


def db_time(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_time(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class AdaptiveSourceScheduler:
    def __init__(self, adapter, poll_seconds=15):
        self.adapter = adapter
        self.poll_seconds = max(5, int(poll_seconds))
        self._stop = threading.Event()
        self._thread = None
        self._schema_warning = False
        root = str(adapter.root)
        if root not in sys.path:
            sys.path.insert(0, root)
        from cti_services.source_change_detector import SourceChangeDetector
        from cti_source_config import parse_config
        self.detector = SourceChangeDetector()
        self.parse_config = parse_config

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cti-adaptive-source-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                print(f"Adaptive CTI scheduler error: {type(exc).__name__}: {exc}")
            self._stop.wait(self.poll_seconds)

    def run_once(self):
        rows = self._due_sources()
        if rows is None:
            return {"status": "SCHEMA_REQUIRED", "processed": 0}
        processed = 0
        for row in rows:
            if self._stop.is_set():
                break
            self._probe_one(row)
            processed += 1
        return {"status": "OK", "processed": processed}

    def _due_sources(self):
        now = db_time(utcnow())
        try:
            with self.adapter.database() as cursor:
                cursor.execute(
                    "SELECT r.source_id,r.protocol,r.endpoint_ref,r.credential_ref,r.incremental_strategy,"
                    "r.freshness_sla_seconds,r.criticality,r.config_json,r.enabled,"
                    "s.watermark_value,s.last_success_at,s.last_attempt_at,s.failure_count,s.circuit_state,s.next_retry_at,"
                    "m.detector_strategy,m.scheduler_status,m.last_probe_at,m.last_change_at,m.next_check_at,"
                    "m.unchanged_streak,m.change_rate_ema,m.last_fingerprint,m.etag,m.last_modified_header,m.source_version,"
                    "m.last_total_results,m.last_probe_status,m.last_error,m.last_auto_mission_id "
                    "FROM cti_source_registry r "
                    "LEFT JOIN cti_source_state s ON s.source_id=r.source_id "
                    "LEFT JOIN cti_source_monitor_state m ON m.source_id=r.source_id "
                    "WHERE r.enabled=1 AND (m.next_check_at IS NULL OR m.next_check_at<=%s) "
                    "ORDER BY r.criticality DESC,r.source_id",
                    (now,),
                )
                return cursor.fetchall()
        except Exception as exc:
            if not self._schema_warning:
                print("Adaptive CTI scheduler disabled until sql_update_cti_harmonized/09_adaptive_source_monitoring.sql is applied.")
                self._schema_warning = True
            return None

    def _probe_one(self, row):
        config = self.parse_config(row.get("config_json"))
        if config.get("adaptive_monitor_enabled", True) is False:
            return
        next_retry = parse_time(row.get("next_retry_at"))
        if str(row.get("circuit_state") or "CLOSED").upper() == "OPEN" and next_retry and next_retry > utcnow():
            self._persist(row, {"status": "CIRCUIT_BACKOFF", "changed": False, "detector_strategy": row.get("detector_strategy") or row.get("incremental_strategy") or "UNKNOWN", "checked_at": utcnow().isoformat()}, config, error=None, preserve_schedule_until=next_retry)
            return
        try:
            result = self.detector.probe(row, row, self.adapter.environment())
        except Exception as exc:
            result = {"status": "PROBE_FAILED", "changed": False,
                      "detector_strategy": row.get("incremental_strategy") or "UNKNOWN",
                      "checked_at": utcnow().isoformat()}
            self._persist(row, result, config, error=f"{type(exc).__name__}: {exc}")
            return
        monitor = self._persist(row, result, config, error=None)
        if result.get("changed"):
            self._maybe_start_sync(row, config, monitor)

    def _interval(self, row, result, config):
        sla = max(60, int(row.get("freshness_sla_seconds") or 86400))
        minimum = int(config.get("adaptive_min_interval_seconds") or max(300, min(3600, sla // 8)))
        maximum = int(config.get("adaptive_max_interval_seconds") or max(minimum, min(86400, sla // 2)))
        minimum = max(60, min(minimum, sla))
        maximum = max(minimum, min(maximum, max(sla, minimum)))
        old_streak = max(0, int(row.get("unchanged_streak") or 0))
        streak = 0 if result.get("changed") else min(old_streak + 1, 20)
        interval = minimum if result.get("changed") else min(maximum, minimum * (2 ** min(streak, 10)))
        # Deterministic +/- 5% jitter prevents synchronized bursts while keeping tests repeatable.
        seed = hashlib.sha256(f"{row.get('source_id')}:{streak}:{result.get('checked_at')}".encode()).digest()[0]
        jitter = ((seed / 255.0) - 0.5) * 0.10
        return max(60, int(interval * (1.0 + jitter))), streak

    def _persist(self, row, result, config, error=None, preserve_schedule_until=None):
        now = utcnow()
        interval, streak = self._interval(row, result, config)
        next_check = preserve_schedule_until or (now + timedelta(seconds=interval))
        changed = bool(result.get("changed"))
        old_ema = float(row.get("change_rate_ema") or 0.0)
        ema = round(0.20 * (1.0 if changed else 0.0) + 0.80 * old_ema, 6)
        status = "PROBE_ERROR" if error else ("CHANGE_DETECTED" if changed else "UNCHANGED")
        total = result.get("total_results")
        probe_json = json.dumps(result, ensure_ascii=False, default=json_default)
        with self.adapter.database(write=True) as cursor:
            cursor.execute(
                "INSERT INTO cti_source_monitor_state "
                "(source_id,detector_strategy,scheduler_status,last_probe_at,last_change_at,next_check_at,unchanged_streak,"
                "change_rate_ema,last_fingerprint,etag,last_modified_header,source_version,last_total_results,last_probe_status,last_error,last_probe_json,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE detector_strategy=VALUES(detector_strategy),scheduler_status=VALUES(scheduler_status),"
                "last_probe_at=VALUES(last_probe_at),last_change_at=COALESCE(VALUES(last_change_at),last_change_at),"
                "next_check_at=VALUES(next_check_at),unchanged_streak=VALUES(unchanged_streak),change_rate_ema=VALUES(change_rate_ema),"
                "last_fingerprint=COALESCE(VALUES(last_fingerprint),last_fingerprint),etag=COALESCE(VALUES(etag),etag),"
                "last_modified_header=COALESCE(VALUES(last_modified_header),last_modified_header),"
                "source_version=COALESCE(VALUES(source_version),source_version),last_total_results=VALUES(last_total_results),"
                "last_probe_status=VALUES(last_probe_status),last_error=VALUES(last_error),last_probe_json=VALUES(last_probe_json),updated_at=VALUES(updated_at)",
                (row["source_id"], result.get("detector_strategy"), status, db_time(now), db_time(now) if changed else None,
                 db_time(next_check), streak, ema, result.get("fingerprint"), result.get("etag"), result.get("last_modified_header"),
                 json.dumps(result.get("source_version"), ensure_ascii=False, default=json_default) if result.get("source_version") is not None else None,
                 total, result.get("status"), error, probe_json, db_time(now)),
            )
            # change_signal is consumed by CTI-A02. Probe failures deliberately do not claim a source change.
            signal = 0.0 if error or not changed else min(1.0, 0.25 + 0.75 * min(1.0, float(total or 1) / 100.0))
            cursor.execute(
                "INSERT INTO cti_source_state(source_id,status,change_signal,state_version,created_at,updated_at) "
                "VALUES(%s,%s,%s,1,%s,%s) ON DUPLICATE KEY UPDATE change_signal=VALUES(change_signal),state_version=state_version+1,updated_at=VALUES(updated_at)",
                (row["source_id"], "NEW", signal, db_time(now), db_time(now)),
            )
        return {"next_check_at": next_check, "unchanged_streak": streak, "change_rate_ema": ema, "status": status}

    def _maybe_start_sync(self, row, config, monitor):
        if config.get("auto_update", False) is not True:
            self._set_monitor_status(row["source_id"], "CHANGE_DETECTED_MANUAL_SYNC")
            return
        scope = str(config.get("auto_scope_contract_id") or self.adapter.environment().get("CTI_AUTONOMOUS_SCOPE_CONTRACT_ID") or "").strip()
        if not scope:
            self._set_monitor_status(row["source_id"], "CHANGE_DETECTED_SCOPE_REQUIRED", "Autonomous update requires auto_scope_contract_id or CTI_AUTONOMOUS_SCOPE_CONTRACT_ID.")
            return
        previous = str(row.get("last_auto_mission_id") or "")
        if previous:
            try:
                mission = self.adapter.mission(previous, "status")
                if str(mission.get("status") or "").upper() not in TERMINAL_MISSION_STATES:
                    self._set_monitor_status(row["source_id"], "SYNC_IN_PROGRESS")
                    return
            except AppError:
                pass
        stamp = utcnow().strftime("%Y%m%d%H%M%S")
        suffix = hashlib.sha256(f"{row['source_id']}:{stamp}".encode()).hexdigest()[:8]
        source_slug = "".join(ch if ch.isalnum() or ch in "_.-" else "-" for ch in row["source_id"])[-45:]
        mission_id = f"auto-cti-{source_slug}-{stamp}-{suffix}"[:100]
        try:
            result = self.adapter.start_mission({"mission_id": mission_id, "scope_contract_id": scope, "source_id": row["source_id"]})
            self._set_monitor_status(row["source_id"], "SYNC_REQUESTED", None, mission_id)
            return result
        except Exception as exc:
            self._set_monitor_status(row["source_id"], "SYNC_REQUEST_FAILED", f"{type(exc).__name__}: {exc}")

    def _set_monitor_status(self, source_id, status, error=None, mission_id=None):
        with self.adapter.database(write=True) as cursor:
            cursor.execute(
                "UPDATE cti_source_monitor_state SET scheduler_status=%s,last_error=%s,"
                "last_auto_mission_id=COALESCE(%s,last_auto_mission_id),updated_at=%s WHERE source_id=%s",
                (status, error, mission_id, db_time(utcnow()), source_id),
            )
