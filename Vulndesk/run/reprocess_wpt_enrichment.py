"""Recover enrichment from integrity-checked local WPT evidence (dry run by default)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cti_services.wpt_verified_enrichment import VerifiedWPTEnrichment, canonical_bytes, normalize, MATCHING_REVISION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mission-root', type=Path, default=ROOT.parent / 'mission_orchestrator')
    parser.add_argument('--wpt-db', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--force', action='store_true', help='Recompute even current results after dictionary updates')
    parser.add_argument('--sync-missing', action='store_true', help='Fetch one bounded official NVD page for each unresolved technology before reprocessing')
    args = parser.parse_args()
    if args.sync_missing and not args.apply:
        parser.error('--sync-missing requires --apply (writes dictionary and audit records)')
    sys.path.insert(1, str(args.mission_root.resolve()))
    from execution_subsystem.wpt_intake_repository import WPTIntakeRepository
    from mission_orchestrator.mission_wpt_cti_delivery import build_delivery

    path = (args.wpt_db or args.mission_root / 'data' / 'wpt_governed_intake.db').resolve()
    service = VerifiedWPTEnrichment()
    rows = service.db.fetch_all('SELECT intake_id,input_sha256,result_json FROM cti_wpt_verified_evidence')
    prepared = []
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        for row in rows:
            saved = json.loads(row['result_json'])
            if not (args.force or args.sync_missing) and saved.get('enrichment_version') == 2 and saved.get('matching_revision') == MATCHING_REVISION:
                continue
            key = (row['intake_id'],)
            intake = source.execute('SELECT * FROM wpt_governed_intakes WHERE intake_id=?', key).fetchone()
            result = source.execute('SELECT * FROM wpt_stage6_results WHERE intake_id=?', key).fetchone()
            handoff = source.execute('SELECT * FROM wpt_recon_handoff_outbox WHERE intake_id=?', key).fetchone()
            if any(item is None for item in (intake, result, handoff)):
                raise ValueError('Missing source evidence for ' + row['intake_id'])
            delivery = build_delivery(WPTIntakeRepository._row(intake)['record']['intake'],
                                      WPTIntakeRepository._result_row(result)['record'],
                                      WPTIntakeRepository._handoff_row(handoff))
            if hashlib.sha256(canonical_bytes(normalize(delivery))).hexdigest() != row['input_sha256']:
                raise ValueError('Original envelope digest mismatch for ' + row['intake_id'])
            prepared.append(delivery)
    # Validate all source records before applying any derived-result updates.
    if args.sync_missing:
        from config import Config
        from urllib.parse import urlsplit
        from cpe_dictionary_services import CpeDictionaryService, CpeDictionarySyncService, normalize_technology
        endpoint = urlsplit(Config.NVD_CPE_API_URL)
        if (endpoint.scheme != 'https' or endpoint.netloc != 'services.nvd.nist.gov'
                or endpoint.path != '/rest/json/cpes/2.0' or endpoint.query or endpoint.fragment):
            raise ValueError('Synchronization requires the official NVD CPE endpoint')
        matcher = CpeDictionaryService()
        queries = set()
        for delivery in prepared:
            for observed in delivery['technologies']:
                tech = normalize_technology(observed)
                resolution = matcher.resolve_technology(tech)
                if resolution['status'] in {'PRODUCT_NOT_FOUND', 'VERSION_NOT_FOUND'}:
                    queries.add((tech['name'], tech['version']))
        for name, version in sorted(queries):
            search_name = {'Laravel':'Laravel Framework', 'OWASP Juice Shop':'Juice Shop'}.get(name, name)
            keyword = ' '.join(filter(None, (search_name, version)))
            try:
                sync_service = CpeDictionarySyncService()
                if name == 'Angular' and not version:
                    sync = sync_service.sync_match_string('cpe:2.3:a:angular:angular:*:*:*:*:*:*:*:*', max_pages=1, page_size=100)
                else:
                    sync = sync_service.sync_keyword(keyword, max_pages=1, page_size=100)
                print(json.dumps({'sync_keyword':keyword, 'status':sync['status'], 'fetched':sync['total_fetched']}))
            except Exception as exc:
                print(json.dumps({'sync_keyword':keyword, 'status':'FAILED', 'error_type':type(exc).__name__}))
    for delivery in prepared:
        result = service.enrich(delivery, reprocess=args.force or args.sync_missing) if args.apply else None
        print(json.dumps({'intake_id': delivery['wpt_intake_id'], 'target': delivery['target'],
                          'applied': args.apply, 'technology_count': len(delivery['technologies']),
                          'candidate_count': len(result['cpe_candidates']) if result else None}))
    print(json.dumps({'checked': len(rows), 'reprocessed': len(prepared) if args.apply else 0,
                      'eligible': len(prepared)}))


if __name__ == '__main__':
    main()
