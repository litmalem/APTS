"""Versioned CTID/CAPEC imports. Parse fully before an atomic, source-owned refresh."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import xml.etree.ElementTree as ET

CTID_URL = 'https://raw.githubusercontent.com/center-for-threat-informed-defense/mappings-explorer/main/mappings/kev/attack-16.1/kev-07.28.2025/enterprise/kev-07.28.2025_attack-16.1-enterprise.json'
CAPEC_URL = 'https://capec.mitre.org/data/xml/capec_latest.xml'
SOURCES = {'ctid-cve-attack': CTID_URL, 'mitre-capec': CAPEC_URL}
TABLES = ('vuln_attack_mappings', 'capec_cwe_mappings', 'capec_attack_mappings')
PROVENANCE = {
    'source_dataset': 'varchar(120)', 'source_version': 'varchar(160)',
    'source_url': 'varchar(1000)', 'source_sha256': 'char(64)',
    'relationship_type': 'varchar(80)', 'references_json': 'longtext',
    'record_key': 'char(64)', 'publisher_status': 'varchar(40)',
}
MAX_BYTES = 16 * 1024 * 1024
PATTERN_FIELDS = ('capec_id', 'name', 'abstraction', 'status', 'description',
                  'likelihood', 'severity', 'prerequisites', 'mitigations')


def validate_source_url(kind, url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.query or p.fragment or p.port not in (None, 443):
        raise ValueError('Sumber mapping harus URL HTTPS resmi tanpa kredensial/query.')
    if kind == 'ctid-cve-attack':
        valid = p.hostname == 'raw.githubusercontent.com' and p.path.startswith('/center-for-threat-informed-defense/mappings-explorer/') and p.path.endswith('.json')
    elif kind == 'mitre-capec':
        valid = p.hostname == 'capec.mitre.org' and p.path.startswith('/data/xml/') and p.path.endswith('.xml')
    else:
        raise ValueError('Adapter mapping tidak dikenal.')
    if not valid:
        raise ValueError('Gunakan dataset resmi CTID mappings-explorer atau XML resmi CAPEC.')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Redirect sumber mapping ditolak; simpan URL resmi tujuan.')


def download(kind, url, timeout=90):
    validate_source_url(kind, url)
    with build_opener(ProxyHandler({}), NoRedirect()).open(
            Request(url, headers={'User-Agent': 'APTS-CTI-Mapping/1.0'}), timeout=timeout) as response:
        data = response.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Dataset mapping kosong atau melebihi batas 16 MB.')
    return data


def _key(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _xml_text(element):
    """Preserve text inside CAPEC's nested XHTML paragraphs without storing markup."""
    if element is None:
        return None
    parts = []
    def visit(node):
        block = node.tag.rsplit('}', 1)[-1] in {'p', 'div', 'li', 'br'}
        if block:
            parts.append(' ')
        parts.append(node.text or '')
        for child in node:
            visit(child)
            parts.append(child.tail or '')
        if block:
            parts.append(' ')
    visit(element)
    return ' '.join(''.join(parts).split()) or None


def _xml_items(pattern, path):
    values = [_xml_text(element) for element in pattern.findall(path)]
    return '\n\n'.join(value for value in values if value) or None


def parse_dataset(kind, data, url):
    validate_source_url(kind, url)
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Ukuran dataset mapping tidak valid.')
    digest = hashlib.sha256(data).hexdigest()
    rows = {table: {} for table in TABLES}
    if kind == 'ctid-cve-attack':
        obj = json.loads(data)
        meta = obj['metadata']
        if meta.get('technology_domain') != 'enterprise' or meta.get('mapping_framework') not in {'kev', 'cve'}:
            raise ValueError('Dataset harus pemetaan CVE/KEV untuk ATT&CK Enterprise.')
        version = f"{meta['mapping_framework']}:{meta['mapping_framework_version']};ATT&CK:{meta['attack_version']}"
        for item in obj['mapping_objects']:
            if item.get('status') != 'complete':
                continue
            cve, attack, relationship = item.get('capability_id', ''), item.get('attack_object_id', ''), item.get('mapping_type')
            if not re.fullmatch(r'CVE-\d{4}-\d{4,}', cve) or not re.fullmatch(r'T\d{4}(?:\.\d{3})?', attack):
                raise ValueError('Identitas CVE/ATT&CK tidak valid dalam dataset CTID.')
            if relationship not in {'exploitation_technique', 'primary_impact', 'secondary_impact', 'uncategorized'}:
                raise ValueError('Jenis hubungan CTID belum didukung.')
            key = _key(cve, attack, relationship)
            rows['vuln_attack_mappings'][key] = {
                'cve_id': cve, 'attack_id': attack, 'attack_name': item.get('attack_object_name'),
                'mapping_level': 'cve_to_attack', 'mapping_source': 'analyst',
                # Local ranking policy; the publisher supplies no numeric confidence.
                'confidence': 0.75, 'rationale': item.get('comments') or item.get('capability_description'),
                'relationship_type': relationship, 'references_json': json.dumps(item.get('references') or []),
                'publisher_status': item['status'],
            }
    elif kind == 'mitre-capec':
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValueError('DTD/entity XML tidak didukung.')
        root = ET.fromstring(data)
        if root.tag != '{http://capec.mitre.org/capec-3}Attack_Pattern_Catalog':
            raise ValueError('Bukan katalog CAPEC XML resmi.')
        version = 'CAPEC:' + root.attrib['Version']
        rows['capec_patterns'] = {}
        for pattern in root.findall('./{*}Attack_Patterns/{*}Attack_Pattern'):
            if pattern.get('Status') in {'Deprecated', 'Obsolete'}:
                continue
            number = pattern.get('ID', '')
            if not number.isdigit():
                raise ValueError('CAPEC ID tidak valid.')
            capec = 'CAPEC-' + str(int(number))
            name = (pattern.get('Name') or '').strip()
            if not name or len(name) > 255:
                raise ValueError('Nama pola CAPEC kosong atau melebihi batas katalog.')
            rows['capec_patterns'][capec] = {
                'capec_id': capec, 'name': name, 'abstraction': pattern.get('Abstraction'),
                'status': pattern.get('Status'), 'description': _xml_text(pattern.find('{*}Description')),
                'likelihood': _xml_text(pattern.find('{*}Likelihood_Of_Attack')),
                'severity': _xml_text(pattern.find('{*}Typical_Severity')),
                'prerequisites': _xml_items(pattern, './{*}Prerequisites/{*}Prerequisite'),
                'mitigations': _xml_items(pattern, './{*}Mitigations/{*}Mitigation'),
            }
            for weakness in pattern.findall('./{*}Related_Weaknesses/{*}Related_Weakness'):
                number = weakness.get('CWE_ID', '')
                if not number.isdigit():
                    raise ValueError('CWE ID CAPEC tidak valid.')
                cwe = 'CWE-' + str(int(number))
                rows['capec_cwe_mappings'][_key(capec, cwe)] = {
                    'capec_id': capec, 'cwe_id': cwe, 'mapping_type': 'Related_Weakness',
                    'relationship_type': 'related_weakness', 'publisher_status': pattern.get('Status'),
                }
            for mapping in pattern.findall('./{*}Taxonomy_Mappings/{*}Taxonomy_Mapping'):
                if mapping.get('Taxonomy_Name') != 'ATTACK':
                    continue
                attack = (mapping.findtext('{*}Entry_ID') or '').strip()
                attack = attack if attack.startswith('T') else 'T' + attack
                if not re.fullmatch(r'T\d{4}(?:\.\d{3})?', attack):
                    raise ValueError('ATT&CK ID CAPEC tidak valid.')
                rows['capec_attack_mappings'][_key(capec, attack)] = {
                    'capec_id': capec, 'attack_id': attack,
                    'attack_name': mapping.findtext('{*}Entry_Name'), 'confidence': 0.60,
                    'rationale': f"{capec}: {pattern.get('Name')} — CAPEC Taxonomy_Mapping ATTACK; contextual association.",
                    'relationship_type': 'taxonomy_mapping', 'publisher_status': pattern.get('Status'),
                    'references_json': json.dumps(['https://capec.mitre.org/data/definitions/' + pattern.get('ID') + '.html']),
                }
    if not rows['vuln_attack_mappings'] and not rows.get('capec_patterns'):
        raise ValueError('Dataset tidak memiliki relasi yang didukung; data lama dipertahankan.')
    for table in TABLES:
        for key, row in rows[table].items():
            row.update(source_dataset=kind, source_version=version, source_url=url,
                       source_sha256=digest, record_key=key, is_active=1)
    return {'source_id': kind, 'version': version, 'sha256': digest, 'url': url,
            'counts': {t: len(r) for t, r in rows.items()}, 'rows': rows}


def migrate(cursor):
    """Additive, repeatable MariaDB migration. DDL is explicit, separate from sync."""
    cursor.execute('''CREATE TABLE IF NOT EXISTS cti_mapping_datasets (
        source_id varchar(120) PRIMARY KEY, source_version varchar(160), source_url varchar(1000),
        source_sha256 char(64), counts_json longtext, imported_at datetime DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS cti_mapping_imports (
        source_id varchar(120) NOT NULL, source_sha256 char(64) NOT NULL,
        source_version varchar(160), source_url varchar(1000), counts_json longtext,
        imported_at datetime DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(source_id,source_sha256)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS capec_patterns (
        id bigint unsigned NOT NULL AUTO_INCREMENT PRIMARY KEY, capec_id varchar(40) NOT NULL,
        name varchar(255) NOT NULL, abstraction varchar(80), status varchar(80),
        description mediumtext, likelihood varchar(80), severity varchar(80),
        prerequisites mediumtext, mitigations mediumtext,
        created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_capec_id (capec_id), KEY idx_capec_name (name), KEY idx_capec_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    for table in TABLES:
        # Use native idempotent DDL, avoiding SHOW COLUMNS / I_S metadata scans
        # (the deployed XAMPP 10.4.32 crashes in get_column_grant on those scans).
        additions = [f'ADD COLUMN IF NOT EXISTS {name} {definition} DEFAULT NULL'
                     for name, definition in PROVENANCE.items()]
        additions.append('ADD COLUMN IF NOT EXISTS is_active tinyint(1) NOT NULL DEFAULT 1')
        additions.append('ADD UNIQUE KEY IF NOT EXISTS uq_mapping_source_record (source_dataset,record_key)')
        cursor.execute(f'ALTER TABLE {table} ' + ','.join(additions))



def _upsert_capec_patterns(cursor, records):
    if not records:
        return 0
    fields = ','.join(PATTERN_FIELDS)
    cursor.execute('SELECT ' + fields + ' FROM capec_patterns')
    existing = {row['capec_id']: row for row in cursor.fetchall()}
    changed = 0
    for capec_id, row in records.items():
        if existing.get(capec_id) == row:
            continue
        cursor.execute('INSERT INTO capec_patterns (' + fields + ') VALUES (' +
                       ','.join(['%s'] * len(PATTERN_FIELDS)) + ') ON DUPLICATE KEY UPDATE ' +
                       ','.join(f'{field}=VALUES({field})' for field in PATTERN_FIELDS if field != 'capec_id'),
                       tuple(row[field] for field in PATTERN_FIELDS))
        changed += 1
    return changed


def import_dataset(cursor, dataset):
    """Caller owns one write transaction; lock dataset to serialize refreshes."""
    source = dataset['source_id']
    cursor.execute('INSERT INTO cti_mapping_datasets (source_id) VALUES (%s) ON DUPLICATE KEY UPDATE source_id=VALUES(source_id)', (source,))
    cursor.execute('SELECT source_sha256 FROM cti_mapping_datasets WHERE source_id=%s FOR UPDATE', (source,))
    same_source = (cursor.fetchone() or {}).get('source_sha256') == dataset['sha256']
    # Repair catalogs produced by older importers even when the XML hash is unchanged.
    patterns_updated = _upsert_capec_patterns(cursor, dataset['rows'].get('capec_patterns', {}))
    if same_source and not patterns_updated:
        return {**{k: v for k, v in dataset.items() if k != 'rows'}, 'status': 'SUCCESS', 'unchanged': True}
    skipped = 0
    for table, records in ({} if same_source else dataset['rows']).items():
        if table == 'capec_patterns':
            continue
        if not records:
            continue
        cursor.execute(f'UPDATE {table} SET is_active=0 WHERE source_dataset=%s', (source,))
        for row in records.values():
            if table == 'capec_cwe_mappings':
                # The pre-existing schema has a unique (capec_id,cwe_id). Preserve
                # analyst-owned rows instead of taking ownership on collision.
                cursor.execute('SELECT source_dataset FROM capec_cwe_mappings WHERE capec_id=%s AND cwe_id=%s',
                               (row['capec_id'], row['cwe_id']))
                existing = cursor.fetchone()
                if existing and existing.get('source_dataset') != source:
                    skipped += 1
                    continue
            keys = list(row)
            sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join(['%s'] * len(keys))}) ON DUPLICATE KEY UPDATE "
            sql += ','.join(f'{key}=VALUES({key})' for key in keys if key not in {'record_key', 'source_dataset'})
            cursor.execute(sql, tuple(row[key] for key in keys))
    cursor.execute('UPDATE cti_mapping_datasets SET source_version=%s,source_url=%s,source_sha256=%s,counts_json=%s,imported_at=CURRENT_TIMESTAMP WHERE source_id=%s',
                   (dataset['version'], dataset['url'], dataset['sha256'], json.dumps(dataset['counts']), source))
    cursor.execute('INSERT INTO cti_mapping_imports (source_id,source_sha256,source_version,source_url,counts_json) VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE counts_json=VALUES(counts_json)',
                   (source,dataset['sha256'],dataset['version'],dataset['url'],json.dumps(dataset['counts'])))
    return {**{k: v for k, v in dataset.items() if k != 'rows'}, 'status': 'SUCCESS', 'unchanged': False,
            'preserved_manual_rows': skipped, 'patterns_updated': patterns_updated}


def sync(kind, url, transaction, timeout=90, data=None):
    dataset = parse_dataset(kind, download(kind, url, timeout) if data is None else data, url)
    with transaction() as cursor:
        return import_dataset(cursor, dataset)
