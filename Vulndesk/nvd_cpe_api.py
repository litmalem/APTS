from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import requests

from config import Config


class NvdCpeApiClient:
    """Client for the NVD 2.0 CPE Dictionary/Product API."""

    def __init__(self):
        self.base_url = Config.NVD_CPE_API_URL
        self.api_key = Config.NVD_API_KEY
        self.timeout = Config.NVD_CPE_TIMEOUT_SECONDS

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "VulnDesk/1.0 CPE Dictionary Sync"}
        if self.api_key:
            headers["apiKey"] = self.api_key
        return headers

    def fetch_page(self, start_index: int = 0, results_per_page: int | None = None, **params: Any) -> Dict[str, Any]:
        query = {
            "startIndex": int(start_index),
            "resultsPerPage": int(results_per_page or Config.NVD_CPE_PAGE_SIZE),
        }
        for key, value in params.items():
            if value is not None and value != "":
                if isinstance(value, datetime):
                    query[key] = value.isoformat()
                else:
                    query[key] = value
        response = requests.get(self.base_url, headers=self._headers(), params=query, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch_modified_range(
        self,
        start_index: int = 0,
        results_per_page: int | None = None,
        last_mod_start_date: datetime | None = None,
        last_mod_end_date: datetime | None = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if last_mod_start_date is not None:
            params["lastModStartDate"] = last_mod_start_date
        if last_mod_end_date is not None:
            params["lastModEndDate"] = last_mod_end_date
        return self.fetch_page(start_index=start_index, results_per_page=results_per_page, **params)

    def search_keyword(self, keyword: str, start_index: int = 0, results_per_page: int | None = None) -> Dict[str, Any]:
        return self.fetch_page(start_index=start_index, results_per_page=results_per_page, keywordSearch=keyword)

    def search_match_string(self, cpe_match_string: str, start_index: int = 0, results_per_page: int | None = None) -> Dict[str, Any]:
        return self.fetch_page(start_index=start_index, results_per_page=results_per_page, cpeMatchString=cpe_match_string)

    def fetch_by_cpe_name_id(self, cpe_name_id: str) -> Dict[str, Any]:
        return self.fetch_page(start_index=0, results_per_page=1, cpeNameId=cpe_name_id)
