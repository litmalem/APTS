"""Explicit local operator command for schema installation and repeatable source sync."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Vulndesk_Web'))
from backend import Adapter
from mapping_source_services import SOURCES, migrate, parse_dataset, sync, download


def main():
    parser = argparse.ArgumentParser(description='Import CTID CVE and CAPEC mapping sources')
    parser.add_argument('--migrate', action='store_true', help='Install additive provenance columns first')
    parser.add_argument('--source', choices=[*SOURCES, 'all'], default='all')
    parser.add_argument('--dry-run', action='store_true', help='Download and validate without database writes')
    parser.add_argument('--file', type=Path, help='Use a local snapshot; requires a single source and its source URL')
    parser.add_argument('--url', help='Official source URL for the selected single source')
    parser.add_argument('--config', type=Path, default=ROOT / 'Vulndesk_Web' / 'config.json')
    args = parser.parse_args()
    if (args.file or args.url) and args.source == 'all':
        parser.error('--file/--url require one --source')
    if args.file and not args.url:
        parser.error('--file requires --url to retain the snapshot provenance')
    adapter = None
    if not args.dry_run:
        adapter = Adapter(json.loads(args.config.read_text(encoding='utf-8-sig')), ROOT / 'Vulndesk_Web')
        if args.migrate:
            with adapter.database(write=True) as cursor:
                migrate(cursor)
    for source in SOURCES if args.source == 'all' else [args.source]:
        url = args.url or SOURCES[source]
        data = args.file.read_bytes() if args.file else download(source, url)
        if args.dry_run:
            result = {k: v for k, v in parse_dataset(source, data, url).items() if k != 'rows'}
        else:
            result = sync(source, url, lambda: adapter.database(write=True), data=data)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
