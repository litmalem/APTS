"""Copy live MySQL governance into a new, verified SQLite file. Never changes source data."""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, date
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.db import sqlite_params  # Registers stable DATETIME and DECIMAL_TEXT converters.
from app.utils import sha256_json
import pymysql


def quote(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name): raise ValueError('Unsupported schema identifier')
    return '"'+name+'"'


def plain(value):
    if isinstance(value,datetime): return value.isoformat(sep=' ')
    if isinstance(value,date): return value.isoformat()
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,bytes): return value.decode('utf-8')
    return value


def digest_rows(rows, names):
    payload=[[plain(row[name]) for name in names] for row in rows]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def audit_check(rows):
    previous=None
    for row in rows:
        body={name:row[name] for name in ('audit_id','event_type','actor_id','mission_id','subject_type','subject_id','previous_hash')}
        body['payload']=json.loads(row['payload_json']) if row['payload_json'] else {}
        if row['previous_hash']!=previous or sha256_json(body)!=row['record_hash']:
            raise ValueError('Source audit chain invalid at audit record '+str(row['id']))
        previous=row['record_hash']
    return {'records':len(rows),'head_sha256':previous,'valid':True}


def column_sql(column, pk):
    name=column['COLUMN_NAME']; kind=column['DATA_TYPE'].lower(); full=column['COLUMN_TYPE'].lower()
    if kind in ('bigint','int','tinyint','smallint'):
        declared='INTEGER'
    elif kind=='datetime': declared='DATETIME'
    elif kind=='decimal':
        if full!='decimal(6,2)': raise ValueError('Unsupported decimal scale: '+full)
        declared='DECIMAL_TEXT'
    elif kind in ('char','varchar','enum'): declared='TEXT COLLATE NOCASE'
    elif kind in ('longtext','text'): declared='TEXT'
    else: raise ValueError('Unsupported MySQL type: '+kind)
    if 'auto_increment' in column['EXTRA']:
        if pk != [name] or declared!='INTEGER': raise ValueError('Unsupported AUTO_INCREMENT key')
        return quote(name)+' INTEGER PRIMARY KEY AUTOINCREMENT'
    sql=quote(name)+' '+declared
    if column['IS_NULLABLE']=='NO': sql+=' NOT NULL'
    default=column['COLUMN_DEFAULT']
    if default is not None:
        value=str(default)
        if value.upper()=='NULL': sql+=' DEFAULT NULL'
        elif value.lower() in ('current_timestamp()','current_timestamp'): sql+=' DEFAULT CURRENT_TIMESTAMP'
        elif value.startswith("'") and value.endswith("'"):
            literal=value[1:-1].replace("''", "'").replace("\\'", "'")
            sql+=" DEFAULT '"+literal.replace("'","''")+"'"
        elif re.fullmatch(r'-?\d+(?:\.\d+)?',value):
            sql+=' DEFAULT '+("'"+value+"'" if kind=='decimal' else value)
        else: raise ValueError('Unsupported schema default for '+name)
    if 'unsigned' in full: sql+=' CHECK ('+quote(name)+'>=0)'
    if kind=='tinyint' and full=='tinyint(1)': sql+=' CHECK ('+quote(name)+' IN (0,1))'
    if kind in ('char','varchar'):
        size=int(re.search(r'\((\d+)\)',full)[1]);sql+=' CHECK (length('+quote(name)+')<='+str(size)+')'
    if kind=='enum':
        choices=re.findall(r"'([^']*)'",column['COLUMN_TYPE'])
        sql+=' CHECK ('+quote(name)+' IN ('+','.join("'"+x.replace("'","''")+"'" for x in choices)+'))'
    return sql


def read_snapshot():
    config={k:getattr(settings,'db_'+k) for k in ('host','port','user','password')}
    config.update(database=settings.db_name,charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    with closing(pymysql.connect(**config)) as connection:
        with connection.cursor() as cur:
            cur.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            def fetch(sql):
                cur.execute(sql,(settings.db_name,));return cur.fetchall()
            tables=fetch("SELECT TABLE_NAME,AUTO_INCREMENT,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
            if not tables or any(not t['TABLE_NAME'].startswith('gov_') or t['ENGINE']!='InnoDB' for t in tables):
                raise ValueError('Expected only InnoDB governance tables')
            if fetch('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s'):
                raise ValueError('Source contains triggers requiring explicit migration')
            columns=fetch('SELECT * FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION')
            indexes=fetch('SELECT * FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX')
            foreign_keys=fetch("SELECT k.TABLE_NAME,k.CONSTRAINT_NAME,k.COLUMN_NAME,k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,k.ORDINAL_POSITION,r.UPDATE_RULE,r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME AND r.TABLE_NAME=k.TABLE_NAME WHERE k.TABLE_SCHEMA=%s AND k.REFERENCED_TABLE_NAME IS NOT NULL ORDER BY k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION")
            data={}
            for table in tables:
                name=table['TABLE_NAME']; pk=[i['COLUMN_NAME'] for i in indexes if i['TABLE_NAME']==name and i['INDEX_NAME']=='PRIMARY']
                if not pk: raise ValueError('Table missing primary key: '+name)
                cur.execute('SELECT * FROM `'+name+'` ORDER BY '+','.join('`'+key+'`' for key in pk))
                data[name]=cur.fetchall()
            connection.rollback()
    return {'tables':tables,'columns':columns,'indexes':indexes,'foreign_keys':foreign_keys,'data':data}


def migrate(destination, report_path, snapshot_path):
    destination=Path(destination).resolve()
    if destination.exists(): raise FileExistsError('Migration destination already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    source=read_snapshot()
    audit=audit_check(source['data'].get('gov_audit_log',[]))
    # No Unicode identity/unique-key collation is silently weakened to ASCII NOCASE.
    keys={(i['TABLE_NAME'],i['COLUMN_NAME']) for i in source['indexes'] if not i['NON_UNIQUE']}
    keys|={(k['TABLE_NAME'],k['COLUMN_NAME']) for k in source['foreign_keys']}
    for table,column in keys:
        for row in source['data'][table]:
            if isinstance(row[column],str) and not row[column].isascii():
                raise ValueError('Non-ASCII identity requires explicit collation mapping: '+table+'.'+column)
    if snapshot_path:
        Path(snapshot_path).parent.mkdir(parents=True,exist_ok=True)
        with Path(snapshot_path).open('x',encoding='utf-8') as stream:
            json.dump(source,stream,default=plain,ensure_ascii=False,indent=2)
    fd,tmp=tempfile.mkstemp(prefix='governance-migration-',suffix='.sqlite3',dir=destination.parent);os.close(fd)
    report={'source':'mysql','target':'sqlite','tables':{},'audit':audit,'foreign_keys':len({(k['TABLE_NAME'],k['CONSTRAINT_NAME']) for k in source['foreign_keys']}),'identity_collation':'ASCII NOCASE; non-ASCII identity keys rejected'}
    try:
        with closing(sqlite3.connect(tmp,detect_types=sqlite3.PARSE_DECLTYPES)) as db:
            db.row_factory=sqlite3.Row
            for table in source['tables']:
                name=table['TABLE_NAME']; columns=[c for c in source['columns'] if c['TABLE_NAME']==name]
                groups=defaultdict(list)
                for index in source['indexes']:
                    if index['TABLE_NAME']==name:groups[index['INDEX_NAME']].append(index)
                pk=[i['COLUMN_NAME'] for i in groups['PRIMARY']]
                definitions=[column_sql(column,pk) for column in columns]
                if not any('auto_increment' in c['EXTRA'] for c in columns): definitions.append('PRIMARY KEY ('+','.join(map(quote,pk))+')')
                fks=defaultdict(list)
                for fk in source['foreign_keys']:
                    if fk['TABLE_NAME']==name:fks[fk['CONSTRAINT_NAME']].append(fk)
                for constraint,parts in fks.items():
                    definitions.append('CONSTRAINT '+quote(constraint)+' FOREIGN KEY ('+','.join(quote(p['COLUMN_NAME']) for p in parts)+') REFERENCES '+quote(parts[0]['REFERENCED_TABLE_NAME'])+' ('+','.join(quote(p['REFERENCED_COLUMN_NAME']) for p in parts)+') ON UPDATE '+parts[0]['UPDATE_RULE']+' ON DELETE '+parts[0]['DELETE_RULE'])
                db.execute('CREATE TABLE '+quote(name)+' ('+','.join(definitions)+')')
                for index,parts in groups.items():
                    if index=='PRIMARY':continue
                    if any(not p['COLUMN_NAME'] or p['SUB_PART'] and not p['NON_UNIQUE'] for p in parts):raise ValueError('Unsupported expression or unique prefix index')
                    db.execute('CREATE '+('UNIQUE ' if not parts[0]['NON_UNIQUE'] else '')+'INDEX '+quote(name+'__'+index)+' ON '+quote(name)+' ('+','.join(quote(p['COLUMN_NAME']) for p in parts)+')')
                names=[c['COLUMN_NAME'] for c in columns]
                db.executemany('INSERT INTO '+quote(name)+' ('+','.join(map(quote,names))+') VALUES ('+','.join('?' for _ in names)+')',[[plain(row[key]) for key in names] for row in source['data'][name]])
                if table['AUTO_INCREMENT'] is not None:
                    db.execute('DELETE FROM sqlite_sequence WHERE name=?',(name,))
                    db.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)',(name,int(table['AUTO_INCREMENT'])-1))
                copied=[dict(r) for r in db.execute('SELECT * FROM '+quote(name)+' ORDER BY '+','.join(map(quote,pk)))]
                expected=digest_rows(source['data'][name],names);actual=digest_rows(copied,names)
                if expected!=actual:raise ValueError('Row content verification failed: '+name)
                report['tables'][name]={'rows':len(copied),'sha256':actual}
                for column in columns:
                    if 'on update current_timestamp' in column['EXTRA'].lower():
                        field=quote(column['COLUMN_NAME'])
                        db.execute('CREATE TRIGGER '+quote(name+'__touch_'+column['COLUMN_NAME'])+' AFTER UPDATE ON '+quote(name)+' WHEN NEW.'+field+' IS OLD.'+field+' BEGIN UPDATE '+quote(name)+' SET '+field+"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "+' AND '.join(quote(key)+'=NEW.'+quote(key) for key in pk)+'; END')
            errors=list(db.execute('PRAGMA foreign_key_check'))
            if errors:raise ValueError('Migrated foreign keys invalid: '+str(errors[:3]))
            if db.execute('PRAGMA integrity_check').fetchall()[0][0]!='ok':raise ValueError('SQLite integrity check failed')
            db.commit();db.execute('PRAGMA foreign_keys=ON')

            report.update(total_rows=sum(t['rows'] for t in report['tables'].values()),integrity_check='ok',foreign_key_check='ok',target=str(destination))
        with closing(sqlite3.connect(tmp, isolation_level=None)) as journal:
            if journal.execute('PRAGMA journal_mode=WAL').fetchall()[0][0]!='wal':raise ValueError('WAL activation failed')
            journal.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
        os.replace(tmp,destination)
        if report_path:
            Path(report_path).parent.mkdir(parents=True,exist_ok=True)
            Path(report_path).write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
    finally:
        for extra in (tmp,tmp+'-wal',tmp+'-shm'):
            if Path(extra).exists():Path(extra).unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True);parser.add_argument('--report',required=True);parser.add_argument('--snapshot',required=True)
    args=parser.parse_args();report=migrate(args.destination,args.report,args.snapshot)
    print(json.dumps({'target':report['target'],'tables':len(report['tables']),'rows':report['total_rows'],'integrity_check':report['integrity_check'],'audit':report['audit']}))
