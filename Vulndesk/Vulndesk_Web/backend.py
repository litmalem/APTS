"""Local bridge for the existing Vulndesk MariaDB schema and loopback CTI APIs."""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(type(value).__name__)


def clean_result(value):
    """Suppress credential-shaped fields in runtime diagnostics, not policy identifiers."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if re.search(r"password|secret|api_key|access_token|credential|database_url|authorization_header", k, re.I)
                    else clean_result(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_result(v) for v in value]
    return value


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
        raise AppError(f"{label} tidak valid. Gunakan ID tanpa spasi.")
    return value


def bounded_int(value, low, high, default):
    try:
        return min(high, max(low, int(value)))
    except (TypeError, ValueError):
        return default


def exact_keys(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body):
        raise AppError("Parameter permintaan tidak sesuai dengan operasi ini.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AppError("API lokal mengembalikan redirect yang tidak diizinkan.", 502)


CATALOGS = {
    "vulnerabilities": ("vulnerabilities", "v", ["cve_id", "description_text"],
        "id,cve_id,description_text,source_name,vuln_status,published_at,modified_at,nvd_url,preferred_cvss_version,preferred_base_score,preferred_base_severity,preferred_vector_string"),
    "attack": ("attack_patterns", "v", ["attack_id", "name", "description_text"],
        "id,attack_id,stix_id,name,description_text,platforms_json,modified_at_source,is_subtechnique,deprecated,revoked"),
    "malware": ("attack_malware", "v", ["software_id", "name", "description_text"],
        "id,software_id,stix_id,name,description_text,platforms_json,modified_at_source,aliases_json"),
    "actors": ("attack_threat_actors", "v", ["group_id", "name", "description_text"],
        "id,group_id,stix_id,name,description_text,modified_at_source,aliases_json"),
    "cwe": ("cwe_catalog", "v", ["cwe_id", "cwe_name", "description_text"],
        "id,cwe_id,cwe_name,cwe_url,description_text,abstraction,status_value,likelihood_of_exploit,api_synced_at"),
    "cpe": ("nvd_cpe_dictionary", "v", ["vendor", "product", "cpe23_uri", "title"],
        "id,cpe_name_id,cpe23_uri,vendor,product,version,title,deprecated,last_synced_at"),
    "tweets": ("tweet_topic_records", "v", ["tweet_text", "topic_text"], "id,tweet_text,topic_text,created_at"),
    "topics": ("topic_master_records", "v", ["topic_text"], "id,topic_text,created_at"),
    "components": ("cti_component_registry", "v", ["component_id", "service_name"],
        "id,component_id,service_key,service_name,component_type,mechanism,authority_boundary,optional_component,enabled,status,sort_order,last_run_at,last_error"),
}


def query_plan(dataset, args):
    """All identifiers are fixed allowlists; every user value is a bound parameter."""
    if dataset not in CATALOGS:
        raise AppError("Katalog tidak dikenal.", 404)
    table, alias, searchable, fields = CATALOGS[dataset]
    page = bounded_int(args.get("page"), 1, 100000, 1)
    limit = bounded_int(args.get("limit"), 1, 250, 10)
    search = str(args.get("search", ""))[:200]
    where, params = [], []
    if search:
        where.append("(" + " OR ".join(f"v.{c} LIKE %s" for c in searchable) + ")")
        params.extend(["%" + search + "%"] * len(searchable))
    if dataset == "vulnerabilities":
        severity = args.get("severity")
        if severity:
            if severity not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
                raise AppError("Filter severity tidak valid.")
            if severity == "UNKNOWN":
                where.append("(v.preferred_base_severity IS NULL OR v.preferred_base_severity NOT IN ('CRITICAL','HIGH','MEDIUM','LOW'))")
            else:
                where.append("v.preferred_base_severity=%s")
                params.append(severity)
        for key, operator in (("min", ">="), ("max", "<=")):
            if args.get(key) not in (None, ""):
                try:
                    score = float(args[key])
                except (TypeError, ValueError):
                    raise AppError("Filter CVSS harus berupa angka.")
                if not 0 <= score <= 10:
                    raise AppError("CVSS harus antara 0 dan 10.")
                where.append(f"v.preferred_base_score {operator} %s")
                params.append(score)
        if args.get("min") and args.get("max") and float(args["min"]) > float(args["max"]):
            raise AppError("CVSS minimum melebihi maksimum.")
        if args.get("year"):
            year = bounded_int(args["year"], 1990, 2100, 0)
            if not year:
                raise AppError("Tahun tidak valid.")
            where.extend(["v.published_at >= %s", "v.published_at < %s"])
            params.extend([f"{year}-01-01", f"{year+1}-01-01"])
        if args.get("cwe"):
            cwe_value = str(args["cwe"]).strip().upper()[:40]
            if re.fullmatch(r"(CWE-)?\d{1,5}", cwe_value):
                # Pencocokan persis: CWE-1 tidak ikut mencocokkan CWE-12, CWE-119, dst.
                cwe_value = "CWE-" + str(int(cwe_value.replace("CWE-", "")))
                where.append("EXISTS (SELECT 1 FROM vulnerability_cwes vc JOIN cwe_catalog cw ON cw.id=vc.cwe_catalog_id WHERE vc.vulnerability_id=v.id AND cw.cwe_id=%s)")
                params.append(cwe_value)
            else:
                where.append("EXISTS (SELECT 1 FROM vulnerability_cwes vc JOIN cwe_catalog cw ON cw.id=vc.cwe_catalog_id WHERE vc.vulnerability_id=v.id AND cw.cwe_id LIKE %s)")
                params.append("%" + cwe_value + "%")
        if args.get("has_cpe") == "1":
            where.append("EXISTS (SELECT 1 FROM cpe_matches cp WHERE cp.vulnerability_id=v.id)")
    from_sql = f"{table} v"
    select = ",".join(f"v.{c}" for c in fields.split(","))
    allowed_sort = set(fields.split(",")) - {"description_text", "platforms_json", "aliases_json", "last_error"}
    if dataset == "vulnerabilities":
        select += ",(SELECT COUNT(*) FROM vulnerability_cwes vc WHERE vc.vulnerability_id=v.id) cwe_count"
        select += ",(SELECT COUNT(*) FROM cpe_matches cp WHERE cp.vulnerability_id=v.id) affected_product_count"
        select += ",(SELECT COUNT(*) FROM reference_links rl WHERE rl.vulnerability_id=v.id) reference_count"
    if dataset == "cwe":
        select += ",(SELECT COUNT(*) FROM vulnerability_cwes vc WHERE vc.cwe_catalog_id=v.id) cve_count"
        allowed_sort.add("cve_count")
    if dataset in {"tweets", "topics"}:
        from_sql += " JOIN dataset_uploads u ON u.id=v.upload_id"
        select += ",u.file_name,u.uploaded_at"
        allowed_sort |= {"file_name", "uploaded_at"}
    sort = args.get("sort", "id")
    if sort not in allowed_sort:
        sort = "id"
    sort_alias = "u" if sort in {"file_name", "uploaded_at"} else "v"
    direction = "ASC" if args.get("direction") == "asc" else "DESC"
    clause = " WHERE " + " AND ".join(where) if where else ""
    count = f"SELECT COUNT(*) AS total FROM {from_sql}{clause}"
    order = f"{sort_alias}.{sort} {direction}"
    if sort == "cve_count":
        order = f"cve_count {direction}"
    elif dataset == "cwe" and sort == "cwe_id":
        # Urutkan numerik (CWE-2 < CWE-10); ID non-numerik seperti NVD-CWE-* di akhir.
        order = f"(v.cwe_id NOT LIKE 'CWE-%%') ASC,CAST(SUBSTRING(v.cwe_id,5) AS UNSIGNED) {direction}"
    sql = f"SELECT {select} FROM {from_sql}{clause} ORDER BY {order},v.id {direction} LIMIT %s OFFSET %s"
    return count, sql, params, page, limit


class Adapter:
    def __init__(self, config, app_dir):
        self.config = config
        self.app_dir = Path(app_dir).resolve()
        self.root = Path(config["vulndesk_root"]).expanduser().resolve()
        self.ports = config["service_ports"]
        self._lock = threading.RLock()
        self._child = None
        self._child_log = None
        self._started_missions = set()
        self._health_cache = (0, [])
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def environment(self):
        values = dict(os.environ)
        env_path = self.root / ".env"
        if env_path.is_file():
            # python-dotenv supports quoted values and existing environment precedence.
            from dotenv import dotenv_values
            for k, v in dotenv_values(env_path).items():
                if v is not None and k not in values:
                    values[k] = v
        return values

    @contextmanager
    def database(self, write=False):
        connection = None
        try:
            import pymysql
            values = self.environment()
            options = dict(host=values.get("DB_HOST", "127.0.0.1"), port=int(values.get("DB_PORT", "3306")),
                           user=values.get("DB_USER", "root"), password=values.get("DB_PASSWORD", ""),
                           database=values.get("DB_NAME", "vulndesk"), charset="utf8mb4", autocommit=False,
                           connect_timeout=5, read_timeout=15, write_timeout=15, cursorclass=pymysql.cursors.DictCursor)
            dsn = values.get("DATABASE_URL", "").strip()
            if dsn:
                parsed = urlsplit(dsn)
                if parsed.scheme not in {"mysql", "mysql+pymysql", "mariadb", "mariadb+pymysql"}:
                    raise AppError("DATABASE_URL harus menggunakan database MariaDB/MySQL.", 503)
                options.update(host=parsed.hostname or "127.0.0.1", port=parsed.port or 3306,
                               user=unquote(parsed.username or "root"), password=unquote(parsed.password or ""), database=unquote(parsed.path.lstrip("/")))
            connection = pymysql.connect(**options)
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION" if write else "START TRANSACTION READ ONLY")
                yield cursor
            if write:
                connection.commit()
            else:
                connection.rollback()
        except AppError:
            if connection:
                connection.rollback()
            raise
        except ImportError:
            raise AppError("Dependensi belum terpasang. Jalankan pip install -r requirements-web.txt.", 503)
        except Exception:
            if connection:
                connection.rollback()
            raise AppError("Database belum tersedia atau skema belum sesuai. Periksa konfigurasi Vulndesk dan layanan MariaDB.", 503)
        finally:
            if connection:
                connection.close()

    def data_list(self, dataset, args):
        count_sql, list_sql, params, page, limit = query_plan(dataset, args)
        with self.database() as cursor:
            cursor.execute(count_sql, params)
            total = cursor.fetchone()["total"]
            cursor.execute(list_sql, params + [limit, (page - 1) * limit])
            items = cursor.fetchall()
            if dataset == "vulnerabilities":
                self._attach_cwe_attack_mappings(cursor, items)
        return {"items": items, "total": total, "page": page, "limit": limit}

    @staticmethod
    def _attach_cwe_attack_mappings(cursor, vulnerabilities):
        """Resolve catalog context on read, without creating mission/verified claims.

        Batch only the requested page. Group techniques but retain every distinct
        supporting rule/CWE path; confidence is the strongest rule, not a sum.
        """
        if not vulnerabilities:
            return
        ids = tuple(dict.fromkeys(row["id"] for row in vulnerabilities))
        placeholders = ",".join(["%s"] * len(ids))
        provenance = "source_dataset,source_version,source_url,source_sha256,relationship_type,references_json,publisher_status".split(',')
        def fields(alias):
            return ','.join(f'{alias}.{key}' for key in provenance)
        select = ("m.id AS rule_id,m.attack_id,m.attack_name,m.tactic_name,m.mapping_source,m.confidence,m.rationale,")
        cursor.execute(
            "SELECT DISTINCT v.id AS vulnerability_id,NULL AS cwe_id,NULL AS cwe_name,NULL AS capec_id,"
            "'DIRECT_CVE' AS mapping_kind," + select + fields('m') +
            " FROM vulnerabilities v JOIN vuln_attack_mappings m ON m.cve_id=v.cve_id "
            "WHERE v.id IN (" + placeholders + ") AND m.is_active=1 AND m.mapping_level='cve_to_attack' "
            "AND m.attack_id IS NOT NULL AND TRIM(m.attack_id)<>'' "
            "UNION ALL SELECT DISTINCT vc.vulnerability_id,cw.cwe_id,cw.cwe_name,NULL,'CWE_RULE'," + select + fields('m') +
            " FROM vulnerability_cwes vc JOIN cwe_catalog cw ON cw.id=vc.cwe_catalog_id "
            "JOIN vuln_attack_mappings m ON m.cwe_id=cw.cwe_id "
            "WHERE vc.vulnerability_id IN (" + placeholders + ") AND m.is_active=1 AND m.mapping_level='cwe_to_attack' "
            "AND m.attack_id IS NOT NULL AND TRIM(m.attack_id)<>'' "
            "UNION ALL SELECT DISTINCT vc.vulnerability_id,cw.cwe_id,cw.cwe_name,cam.capec_id,'CAPEC',"
            "cam.id,cam.attack_id,cam.attack_name,cam.tactic_name,'capec',cam.confidence,cam.rationale," + fields('cam') +
            " FROM vulnerability_cwes vc JOIN cwe_catalog cw ON cw.id=vc.cwe_catalog_id "
            "JOIN capec_cwe_mappings ccm ON ccm.cwe_id=cw.cwe_id AND ccm.is_active=1 "
            "JOIN capec_attack_mappings cam ON cam.capec_id=ccm.capec_id AND cam.is_active=1 "
            "WHERE vc.vulnerability_id IN (" + placeholders + ") AND cam.attack_id IS NOT NULL AND TRIM(cam.attack_id)<>'' "
            "ORDER BY confidence DESC,attack_id,cwe_id,rule_id",
            ids * 3,
        )
        grouped = {key: {} for key in ids}
        for match in cursor.fetchall():
            techniques = grouped[match['vulnerability_id']]
            attack_id = match['attack_id']
            confidence = float(match['confidence']) if match['confidence'] is not None else None
            direct = match['mapping_kind'] == 'DIRECT_CVE'
            technique = techniques.setdefault(attack_id, {
                'attack_id': attack_id, 'technique_name': match['attack_name'],
                'mapping_level': 'cve_via_cwe_to_attack', 'mapping_status': 'INFERRED',
                'confidence': confidence, 'paths': [],
            })
            if direct:
                technique['mapping_status'] = 'CURATED' if match['source_dataset'] else 'DIRECT'
                technique['mapping_level'] = 'cve_to_attack'
            if confidence is not None:
                technique['confidence'] = max(technique['confidence'] or 0, confidence)
            path = {key: match.get(key) for key in [
                'rule_id','cwe_id','cwe_name','capec_id','tactic_name','mapping_source',
                'rationale','mapping_kind',*provenance]}
            path['confidence'] = confidence
            path['confidence_basis'] = 'APTS_POLICY_BASELINE' if match['source_dataset'] else 'RULE'
            if path not in technique['paths']:
                technique['paths'].append(path)
        for row in vulnerabilities:
            mappings = sorted(grouped[row['id']].values(),
                              key=lambda m: (-(m['confidence'] if m['confidence'] is not None else -1), m['attack_id']))
            row['attack_mappings'] = mappings
            row['attack_technique_count'] = len(mappings)
            kinds = {p['mapping_kind'] for m in mappings for p in m['paths']}
            row['attack_mapping_status'] = ('MAPPED_DIRECT' if 'DIRECT_CVE' in kinds else
                                           'MAPPED_VIA_CAPEC' if 'CAPEC' in kinds else
                                           'MAPPED_VIA_CWE' if mappings else 'NO_CWE_MAPPING')

    @staticmethod
    def _attack_relation_plan(attack_id, kind, search=''):
        """Return unique CVE row IDs, independent of how many rules support a pair."""
        branches = {
            'DIRECT_CVE': "SELECT v.id AS vulnerability_id FROM vuln_attack_mappings m JOIN vulnerabilities v ON v.cve_id=m.cve_id WHERE m.attack_id=%s AND m.is_active=1 AND m.mapping_level='cve_to_attack'",
            'CWE_RULE': "SELECT vc.vulnerability_id FROM vuln_attack_mappings m JOIN cwe_catalog cw ON cw.cwe_id=m.cwe_id JOIN vulnerability_cwes vc ON vc.cwe_catalog_id=cw.id WHERE m.attack_id=%s AND m.is_active=1 AND m.mapping_level='cwe_to_attack'",
            'CAPEC': "SELECT vc.vulnerability_id FROM capec_attack_mappings cam JOIN capec_cwe_mappings ccm ON ccm.capec_id=cam.capec_id AND ccm.is_active=1 JOIN cwe_catalog cw ON cw.cwe_id=ccm.cwe_id JOIN vulnerability_cwes vc ON vc.cwe_catalog_id=cw.id WHERE cam.attack_id=%s AND cam.is_active=1",
        }
        selected = list(branches.items()) if kind == 'ALL' else [(kind,branches[kind])]
        statements,params = [],[]
        exact_cve = bool(re.fullmatch(r'CVE-\d{4}-\d{4,}', search, re.I))
        for branch,sql in selected:
            params.append(attack_id)
            if search:
                if branch != 'DIRECT_CVE':
                    sql = sql.replace(' WHERE ', ' JOIN vulnerabilities v ON v.id=vc.vulnerability_id WHERE ', 1)
                sql += ' AND v.cve_id=%s' if exact_cve else " AND v.cve_id LIKE %s ESCAPE '='"
                params.append(search.upper() if exact_cve else '%'+search.replace('=','==').replace('%','=%').replace('_','=_')+'%')
            statements.append(sql)
        return ' UNION '.join(statements), params

    def attack_vulnerabilities(self, attack_id, args):
        with self.database() as cursor:
            return self._attack_vulnerabilities(cursor, attack_id, args)

    def _attack_vulnerabilities(self, cursor, attack_id, args):
        if not isinstance(attack_id, str) or not re.fullmatch(r'T\d{4}(?:\.\d{3})?', attack_id):
            raise AppError('ATT&CK ID tidak valid.')
        kind = args.get('mapping_kind', 'ALL')
        if not isinstance(kind,str) or kind not in {'ALL','DIRECT_CVE','CWE_RULE','CAPEC'}:
            raise AppError('Jenis jalur pemetaan tidak valid.')
        search = args.get('search', '')
        if not isinstance(search, str) or len(search) > 100:
            raise AppError('Pencarian CVE maksimum 100 karakter.')
        search = search.strip()
        limit = bounded_int(args.get('limit'), 1, 50, 10)
        page = bounded_int(args.get('page'), 1, 100000, 1)
        cursor.execute('SELECT id,attack_id,name,description_text,deprecated,revoked FROM attack_patterns WHERE attack_id=%s LIMIT 1', (attack_id,))
        technique = cursor.fetchone() or {'attack_id':attack_id, 'name':'Teknik belum ada di katalog lokal'}
        union, params = self._attack_relation_plan(attack_id, kind, search)
        # vulnerability_cwes.vulnerability_id has an enforced FK to vulnerabilities.
        # Count/page the linked IDs directly; visiting every clustered CVE row
        # just to check existence would turn a small index scan into random I/O.
        join = ' FROM ('+union+') linked'
        cursor.execute('SELECT COUNT(DISTINCT linked.vulnerability_id) AS total'+join, params)
        total = int(cursor.fetchone()['total'])
        page = min(page, max(1, (total+limit-1)//limit))
        # Page IDs before loading descriptions. DISTINCT over large text fields
        # otherwise forces a disk temporary table for every linked CVE.
        cursor.execute('SELECT DISTINCT linked.vulnerability_id AS id'+join+' ORDER BY linked.vulnerability_id DESC LIMIT %s OFFSET %s', params+[limit,(page-1)*limit])
        ids = [r['id'] for r in cursor.fetchall()]
        rows = []
        if ids:
            cursor.execute('SELECT id,cve_id,description_text,preferred_base_score,preferred_base_severity,modified_at FROM vulnerabilities WHERE id IN ('+','.join(['%s']*len(ids))+') ORDER BY id DESC', ids)
            rows = cursor.fetchall()
        self._attach_cwe_attack_mappings(cursor, rows)
        items = []
        for row in rows:
            mapping = next((m for m in row['attack_mappings'] if m['attack_id']==attack_id), None)
            if mapping is None:
                raise AppError('Relasi CVE dan ATT&CK berubah saat pembacaan. Muat ulang.', 409)
            paths = [p for p in mapping['paths'] if kind=='ALL' or p['mapping_kind']==kind]
            direct = [p for p in paths if p['mapping_kind']=='DIRECT_CVE']
            mapping = {**mapping, 'paths':paths,
                       'confidence':max((p['confidence'] for p in paths if p['confidence'] is not None), default=None),
                       'mapping_status':('CURATED' if any(p['source_dataset'] for p in direct) else 'DIRECT') if direct else 'INFERRED',
                       'mapping_level':'cve_to_attack' if direct else 'cve_via_cwe_to_attack'}
            item = {k:row.get(k) for k in ('id','cve_id','description_text','preferred_base_score','preferred_base_severity','modified_at')}
            item['mapping'] = mapping
            items.append(item)
        return clean_result({'technique':technique,'attack_id':attack_id,'items':items,'total':total,
                             'page':page,'limit':limit,'mapping_kind':kind,'search':search,
                             'semantics':'CATALOG_CONTEXT_NOT_CONFIRMED_EXPLOITATION'})

    def data_detail(self, dataset, row_id):
        if dataset not in CATALOGS:
            raise AppError("Katalog tidak dikenal.", 404)
        try:
            row_id = int(row_id)
        except ValueError:
            raise AppError("ID data tidak valid.")
        table = CATALOGS[dataset][0]
        fields = "*" if dataset != "components" else CATALOGS[dataset][3]
        with self.database() as cursor:
            cursor.execute(f"SELECT {fields} FROM {table} WHERE id=%s", (row_id,))
            row = cursor.fetchone()
            if not row:
                raise AppError("Data tidak ditemukan.", 404)
            if dataset == 'attack':
                row['related_vulnerabilities'] = self._attack_vulnerabilities(cursor, row['attack_id'], {})
            if dataset == "vulnerabilities":
                cursor.execute("SELECT cw.cwe_id,cw.cwe_name,vc.source_name FROM vulnerability_cwes vc JOIN cwe_catalog cw ON cw.id=vc.cwe_catalog_id WHERE vc.vulnerability_id=%s", (row_id,))
                row["cwes"] = cursor.fetchall()
                self._attach_cwe_attack_mappings(cursor, [row])
                for table_name, field in (("cpe_matches", "cpe_matches"), ("reference_links", "references"), ("cvss_metrics", "cvss_metrics")):
                    cursor.execute(f"SELECT * FROM {table_name} WHERE vulnerability_id=%s LIMIT 1000", (row_id,))
                    row[field] = cursor.fetchall()
                if not row.get("raw_json"):
                    cursor.execute("SELECT compressed_data,sha256_hex FROM vulnerability_raw_json_chunks WHERE vulnerability_id=%s ORDER BY chunk_index LIMIT 1024", (row_id,))
                    chunks = cursor.fetchall()
                    if chunks:
                        compressed = b"".join(c["compressed_data"] for c in chunks)
                        try:
                            # Bounded decompression prevents excessive allocation from corrupted records.
                            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
                                raw = handle.read(16 * 1024 * 1024 + 1)
                            if len(raw) > 16 * 1024 * 1024:
                                row["raw_json"] = "Raw JSON melebihi batas tampilan 16 MB."
                            elif chunks[0].get("sha256_hex") and hashlib.sha256(raw).hexdigest() != chunks[0]["sha256_hex"]:
                                row["raw_json"] = "Integritas Raw JSON tidak cocok dengan hash sumber."
                            else:
                                row["raw_json"] = raw.decode("utf-8")
                        except (OSError, UnicodeError):
                            row["raw_json"] = "Raw JSON terkompresi tidak dapat dibaca."
        row.pop("stored_file_path", None)
        return clean_result(row)

    def upstream(self, service, path, body=None):
        if service not in self.ports or not path.startswith("/") or ".." in path or "//" in path:
            raise AppError("Endpoint tidak diizinkan.")
        url = f"http://127.0.0.1:{self.ports[service]}{path}"
        request = Request(url, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Accept": "application/json"}, method="GET" if body is None else "POST")
        try:
            with self.opener.open(request, timeout=15 if body is not None else 4) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise AppError("Respons API terlalu besar.", 502)
                return clean_result(json.loads(raw))
        except HTTPError as error:
            if error.code == 404:
                raise AppError("Misi atau endpoint belum tersedia pada runtime ini.", 404)
            raise AppError(f"API {service.upper()} menolak permintaan (HTTP {error.code}). Periksa diagnostik modul.", 502)
        except (URLError, TimeoutError, OSError):
            raise AppError(f"API {service.upper()} belum dapat dihubungi pada port {self.ports[service]}.", 503)
        except (ValueError, TypeError):
            raise AppError("Respons API lokal tidak valid.", 502)

    @property
    def api_owned(self):
        return self._child is not None and self._child.poll() is None

    def _probe(self, item):
        key, name = item
        result = {"key": key, "name": name, "port": self.ports[key], "status": "OFFLINE", "readiness": "API belum dapat dihubungi", "owned": key == "cti" and self.api_owned, "queue_depth": None}
        try:
            health = self.upstream(key, "/health")
            if not isinstance(health, dict):
                raise AppError("Format health tidak valid.")
            declared = str(health.get("readiness_status") or health.get("readiness") or "").upper()
            if isinstance(health.get("readiness"), dict):
                declared = str(health["readiness"].get("status", "")).upper()
            status = str(health.get("status") or "UNKNOWN").upper()
            if status in {"DEGRADED", "ERROR", "FAILED"} or declared in {"NOT_READY", "DEGRADED", "BLOCKED"}:
                result["status"] = "DEGRADED"
            elif declared in {"READY", "HEALTHY"}:
                result["status"] = "READY"
            elif status in {"OK", "HEALTHY", "UP"}:
                result["status"] = "REACHABLE"
            else:
                result["status"] = "UNKNOWN"
            result["readiness"] = ("Readiness: " + declared) if declared else "API terjangkau; readiness tidak dilaporkan"
            result["queue_depth"] = health.get("event_queue_depth")
            result["health"] = health
        except AppError as error:
            result["error"] = str(error)
        return result

    def services(self, refresh=False):
        if not refresh and time.monotonic() - self._health_cache[0] < 3:
            cached = [dict(s) for s in self._health_cache[1]]
            for service in cached:
                service["owned"] = service["key"] == "cti" and self.api_owned
            return cached
        with ThreadPoolExecutor(max_workers=4) as pool:
            items = list(pool.map(self._probe, [("cti", "Vulndesk CTI"), ("gss", "aptsGS"), ("mission", "Mission Orchestrator"), ("pentest", "Pentest Subsystem")]))
        self._health_cache = (time.monotonic(), items)
        return items

    def summary(self):
        counts = {k: None for k in ("vulnerabilities", "attack", "cwe", "cpe", "components")}
        result = {"counts": counts, "severity": {}, "recent": [], "sync": [], "database": {"status": "OFFLINE"}, "checked_at": datetime.now(timezone.utc).isoformat()}
        try:
            with self.database() as cursor:
                for key in counts:
                    cursor.execute(f"SELECT COUNT(*) AS n FROM {CATALOGS[key][0]}")
                    counts[key] = cursor.fetchone()["n"]
                cursor.execute("SELECT COALESCE(preferred_base_severity,'UNKNOWN') severity,COUNT(*) n FROM vulnerabilities GROUP BY preferred_base_severity")
                result["severity"] = {r["severity"]: r["n"] for r in cursor.fetchall()}
                cursor.execute("SELECT sync_type,started_at,finished_at,status_value,total_fetched,total_inserted,total_updated,total_failed FROM sync_audit ORDER BY id DESC LIMIT 5")
                result["sync"] = cursor.fetchall()
            result["recent"] = self.data_list("vulnerabilities", {"limit": "5", "sort": "modified_at", "direction": "desc"})["items"]
            result["database"] = {"status": "OK"}
        except AppError as error:
            result["counts"] = {k: None for k in counts}
            result["database"]["message"] = str(error)
        result["services"] = self.services()
        return result

    def components(self):
        data = self.data_list("components", {"limit": "250", "sort": "sort_order", "direction": "asc"})
        data.update(services=self.services(), api_owned=self.api_owned)
        return data

    def sources(self, args):
        from source_manager import SourceManager
        return SourceManager(self).list_sources(args)

    def source_detail(self, source_id):
        from source_manager import SourceManager
        return SourceManager(self).detail(source_id)

    def create_source(self, body):
        from source_manager import SourceManager
        return SourceManager(self).create(body)

    def update_source(self, body):
        from source_manager import SourceManager
        return SourceManager(self).update(body)

    def delete_source(self, body):
        from source_manager import SourceManager
        return SourceManager(self).delete(body)

    def toggle(self, body):
        exact_keys(body, {"service_key", "enabled"}, {"service_key", "enabled"})
        key = identifier(body["service_key"], "Service key")
        if not isinstance(body["enabled"], bool):
            raise AppError("Enabled harus bernilai boolean.")
        with self.database(write=True) as cursor:
            cursor.execute("SELECT component_type FROM cti_component_registry WHERE service_key=%s FOR UPDATE", (key,))
            row = cursor.fetchone()
            if not row:
                raise AppError("Komponen tidak ditemukan.", 404)
            if row["component_type"] == "Data Artifact":
                raise AppError("Data Artifact tidak memiliki kontrol enabled.")
            cursor.execute("UPDATE cti_component_registry SET enabled=%s WHERE service_key=%s", (int(body["enabled"]), key))
        return {"service_key": key, "enabled": body["enabled"]}

    def mission(self, mission_id, view):
        mission_id = identifier(mission_id, "Mission ID")
        if view == "events":
            path = f"/api/cti/events/{mission_id}"
        elif view in {"status", "diagnostics", "lineage", "integrity"}:
            path = f"/api/cti/missions/{mission_id}" + ("" if view == "status" else "/" + view)
        else:
            raise AppError("Tampilan misi tidak dikenal.", 404)
        result = self.upstream("cti", path)
        if view == "status" and isinstance(result, dict) and isinstance(result.get("mission"), dict):
            result = result["mission"]
        if view == "status" and str(result.get("status", "")).upper() == "NOT_FOUND":
            raise AppError("Mission ID tidak ditemukan pada runtime CTI.", 404)
        return result

    def start_mission(self, body):
        exact_keys(body, {"mission_id", "scope_contract_id", "source_id"}, {"mission_id", "scope_contract_id", "source_id"})
        mission_id = identifier(body["mission_id"], "Mission ID")
        if len(mission_id) > 100:
            raise AppError("Mission ID dibatasi 100 karakter sesuai skema Vulndesk.")
        scope = identifier(body["scope_contract_id"], "Scope contract ID")
        source = body["source_id"]
        source = identifier(source, "Source ID")
        env = self.environment()
        if env.get("GOVERNANCE_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
            raise AppError("Aktifkan governance Vulndesk sebelum mengirim proposal akuisisi.", 409)
        descriptor = self.source_detail(source)
        if not descriptor["enabled"] or not descriptor["acquisition_supported"] or descriptor.get("endpoint_error"):
            raise AppError("Sumber harus terdaftar, aktif, dan memiliki endpoint serta adapter akuisisi yang valid.", 409)
        with self._lock:
            if mission_id in self._started_missions:
                raise AppError("Mission ID sudah pernah dikirim oleh Web App ini. Periksa monitor misi.", 409)
            try:
                self.mission(mission_id, "status")
            except AppError as error:
                if error.status != 404:
                    raise
            else:
                raise AppError("Mission ID sudah ada. Gunakan ID baru agar misi sebelumnya tetap utuh.", 409)
            self._started_missions.add(mission_id)
        payload = {"mission_id": mission_id, "scope_contract_id": scope, "source_app": "Vulndesk Web",
                   "assets": [], "auto_acquire_cti": True, "cti_source_set": [source], "cti_acquisition_max_actions": 1,
                   "policy_context": {"scope_contract_id": scope, "governance_authority": "aptsGSS"}}
        # No client decision, task authorization, arbitrary command, or target is accepted.
        result = self.upstream("cti", "/api/cti/missions/start", payload)
        if result.get("status") != "accepted":
            raise AppError("CTI tidak menerima misi. Periksa enabled orchestrator dan diagnostik runtime.", 409)
        return result

    def start_api(self):
        with self._lock:
            if self.api_owned:
                return {"message": "API yang dimiliki Web App sudah berjalan."}
            port = self.ports["cti"]
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    raise AppError("Port CTI sedang digunakan oleh proses lain. Web App tidak mengambil alih proses tersebut.", 409)
            launcher = self.root / "run" / "run_vulndesk_api.py"
            if not launcher.is_file():
                raise AppError("Launcher run/run_vulndesk_api.py tidak ditemukan di instalasi Vulndesk.", 404)
            python = self.config.get("vulndesk_python") or sys.executable
            if not Path(python).is_file():
                raise AppError("Interpreter Python Vulndesk tidak ditemukan. Periksa config.json.", 503)
            log_path = self.app_dir / "runtime-api.log"
            if self._child_log:
                self._child_log.close()
            self._child_log = log_path.open("ab")
            environment = dict(os.environ)
            environment["GOVERNANCE_ENABLED"] = "true"
            try:
                self._child = subprocess.Popen([python, str(launcher), "--host", "127.0.0.1", "--port", str(port)], cwd=str(self.root),
                    env=environment, stdout=self._child_log, stderr=subprocess.STDOUT, shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                self._child_log.close()
                self._child_log = None
                raise AppError("API tidak dapat dijalankan. Periksa interpreter dan dependensi instalasi Vulndesk.", 503)
            self._health_cache = (0, [])
        return {"message": "Proses API dimulai. Perbarui status untuk memeriksa kesiapan; kegagalan startup tercatat di runtime-api.log."}

    def stop_api(self):
        with self._lock:
            if not self.api_owned:
                raise AppError("Tidak ada proses API aktif yang dimiliki oleh Web App ini.", 409)
            child = self._child
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            self._child = None
            if self._child_log:
                self._child_log.close()
                self._child_log = None
            self._health_cache = (0, [])
        return {"message": "Proses API yang dimiliki Web App dihentikan."}

    def enrichment_list(self, args):
        page = bounded_int(args.get("page"), 1, 100000, 1)
        limit = bounded_int(args.get("limit"), 1, 100, 25)
        mission = str(args.get("mission_id", ""))[:192].strip()
        search = str(args.get("search", ""))[:200].strip()
        offset = (page - 1) * limit
        direction = 'ASC' if str(args.get('direction', '')).lower() == 'asc' else 'DESC'
        where, params = [], []
        if mission:
            where.append("e.mission_id = %s")
            params.append(mission)
        if search:
            where.append("(e.intake_id LIKE %s OR e.mission_id LIKE %s OR e.task_id LIKE %s OR JSON_UNQUOTE(JSON_EXTRACT(e.result_json, '$.target.target_value')) LIKE %s)")
            params.extend(["%" + search + "%"] * 4)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.database() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM cti_wpt_verified_evidence e{clause}", params)
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"SELECT e.intake_id, e.mission_id, e.task_id, e.recon_run_id, "
                f"e.input_sha256, e.evidence_manifest_sha256, e.result_json, e.created_at "
                f"FROM cti_wpt_verified_evidence e{clause} "
                f"ORDER BY e.created_at {direction}, e.intake_id {direction} LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cursor.fetchall()
        items = []
        for row in rows:
            record = dict(row)
            raw = record.pop("result_json", None)
            result = {}
            if raw:
                try:
                    result = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    pass
            result = result if isinstance(result, dict) else {}
            record["technology_count"] = result.get("technology_count", 0)
            record["cpe_candidate_count"] = len(result.get("cpe_candidates", []))
            record["classification"] = result.get("classification", "")
            record["target"] = result.get("target")
            record["technologies"] = result.get("technologies", [])
            record["enrichment_version"] = result.get("enrichment_version", 1)
            items.append(record)
        return {"items": items, "total": total, "page": page, "limit": limit}

    @staticmethod
    def _downstream_stage_status(cursor, mission_id, intake_id, manifest_sha256):
        """Read-only status of stages after CPE resolution, from their own tables.

        Correlation, ATT&CK and risk records are keyed by mission, not by intake,
        so they are reported as mission-level. PIP is checked for whether any
        revision actually references this evidence.
        """
        stages = ("vulnerability_correlation", "attack_mapping", "risk_prioritization", "pip_assembly")
        status, details = {}, {}
        try:
            for key, table in (("vulnerability_correlation", "cti_vulnerability_correlations"),
                               ("attack_mapping", "cti_attack_mappings"),
                               ("risk_prioritization", "cti_priority_portfolios")):
                cursor.execute("SELECT COUNT(*) AS n FROM " + table + " WHERE mission_id = %s", (mission_id,))
                count = int((cursor.fetchone() or {}).get("n") or 0)
                status[key] = "RECORDED_FOR_MISSION" if count else "NOT_RECORDED"
                details[key] = {"mission_record_count": count}
            cursor.execute(
                "SELECT revision_no, readiness, created_at, "
                "LOCATE(%s, artifact_json) > 0 AS has_intake, LOCATE(%s, artifact_json) > 0 AS has_manifest "
                "FROM cti_pip_artifacts WHERE mission_id = %s ORDER BY revision_no DESC",
                (intake_id, manifest_sha256 or "\0", mission_id),
            )
            revisions = list(cursor.fetchall() or [])
            if not revisions:
                status["pip_assembly"] = "NOT_RECORDED"
                details["pip_assembly"] = {"revision_count": 0}
            else:
                latest = revisions[0]
                covering = [r for r in revisions if r.get("has_intake") or r.get("has_manifest")]
                status["pip_assembly"] = "ASSEMBLED_WITH_EVIDENCE" if covering else "ASSEMBLED_WITHOUT_EVIDENCE"
                created = latest.get("created_at")
                details["pip_assembly"] = {
                    "revision_count": len(revisions), "latest_revision": latest.get("revision_no"),
                    "latest_readiness": latest.get("readiness"),
                    "latest_created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                    "latest_includes_evidence": bool(latest.get("has_intake") or latest.get("has_manifest")),
                    "revisions_including_evidence": [r.get("revision_no") for r in covering]}
        except Exception:
            # Never present a stale hardcoded NOT_RUN as fact when the lookup failed.
            return {key: "UNKNOWN" for key in stages}, {}
        return status, details

    def _wpt_pipeline_status(self, cursor, intake_id, manifest_sha256):
        try:
            cursor.execute('SELECT * FROM cti_wpt_pipeline_jobs WHERE intake_id=%s', (intake_id,))
            job = cursor.fetchone()
        except Exception as error:
            if error.args and error.args[0] == 1146:
                return None
            raise
        if not job:
            return None
        state = job['status']
        stages = ('vulnerability_correlation','attack_mapping','risk_prioritization','pip_assembly')
        status = {stage: 'QUEUED' if state=='PENDING' else state for stage in stages}
        details = {}
        summary = json.loads(job.get('summary_json') or '{}') or {}
        child = job.get('pipeline_mission_id')
        if child:
            recorded, details = self._downstream_stage_status(cursor,child,intake_id,manifest_sha256)
            if state=='COMPLETED':
                status.update(json.loads(job.get('stage_status_json') or '{}'))
                status['pip_assembly'] = recorded['pip_assembly']
            elif state in {'RUNNING','FAILED'}:
                cursor.execute('SELECT assigned_component,status FROM cti_task_contracts WHERE mission_id=%s', (child,))
                components = {r['assigned_component']:r['status'] for r in cursor.fetchall()}
                for stage, component in [('vulnerability_correlation','vulnerability_correlation_service'),
                                          ('attack_mapping','attack_mapping_service'),('risk_prioritization','risk_prioritization_agent'),
                                          ('pip_assembly','pip_assembly_validation_service')]:
                    status[stage] = components.get(component,'QUEUED')
            for stage, key in [('vulnerability_correlation','vulnerability_correlations'),('attack_mapping','attack_mappings'),('risk_prioritization','risk_priorities')]:
                info = details.setdefault(stage,{})
                info['intake_record_count'] = info.pop('mission_record_count',0)
                if key in summary:
                    info['intake_record_count'] = summary[key]
        public = {k:job.get(k) for k in ('status','pipeline_mission_id','attempt_count')}
        public['summary'] = summary
        return status, details, public

    def enrichment_detail(self, intake_id):
        if not isinstance(intake_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:@-]{0,191}', intake_id):
            raise AppError('Intake ID tidak valid.')
        with self.database() as cursor:
            cursor.execute(
                "SELECT intake_id, mission_id, task_id, recon_run_id, "
                "input_sha256, evidence_manifest_sha256, result_json, created_at "
                "FROM cti_wpt_verified_evidence WHERE intake_id = %s",
                (intake_id,),
            )
            row = cursor.fetchone()
            record = dict(row) if row else {}
            raw = record.pop("result_json", None)
            result = {}
            if raw:
                try:
                    result = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    pass
            result = result if isinstance(result, dict) else {}
            downstream = None
            pipeline_job = None
            if row and result.get("pipeline_status"):
                # The stored value is a snapshot written at intake time; downstream
                # stages run later, so derive their status from their own tables
                # (must happen while the cursor/connection is still open).
                pipeline_job = self._wpt_pipeline_status(cursor, record.get('intake_id'), record.get('evidence_manifest_sha256'))
                downstream = pipeline_job[:2] if pipeline_job else self._downstream_stage_status(cursor, record.get("mission_id"), record.get("intake_id"),
                                                           record.get("evidence_manifest_sha256"))
        if not row:
            raise AppError("Evidence tidak ditemukan.", 404)
        record["result"] = result
        record["technology_count"] = result.get("technology_count", 0)
        record["cpe_candidate_count"] = len(result.get("cpe_candidates", []))
        record["classification"] = result.get("classification", "")
        record["target"] = result.get("target")
        record["enrichment_version"] = result.get("enrichment_version", 1)
        record["pipeline_status"] = result.get("pipeline_status", {})
        record["pipeline_details"] = {}
        record["pipeline"] = pipeline_job[2] if pipeline_job else None
        if downstream:
            record["pipeline_status"] = {**record["pipeline_status"], **downstream[0]}
            record["pipeline_details"] = downstream[1]
        record["evidence_status"] = result.get("evidence_status", 'UNKNOWN')
        record["technologies"] = result.get("technologies", [])
        record["technology_resolution"] = result.get("technology_resolution", [])
        record["cpe_candidates"] = result.get("cpe_candidates", [])
        record["target_io_performed_by_cti"] = result.get("target_io_performed_by_cti", False)
        record["verified_vulnerability_count"] = result.get("verified_vulnerability_count", 0)
        return record

    def close(self):
        if self.api_owned:
            self.stop_api()
        elif self._child_log:
            self._child_log.close()

    def upload_root(self):
        custom = self.environment().get("DATASET_UPLOAD_DIR", "").strip()
        if custom:
            path = Path(custom)
            return (path if path.is_absolute() else self.root / path).resolve()
        return (self.root / "data" / "uploads").resolve()

    def import_dataset(self, body):
        exact_keys(body, {"dataset_type", "file_name", "content_base64"}, {"dataset_type", "file_name", "content_base64"})
        kind = body["dataset_type"]
        if not isinstance(kind, str) or kind not in {"tweet_topics", "topics_master"}:
            raise AppError("Jenis dataset tidak valid.")
        if not isinstance(body["file_name"], str) or not body["file_name"].lower().endswith(".csv"):
            raise AppError("File harus berformat CSV.")
        try:
            raw = base64.b64decode(body["content_base64"], validate=True)
            if len(raw) > 5 * 1024 * 1024:
                raise AppError("Ukuran maksimum CSV adalah 5 MB.", 413)
            text = raw.decode("utf-8-sig")
        except (ValueError, TypeError, UnicodeError):
            raise AppError("CSV harus menggunakan UTF-8 dan data base64 yang valid.")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        normalized = {re.sub(r"[^a-z0-9]", "", h.lower()): h for h in reader.fieldnames or []}
        topic = next((normalized[k] for k in ("topic", "topics") if k in normalized), None)
        tweet = next((normalized[k] for k in ("tweet", "tweets", "text") if k in normalized), None)
        if not topic or (kind == "tweet_topics" and not tweet):
            raise AppError("Kolom CSV diperlukan: Tweet dan Topic; topics master hanya memerlukan Topic.")
        rows = []
        try:
            for item in reader:
                topic_text = (item.get(topic) or "").strip()
                tweet_text = (item.get(tweet) or "").strip() if tweet else ""
                if kind == "tweet_topics" and (tweet_text or topic_text):
                    rows.append((tweet_text, topic_text or None))
                elif kind == "topics_master" and topic_text:
                    rows.append((topic_text,))
                if len(rows) > 100000:
                    raise AppError("CSV dibatasi maksimum 100.000 baris.", 413)
        except csv.Error:
            raise AppError("Struktur CSV tidak valid.")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(body["file_name"].replace("\\", "/")).name)[:100] or "dataset.csv"
        target = self.upload_root() / kind / (datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8] + "_" + name)
        try:
            with self.database(write=True) as cursor:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                cursor.execute("INSERT INTO dataset_uploads (dataset_type,file_name,stored_file_path,file_size_bytes,row_count,uploaded_at) VALUES (%s,%s,%s,%s,%s,UTC_TIMESTAMP())", (kind, name, str(target), len(raw), len(rows)))
                upload_id = cursor.lastrowid
                table, columns = ("tweet_topic_records", "tweet_text,topic_text") if kind == "tweet_topics" else ("topic_master_records", "topic_text")
                placeholders = "%s,%s,%s" if kind == "tweet_topics" else "%s,%s"
                sql = f"INSERT INTO {table} (upload_id,{columns}) VALUES ({placeholders})"
                for index in range(0, len(rows), 1000):
                    cursor.executemany(sql, [(upload_id,) + r for r in rows[index:index+1000]])
            return {"upload_id": upload_id, "row_count": len(rows), "file_name": name, "dataset_type": kind}
        except Exception:
            if target.is_file():
                target.unlink()
            raise

    def delete_dataset(self, body):
        exact_keys(body, {"dataset_type", "upload_date", "confirm"}, {"dataset_type", "upload_date", "confirm"})
        kind, day = body["dataset_type"], body["upload_date"]
        if not isinstance(kind, str) or kind not in {"tweet_topics", "topics_master"} or body["confirm"] is not True:
            raise AppError("Jenis dataset atau konfirmasi penghapusan tidak valid.")
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except (ValueError, TypeError):
            raise AppError("Tanggal unggahan harus berformat YYYY-MM-DD.")
        upload_root = (self.upload_root() / kind).resolve()
        with self.database(write=True) as cursor:
            cursor.execute("SELECT id,stored_file_path,row_count FROM dataset_uploads WHERE dataset_type=%s AND DATE(uploaded_at)=%s FOR UPDATE", (kind, day))
            uploads = cursor.fetchall()
            paths = []
            for upload in uploads:
                if upload["stored_file_path"]:
                    path = Path(upload["stored_file_path"]).resolve()
                    if not path.is_relative_to(upload_root):
                        raise AppError("Lokasi file dataset berada di luar folder unggahan. Periksa dataset sebelum menghapus.", 409)
                    paths.append(path)
                table = "tweet_topic_records" if kind == "tweet_topics" else "topic_master_records"
                cursor.execute(f"DELETE FROM {table} WHERE upload_id=%s", (upload["id"],))
                cursor.execute("DELETE FROM dataset_uploads WHERE id=%s", (upload["id"],))
        failed = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed += 1
        return {"deleted_uploads": len(uploads), "deleted_rows": sum(u["row_count"] or 0 for u in uploads), "failed_file_deletions": failed}
