"""CRUD over Vulndesk's existing CTI source registry; no schema or credential writes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from backend import AppError, bounded_int, exact_keys, json_default


REGISTRY_FIELDS = ("id", "source_id", "protocol", "endpoint_ref", "credential_ref", "incremental_strategy",
                   "freshness_sla_seconds", "criticality", "rate_limit_per_window", "rate_window_seconds",
                   "max_payload_bytes", "trust_tier", "config_json", "enabled", "created_at", "updated_at")
CONFIG_FIELDS = ("display_name", "description", "adapter_type", "timeout_seconds", "max_pages", "page_size",
                 "collection_id", "sync_mode", "keyword", "match_string", "cwe_id", "cwe_range_start", "cwe_range_end", "auth_mode",
                 "adaptive_monitor_enabled", "auto_update", "auto_scope_contract_id",
                 "adaptive_min_interval_seconds", "adaptive_max_interval_seconds")
WRITE_FIELDS = {"source_id", "endpoint_ref", "credential_ref", "enabled", "freshness_sla_seconds", "criticality",
                "trust_tier", "protocol", *CONFIG_FIELDS}


def revision(row):
    data = {key: row.get(key) for key in REGISTRY_FIELDS}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=json_default, ensure_ascii=False).encode()).hexdigest()


class SourceManager:
    def __init__(self, adapter):
        self.adapter = adapter
        module_path = adapter.root / "cti_source_config.py"
        if not module_path.is_file():
            module_path = Path(__file__).resolve().parents[1] / "cti_source_config.py"
        if not module_path.is_file():
            raise AppError("Paket pengelolaan API belum lengkap. Pasang cti_source_config.py di direktori Vulndesk.", 503)
        spec = importlib.util.spec_from_file_location("vulndesk_source_rules", module_path)
        self.rules = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.rules)

    @staticmethod
    def source_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value):
            raise AppError("Source ID harus 1–120 karakter berupa huruf, angka, titik, garis bawah, tanda minus, atau titik dua.")
        return value

    @staticmethod
    def text(value, label, maximum, required=False):
        if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()) or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
            raise AppError(f"{label} tidak valid; maksimum {maximum} karakter.")
        return value.strip()

    @staticmethod
    def integer(value, label, low, high):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise AppError(f"{label} harus bilangan bulat antara {low} dan {high}.")
        return value

    def public(self, row, environment=None):
        environment = self.adapter.environment() if environment is None else environment
        try:
            config = self.rules.parse_config(row.get("config_json"))
        except (ValueError, TypeError):
            config = {}
        kind = self.rules.adapter_type(row["source_id"], config)
        item = {k: row.get(k) for k in REGISTRY_FIELDS if k != "config_json"}
        # Return only typed, credential-free fields. Unknown config and observation JSON stay on the server.
        for key in CONFIG_FIELDS:
            value = config.get(key)
            if key in {"timeout_seconds", "max_pages", "page_size", "adaptive_min_interval_seconds", "adaptive_max_interval_seconds"}:
                item[key] = value if isinstance(value, int) and not isinstance(value, bool) else None
            elif key in {"adaptive_monitor_enabled", "auto_update"}:
                item[key] = value if isinstance(value, bool) else None
            elif key != "adapter_type":
                item[key] = value if isinstance(value, str) else None
        item.update(adapter_type=kind, adapter_label=self.rules.ADAPTERS[kind]["label"],
                    acquisition_supported=kind != "registry-only", enabled=bool(row.get("enabled")), revision=revision(row))
        item["display_name"] = item.get("display_name") or row["source_id"]
        try:
            item["endpoint_url"] = self.rules.resolve_endpoint(row.get("endpoint_ref"), kind, environment)
            item["endpoint_error"] = None
        except (ValueError, TypeError):
            item["endpoint_url"] = None
            item["endpoint_error"] = "Endpoint belum valid; buka Ubah untuk menyimpan URL HTTPS."
            item["endpoint_ref"] = "[endpoint perlu diperbaiki]"
        try:
            reference = self.rules.normalize_credential(row.get("credential_ref"))
        except (ValueError, TypeError):
            reference = None
        item["credential_ref"] = reference
        item["credential_configured"] = bool(reference and environment.get(reference[4:]))
        item["auth_mode"] = item.get("auth_mode") or ("api-key" if kind.startswith("nvd-") else "bearer" if reference else "none")
        item["timeout_seconds"] = item.get("timeout_seconds") or 90
        item["max_pages"] = item.get("max_pages") or 1
        item["page_size"] = item.get("page_size") or 500
        item["sync_mode"] = item.get("sync_mode") or ("KNOWN" if kind == "mitre-cwe" else "INCREMENTAL")
        item["collection_id"] = item.get("collection_id") or environment.get("MITRE_ENTERPRISE_COLLECTION_ID") or self.rules.DEFAULT_COLLECTION
        item["cwe_id"] = item.get("cwe_id") or "CWE-20"
        item["adaptive_monitor_enabled"] = item.get("adaptive_monitor_enabled") is not False
        item["auto_update"] = item.get("auto_update") is True
        item["auto_scope_contract_id"] = item.get("auto_scope_contract_id") or ""
        item["health"] = {k: row.get(k) for k in ("status", "last_success_at", "last_attempt_at", "failure_count", "circuit_state", "health_score", "next_retry_at")}
        item["health"]["status"] = item["health"].get("status") or "NEW"
        item["monitor"] = {k: row.get(k) for k in ("detector_strategy", "scheduler_status", "last_probe_at", "last_change_at", "next_check_at", "unchanged_streak", "change_rate_ema", "last_total_results", "last_probe_status", "last_auto_mission_id", "monitor_last_error")}
        item["monitor"]["scheduler_status"] = item["monitor"].get("scheduler_status") or ("NOT_MIGRATED" if row.get("monitor_unavailable") else "NEW")
        return item

    def list_sources(self, args):
        exact_keys(args, {"search", "enabled", "adapter_type", "page", "limit"})
        search = str(args.get("search", ""))[:200]
        enabled = args.get("enabled", "")
        kind = args.get("adapter_type", "")
        if enabled not in {"", "1", "0"} or (kind and kind not in self.rules.ADAPTERS):
            raise AppError("Filter sumber API tidak valid.")
        page = bounded_int(args.get("page"), 1, 100000, 1)
        limit = bounded_int(args.get("limit"), 1, 100, 10)
        # Registries are small; filter the public projection so legacy and explicit adapters behave identically.
        base_select = "SELECT " + ",".join("r." + field for field in REGISTRY_FIELDS) +             ",s.status,s.last_success_at,s.last_attempt_at,s.failure_count,s.circuit_state,s.health_score,s.next_retry_at "
        try:
            with self.adapter.database() as cursor:
                cursor.execute(base_select +
                    ",m.detector_strategy,m.scheduler_status,m.last_probe_at,m.last_change_at,m.next_check_at,m.unchanged_streak,m.change_rate_ema,m.last_total_results,m.last_probe_status,m.last_auto_mission_id,m.last_error AS monitor_last_error "
                    "FROM cti_source_registry r LEFT JOIN cti_source_state s ON s.source_id=r.source_id "
                    "LEFT JOIN cti_source_monitor_state m ON m.source_id=r.source_id ORDER BY r.source_id")
                records = cursor.fetchall()
        except Exception:
            with self.adapter.database() as cursor:
                cursor.execute(base_select + "FROM cti_source_registry r LEFT JOIN cti_source_state s ON s.source_id=r.source_id ORDER BY r.source_id")
                records = cursor.fetchall()
            for record in records:
                record["monitor_unavailable"] = True
        environment = self.adapter.environment()
        items = [self.public(row, environment) for row in records]
        stats = {"total": len(items), "enabled": sum(row["enabled"] for row in items),
                 "supported": sum(row["acquisition_supported"] for row in items),
                 "attention": sum(bool(row["endpoint_error"]) or bool(row["health"].get("failure_count")) for row in items)}
        query = search.casefold()
        filtered = [row for row in items if (not query or any(query in str(row.get(key) or "").casefold()
                    for key in ("source_id", "display_name", "endpoint_url", "adapter_label", "description")))
                    and (enabled == "" or row["enabled"] == (enabled == "1")) and (not kind or row["adapter_type"] == kind)]
        total = len(filtered)
        page = min(page, max(1, (total + limit - 1) // limit))
        existing = {row["source_id"] for row in items}
        return {"items": filtered[(page - 1) * limit:page * limit], "total": total, "page": page, "limit": limit, "stats": stats,
                "templates": [row for row in self.rules.builtin_templates(environment) if row["source_id"] not in existing],
                "adapters": [{"id": k, "label": v["label"]} for k, v in self.rules.ADAPTERS.items()]}

    def _row(self, cursor, source_id, lock=False):
        cursor.execute("SELECT " + ",".join(REGISTRY_FIELDS) + " FROM cti_source_registry WHERE source_id=%s" + (" FOR UPDATE" if lock else ""), (source_id,))
        row = cursor.fetchone()
        if not row:
            raise AppError("Sumber API tidak ditemukan. Muat ulang daftar sumber.", 404)
        return row

    def detail(self, source_id):
        source_id = self.source_id(source_id)
        with self.adapter.database() as cursor:
            row = self._row(cursor, source_id)
            cursor.execute("SELECT status,last_success_at,last_attempt_at,failure_count,circuit_state,health_score,next_retry_at FROM cti_source_state WHERE source_id=%s", (source_id,))
            row.update(cursor.fetchone() or {})
        try:
            with self.adapter.database() as cursor:
                cursor.execute("SELECT detector_strategy,scheduler_status,last_probe_at,last_change_at,next_check_at,unchanged_streak,change_rate_ema,last_total_results,last_probe_status,last_auto_mission_id,last_error AS monitor_last_error FROM cti_source_monitor_state WHERE source_id=%s", (source_id,))
                row.update(cursor.fetchone() or {})
        except Exception:
            row["monitor_unavailable"] = True
        return self.public(row)

    def values(self, body, current=None):
        exact_keys(body, WRITE_FIELDS | {"expected_revision"}, {"source_id", "display_name", "adapter_type", "endpoint_ref", "enabled"})
        source_id = self.source_id(body["source_id"])
        kind = body["adapter_type"]
        if not isinstance(kind, str) or kind not in self.rules.ADAPTERS:
            raise AppError("Adapter sumber tidak didukung.")
        if not isinstance(body["enabled"], bool):
            raise AppError("Enabled harus bernilai boolean.")
        try:
            config = self.rules.parse_config(current.get("config_json")) if current else {}
            endpoint = self.rules.validate_endpoint(body["endpoint_ref"])
            credential = self.rules.normalize_credential(body.get("credential_ref"))
        except (ValueError, TypeError) as error:
            raise AppError(str(error)) from None
        config.update(display_name=self.text(body["display_name"], "Nama API", 160, True),
                      description=self.text(body.get("description", ""), "Deskripsi", 1500), adapter_type=kind,
                      timeout_seconds=self.integer(body.get("timeout_seconds", 90), "Timeout", 1, 300))
        auth = body.get("auth_mode", "api-key" if kind.startswith("nvd-") else "none")
        if auth not in {"none", "api-key", "bearer"} or (kind.startswith("nvd-") and auth == "bearer"):
            raise AppError("Mode autentikasi tidak sesuai dengan adapter.")
        if auth == "none" and credential:
            raise AppError("Pilih mode autentikasi sebelum mengatur referensi kredensial.")
        if kind in {"ctid-cve-attack", "mitre-capec"}:
            import sys
            root = str(Path(__file__).resolve().parents[1])
            if root not in sys.path:
                sys.path.insert(0, root)
            from mapping_source_services import validate_source_url
            try:
                validate_source_url(kind, endpoint)
            except ValueError as error:
                raise AppError(str(error)) from None
            if auth != 'none' or credential:
                raise AppError('Dataset publik mapping menggunakan tanpa autentikasi.')
        config["auth_mode"] = auth
        for key, default in (("adaptive_monitor_enabled", True), ("auto_update", False)):
            value = body.get(key, config.get(key, default))
            if not isinstance(value, bool):
                raise AppError(f"{key} harus bernilai boolean.")
            config[key] = value
        scope = self.text(body.get("auto_scope_contract_id", config.get("auto_scope_contract_id", "")), "Scope contract otomatis", 100)
        if scope and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", scope):
            raise AppError("Scope contract otomatis hanya boleh berisi huruf, angka, titik, garis bawah, minus, atau titik dua.")
        config["auto_scope_contract_id"] = scope
        min_interval = self.integer(body.get("adaptive_min_interval_seconds", config.get("adaptive_min_interval_seconds", 300)), "Interval minimum adaptif", 60, 31536000)
        max_interval = self.integer(body.get("adaptive_max_interval_seconds", config.get("adaptive_max_interval_seconds", 43200)), "Interval maksimum adaptif", 60, 31536000)
        if max_interval < min_interval:
            raise AppError("Interval maksimum adaptif tidak boleh lebih kecil dari interval minimum.")
        config["adaptive_min_interval_seconds"] = min_interval
        config["adaptive_max_interval_seconds"] = max_interval
        if kind in {"nvd-cve", "nvd-cpe"}:
            config["max_pages"] = self.integer(body.get("max_pages", 1), "Batas halaman", 1, 100)
            config["page_size"] = self.integer(body.get("page_size", 500), "Entri per halaman", 1, 2000)
        if kind == "nvd-cpe":
            config["keyword"] = self.text(body.get("keyword", ""), "Keyword CPE", 200)
            config["match_string"] = self.text(body.get("match_string", ""), "Match string CPE", 500)
        if kind == "mitre-attack":
            collection = body.get("collection_id", self.rules.DEFAULT_COLLECTION)
            if not isinstance(collection, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", collection):
                raise AppError("Collection ID TAXII tidak valid.")
            mode = body.get("sync_mode", "INCREMENTAL")
            if mode not in {"INCREMENTAL", "FULL"}:
                raise AppError("Mode sinkronisasi ATT&CK tidak valid.")
            config.update(collection_id=collection, sync_mode=mode)
        if kind == "mitre-cwe":
            mode = body.get("sync_mode", "KNOWN")
            if mode not in {"SINGLE", "KNOWN", "RANGE"}:
                raise AppError("Mode sinkronisasi CWE tidak valid.")
            config["sync_mode"] = mode
            if mode == "SINGLE":
                cwe_id = body.get("cwe_id", "CWE-20")
                if not isinstance(cwe_id, str) or not re.fullmatch(r"CWE-[1-9][0-9]{0,4}", cwe_id):
                    raise AppError("Gunakan CWE ID seperti CWE-20 untuk akuisisi terbatas satu CWE.")
                config["cwe_id"] = cwe_id
            elif mode == "RANGE":
                start = self.integer(body.get("cwe_range_start", 1), "Awal range CWE", 1, 99999)
                end = self.integer(body.get("cwe_range_end", 1500), "Akhir range CWE", 1, 99999)
                if end < start:
                    raise AppError("Akhir range CWE tidak boleh lebih kecil dari awal.")
                if end - start > 2000:
                    raise AppError("Range CWE maksimum 2000 ID per akuisisi.")
                config.update(cwe_range_start=start, cwe_range_end=end)
        definition = self.rules.ADAPTERS[kind]
        config["semantic_role"] = definition["role"]
        if kind in {"nvd-cve", "nvd-cpe", "mitre-cwe"}:
            config["bounded_agent_refresh"] = True
        # Keep unrelated legacy config, but remove stale adapter-specific parameters.
        applicable = {"max_pages", "page_size"} if kind.startswith("nvd-") else set()
        applicable |= {"keyword", "match_string"} if kind == "nvd-cpe" else set()
        applicable |= {"collection_id", "sync_mode"} if kind == "mitre-attack" else set()
        applicable |= {"cwe_id", "sync_mode", "cwe_range_start", "cwe_range_end"} if kind == "mitre-cwe" else set()
        for key in {"max_pages", "page_size", "keyword", "match_string", "collection_id", "sync_mode", "cwe_id", "cwe_range_start", "cwe_range_end"} - applicable:
            config.pop(key, None)
        config.pop("sync_adapter", None)
        try:
            criticality = Decimal(str(body.get("criticality", "0.5")))
        except (InvalidOperation, ValueError):
            raise AppError("Criticality harus angka antara 0 dan 1.") from None
        if not criticality.is_finite() or not 0 <= criticality <= 1:
            raise AppError("Criticality harus angka antara 0 dan 1.")
        protocol = definition["protocol"] if kind != "registry-only" else body.get("protocol", "REST_JSON")
        if protocol not in {"REST_JSON", "REST_XML", "TAXII_2_1", "STIX_FEED", "JSON_FEED"}:
            raise AppError("Protokol sumber tidak didukung.")
        return {"source_id": source_id, "protocol": protocol, "endpoint_ref": endpoint, "credential_ref": credential,
                "enabled": int(body["enabled"]), "freshness_sla_seconds": self.integer(body.get("freshness_sla_seconds", 86400), "Freshness SLA", 60, 31536000),
                "criticality": criticality.quantize(Decimal("0.0001")), "trust_tier": self.text(body.get("trust_tier", "EXTERNAL"), "Trust tier", 80, True),
                "incremental_strategy": definition["strategy"], "config_json": json.dumps(config, ensure_ascii=False)}

    @staticmethod
    def check_revision(body, row):
        expected = body.get("expected_revision")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise AppError("Versi sumber diperlukan. Buka kembali form dari daftar terbaru.")
        if expected != revision(row):
            raise AppError("Konfigurasi sumber telah berubah. Tutup form, muat ulang daftar, lalu coba lagi.", 409)

    def create(self, body):
        exact_keys(body, WRITE_FIELDS)
        values = self.values(body)
        # The unique registry key also guards inserts from another Web App process.
        with self.adapter._lock, self.adapter.database(write=True) as cursor:
            cursor.execute("SELECT source_id FROM cti_source_registry WHERE source_id=%s FOR UPDATE", (values["source_id"],))
            if cursor.fetchone():
                raise AppError("Source ID sudah digunakan. Pilih ID baru atau gunakan Ubah.", 409)
            fields = tuple(values)
            try:
                cursor.execute("INSERT INTO cti_source_registry (" + ",".join(fields) + ") VALUES (" + ",".join(["%s"] * len(fields)) + ")", tuple(values[k] for k in fields))
            except Exception as error:
                if error.args and error.args[0] in {1062, 1213}:
                    raise AppError("Source ID sedang digunakan atau diperbarui. Muat ulang daftar.", 409) from None
                raise
            saved = self._row(cursor, values["source_id"])
        return {"message": "Sumber API ditambahkan.", "source": self.public(saved)}

    def update(self, body):
        exact_keys(body, WRITE_FIELDS | {"expected_revision"}, {"source_id", "expected_revision"})
        source_id = self.source_id(body["source_id"])
        with self.adapter._lock, self.adapter.database(write=True) as cursor:
            row = self._row(cursor, source_id, lock=True)
            self.check_revision(body, row)
            values = self.values(body, row)
            fields = tuple(key for key in values if key != "source_id")
            cursor.execute("UPDATE cti_source_registry SET " + ",".join(key + "=%s" for key in fields) + ",updated_at=CURRENT_TIMESTAMP WHERE source_id=%s", tuple(values[k] for k in fields) + (source_id,))
            saved = self._row(cursor, source_id)
        return {"message": "Konfigurasi API diperbarui.", "source": self.public(saved)}

    def delete(self, body):
        exact_keys(body, {"source_id", "expected_revision", "confirm"}, {"source_id", "expected_revision", "confirm"})
        source_id = self.source_id(body["source_id"])
        if body["confirm"] is not True:
            raise AppError("Konfirmasi penghapusan sumber diperlukan.")
        with self.adapter._lock, self.adapter.database(write=True) as cursor:
            row = self._row(cursor, source_id, lock=True)
            self.check_revision(body, row)
            cursor.execute("DELETE FROM cti_source_registry WHERE source_id=%s", (source_id,))
        return {"message": "Sumber API dihapus dari registry. Data CTI dan riwayat akuisisi tetap tersedia.", "source_id": source_id}
