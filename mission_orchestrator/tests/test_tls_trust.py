from types import SimpleNamespace
import ssl
import pytest
from execution_subsystem import tls_trust


def test_windows_loads_only_roots_trusted_for_server_auth(monkeypatch):
    root=ssl.create_default_context().get_ca_certs(binary_form=True)[0]
    stores=[]
    def certificates(store):
        stores.append(store)
        assert store=='ROOT'  # Never import stale cached CA intermediates.
        return [(root,'x509_asn',{ssl.Purpose.SERVER_AUTH.oid}),
                (b'not-a-certificate','x509_asn',{'unrelated-purpose'}),
                (b'not-a-certificate','pkcs_7_asn',True)]
    monkeypatch.setattr(tls_trust,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(ssl,'enum_certificates',certificates,raising=False)
    context=tls_trust.create_verified_tls_context()
    assert stores==['ROOT']
    assert root in context.get_ca_certs(binary_form=True)
    assert context.check_hostname is True
    assert context.verify_mode==ssl.CERT_REQUIRED


def test_empty_windows_root_store_fails_closed(monkeypatch):
    monkeypatch.setattr(tls_trust,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(ssl,'enum_certificates',lambda store:[],raising=False)
    with pytest.raises(ssl.SSLError,match='No trusted Windows'):
        tls_trust.create_verified_tls_context()


def test_other_platform_uses_default_verified_context(monkeypatch):
    monkeypatch.setattr(tls_trust,'sys',SimpleNamespace(platform='linux'))
    context=tls_trust.create_verified_tls_context()
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
