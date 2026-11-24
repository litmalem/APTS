from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cti_services import PentestEnrichmentApiService


def main():
    parser = argparse.ArgumentParser(description="Run VulnDesk Pentest Enrichment API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    api = PentestEnrichmentApiService(host=args.host, port=args.port)
    host, port = api.start()
    print(f"VulnDesk Pentest Enrichment API running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        api.stop()
        print("Stopped.")


if __name__ == "__main__":
    main()
