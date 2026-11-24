"""Offline reset of selected APTS operational data. Run with all APTS services stopped."""
import argparse
import datetime
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys

KEEP = {'sqlite_sequence','mission_repository_metadata','subsystem_registry_snapshots',
'canonical_subsystems','subsystem_capability_contracts','pentest_repository_meta',
'pentest_capability_registry_snapshots','pentest_capability_contracts','pentest_tool_contracts',
'pentest_capability_tool_mappings','execution_repository_meta','cti_feedback_meta','remote_allowlist'}
GOV = ['gov_approval_decisions','gov_approval_requests','gov_policy_decisions',
'gov_risk_assessments','gov_authorization_requests','gov_scope_action_constraints',
'gov_scope_sources','gov_scope_targets','gov_scope_contracts','gov_event_outbox','gov_audit_log']


def quote(name):
    return '"'+name.replace('"','""')+'"'


def reset_sqlite(path, backup, only_jobs=False, preview=False, enabled=True):
    c=sqlite3.connect(str(path),timeout=5)
    try:
        c.execute('PRAGMA foreign_keys=OFF')
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        eligible=[n for n in tables if (n in {'jobs','governed_intakes'} if only_jobs else n not in KEEP)]
        selected=eligible if enabled else []
        before={n:c.execute('SELECT COUNT(*) FROM '+quote(n)).fetchone()[0] for n in selected}
        if preview:
            # Preview always reports the complete available reset scope.
            full={n:c.execute('SELECT COUNT(*) FROM '+quote(n)).fetchone()[0] for n in eligible}
            return {'database':str(path),'tables':[{'table':n,'rows':full[n]} for n in eligible], 'rows':sum(full.values())}
        if not enabled:
            return {'database':str(path),'rows_removed':0,'selected':False}
        dest=sqlite3.connect(str(backup)); c.backup(dest); dest.close()
        preserved={n:list(c.execute('SELECT * FROM '+quote(n))) for n in tables if n not in selected}
        triggers=list(c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        c.execute('BEGIN EXCLUSIVE')
        for n,_ in triggers: c.execute('DROP TRIGGER '+quote(n))
        for n in selected: c.execute('DELETE FROM '+quote(n))
        for _,sql in triggers: c.execute(sql)
        if any(c.execute('SELECT COUNT(*) FROM '+quote(n)).fetchone()[0] for n in selected):
            raise RuntimeError('Selected SQLite tables are not empty after reset.')
        if any(list(c.execute('SELECT * FROM '+quote(n)))!=rows for n,rows in preserved.items()):
            raise RuntimeError('A preserved SQLite table changed during reset.')
        errors=list(c.execute('PRAGMA foreign_key_check'))
        if errors: raise RuntimeError('Foreign key check failed: '+str(errors[:3]))
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Integrity check failed')
        c.commit()
        print(path.name+': '+str(sum(before.values()))+' records removed; verified empty.')
        return {'database':str(path),'rows_removed':sum(before.values()),'selected':True}
    except Exception:
        c.rollback(); raise
    finally: c.close()


def _run_vulndesk(python, root, args):
    script=pathlib.Path(__file__).with_name('reset_vulndesk.py')
    root=pathlib.Path(root).resolve()
    if not (root/'db.py').is_file() or not (root/'config.py').is_file():
        raise RuntimeError('Vulndesk root tidak valid: db.py/config.py tidak ditemukan di '+str(root))
    env=os.environ.copy()
    existing=env.get('PYTHONPATH','').strip()
    env['PYTHONPATH']=str(root)+(os.pathsep+existing if existing else '')
    result=subprocess.run([str(python),str(script),*args],cwd=str(root),env=env,capture_output=True,text=True,timeout=180)
    if result.returncode: raise RuntimeError('Vulndesk reset helper failed: '+(result.stderr or result.stdout)[-1200:])
    try: return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc: raise RuntimeError('Vulndesk helper returned an invalid report') from exc


def _context(a):
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
    for f in [pathlib.Path(os.getenv('WTP_DB_PATH',str(pathlib.Path(a.wtp_root)/'data'/'profiler.sqlite3'))).resolve(), pathlib.Path(a.mission_root).resolve()/'data'/'profiler.sqlite3']:
        if f.is_file() and all(f!=x[0] for x in paths): paths.append((f,True))
    if not any(j for _,j in paths): raise FileNotFoundError('WTP profiler.sqlite3 not found; set WTP_DB_PATH to the actual path.')
    backend=getattr(settings,'db_driver','mysql')
    if backend=='sqlite':
        path=pathlib.Path(settings.sqlite_path).resolve()
        conn=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=30)
        available={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(GOV)<=available: conn.close(); raise RuntimeError('Governance SQLite schema differs; reset cancelled.')
        gov_counts=[{'table':t,'rows':conn.execute('SELECT COUNT(*) FROM '+quote(t)).fetchone()[0]} for t in GOV]
    else:
        conn=pymysql.connect(**settings.db_config,autocommit=False)
        with conn.cursor() as cur:
            cur.execute('SHOW TABLES'); available={r[0] for r in cur.fetchall()}
            if not set(GOV)<=available: conn.close(); raise RuntimeError('Governance schema differs; reset cancelled.')
            gov_counts=[]
            for t in GOV:
                cur.execute('SELECT COUNT(*) FROM `'+t+'`'); gov_counts.append({'table':t,'rows':cur.fetchone()[0]})
    return paths,conn,backend,gov_counts


def backup_governance(conn, backend, backup):
    if backend=='sqlite':
        dest=sqlite3.connect(str(backup/'governance-before.sqlite3'))
        try: conn.backup(dest)
        finally: dest.close()
        return
    with conn.cursor() as cur, (backup/'governance-before.sql').open('w',encoding='utf-8') as out:
        cur.execute('SHOW TABLES'); available={r[0] for r in cur.fetchall()}
        out.write('SET FOREIGN_KEY_CHECKS=0;\n')
        for t in sorted(available):
            cur.execute('SHOW CREATE TABLE `'+t+'`'); ddl=cur.fetchone()[1]
            out.write('DROP TABLE IF EXISTS `'+t+'`;\n'+ddl+';\n')
            cur.execute('SELECT * FROM `'+t+'`')
            for row in cur.fetchall(): out.write(cur.mogrify('INSERT INTO `'+t+'` VALUES ('+','.join(['%s']*len(row))+')',row)+';\n')
        out.write('SET FOREIGN_KEY_CHECKS=1;\n')
    conn.rollback()


def reset_governance(conn, backend, selected):
    if not selected:return
    if backend=='sqlite':
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN IMMEDIATE')
            for table in selected:conn.execute('DELETE FROM '+quote(table))
            if any(conn.execute('SELECT COUNT(*) FROM '+quote(t)).fetchone()[0] for t in selected):
                raise RuntimeError('Governance SQLite tables not empty')
            if list(conn.execute('PRAGMA foreign_key_check')):raise RuntimeError('Governance SQLite foreign key check failed')
            conn.commit()
        except Exception:conn.rollback();raise
        finally:conn.execute('PRAGMA foreign_keys=ON')
        return
    with conn.cursor() as cur:
        cur.execute('SET FOREIGN_KEY_CHECKS=0')
        try:
            for t in selected:cur.execute('DELETE FROM `'+t+'`')
            for t in selected:
                cur.execute('SELECT COUNT(*) FROM `'+t+'`')
                if cur.fetchone()[0]:raise RuntimeError('Governance table not empty: '+t)
            conn.commit()
        except Exception:conn.rollback();raise
        finally:cur.execute('SET FOREIGN_KEY_CHECKS=1')


def _check_ports(ports):
    for port in ports:
        with socket.socket() as s:
            s.settimeout(.2)
            if s.connect_ex(('127.0.0.1',int(port)))==0:
                raise RuntimeError('Matikan semua layanan APTS sebelum preview/reset (port aktif '+str(port)+'). MySQL boleh tetap aktif.')


def _parse_selection(raw, paths, vulndesk_preview):
    if raw is None:
        # Preserve the existing command-line behavior: no selection means all scopes.
        return {'sqlite_databases':[str(path) for path,_ in paths], 'gss':True,
                'vulndesk':True, 'vulndesk_uploads':True,'cti_enrichment':bool(vulndesk_preview.get('enrichment_tables'))}
    try: selection=json.loads(raw)
    except (TypeError,json.JSONDecodeError) as exc: raise ValueError('Pilihan reset bukan JSON yang valid.') from exc
    if not isinstance(selection,dict): raise ValueError('Pilihan reset harus berupa objek.')
    allowed={'sqlite_databases','gss','vulndesk','vulndesk_uploads','cti_enrichment'}
    if set(selection)-allowed: raise ValueError('Pilihan reset memuat cakupan yang tidak dikenal.')
    dbs=selection.get('sqlite_databases',[])
    if not isinstance(dbs,list) or any(not isinstance(x,str) for x in dbs): raise ValueError('Daftar database SQLite tidak valid.')
    known={str(path) for path,_ in paths}
    if len(set(dbs))!=len(dbs) or not set(dbs)<=known: raise ValueError('Pilihan database SQLite tidak cocok dengan preview.')
    for name in ('gss','vulndesk','vulndesk_uploads','cti_enrichment'):
        if type(selection.get(name,False)) is not bool: raise ValueError('Pilihan '+name+' harus bernilai boolean.')
    if selection.get('vulndesk_uploads') and not vulndesk_preview.get('uploaded_files'):
        raise ValueError('Tidak ada file unggahan Vulndesk pada preview.')
    enrichment=selection.get('cti_enrichment',bool(selection.get('vulndesk') and vulndesk_preview.get('enrichment_tables')))
    if enrichment and not vulndesk_preview.get('enrichment_tables'):
        raise ValueError('Tabel CTI Enrichment tidak tersedia pada preview.')
    if not dbs and not selection.get('gss') and not selection.get('vulndesk') and not selection.get('vulndesk_uploads') and not enrichment:
        raise ValueError('Pilih setidaknya satu cakupan data untuk dihapus.')
    return {'sqlite_databases':dbs,'gss':selection.get('gss',False),
            'vulndesk':selection.get('vulndesk',False),
            'cti_enrichment':enrichment,
            'vulndesk_uploads':selection.get('vulndesk_uploads',False)}


def main():
    p=argparse.ArgumentParser(); p.add_argument('--mission-root',default=r'D:\APTS\mission_orchestrator'); p.add_argument('--gss-root',default=r'D:\APTS\aptsGS'); p.add_argument('--wtp-root',default=r'D:\APTS\WebTechnologyProfiler'); p.add_argument('--vulndesk-root',default=r'D:\APTS\vulndesk'); p.add_argument('--vulndesk-python',default=sys.executable); p.add_argument('--backup-root'); p.add_argument('--service-port',action='append',type=int,default=[]); p.add_argument('--preview-json',action='store_true'); p.add_argument('--selection-json'); a=p.parse_args()
    ports=a.service_port or [8765,8770,8780,8781,8782,8790,8791,8792]
    _check_ports(ports)
    paths,conn,gov_backend,gov_counts=_context(a)
    try:
        sqlite_preview=[reset_sqlite(f,None,jobs,preview=True) for f,jobs in paths]
        vulndesk=_run_vulndesk(a.vulndesk_python,a.vulndesk_root,['--preview'])
        if a.preview_json:
            print(json.dumps({'modules':{'Mission/Pentest/Execution/WPT':sqlite_preview,'GSS':gov_counts,'Vulndesk':vulndesk},'total_rows':sum(x['rows'] for x in gov_counts)+sum(x['rows'] for d in sqlite_preview for x in d['tables'])+sum(x['rows'] for x in vulndesk['tables']),'warning':'Reset data operasional; kebijakan, katalog referensi, konfigurasi, allowlist dan registry dipertahankan.'},ensure_ascii=False))
            return
        selection=_parse_selection(a.selection_json,paths,vulndesk)
        selected_dbs=set(selection['sqlite_databases'])
        backup=pathlib.Path(a.backup_root or str(pathlib.Path(a.mission_root)/'backups'/('reset-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')))); backup.mkdir(parents=True,exist_ok=False)
        print('Backup:',backup)
        backup_governance(conn,gov_backend,backup)
        for i,(f,_) in enumerate(paths):
            src=sqlite3.connect(str(f)); dst=sqlite3.connect(str(backup/(str(i)+'-'+f.name))); src.backup(dst); dst.close(); src.close()
        vulndesk_backup=_run_vulndesk(a.vulndesk_python,a.vulndesk_root,['--prepare-backup-dir',str(backup)])
        report={}
        for i,(f,jobs) in enumerate(paths):
            report[str(f)]=reset_sqlite(f,backup/(str(i)+'-'+f.name),jobs,enabled=str(f) in selected_dbs)
        selected_gov=GOV if selection['gss'] else []
        reset_governance(conn,gov_backend,selected_gov)
        vd_selection=json.dumps({'delete_database':selection['vulndesk'],'delete_uploads':selection['vulndesk_uploads'],'delete_cti_enrichment':selection['cti_enrichment']},separators=(',',':'))
        report['vulndesk']=_run_vulndesk(a.vulndesk_python,a.vulndesk_root,['--apply-backup-dir',str(backup),'--selection-json',vd_selection])
        report['vulndesk_backup']=vulndesk_backup
        report['governance_selected']=selected_gov
        report['selected_sqlite_databases']=sorted(selected_dbs)
        (backup/'reset-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'status':'SUCCESS','backup':str(backup),'report':report},ensure_ascii=False))
    finally: conn.close()
if __name__=='__main__':
    try: main()
    except Exception as e:
        print('FAILED: '+str(e)+'. If deletion already started, use the printed backup folder; no cross-database atomic rollback.',file=sys.stderr); sys.exit(1)
