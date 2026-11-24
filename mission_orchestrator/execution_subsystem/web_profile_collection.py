"""Fixed bounded collection; every connection goes through the Stage 6 broker."""
import base64
from dataclasses import replace
import hashlib
import logging
import re
import ssl
import time
from urllib.parse import urljoin,urlsplit,urlunsplit
from .execution_contract import ExecutionSourceRejected

REDIRECTS={301,302,303,307,308}

# OpenSSL X509 verify codes -> distinct operator-facing reason codes.
_TLS_VERIFY_REASONS={10:'WEB_PROFILE_TLS_CERT_EXPIRED',9:'WEB_PROFILE_TLS_CERT_NOT_YET_VALID',
    62:'WEB_PROFILE_TLS_HOSTNAME_MISMATCH',64:'WEB_PROFILE_TLS_HOSTNAME_MISMATCH',
    18:'WEB_PROFILE_TLS_CERT_UNTRUSTED',19:'WEB_PROFILE_TLS_CERT_UNTRUSTED',
    20:'WEB_PROFILE_TLS_CERT_UNTRUSTED',21:'WEB_PROFILE_TLS_CERT_UNTRUSTED'}

def tls_failure_reason(exc):
    """Classify a TLS failure; None when the error is not TLS related."""
    if isinstance(exc,ssl.SSLCertVerificationError):
        return _TLS_VERIFY_REASONS.get(getattr(exc,'verify_code',None),'WEB_PROFILE_TLS_VERIFY_FAILED')
    if isinstance(exc,ssl.SSLError):return 'WEB_PROFILE_TLS_HANDSHAKE_FAILED'
    return None

def redirect_destination(target,current,location):
    dest=urljoin(current,location)
    root,u=urlsplit(target),urlsplit(dest)
    origin=lambda p:(p.scheme,p.hostname,p.port or (443 if p.scheme=='https' else 80))
    prefix=root.path.rstrip('/') or '/'
    if (origin(root)!=origin(u) or u.username or u.password or u.query
        or re.search(r'[^A-Za-z0-9/._~-]',u.path) or '..' in u.path.split('/')
        or not (prefix=='/' or u.path==prefix or u.path.startswith(prefix+'/'))): return None
    return urlunsplit(u._replace(fragment=''))

class BatchCapture:
    def __init__(self): self.parts=[];self.last=None;self.complete=True;self.truncated=False
    def observe_target(self,o,*,complete):
        self.parts.append(base64.b64decode(o['response_b64'],validate=True));self.last=o
        self.complete=self.complete and complete;self.truncated=self.truncated or o['byte_limit_reached']
    def combined(self):
        data=b''.join(self.parts)
        return {**self.last,'response_bytes':len(data),'response_sha256':hashlib.sha256(data).hexdigest(),
            'response_b64':base64.b64encode(data).decode(),'byte_limit_reached':self.truncated}

class RuntimeProxy:
    def __init__(self,runtime,capture): self.runtime=runtime;self.evidence_capture=capture
    def __getattr__(self,key): return getattr(self.runtime,key)

def collect_profile(broker,adapter,pinned,target,limits,budget,*,deadline,before_io,validate_child,runtime=None,enumeration_context=None):
    capture=BatchCapture();proxy=RuntimeProxy(runtime,capture) if runtime else None
    prefix=urlsplit(target).path.rstrip('/')
    enumeration = adapter.operation == 'WEB_PROFILE_ENUMERATION'
    if enumeration:
        # Source the probe set (including verified CTI follow-up paths) from the
        # shared planner so the collector, the sandbox parser and the contract
        # verifier agree on an identical, ordered, bounded request plan.
        from adapters.profile_engine import ENUMERATION_PATHS,cti_surface_paths
        suffixes = ENUMERATION_PATHS + cti_surface_paths(enumeration_context)
    else:
        enumeration_context=None
        suffixes = ('/','/favicon.ico')
    probes=[urlunsplit(urlsplit(target)._replace(path=prefix+suffix,query='',fragment='')) for suffix in suffixes]
    frames=[];errors=[];tls_reasons=[];requests=0;remaining=limits['max_network_bytes'];last_start=None;complete=False
    try:
        for probe,initial in enumerate(probes):
            current=initial;seen=set()
            for hop in range(3):
                if requests>=budget or remaining<1024:
                    errors.append({'probe':probe,'error_code':'BUDGET_EXHAUSTED'});break
                seen.add(current)
                child=replace(pinned,path=urlsplit(current).path or '/')
                if last_start is not None:
                    wait=limits['rate_window_seconds']/limits['rate_requests']-(time.monotonic()-last_start)
                    while wait>0:
                        if runtime:runtime.check()
                        if time.monotonic()+wait>=deadline:raise TimeoutError('profile deadline')
                        time.sleep(min(.05,wait))
                        wait=limits['rate_window_seconds']/limits['rate_requests']-(time.monotonic()-last_start)
                def authorize():
                    fresh=before_io();validate_child(current,child);return fresh
                request_limits={**limits,'max_network_bytes':min(remaining,65536 if enumeration else 270336 if probe==0 else 69632)}
                requests+=1;last_start=time.monotonic()
                try:
                    raw=broker.observe(adapter,child,request_limits,deadline=deadline,before_io=authorize,runtime=proxy)
                except (OSError,TimeoutError) as exc:
                    tls_reason=tls_failure_reason(exc)
                    tls_reasons.append(tls_reason)
                    logging.getLogger(__name__).warning('WPT collection connection failed probe=%s reason=%s tls=%s',
                                                        probe,type(exc).__name__,tls_reason)
                    errors.append({'probe':probe,'error_code':'CONNECTION_FAILED'});break
                if not runtime:capture.observe_target(raw,complete=True)
                data=base64.b64decode(raw['response_b64'],validate=True)
                remaining-=len(data)+len(child.path.encode('ascii'))+len(child.host)+512
                frame={'offset':sum(map(len,capture.parts[:-1])),'length':len(data),'probe':probe,'url':current,
                    'redirect_count':hop,'redirect_blocked':False,'truncated':raw['byte_limit_reached']}
                frames.append(frame)
                header=data.partition(b'\r\n\r\n')[0]
                status=re.match(rb'HTTP/1\.[01] ([1-5][0-9]{2})',header)
                if status is None or int(status[1]) not in REDIRECTS:break
                location=next((line.split(b':',1)[1].strip().decode('latin-1') for line in header.split(b'\r\n')[1:] if line.lower().startswith(b'location:')),'')
                dest=redirect_destination(target,current,location) if location else None
                if enumeration or dest is None or dest in seen or hop==2 or requests>=budget:
                    frame['redirect_blocked']=True;break
                try:validate_child(dest,replace(pinned,path=urlsplit(dest).path or '/'))
                except ExecutionSourceRejected:frame['redirect_blocked']=True;break
                current=dest
        complete=True
        if not frames:
            # Every probe failed. When each failure was the same TLS problem,
            # report it instead of the misleading generic NO_RESPONSE.
            if tls_reasons and len(set(tls_reasons))==1 and tls_reasons[0]:
                raise ExecutionSourceRejected(tls_reasons[0])
            raise ExecutionSourceRejected('WEB_PROFILE_NO_RESPONSE')
        return {**capture.combined(),'target':target,'mode':'enumeration' if enumeration else 'fingerprinting','frames':frames,'collection_errors':errors,
            'requests_performed':requests,'request_budget':budget,
            **({'enumeration_context':enumeration_context} if enumeration and enumeration_context is not None else {})}
    finally:
        if runtime and capture.last is not None:
            runtime.evidence_capture.observe_target(capture.combined(),complete=complete and capture.complete)
