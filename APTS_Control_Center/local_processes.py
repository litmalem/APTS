"""Recover APTS listeners using native Windows process identity and working directory."""
import ctypes
import os
import socket
from pathlib import Path
import threading
import time
import windows_processes

_lock = threading.RLock()
_cached = (0, [])
_last_error = (0, None)


def port_open(port):
    """Read IPv4 listener state directly; connection timeouts cannot prove OFF."""
    if os.name == 'nt':
        return any(row['port'] == int(port) for row in windows_processes.tcp_listeners())
    with socket.socket() as probe:
        probe.settimeout(.5)
        code = probe.connect_ex(('127.0.0.1', int(port)))
        if code not in (0, 111):
            raise RuntimeError('Tidak dapat memverifikasi port (socket error ' + str(code) + ').')
        return code == 0


def listeners(fresh=False):
    global _cached, _last_error
    if os.name != 'nt':
        return []
    with _lock:
        if not fresh and time.monotonic() - _last_error[0] < 2:
            raise RuntimeError(_last_error[1])
        if not fresh and time.monotonic() - _cached[0] < 2:
            return _cached[1]
        try:
            by_pid = {}
            for row in windows_processes.tcp_listeners():
                by_pid.setdefault(row['pid'], set()).add(row['port'])
            rows = []
            for pid, ports in by_pid.items():
                try:
                    identity = windows_processes.inspect(pid)
                except (OSError, RuntimeError) as exc:
                    identity = {'pid': pid, 'identity_error': str(exc)}
                rows.append({**identity, 'ports': sorted(ports)})
        except (OSError, RuntimeError) as exc:
            _last_error = (time.monotonic(), str(exc))
            raise
        _last_error = (0, None)
        _cached = (time.monotonic(), rows)
        return rows


def command_args(command):
    """Use Windows' own argument parser, including paths containing spaces."""
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    ptr = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not ptr:
        return []
    try:
        return list(ptr[:count.value])
    finally:
        kernel.LocalFree(ptr)


def matches(row, root, launcher, port):
    if not row.get('created') or not row.get('command') or int(row.get('pid', 0)) <= 0:
        return False
    if int(port) not in row.get('ports', []):
        return False
    if Path(row.get('executable') or '').name.lower() not in ('python.exe', 'pythonw.exe'):
        return False
    args = command_args(row['command'])
    # Only permit benign interpreter options preceding the script. A launcher
    # appearing as an argument to another program does not establish identity.
    tail = args[1:]
    while tail and tail[0] in ('-u', '-B', '-E', '-s', '-S', '-I', '-O', '-OO'):
        tail = tail[1:]
    if not tail:
        return False
    script = Path(tail[0])
    if not script.is_absolute():
        cwd = Path(row.get('cwd') or '')
        if not cwd.is_absolute():
            return False
        script = cwd / script
    return script.resolve() == (Path(root) / launcher).resolve()


def find(root, launcher, port, fresh=False):
    candidates = [row for row in listeners(fresh) if int(port) in row.get('ports', [])]
    blocked = [row for row in candidates if row.get('identity_error')]
    if blocked:
        raise RuntimeError('Identitas pemilik port '+str(port)+' tidak dapat dibaca: '+blocked[0]['identity_error'])
    rows = [row for row in candidates if matches(row, root, launcher, port)]
    # Ambiguous listeners (e.g. multiple workers) require explicit investigation.
    return rows[0] if len(rows) == 1 else None


def stop(row, port):
    windows_processes.terminate(row, port)
    global _cached
    with _lock:
        _cached = (0, [])
