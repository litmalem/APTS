"""Offline reset of the supplied APTS schema. Run with all APTS services stopped."""
import argparse, datetime, json, os, pathlib, socket, sqlite3, sys

KEEP = {'sqlite_sequence','mission_repository_metadata','subsystem_registry_snapshots',
'canonical_subsystems','subsystem_capability_contracts','pentest_repository_meta',
'pentest_capability_registry_snapshots','pentest_capability_contracts','pentest_tool_contracts',
'pentest_capability_tool_mappings','execution_repository_meta','cti_feedback_meta','remote_allowlist'}
GOV = ['gov_approval_decisions','gov_approval_requests','gov_policy_decisions',
'gov_risk_assessments','gov_authorization_requests','gov_scope_action_constraints',
'gov_scope_sources','gov_scope_targets','gov_scope_contracts','gov_event_outbox','gov_audit_log']
def quote(n): return '"'+n.replace('"','""')+'"'

def reset_sqlite(path, backup, only_jobs=False):
    c=sqlite3.connect(str(path),timeout=5)
    try:
        c.execute('PRAGMA foreign_keys=OFF')
        dest=sqlite3.connect(str(backup)); c.backup(dest); dest.close()
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        selected=[n for n in tables if (n=='jobs' if only_jobs else n not in KEEP)]
        preserved={n:list(c.execute('SELECT * FROM '+quote(n))) for n in tables if n not in selected}
        triggers=list(c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        before={n:c.execute('SELECT COUNT(*) FROM '+quote(n)).fetchone()[0] for n in selected}
        c.execute('BEGIN EXCLUSIVE')
        for n,_ in triggers: c.execute('DROP TRIGGER '+quote(n))
        for n in selected: c.execute('DELETE FROM '+quote(n))
        for _,sql in triggers: c.execute(sql)
        assert all(c.execute('SELECT COUNT(*) FROM '+quote(n)).fetchone()[0]==0 for n in selected)
        assert all(list(c.execute('SELECT * FROM '+quote(n)))==rows for n,rows in preserved.items())
        errors=list(c.execute('PRAGMA foreign_key_check'))
        if errors: raise RuntimeError('Foreign key check failed: '+str(errors[:3]))
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Integrity check failed')
        c.commit()
        print(path.name+': '+str(sum(before.values()))+' records removed; verified empty.')
        return before
    except Exception:
        c.rollback(); raise
    finally: c.close()

def main():
    p=argparse.ArgumentParser(); p.add_argument('--mission-root',default=r'D:\mission_orchestrator'); p.add_argument('--gss-root',default=r'D:\aptsGS'); p.add_argument('--wtp-root',default=r'D:\WebTechnologyProfiler'); p.add_argument('--backup-root'); a=p.parse_args()
    # Offline maintenance only: do not race API workers or their in-memory caches.
    for port in (8765,8770,8780,8781,8782,8790,8791):
        with socket.socket() as s:
            s.settimeout(.2)
            if s.connect_ex(('127.0.0.1',port))==0: raise RuntimeError('Stop ALL APTS services first (active port '+str(port)+'). Keep MySQL running.')
    gss=pathlib.Path(a.gss_root).resolve(); sys.path.insert(0,str(gss)); os.chdir(gss)
    from app.config import settings
    import pymysql
    paths=[]
    if os.getenv('MISSION_DB_DRIVER','sqlite').lower() != 'sqlite': raise RuntimeError('This package requires SQLite Mission; MySQL Mission reset is not supported.')
    envs={'mission_orchestrator.db':'MISSION_SQLITE_PATH','pentest_subsystem.db':'APTS_PENTEST_DB','execution_subsystem.db':'APTS_EXECUTION_DB','cti_feedback_repository.db':'APTS_CTI_FEEDBACK_DB'}
    for name,env in envs.items():
        f=pathlib.Path(os.getenv(env,str(pathlib.Path(a.mission_root)/'data'/name))).resolve()
        if not f.is_file(): raise FileNotFoundError(f)
        paths.append((f,False))
    # WTP can also have a profiler database under Mission/data from earlier launches.
    for f in [pathlib.Path(os.getenv('WTP_DB_PATH',str(pathlib.Path(a.wtp_root)/'data'/'profiler.sqlite3'))).resolve(), pathlib.Path(a.mission_root).resolve()/'data'/'profiler.sqlite3']:
        if f.is_file() and all(f!=x[0] for x in paths): paths.append((f,True))
    if not any(j for _,j in paths): raise FileNotFoundError('WTP profiler.sqlite3 not found; set WTP_DB_PATH to the actual path.')
    backup=pathlib.Path(a.backup_root or str(pathlib.Path(a.mission_root)/'backups'/('reset-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')))); backup.mkdir(parents=True,exist_ok=False)
    print('Backup:',backup)
    conn=pymysql.connect(**settings.db_config,autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('SHOW TABLES'); available={r[0] for r in cur.fetchall()}
            if not set(GOV)<=available: raise RuntimeError('Governance schema differs; reset cancelled.')
            # Backup all governance tables, including configuration, before any mutation.
            with (backup/'governance-before.sql').open('w',encoding='utf-8') as out:
                out.write('SET FOREIGN_KEY_CHECKS=0;\n')
                for t in sorted(available):
                    cur.execute('SHOW CREATE TABLE `'+t+'`'); ddl=cur.fetchone()[1]
                    out.write('DROP TABLE IF EXISTS `'+t+'`;\n'+ddl+';\n')
                    cur.execute('SELECT * FROM `'+t+'`')
                    for row in cur.fetchall():
                        out.write(cur.mogrify('INSERT INTO `'+t+'` VALUES ('+','.join(['%s']*len(row))+')',row)+';\n')
                out.write('SET FOREIGN_KEY_CHECKS=1;\n')
            conn.rollback()
            # All SQLite backups are made before the first DELETE.
            for i,(f,_) in enumerate(paths):
                src=sqlite3.connect(str(f)); dst=sqlite3.connect(str(backup/(str(i)+'-'+f.name))); src.backup(dst); dst.close(); src.close()
            report={}
            for i,(f,jobs) in enumerate(paths): report[str(f)]=reset_sqlite(f,backup/(str(i)+'-'+f.name),jobs)
            cur.execute('SET FOREIGN_KEY_CHECKS=0')
            try:
                for t in GOV: cur.execute('DELETE FROM `'+t+'`')
                for t in GOV:
                    cur.execute('SELECT COUNT(*) FROM `'+t+'`')
                    if cur.fetchone()[0]: raise RuntimeError('Not empty: '+t)
                conn.commit()
            except Exception: conn.rollback(); raise
            finally: cur.execute('SET FOREIGN_KEY_CHECKS=1')
            report['governance_verified_empty']=GOV
            (backup/'reset-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print('SUCCESS: Mission, Scope/RoE and WTP jobs are empty. Restart APTS and press Ctrl+F5.')
    finally: conn.close()
if __name__=='__main__':
    try: main()
    except Exception as e:
        print('FAILED: '+str(e)+'. If deletion already started, use the printed backup folder; no cross-database atomic rollback.',file=sys.stderr); sys.exit(1)
