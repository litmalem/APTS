"""Vulndesk Web local server. Python 3.10+, loopback access only."""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import re
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from backend import Adapter, AppError, json_default

APP_DIR = Path(__file__).resolve().parent
DEFAULTS = {"vulndesk_root": "D:/Vulndesk", "vulndesk_python": "", "web_port": 8801,
            "service_ports": {"cti": 8765, "gss": 8770, "mission": 8780, "pentest": 8790}}
MAX_BODY = 7 * 1024 * 1024


def load_config(path, args):
    config = {**DEFAULTS, "service_ports": dict(DEFAULTS["service_ports"])}
    if path.is_file():
        supplied = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
            raise ValueError("config.json memiliki parameter tidak dikenal")
        config.update({k: v for k, v in supplied.items() if k != "service_ports"})
        if not isinstance(supplied.get("service_ports", {}), dict) or set(supplied.get("service_ports", {})) - set(DEFAULTS["service_ports"]):
            raise ValueError("service_ports tidak valid")
        config["service_ports"].update(supplied.get("service_ports", {}))
    if args.vulndesk_root:
        config["vulndesk_root"] = args.vulndesk_root
    if args.port:
        config["web_port"] = args.port
    for port in [config["web_port"], *config["service_ports"].values()]:
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError("Port harus angka 1024–65535")
    if config["web_port"] in config["service_ports"].values():
        raise ValueError("Port Web App harus berbeda dari port modul")
    return config


def make_handler(adapter, csrf, mode, port):
    web_root = (APP_DIR / "web").resolve()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "VulndeskWeb/1.1"
        sys_version = ""

        def log_message(self, format, *args):
            # Avoid dumping queries, uploaded records, or runtime response bodies.
            if args:
                print(f"Web request: {self.command} {urlsplit(self.path).path} {args[1] if len(args)>1 else ''}")

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, default=json_default).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def check_origin(self, mutation=False):
            host = self.headers.get("Host", "")
            if host not in allowed_hosts:
                raise AppError("Host Web App tidak diizinkan.", 403)
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                raise AppError("Permintaan harus berasal dari Web App lokal ini.", 403)
            fetch_site = self.headers.get("Sec-Fetch-Site", "")
            if fetch_site in {"cross-site", "same-site"}:
                raise AppError("Permintaan lintas origin tidak diizinkan.", 403)
            if mutation:
                token = self.headers.get("X-Vulndesk-CSRF", "")
                if not hmac.compare_digest(token, csrf):
                    raise AppError("Token sesi tidak valid. Muat ulang halaman.", 403)
                if self.headers.get_content_type() != "application/json":
                    raise AppError("Gunakan Content-Type application/json.", 415)

        def api_get(self, path, args):
            if path == "/api/config":
                return {"vulndesk_root": str(adapter.root), "service_ports": adapter.ports, "api_owned": adapter.api_owned, "mode": mode, "version": "1.1"}
            if path == "/api/summary":
                return adapter.summary()
            if path == "/api/components":
                return adapter.components()
            if path == "/api/sources":
                return adapter.sources(args)
            match = re.fullmatch(r"/api/sources/([A-Za-z0-9_.:-]{1,120})", path)
            if match:
                return adapter.source_detail(match[1])
            if path == "/api/enrichment":
                return adapter.enrichment_list(args)
            match = re.fullmatch(r"/api/enrichment/([A-Za-z0-9][A-Za-z0-9._:@-]{0,191})", path)
            if match:
                return adapter.enrichment_detail(match[1])
            if path == "/api/diagnostics":
                return adapter.upstream("cti", "/api/cti/diagnostics?deep=true")
            match = re.fullmatch(r"/api/attack/(T[0-9]{4}(?:\.[0-9]{3})?)/vulnerabilities", path)
            if match:
                return adapter.attack_vulnerabilities(match[1], args)
            capec_match = re.fullmatch(r"/api/data/capec/(CAPEC-[0-9]{1,8})", path)
            if capec_match:
                return adapter.data_detail("capec", capec_match[1])
            match = re.fullmatch(r"/api/data/([a-z]+)/([0-9]+)", path)
            if match:
                return adapter.data_detail(*match.groups())
            match = re.fullmatch(r"/api/data/([a-z]+)", path)
            if match:
                return adapter.data_list(match[1], args)
            match = re.fullmatch(r"/api/missions/([A-Za-z0-9_.:-]{1,160})/(status|events|diagnostics|lineage|integrity)", path)
            if match:
                return adapter.mission(*match.groups())
            raise AppError("Endpoint tidak ditemukan.", 404)

        def do_GET(self):
            try:
                self.check_origin()
                url = urlsplit(self.path)
                path = unquote(url.path)
                if path.startswith("/api/"):
                    args = {k: v[0] for k, v in parse_qs(url.query, max_num_fields=30).items()}
                    return self.send(200, self.api_get(path, args))
                if path == "/bootstrap.js":
                    bootstrap = {"mode": mode, "local": True, "csrf": csrf, "version": "1.1"}
                    return self.send(200, "window.VULNDESK_CONFIG=" + json.dumps(bootstrap) + ";", "text/javascript; charset=utf-8")
                allowed = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/sources.js": "sources.js", "/demo.js": "demo.js", "/style.css": "style.css"}
                if path not in allowed:
                    raise AppError("File tidak ditemukan.", 404)
                file = (web_root / allowed[path]).resolve()
                if not file.is_relative_to(web_root) or not file.is_file():
                    raise AppError("File antarmuka tidak ditemukan.", 404)
                mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                self.send(200, file.read_bytes(), mime + "; charset=utf-8")
            except AppError as error:
                self.send(error.status, {"error": "request_failed", "message": str(error)})
            except (ValueError, TypeError):
                self.send(400, {"error": "invalid_request", "message": "Parameter permintaan tidak valid."})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "server_error", "message": "Operasi belum berhasil. Periksa konfigurasi server lokal."})

        def do_POST(self):
            try:
                self.check_origin(mutation=True)
                if self.headers.get("Transfer-Encoding"):
                    raise AppError("Transfer-Encoding tidak didukung.", 400)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise AppError("Ukuran permintaan tidak valid atau melebihi batas.", 413)
                self.connection.settimeout(15)
                body = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                routes = {"/api/components/toggle": adapter.toggle, "/api/missions/start": adapter.start_mission,
                          "/api/datasets/import": adapter.import_dataset, "/api/datasets/delete": adapter.delete_dataset}
                # Resolve new routes only when requested, so older integration adapters remain usable.
                source_routes = {"/api/sources/create": "create_source", "/api/sources/update": "update_source", "/api/sources/delete": "delete_source"}
                if path in {"/api/runtime/start", "/api/runtime/stop"}:
                    if body != {}:
                        raise AppError("Operasi runtime tidak menerima parameter tambahan.")
                    result = adapter.start_api() if path.endswith("start") else adapter.stop_api()
                elif path in source_routes:
                    result = getattr(adapter, source_routes[path])(body)
                elif path in routes:
                    result = routes[path](body)
                else:
                    raise AppError("Endpoint tidak ditemukan.", 404)
                self.send(200, result)
            except AppError as error:
                self.send(error.status, {"error": "request_failed", "message": str(error)})
            except (ValueError, TypeError, UnicodeError):
                self.send(400, {"error": "invalid_json", "message": "Body JSON tidak valid."})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "server_error", "message": "Operasi belum berhasil. Periksa konfigurasi dan dependensi Vulndesk."})

        def do_HEAD(self):
            self.do_GET()

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Vulndesk Web — antarmuka lokal")
    parser.add_argument("--vulndesk-root", help="Direktori instalasi Vulndesk")
    parser.add_argument("--port", type=int, help="Port Web App; default 8801")
    parser.add_argument("--demo", action="store_true", help="Buka antarmuka dengan data contoh")
    parser.add_argument("--config", type=Path, default=APP_DIR / "config.json")
    args = parser.parse_args()
    try:
        config = load_config(args.config, args)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    adapter = Adapter(config, APP_DIR)
    port = config["web_port"]
    csrf = secrets.token_urlsafe(32)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(adapter, csrf, "demo" if args.demo else "live", port))
    httpd.daemon_threads = True
    def stop(signum, frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    scheduler = None
    if not args.demo and adapter.environment().get("CTI_ADAPTIVE_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        from adaptive_scheduler import AdaptiveSourceScheduler
        scheduler = AdaptiveSourceScheduler(adapter, poll_seconds=int(adapter.environment().get("CTI_ADAPTIVE_SCHEDULER_TICK_SECONDS", "15")))
        scheduler.start()
    print(f"Vulndesk Web: http://127.0.0.1:{port}")
    print("Mode:", "data contoh" if args.demo else "database & API lokal")
    print("Adaptive CTI scheduler:", "aktif" if scheduler else "nonaktif")
    print("Tekan Ctrl+C untuk menghentikan Web App.")
    try:
        httpd.serve_forever()
    finally:
        if scheduler:
            scheduler.stop()
        httpd.server_close()
        adapter.close()


if __name__ == "__main__":
    main()
