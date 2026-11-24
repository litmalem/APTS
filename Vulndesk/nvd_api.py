from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
import threading
import time

import requests
from requests.adapters import HTTPAdapter

from config import Config


class NvdApiClient:
    """HTTP client for NVD CVE API 2.0 with rate-limit aware retries.

    The client keeps one persistent HTTP session and enforces the configured
    minimum interval between request start times. With an API key, VulnDesk can
    use the higher NVD rate limit without sleeping before the first request.
    """

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self):
        self.base_url = Config.NVD_API_URL
        self.api_key = Config.NVD_API_KEY
        self.timeout_seconds = Config.NVD_TIMEOUT_SECONDS
        configured_delay = max(0.0, Config.NVD_REQUEST_DELAY_SECONDS)
        # Anonymous NVD clients have a much lower rate limit than API-key clients.
        self.request_delay_seconds = (
            configured_delay if self.api_key else max(configured_delay, 6.0)
        )
        self.max_retries = Config.NVD_MAX_RETRIES
        self.backoff_base_seconds = Config.NVD_BACKOFF_BASE_SECONDS
        self._request_lock = threading.Lock()
        self._last_request_started = 0.0

        self.session = requests.Session()
        self.session.headers.update(self._headers())
        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=2, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _headers(self) -> dict:
        headers = {
            "User-Agent": "VulnDesk/1.2",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["apiKey"] = self.api_key
        return headers

    def _wait_for_request_slot(self) -> None:
        """Enforce a minimum start-to-start interval across all client calls."""
        if self.request_delay_seconds <= 0:
            return

        with self._request_lock:
            now = time.monotonic()
            remaining = self.request_delay_seconds - (now - self._last_request_started)
            if self._last_request_started > 0 and remaining > 0:
                time.sleep(remaining)
            self._last_request_started = time.monotonic()

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        value = (response.headers.get("Retry-After") or "").strip()
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                now = datetime.now(retry_at.tzinfo)
                return max(0.0, (retry_at - now).total_seconds())
            except Exception:
                return None

    def _request_json(self, params: dict) -> dict:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._wait_for_request_slot()

            retry_after: float | None = None
            try:
                response = self.session.get(
                    self.base_url,
                    params=params,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    retry_after = self._retry_after_seconds(response)
                    message = response.text[:500].strip()
                    last_error = requests.HTTPError(
                        f"NVD API HTTP {response.status_code}: {message}",
                        response=response,
                    )
                else:
                    # Authentication and parameter errors are not transient.
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("NVD API returned a non-object JSON payload")
                    return payload

            if attempt >= self.max_retries:
                break

            delay = retry_after
            if delay is None:
                delay = self.backoff_base_seconds * (2 ** attempt)
            time.sleep(max(0.0, delay))

        assert last_error is not None
        raise last_error

    def fetch_page(
        self,
        start_index: int = 0,
        results_per_page: int | None = None,
        **params,
    ) -> dict:
        page_size = results_per_page or Config.NVD_PAGE_SIZE
        page_size = max(1, min(int(page_size), 2000))
        query = {
            "startIndex": max(0, int(start_index)),
            "resultsPerPage": page_size,
            **params,
        }
        return self._request_json(query)

    def fetch_by_cve_id(self, cve_id: str) -> dict:
        return self._request_json({"cveId": cve_id})

    def fetch_modified_range(
        self,
        start_index: int = 0,
        results_per_page: int | None = None,
        last_mod_start_date: datetime | None = None,
        last_mod_end_date: datetime | None = None,
    ) -> dict:
        params = {}
        if last_mod_start_date:
            params["lastModStartDate"] = last_mod_start_date.isoformat()
        if last_mod_end_date:
            params["lastModEndDate"] = last_mod_end_date.isoformat()

        return self.fetch_page(
            start_index=start_index,
            results_per_page=results_per_page or Config.NVD_PAGE_SIZE,
            **params,
        )
