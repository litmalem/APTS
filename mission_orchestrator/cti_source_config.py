"""Shared, dependency-free configuration for external CTI source adapters."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit


ADAPTERS = {
    "nvd-cve": {"label": "NVD CVE 2.0", "protocol": "REST_JSON", "endpoint_env": "NVD_API_URL",
                "default_endpoint": "https://services.nvd.nist.gov/rest/json/cves/2.0",
                "strategy": "LAST_MODIFIED_WINDOW", "role": "vulnerability_source"},
    "nvd-cpe": {"label": "NVD CPE 2.0", "protocol": "REST_JSON", "endpoint_env": "NVD_CPE_API_URL",
                "default_endpoint": "https://services.nvd.nist.gov/rest/json/cpes/2.0",
                "strategy": "LAST_MODIFIED_WINDOW", "role": "cpe_dictionary"},
    "mitre-attack": {"label": "MITRE ATT&CK / TAXII 2.1", "protocol": "TAXII_2_1",
                     "endpoint_env": "MITRE_ATTACK_API_ROOT",
                     "default_endpoint": "https://attack-taxii.mitre.org/api/v21",
                     "strategy": "ADDED_AFTER", "role": "attack_ontology"},
    "mitre-cwe": {"label": "MITRE CWE REST", "protocol": "REST_JSON", "endpoint_env": "CWE_API_ROOT",
                  "default_endpoint": "https://cwe-api.mitre.org/api/v1",
                  "strategy": "SINGLE_CWE_REFRESH", "role": "weakness_source"},
    "registry-only": {"label": "Registry saja — adapter belum tersedia", "protocol": "REST_JSON",
                      "strategy": "MANUAL", "role": "external_source"},
}
LEGACY_ENDPOINTS = {"config:NVD_CVE_API": "nvd-cve", "config:NVD_CPE_API": "nvd-cpe",
                    "config:MITRE_ATTACK_SOURCE": "mitre-attack", "config:CWE_API": "mitre-cwe"}
LEGACY_ADAPTERS = {"SyncService.run_incremental_sync": "nvd-cve",
                   "CpeDictionarySyncService.sync_first_pages": "nvd-cpe",
                   "MitreAttackSyncService.run_incremental_sync": "mitre-attack"}
DEFAULT_COLLECTION = "x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019"


def parse_config(value):
    if value in (None, ""):
        return {}
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("config_json sumber harus berupa objek JSON.")
    return parsed


def adapter_type(source_id, config):
    explicit = config.get("adapter_type")
    if explicit is not None:
        return explicit if isinstance(explicit, str) and explicit in ADAPTERS else "registry-only"
    legacy = config.get("sync_adapter")
    return source_id if source_id in ADAPTERS else LEGACY_ADAPTERS.get(legacy, "registry-only") if isinstance(legacy, str) else "registry-only"


def validate_endpoint(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 500:
        raise ValueError("Endpoint harus berupa URL HTTPS, maksimum 500 karakter.")
    if re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise ValueError("Endpoint tidak boleh mengandung spasi atau karakter kontrol.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError:
        raise ValueError("URL endpoint tidak valid.") from None
    if parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None:
        raise ValueError("Gunakan URL HTTPS tanpa username atau password.")
    if parsed.query or parsed.fragment:
        raise ValueError("Gunakan URL dasar tanpa query, fragment, atau API key. Atur parameter pada form.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Port endpoint tidak valid.")
    if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
        raise ValueError("Gunakan hostname publik untuk API eksternal.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or any(not part or part.startswith("-") or part.endswith("-") for part in host.split(".")):
            raise ValueError("Hostname endpoint tidak valid.")
    else:
        if not address.is_global:
            raise ValueError("Alamat API eksternal harus merupakan alamat publik.")
    return value.rstrip("/")


def resolve_endpoint(endpoint_ref, kind, environment):
    if endpoint_ref in LEGACY_ENDPOINTS:
        definition = ADAPTERS[LEGACY_ENDPOINTS[endpoint_ref]]
        endpoint_ref = environment.get(definition["endpoint_env"]) or definition["default_endpoint"]
    elif isinstance(endpoint_ref, str) and endpoint_ref.startswith("config:"):
        # Only documented endpoint variables may be resolved, never arbitrary secrets.
        variable = endpoint_ref[7:]
        definition = next((v for v in ADAPTERS.values() if v.get("endpoint_env") == variable), None)
        if definition is None:
            raise ValueError("Referensi endpoint belum didukung; simpan URL HTTPS pada form sumber.")
        endpoint_ref = environment.get(variable) or definition["default_endpoint"]
    return validate_endpoint(endpoint_ref)


def normalize_credential(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("Referensi kredensial harus berupa nama variabel environment.")
    variable = re.sub(r"^(?:env:|secret-ref:)", "", value.strip())
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}(?:API_KEY|TOKEN)", variable):
        raise ValueError("Gunakan nama environment yang berakhiran API_KEY atau TOKEN, misalnya NVD_API_KEY.")
    return "env:" + variable


def source_binding(row):
    """Bind proposals to registry configuration without including credential values."""
    record = {k: row.get(k) for k in ("source_id", "protocol", "endpoint_ref", "credential_ref")}
    record["config"] = parse_config(row.get("config_json"))
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def apply_client_settings(client, descriptor, environment):
    config = parse_config(descriptor.get("config_json"))
    kind = adapter_type(descriptor["source_id"], config)
    client.base_url = resolve_endpoint(descriptor.get("endpoint_ref"), kind, environment)
    timeout = config.get("timeout_seconds")
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ValueError("Timeout sumber harus berada antara 1 dan 300 detik.")
        if hasattr(client, "timeout_seconds"):
            client.timeout_seconds = timeout
        else:
            client.timeout = timeout
    reference = normalize_credential(descriptor.get("credential_ref"))
    credential = environment.get(reference[4:], "") if reference else ""
    auth = config.get("auth_mode", "api-key" if kind in {"nvd-cve", "nvd-cpe"} else "bearer")
    if auth not in {"none", "api-key", "bearer"}:
        raise ValueError("Mode autentikasi sumber tidak didukung.")
    credential = credential if auth != "none" else ""
    if hasattr(client, "api_key"):
        client.api_key = credential if auth == "api-key" else ""
        if not client.api_key and hasattr(client, "request_delay_seconds"):
            client.request_delay_seconds = max(client.request_delay_seconds, 6.0)
    session = getattr(client, "session", None)
    if session is not None:
        session.headers.pop("apiKey", None)
        session.headers.pop("Authorization", None)
        if credential:
            session.headers["apiKey" if auth == "api-key" else "Authorization"] = credential if auth == "api-key" else "Bearer " + credential
    elif auth == "bearer" and credential:
        raise ValueError("Adapter ini menggunakan autentikasi apiKey, bukan Bearer.")
    if kind == "mitre-attack" and config.get("collection_id"):
        collection = config["collection_id"]
        if not isinstance(collection, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", collection):
            raise ValueError("Collection ID TAXII tidak valid.")
        client.collection_id = collection


def builtin_templates(environment):
    names = {"nvd-cve": "NVD — Kerentanan CVE", "nvd-cpe": "NVD — Kamus produk CPE",
             "mitre-attack": "MITRE ATT&CK", "mitre-cwe": "MITRE — Katalog CWE"}
    result = []
    for kind, name in names.items():
        definition = ADAPTERS[kind]
        endpoint = environment.get(definition["endpoint_env"]) or definition["default_endpoint"]
        try:
            endpoint = validate_endpoint(endpoint)
        except ValueError:
            endpoint = definition["default_endpoint"]
        result.append({"source_id": kind, "display_name": name, "adapter_type": kind,
                       "endpoint_ref": endpoint, "endpoint_env": definition["endpoint_env"],
                       "credential_ref": "env:NVD_API_KEY" if kind.startswith("nvd-") else None,
                       "auth_mode": "api-key" if kind.startswith("nvd-") else "none",
                       "collection_id": environment.get("MITRE_ENTERPRISE_COLLECTION_ID") or DEFAULT_COLLECTION,
                       "cwe_id": "CWE-20", "freshness_sla_seconds": 604800 if kind == "mitre-attack" else 86400,
                       "criticality": 0.9, "trust_tier": "AUTHORITATIVE_PUBLIC", "enabled": True})
    return result
