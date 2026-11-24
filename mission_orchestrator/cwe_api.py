from __future__ import annotations

from typing import Any
import requests

from config import Config


class CweApiClient:
    """Lightweight MITRE CWE REST API client.

    Default root API:
        https://cwe-api.mitre.org/api/v1

    The client is intentionally small and follows the existing VulnDesk style
    used by nvd_api.py and mitre_attack_api.py.
    """

    def __init__(self) -> None:
        self.base_url = Config.CWE_API_ROOT.rstrip("/")
        self.timeout = int(getattr(Config, "CWE_TIMEOUT_SECONDS", 60))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "VulnDesk/1.0 (+MITRE CWE REST API)",
            }
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_version(self) -> dict:
        return self._get("/cwe/version")

    def fetch_weakness(self, cwe_id: str | int) -> dict:
        number = str(cwe_id).strip().upper().replace("CWE-", "")
        return self._get(f"/cwe/weakness/{number}")

    def fetch_cwe_ids(self, cwe_ids: list[str] | tuple[str, ...]) -> dict:
        cleaned: list[str] = []
        for cwe_id in cwe_ids:
            value = str(cwe_id).strip().upper().replace("CWE-", "")
            if value:
                cleaned.append(value)
        if not cleaned:
            return {}
        return self._get(f"/cwe/{','.join(cleaned)}")

    def fetch_view(self, view_id: str | int = 1000) -> dict:
        return self._get(f"/cwe/view/{view_id}")

    def fetch_category(self, category_id: str | int) -> dict:
        number = str(category_id).strip().upper().replace("CWE-", "")
        return self._get(f"/cwe/category/{number}")
