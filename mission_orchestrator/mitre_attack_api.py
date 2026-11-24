from __future__ import annotations

from typing import Any
import requests

from config import Config


class MitreAttackApiClient:
    """
    Lightweight MITRE ATT&CK TAXII 2.1 client.

    Designed to match the style of nvd_api.py in the existing VulnDesk codebase.
    The workflow is intentionally simple:
    - fetch attack-pattern objects
    - fetch malware objects
    - fetch relationship objects

    That keeps the total request count small and stays aligned with MITRE's
    TAXII rate-limit guidance.
    """

    def __init__(self) -> None:
        self.base_url = Config.MITRE_ATTACK_API_ROOT.rstrip("/")
        self.collection_id = Config.MITRE_ENTERPRISE_COLLECTION_ID
        self.timeout = int(getattr(Config, "MITRE_TIMEOUT_SECONDS", 90))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/taxii+json;version=2.1",
                "User-Agent": "VulnDesk/1.0 (+MITRE ATT&CK TAXII)",
            }
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_collections(self) -> list[dict]:
        payload = self._get("/collections")
        return payload.get("collections", [])

    def fetch_objects(
        self,
        object_type: str,
        added_after: str | None = None,
        include_revoked: bool = True,
        include_deprecated: bool = True,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "match[type]": object_type,
        }
        if added_after:
            params["added_after"] = added_after

        payload = self._get(f"/collections/{self.collection_id}/objects", params=params)
        objects = payload.get("objects", [])

        filtered: list[dict] = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if not include_revoked and obj.get("revoked") is True:
                continue
            if not include_deprecated and obj.get("x_mitre_deprecated") is True:
                continue
            filtered.append(obj)
        return filtered

    def has_changes_since(self, added_after: str) -> bool:
        payload = self._get(
            f"/collections/{self.collection_id}/objects",
            params={"added_after": added_after, "limit": 1},
        )
        return bool(payload.get("objects"))

    def fetch_attack_patterns(self, added_after: str | None = None) -> list[dict]:
        return self.fetch_objects(
            object_type="attack-pattern",
            added_after=added_after,
            include_revoked=Config.MITRE_INCLUDE_REVOKED,
            include_deprecated=Config.MITRE_INCLUDE_DEPRECATED,
        )

    def fetch_malware(self, added_after: str | None = None) -> list[dict]:
        return self.fetch_objects(
            object_type="malware",
            added_after=added_after,
            include_revoked=Config.MITRE_INCLUDE_REVOKED,
            include_deprecated=Config.MITRE_INCLUDE_DEPRECATED,
        )

    def fetch_intrusion_sets(self, added_after: str | None = None) -> list[dict]:
        return self.fetch_objects(
            object_type="intrusion-set",
            added_after=added_after,
            include_revoked=Config.MITRE_INCLUDE_REVOKED,
            include_deprecated=Config.MITRE_INCLUDE_DEPRECATED,
        )

    def fetch_relationships(self, added_after: str | None = None) -> list[dict]:
        return self.fetch_objects(
            object_type="relationship",
            added_after=added_after,
            include_revoked=Config.MITRE_INCLUDE_REVOKED,
            include_deprecated=Config.MITRE_INCLUDE_DEPRECATED,
        )
