"""Select the owning Pentest repository without downgrading an upgraded database."""
from contextlib import closing
import sqlite3

def recon_service(sqlite_path=None):
    from pentest_subsystem.reconnaissance import ReconnaissanceAgentRepository,ReconnaissanceAgentService
    from pentest_subsystem.task_repository import PENTEST_REPOSITORY_ID
    repository=ReconnaissanceAgentRepository(sqlite_path)
    if repository.sqlite_path.exists():
        with closing(sqlite3.connect(repository.sqlite_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as conn:
            row=conn.execute('SELECT migration_level FROM pentest_repository_meta WHERE repository_id=?',(PENTEST_REPOSITORY_ID,)).fetchone()
        if row and row[0]==16:
            from pentest_subsystem.governance_bound_e2e import GovernanceBoundE2ERepository
            repository=GovernanceBoundE2ERepository(repository.sqlite_path)
    return ReconnaissanceAgentService(repository)
