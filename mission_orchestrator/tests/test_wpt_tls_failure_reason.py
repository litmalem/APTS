import ssl,time
import pytest
from execution_subsystem.adapter_policy import DEFAULT_LIMITS
from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.target_broker import PinnedTarget
from execution_subsystem.tool_registry import ADAPTERS
from execution_subsystem.web_profile_collection import collect_profile,tls_failure_reason
ADAPTER=next(a for a in ADAPTERS if a.operation=='WEB_PROFILE_FINGERPRINT')
LIMITS={**DEFAULT_LIMITS,'timeout_seconds':15,'max_network_bytes':393216,'max_output_bytes':60000,'rate_requests':100,'rate_window_seconds':.01}

def verify_error(code):
    e=ssl.SSLCertVerificationError(1,'verify failed');e.verify_code=code;return e

class FailingBroker:
    def __init__(self,exc):self.exc=exc
    def observe(self,*a,**k):raise self.exc

def run(exc):
    pin=PinnedTarget('127.0.0.1','127.0.0.1',8443,'/benchmark',True)
    return collect_profile(FailingBroker(exc),ADAPTER,pin,'https://localhost:8443/benchmark',LIMITS,6,
                           deadline=time.monotonic()+8,before_io=lambda:None,validate_child=lambda u,p:None)

@pytest.mark.parametrize('exc,reason',[
    (verify_error(18),'WEB_PROFILE_TLS_CERT_UNTRUSTED'),
    (verify_error(20),'WEB_PROFILE_TLS_CERT_UNTRUSTED'),
    (verify_error(10),'WEB_PROFILE_TLS_CERT_EXPIRED'),
    (verify_error(62),'WEB_PROFILE_TLS_HOSTNAME_MISMATCH'),
    (verify_error(64),'WEB_PROFILE_TLS_HOSTNAME_MISMATCH'),
    (verify_error(999),'WEB_PROFILE_TLS_VERIFY_FAILED'),
    (ssl.SSLError('handshake'),'WEB_PROFILE_TLS_HANDSHAKE_FAILED')])
def test_tls_failures_report_specific_reason(exc,reason):
    with pytest.raises(ExecutionSourceRejected,match='^'+reason+'$'):run(exc)

@pytest.mark.parametrize('exc',[ConnectionRefusedError(),TimeoutError()])
def test_non_tls_failures_keep_generic_reason(exc):
    with pytest.raises(ExecutionSourceRejected,match='^WEB_PROFILE_NO_RESPONSE$'):run(exc)

def test_classifier_ignores_non_tls_errors():
    assert tls_failure_reason(OSError()) is None
