"""Resource-isolated fixed workers, with fail-closed readiness before broker I/O."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
from threading import Thread
import time

from .execution_contract import ExecutionSourceRejected, canonical_json


class WindowsJob:
    def __init__(self, process, limits):
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes, self.kernel.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ExecutionSourceRejected("WINDOWS_JOB_OBJECT_UNAVAILABLE")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x8 | 0x2
        info.BasicLimitInformation.ActiveProcessLimit = 1
        info.BasicLimitInformation.PerProcessUserTimeLimit = limits["cpu_seconds"] * 10_000_000
        info.ProcessMemoryLimit = limits["memory_mb"] * 1024 * 1024
        if (not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                or not self.kernel.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle)))):
            self.close()
            raise ExecutionSourceRejected("WINDOWS_JOB_LIMITS_NOT_ENFORCED")

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise ExecutionSourceRejected("WINDOWS_JOB_HANDLE_CLOSE_FAILED")
            self.handle = None


class ResourceSandbox:
    def __init__(self, limits, *, runtime=None):
        self.limits = dict(limits)
        self.runtime = runtime
        self.process = None
        self.job = None
        self.folder = None
        self.reader = None
        self.messages = queue.Queue()
        self.backend = None
        self.bytes_read = 0
        self.capture = getattr(runtime, "evidence_capture", None)
        self.captured_stdout = bytearray()
        self.stderr_digest = hashlib.sha256()
        self.stderr_size = 0
        self.stderr_reader = None
        self.capture_complete = True
        self.capture_sent = False

    def __enter__(self):
        if self.runtime:
            self.runtime.check()
        if os.name != "nt" and not sys.platform.startswith("linux"):
            raise ExecutionSourceRejected("NATIVE_SANDBOX_BACKEND_UNAVAILABLE")
        self.folder = tempfile.TemporaryDirectory(prefix="apts-sandbox-")
        # Stage 6.8 retains owned objects only, never accepts cleanup paths.
        tracked = getattr(self.runtime, "cleanup_workers", None)
        if tracked is not None:
            tracked.append(self)
        env = {"PATH": "", "LANG": "C.UTF-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "C:\\Windows")
        try:
            self.process = subprocess.Popen([sys.executable, "-I", "-S", str(Path(__file__).with_name("sandbox_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE if self.capture else subprocess.DEVNULL,
                cwd=self.folder.name, env=env, shell=False, close_fds=True,
                start_new_session=os.name != "nt", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if os.name == "nt":
                self.job = WindowsJob(self.process, self.limits)
            if self.runtime:
                self.runtime.attach_worker(self.interrupt)
            self.reader = Thread(target=self._read_output, daemon=True)
            self.reader.start()
            if self.capture:
                self.stderr_reader = Thread(target=self._read_stderr, daemon=True)
                self.stderr_reader.start()
            self._send({"limits": self.limits})
            ready = self._receive(time.monotonic() + 5)
            expected = "JOB_OBJECT_FIXED_WORKER" if os.name == "nt" else "SECCOMP_RLIMIT"
            if ready != {"ready": True, "backend": expected, "pid": self.process.pid}:
                raise ExecutionSourceRejected("SANDBOX_READINESS_NOT_PROVEN")
            self.backend = expected
            return self
        except Exception:
            self.close()
            raise

    def _read_output(self):
        while True:
            line = self.process.stdout.readline(self.limits["max_output_bytes"] + 1)
            if not line:
                self.messages.put(None)
                return
            self.bytes_read += len(line)
            if self.capture:
                self.captured_stdout.extend(line[:max(0, self.limits["max_output_bytes"] - len(self.captured_stdout))])
            if self.bytes_read > self.limits["max_output_bytes"]:
                self.capture_complete = False
                self.messages.put("OVERSIZED")
                return
            self.messages.put(line)

    def _read_stderr(self):
        while True:
            chunk = self.process.stderr.read(4096)
            if not chunk:
                return
            self.stderr_digest.update(chunk)
            self.stderr_size += len(chunk)

    def _send(self, value):
        if self.runtime:
            self.runtime.check()
        try:
            self.process.stdin.write((canonical_json(value) + "\n").encode("utf-8"))
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise ExecutionSourceRejected("SANDBOX_WORKER_FAILED") from exc

    def _receive(self, deadline):
        if self.runtime:
            while True:
                self.runtime.check()
                try:
                    raw = self.messages.get(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                    break
                except queue.Empty:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("sandbox deadline expired")
        else:
            try:
                raw = self.messages.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("sandbox deadline expired") from exc
        if raw is None or raw == "OVERSIZED":
            raise ExecutionSourceRejected("SANDBOX_WORKER_FAILED_OR_OUTPUT_QUOTA")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ExecutionSourceRejected("INVALID_SANDBOX_RESPONSE") from exc

    def parse(self, operation, observation, *, deadline):
        self._send({"operation": operation, "observation": observation})
        result = self._receive(deadline)
        if set(result) != {"result", "backend"} or result["backend"] != self.backend:
            raise ExecutionSourceRejected("INVALID_SANDBOX_RESULT")
        try:
            code = self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("sandbox exit deadline expired") from exc
        if code != 0:
            raise ExecutionSourceRejected("SANDBOX_WORKER_FAILED")
        value = result["result"]
        if operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"}:
            _validate_web_fingerprint_result(value)
            expected = 'enumeration' if operation == 'WEB_PROFILE_ENUMERATION' else 'fingerprinting'
            if value.get('mode') != expected:
                raise ExecutionSourceRejected("WEB_PROFILE_OPERATION_MISMATCH")
        return value

    def interrupt(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            if self.job:
                self.job.close()
            if self.reader:
                self.reader.join(timeout=2)
            if self.stderr_reader:
                self.stderr_reader.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream:
                    stream.close()
        if self.reader:
            self.reader.join(timeout=2)
        if self.folder:
            self.folder.cleanup()
        if self.runtime:
            self.runtime.detach_worker(self.interrupt)
        if self.capture and self.process and not self.capture_sent:
            self.capture_sent = True
            self.capture.worker_output(bytes(self.captured_stdout), self.stderr_digest.hexdigest(),
                self.stderr_size, self.process.returncode,
                complete=self.capture_complete and self.reader is not None and not self.reader.is_alive()
                    and (self.stderr_reader is None or not self.stderr_reader.is_alive()))

    def __exit__(self, *args):
        self.close()


def _validate_web_fingerprint_result(value):
    """Reject worker output outside the sealed, bounded WPT observation contract."""
    if isinstance(value,dict) and value.get("schema_version")=="web-technology-observation-v4":
        from adapters.profile_contract import validate_profile
        try:validate_profile(value)
        except (ValueError,TypeError,KeyError,AttributeError) as exc:raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT") from exc
        return
    if not isinstance(value, dict) or set(value) != {"schema_version", "target", "mode", "observations", "technology_findings", "scan_metrics"}:
        raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    if value["schema_version"] != "web-technology-observation-v3" or value["mode"] != "fingerprinting":
        raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    if not isinstance(value["target"], str) or len(value["target"]) > 2048:
        raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    observations, findings, metrics = value["observations"], value["technology_findings"], value["scan_metrics"]
    if not isinstance(observations, list) or len(observations) > 1 or not isinstance(findings, list) or len(findings) > 32:
        raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    if not isinstance(metrics, dict) or set(metrics) != {"scan_status", "requests_planned", "responses_received", "response_rate_percent", "request_errors", "fingerprints_matched", "redirects_blocked"}:
        raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    if metrics["requests_planned"] != 1 or metrics["responses_received"] not in (0, 1) or metrics["response_rate_percent"] not in (0, 100):
        raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    allowed = {"nginx", "Apache HTTP Server", "PHP", "Express.js", "ASP.NET", "Drupal", "Next.js", "Nuxt", "Angular", "React", "Yii Framework"}
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {"technology", "signal", "confidence_level"} or finding["technology"] not in allowed or not isinstance(finding["signal"], str) or finding["confidence_level"] not in {"low", "medium"}:
            raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
    for item in observations:
        if not isinstance(item, dict) or set(item) - {"status_code", "redirect_blocked", "content_type", "response_bytes", "response_sha256"}:
            raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
        if "response_sha256" in item and (not isinstance(item["response_sha256"], str) or len(item["response_sha256"]) != 64):
            raise ExecutionSourceRejected("INVALID_WEB_FINGERPRINT_RESULT")
