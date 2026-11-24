from __future__ import annotations

from http.client import RemoteDisconnected
import time
from urllib.error import HTTPError
from urllib.request import urlopen


def urlopen_local_with_retry(target, *, timeout: float = 5, attempts: int = 3):
    """Open a localhost test URL with narrow transport-only retry semantics.

    Windows can intermittently abort/reset a loopback connection while pytest rapidly
    tears down and recreates short-lived ThreadingHTTPServer instances.  Only transport
    abort/reset/disconnect failures are retried.  HTTPError is deliberately re-raised
    immediately so 4xx/5xx contract assertions (especially fail-closed HTTP 409) remain
    authoritative and are never converted into a success path.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            return urlopen(target, timeout=timeout)
        except HTTPError:
            raise
        except (ConnectionAbortedError, ConnectionResetError, RemoteDisconnected) as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError(f"localhost HTTP retry exhausted: {last_exc!r}")
