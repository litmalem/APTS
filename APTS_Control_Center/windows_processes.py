"""Windows TCP owners and process identity, without PowerShell/CIM dependencies."""
import ctypes as C
from contextlib import contextmanager
import socket
import struct


def _kernel():
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [C.c_ulong, C.c_int, C.c_ulong]
    k.OpenProcess.restype = C.c_void_p
    k.CloseHandle.argtypes = [C.c_void_p]
    k.ReadProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k.GetProcessTimes.argtypes = [C.c_void_p] * 5
    k.QueryFullProcessImageNameW.argtypes = [C.c_void_p, C.c_ulong, C.c_wchar_p, C.POINTER(C.c_ulong)]
    k.IsWow64Process.argtypes = [C.c_void_p, C.POINTER(C.c_int)]
    k.TerminateProcess.argtypes = [C.c_void_p, C.c_uint]
    k.WaitForSingleObject.argtypes = [C.c_void_p, C.c_ulong]
    return k


@contextmanager
def handle(pid, terminate=False):
    k = _kernel()
    h = k.OpenProcess(0x0410 | (0x100001 if terminate else 0), False, int(pid))
    if not h:
        raise C.WinError(C.get_last_error())
    try:
        yield h
    finally:
        k.CloseHandle(h)


def tcp_listeners():
    api = C.WinDLL('iphlpapi', use_last_error=True)
    api.GetExtendedTcpTable.argtypes = [C.c_void_p, C.POINTER(C.c_ulong), C.c_int, C.c_ulong, C.c_ulong, C.c_ulong]
    api.GetExtendedTcpTable.restype = C.c_ulong
    size = C.c_ulong()
    result = api.GetExtendedTcpTable(None, C.byref(size), False, socket.AF_INET, 3, 0)
    for _ in range(4):
        if result not in (0, 122):
            break
        buffer = C.create_string_buffer(size.value)
        result = api.GetExtendedTcpTable(buffer, C.byref(size), False, socket.AF_INET, 3, 0)
        if result == 122:
            continue
        if result == 0:
            raw = buffer.raw
            rows = []
            for i in range(struct.unpack_from('=I', raw)[0]):
                state, address, port, _, _, pid = struct.unpack_from('=6I', raw, 4 + i * 24)
                # Only listeners accessible via the IPv4 loopback used by APTS.
                # Table class 3 already selects listeners. Do not filter by
                # dwState again: Windows can leave that field unset in this
                # filtered table even while the listener and owner are valid.
                if address in (0, 0x0100007f):
                    rows.append({'pid': pid, 'port': socket.ntohs(port & 0xffff)})
            return rows
        break
    raise OSError(result, 'Tidak dapat membaca pemilik port TCP Windows')


def identity(h):
    """Read executable, start time, command line and working directory on one handle."""
    k = _kernel()
    created, exited, kernel, user = (C.c_ulonglong() for _ in range(4))
    if not k.GetProcessTimes(h, C.byref(created), C.byref(exited), C.byref(kernel), C.byref(user)):
        raise C.WinError(C.get_last_error())
    image = C.create_unicode_buffer(32768)
    size = C.c_ulong(len(image))
    if not k.QueryFullProcessImageNameW(h, 0, image, C.byref(size)):
        raise C.WinError(C.get_last_error())
    nt = C.WinDLL('ntdll')
    nt.NtQueryInformationProcess.argtypes = [C.c_void_p, C.c_ulong, C.c_void_p, C.c_ulong, C.c_void_p]
    nt.NtQueryInformationProcess.restype = C.c_long
    wow = C.c_int()
    if not k.IsWow64Process(h, C.byref(wow)):
        raise C.WinError(C.get_last_error())
    width = C.sizeof(C.c_void_p)
    if width == 8 and wow.value:
        peb = C.c_void_p()
        status = nt.NtQueryInformationProcess(h, 26, C.byref(peb), C.sizeof(peb), None)
        width = 4
        peb_address = peb.value
    else:
        basic = (C.c_void_p * 6)()
        status = nt.NtQueryInformationProcess(h, 0, basic, C.sizeof(basic), None)
        peb_address = basic[1]
    if status < 0 or not peb_address:
        raise RuntimeError('PEB proses tidak tersedia; gunakan Python Control Center 64-bit.')

    def read(address, size):
        if not address or not 0 < size <= 65536:
            raise RuntimeError('Alamat/string proses tidak valid.')
        buffer = C.create_string_buffer(size)
        copied = C.c_size_t()
        if not k.ReadProcessMemory(h, address, buffer, size, C.byref(copied)) or copied.value != size:
            raise C.WinError(C.get_last_error())
        return buffer.raw

    pointer = lambda raw: int.from_bytes(raw, 'little')
    params = pointer(read(peb_address + (0x20 if width == 8 else 0x10), width))

    def string(offset):
        raw = read(params + offset, 16 if width == 8 else 8)
        length = int.from_bytes(raw[:2], 'little')
        address = pointer(raw[8:16] if width == 8 else raw[4:8])
        return read(address, length).decode('utf-16-le') if length else ''

    return {'created': created.value, 'executable': image.value,
            'command': string(0x70 if width == 8 else 0x40),
            'cwd': string(0x38 if width == 8 else 0x24)}


def inspect(pid):
    with handle(pid) as h:
        return {'pid': int(pid), **identity(h)}


def terminate(row, port):
    # Keep this handle open from verification through termination: PID reuse
    # cannot redirect the operation to a different process.
    with handle(row['pid'], terminate=True) as h:
        current = identity(h)
        if any(current[key] != row.get(key) for key in ('created', 'executable', 'command', 'cwd')):
            raise RuntimeError('Identitas proses berubah; muat ulang status.')
        if not any(item['pid'] == row['pid'] and item['port'] == int(port) for item in tcp_listeners()):
            raise RuntimeError('Pemilik port berubah; muat ulang status.')
        k = _kernel()
        if not k.TerminateProcess(h, 1):
            raise C.WinError(C.get_last_error())
        if k.WaitForSingleObject(h, 5000) != 0:
            raise RuntimeError('Proses belum berhenti.')
