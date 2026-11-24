"""Queue hash-validated stored WPT evidence for the running CTI API worker."""
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cti_services.db_adapter import DbAdapter
from cti_services.wpt_pipeline import WptPipeline,migrate


def main():
    parser=argparse.ArgumentParser(description='Resume local WPT -> CTI analysis; no target traffic')
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--intake')
    selection.add_argument('--all',action='store_true')
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--migrate',action='store_true')
    parser.add_argument('--retry-failed',action='store_true',help='Explicitly grant three further attempts; retain total counter and child-mission audit')
    args=parser.parse_args()
    if not 1<=args.limit<=1000:
        parser.error('--limit must be between 1 and 1000')
    db=DbAdapter()
    if args.migrate:
        with db.connect() as connection:
            with connection.cursor() as cursor:migrate(cursor)
    worker=WptPipeline(db,None)
    ids=[args.intake] if args.intake else [r['intake_id'] for r in db.fetch_all(
        'SELECT intake_id FROM cti_wpt_verified_evidence ORDER BY created_at,intake_id LIMIT %(limit)s',{'limit':args.limit})]
    failed=0
    for intake_id in ids:
        try:
            if args.retry_failed:
                worker.retry_failed(intake_id)
            print(json.dumps(worker.enqueue_stored(intake_id)),flush=True)
        except (KeyError,ValueError) as error:
            failed+=1;print(json.dumps({'intake_id':intake_id,'status':'REJECTED','reason':str(error)}),flush=True)
    if failed:
        raise SystemExit(1)


if __name__=='__main__':main()
