"""Fixed parser worker. Never executes code, commands, plugins, or target I/O.

This file is launched directly by the trusted parent with python -I -S.
Linux seccomp is installed after loading the fixed stdlib modules; Windows
resource isolation is attached by the parent before it sends the first input.
"""
from __future__ import annotations

import base64
import ctypes
import errno
import hashlib
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adapters.bounded_profile import parse_batch


def emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    sys.stdout.flush()


def linux_controls(config):
    import resource
    limits = config["limits"]
    for key, value in ((resource.RLIMIT_AS, limits["memory_mb"] * 1024 * 1024),
                       (resource.RLIMIT_CPU, limits["cpu_seconds"]), (resource.RLIMIT_NOFILE, 16),
                       (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_CORE, 0)):
        resource.setrlimit(key, (value, value))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError("no_new_privs unavailable")
    seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not ctx:
        raise RuntimeError("seccomp init failed")
    try:
        # Deny all new file/network/process/namespace/ptrace capabilities.
        names = ("socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
                 "sendto", "sendmsg", "recvfrom", "recvmsg", "open", "openat", "openat2", "creat",
                 "unlink", "unlinkat", "rename", "renameat", "renameat2", "mkdir", "mkdirat",
                 "link", "linkat", "symlink", "symlinkat", "truncate", "chmod", "fchmod", "chown",
                 "execve", "execveat", "fork", "vfork", "clone", "clone3", "ptrace", "process_vm_readv",
                 "process_vm_writev", "mount", "umount2", "unshare", "setns", "bpf", "io_uring_setup")
        for name in names:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and seccomp.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError("seccomp rule failed")
        if seccomp.seccomp_load(ctx) != 0:
            raise RuntimeError("seccomp load failed")
    finally:
        seccomp.seccomp_release(ctx)
    try:
        os.open("/etc/passwd", os.O_RDONLY)
    except PermissionError:
        pass
    else:
        raise RuntimeError("filesystem isolation probe failed")
    return "SECCOMP_RLIMIT"


def main():
    raw = sys.stdin.buffer.readline(4097)
    if not raw or len(raw) > 4096:
        return 2
    setup = json.loads(raw)
    backend = linux_controls(setup) if sys.platform.startswith("linux") else "JOB_OBJECT_FIXED_WORKER" if os.name == "nt" else None
    if backend is None:
        return 3
    emit({"ready": True, "backend": backend, "pid": os.getpid()})
    max_input = setup["limits"]["max_network_bytes"] * 2 + 4096
    raw = sys.stdin.buffer.readline(max_input + 1)
    if not raw or len(raw) > max_input:
        return 4
    item = json.loads(raw)
    if set(item) != {"operation", "observation"} or item["operation"] not in {"HTTP_HEAD", "TCP_CONNECT", "TCP_BANNER", "WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"}:
        return 5
    observation = item["observation"]
    data = base64.b64decode(observation["response_b64"], validate=True)
    if len(data) > setup["limits"]["max_network_bytes"] or hashlib.sha256(data).hexdigest() != observation["response_sha256"]:
        return 6
    if item["operation"] in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"} and "frames" in observation:
        emit({"result":parse_batch(observation,data),"backend":backend})
        return 0
    result = {k: observation[k] for k in ("connected", "peer_ip", "response_bytes", "response_sha256", "byte_limit_reached")}
    result.update({"http_status": None, "server_header_present": False, "server_header_sha256": None,
                   "validation_verdict": "UNDETERMINED", "expected_evidence_confirmed": False})
    if item["operation"] in {"HTTP_HEAD", "WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"}:
        lines = data.split(b"\r\n")
        parts = lines[0].split(b" ", 2)
        if len(parts) < 2 or parts[0] not in {b"HTTP/1.0", b"HTTP/1.1"} or len(parts[1]) != 3 or not parts[1].isdigit():
            return 7
        code = int(parts[1])
        if not 100 <= code <= 599:
            return 7
        result["http_status"] = code
        server = [x.split(b":", 1)[1].strip() for x in lines[1:] if x.lower().startswith(b"server:")]
        if server:
            result["server_header_present"] = True
            result["server_header_sha256"] = hashlib.sha256(b"\n".join(server)).hexdigest()
    if item["operation"] == "WEB_PROFILE_FINGERPRINT":
        # GET is single-request, redirect-deny. Keep only fixed, allowlisted indicators;
        # arbitrary page text, header values, cookies and response bytes are discarded.
        status_line, _, body = data.partition(b"\r\n\r\n")
        if result["http_status"] in {301, 302, 303, 307, 308}:
            observations = [{"status_code": result["http_status"], "redirect_blocked": True}]
            findings = []
        else:
            headers = {}
            for line in lines[1:]:
                if b":" not in line: continue
                key, value = line.split(b":", 1)
                key = key.strip().lower()
                if key in {b"server", b"x-powered-by", b"x-generator", b"content-type"}:
                    headers[key.decode("ascii", "ignore")] = value.strip().decode("latin-1", "ignore")[:256].lower()
            html = body[:16384].lower()
            signatures = (
                (b"server", b"nginx", "nginx", "http.server"),
                (b"server", b"apache", "Apache HTTP Server", "http.server"),
                (b"x-powered-by", b"php", "PHP", "http.x-powered-by"),
                (b"x-powered-by", b"express", "Express.js", "http.x-powered-by"),
                (b"x-powered-by", b"asp.net", "ASP.NET", "http.x-powered-by"),
                (b"x-generator", b"drupal", "Drupal", "http.x-generator"),
            )
            findings = []
            for header_name, marker, technology, signal in signatures:
                if marker in headers.get(header_name.decode(), "").encode() and technology not in {f["technology"] for f in findings}:
                    findings.append({"technology": technology, "signal": signal, "confidence_level": "medium"})
            markup_signatures = ((b"/_next/", "Next.js", "html.next.marker"),
                                 (b"/_nuxt/", "Nuxt", "html.nuxt.marker"),
                                 (b"ng-version=", "Angular", "html.angular.marker"),
                                 (b"data-reactroot", "React", "html.react.marker"),
                                 (b"__viewstate", "ASP.NET", "html.aspnet.marker"),
                                 (b"yii.js", "Yii Framework", "html.yii.asset"))
            for marker, technology, signal in markup_signatures:
                if marker in html and technology not in {f["technology"] for f in findings}:
                    findings.append({"technology": technology, "signal": signal, "confidence_level": "low"})
            observations = [{"status_code": result["http_status"],
                             "content_type": headers.get("content-type", "")[:120],
                             "response_bytes": len(data), "response_sha256": hashlib.sha256(data).hexdigest()}]
        profile_result = {"schema_version": "web-technology-observation-v3",
            "target": observation.get("target", ""), "mode": "fingerprinting",
            "observations": observations, "technology_findings": findings,
            "scan_metrics": {"scan_status": "COMPLETED", "requests_planned": 1,
                "responses_received": 1, "response_rate_percent": 100, "request_errors": 0,
                "fingerprints_matched": len(findings), "redirects_blocked": int(bool(observations and observations[0].get("redirect_blocked")))}}
        emit({"result": profile_result, "backend": backend})
        return 0
    # Raw headers, tokens, cookies, banners, and body bytes are never emitted.
    emit({"result": result, "backend": backend})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # No uncontrolled traceback/target data on stderr or stdout.
        sys.exit(10)
