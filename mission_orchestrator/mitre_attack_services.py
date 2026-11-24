from __future__ import annotations

from datetime import datetime, timezone

from db import session_scope
from mitre_attack_api import MitreAttackApiClient
from mitre_attack_mapper import MitreAttackMapper
from mitre_attack_repositories import (
    MitreAttackUpsertRepository,
    MitreAttackRepository,
    MitreSyncAuditRepository,
)


class MitreAttackService:
    def list_attack_patterns(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.list_attack_patterns(keyword=keyword, limit=limit, offset=offset)

    def count_attack_patterns(self, keyword: str | None = None) -> int:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.count_attack_patterns(keyword=keyword)

    def list_malware(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.list_malware(keyword=keyword, limit=limit, offset=offset)

    def count_malware(self, keyword: str | None = None) -> int:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.count_malware(keyword=keyword)

    def list_threat_actors(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.list_threat_actors(keyword=keyword, limit=limit, offset=offset)

    def count_threat_actors(self, keyword: str | None = None) -> int:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.count_threat_actors(keyword=keyword)

    def get_attack_pattern_detail(self, stix_id: str) -> dict | None:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.get_attack_pattern_detail(stix_id)

    def get_malware_detail(self, stix_id: str) -> dict | None:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.get_malware_detail(stix_id)

    def get_threat_actor_detail(self, stix_id: str) -> dict | None:
        with session_scope() as session:
            repo = MitreAttackRepository(session)
            return repo.get_threat_actor_detail(stix_id)


class MitreAttackSyncService:
    def __init__(self):
        self.api_client = MitreAttackApiClient()

    def run_full_sync(self, progress_callback=None) -> dict:
        return self._run_sync(mode="MITRE_FULL", added_after=None, progress_callback=progress_callback)

    def run_incremental_sync(self, progress_callback=None) -> dict:
        with session_scope() as session:
            audit_repo = MitreSyncAuditRepository(session)
            last_sync_time = audit_repo.get_latest_successful_mitre_time()

        if last_sync_time is None:
            last_sync_time = datetime(2024, 1, 1)

        added_after = last_sync_time.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return self._run_sync(mode="MITRE_INCREMENTAL", added_after=added_after, progress_callback=progress_callback)

    def _relationship_is_supported(self, mapped: dict) -> bool:
        if mapped.get("relationship_type") != "uses":
            return False

        allowed_pairs = {
            ("malware", "attack-pattern"),
            ("intrusion-set", "attack-pattern"),
            ("intrusion-set", "malware"),
        }
        return (mapped.get("source_type"), mapped.get("target_type")) in allowed_pairs

    def _run_sync(self, mode: str, added_after: str | None, progress_callback=None) -> dict:
        with session_scope() as session:
            upsert_repo = MitreAttackUpsertRepository(session)
            audit_repo = MitreSyncAuditRepository(session)

            audit = audit_repo.create_running(sync_type=mode, page_size=None)
            session.commit()

            total_fetched = 0
            total_inserted = 0
            total_updated = 0
            total_failed = 0
            max_modified_at = None

            steps = [
                ("attack-pattern", self.api_client.fetch_attack_patterns),
                ("malware", self.api_client.fetch_malware),
                ("intrusion-set", self.api_client.fetch_intrusion_sets),
                ("relationship", self.api_client.fetch_relationships),
            ]

            try:
                for step_no, (object_type, fetcher) in enumerate(steps, start=1):
                    objects = fetcher(added_after=added_after)
                    total_fetched += len(objects)

                    for obj in objects:
                        try:
                            action = None
                            modified_at = None
                            with session.begin_nested():
                                if object_type == "attack-pattern":
                                    mapped = MitreAttackMapper.map_attack_pattern(obj)
                                    action, _ = upsert_repo.upsert_attack_pattern(mapped)
                                    modified_at = mapped["attack_pattern"].get("modified_at_source")
                                elif object_type == "malware":
                                    mapped = MitreAttackMapper.map_malware(obj)
                                    action, _ = upsert_repo.upsert_malware(mapped)
                                    modified_at = mapped["malware"].get("modified_at_source")
                                elif object_type == "intrusion-set":
                                    mapped = MitreAttackMapper.map_intrusion_set(obj)
                                    action, _ = upsert_repo.upsert_threat_actor(mapped)
                                    modified_at = mapped["threat_actor"].get("modified_at_source")
                                else:
                                    mapped = MitreAttackMapper.map_relationship(obj)
                                    if not self._relationship_is_supported(mapped):
                                        continue
                                    action, _ = upsert_repo.upsert_relationship(mapped)
                                    modified_at = mapped.get("modified_at_source")

                            if modified_at and (max_modified_at is None or modified_at > max_modified_at):
                                max_modified_at = modified_at

                            if action == "inserted":
                                total_inserted += 1
                            elif action == "updated":
                                total_updated += 1
                        except Exception as item_error:
                            total_failed += 1
                            object_id = obj.get("id") if isinstance(obj, dict) else None
                            print(f"[{mode}] failed object type={object_type} id={object_id}: {item_error}")

                    session.commit()

                    if progress_callback:
                        progress_callback(
                            {
                                "mode": mode,
                                "current_page": step_no,
                                "total_pages": len(steps),
                                "current_type": object_type,
                                "total_fetched": total_fetched,
                                "total_inserted": total_inserted,
                                "total_updated": total_updated,
                                "total_failed": total_failed,
                            }
                        )

                audit_repo.mark_success(
                    audit=audit,
                    total_fetched=total_fetched,
                    total_inserted=total_inserted,
                    total_updated=total_updated,
                    total_failed=total_failed,
                    last_successful_modified_at=max_modified_at,
                )
                session.commit()

                return {
                    "status": "SUCCESS",
                    "mode": mode,
                    "total_fetched": total_fetched,
                    "total_inserted": total_inserted,
                    "total_updated": total_updated,
                    "total_failed": total_failed,
                    "last_successful_modified_at": max_modified_at,
                }
            except Exception as e:
                session.rollback()
                with session_scope() as session2:
                    audit_repo2 = MitreSyncAuditRepository(session2)
                    audit2 = session2.get(type(audit), audit.id)
                    if audit2 is not None:
                        audit_repo2.mark_failed(
                            audit=audit2,
                            error_message=str(e),
                            total_fetched=total_fetched,
                            total_inserted=total_inserted,
                            total_updated=total_updated,
                            total_failed=total_failed,
                        )
                        session2.commit()
                raise
