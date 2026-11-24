import time
import ssl
from types import SimpleNamespace
import pytest
from execution_subsystem import target_broker as module
from execution_subsystem.runtime_control import RuntimeResources
from execution_subsystem.cleanup_resources import resource_snapshot, resources_verified
from execution_subsystem.cleanup_contract import verify_resource_snapshot


@pytest.mark.parametrize('fail_handshake',[False,True])
def test_sequential_tls_connections_close_and_release_owned_sockets(monkeypatch,fail_handshake):
    sockets=[]
    class Socket:
        def __init__(self,*args):self.closed=False;sockets.append(self)
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
        def settimeout(self,*args):pass
        def connect(self,peer):assert peer==('8.8.8.8',443)
        def getpeername(self):return ('8.8.8.8',443)
        def fileno(self):return -1 if self.closed else 10
        def close(self):self.closed=True
        def do_handshake(self):
            if fail_handshake:raise ssl.SSLError('test handshake failure')
    class TLS:
        def wrap_socket(self,raw,server_hostname,do_handshake_on_connect):
            assert server_hostname=='scoped.example'
            assert do_handshake_on_connect is False
            raw.close()
            return Socket()
    monkeypatch.setattr(module.socket,'socket',Socket)
    monkeypatch.setattr(module,'create_verified_tls_context',lambda:TLS())
    runtime=RuntimeResources(time.monotonic()+5)
    runtime.cleanup_sockets=[];runtime.cleanup_workers=[]
    broker=module.TargetBroker()
    pinned=module.PinnedTarget('scoped.example','8.8.8.8',443,'/',True)
    for _ in range(6):
        def observe():
            return broker.observe(SimpleNamespace(operation='TCP_CONNECT'),pinned,
                {'timeout_seconds':5,'max_network_bytes':1024},deadline=time.monotonic()+4,
                before_io=lambda:None,runtime=runtime)
        if fail_handshake:
            with pytest.raises(ssl.SSLError):observe()
        else:assert observe()['connected']
        assert sockets and all(s.closed for s in sockets)
        assert runtime.cleanup_sockets==[]
        snapshot=resource_snapshot(runtime)
        assert verify_resource_snapshot(snapshot) and resources_verified(snapshot)
