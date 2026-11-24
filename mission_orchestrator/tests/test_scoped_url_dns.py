from copy import deepcopy
from types import SimpleNamespace
import socket
import pytest

from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.target_broker import TargetBroker


URL='https://scoped.example:443'
REQUEST={'target':{'target_type':'URL','target_value':URL}}
ADAPTER=SimpleNamespace(default_port=443)


def context():
    source={'scope':{'targets':[deepcopy(REQUEST['target'])],
                     'excluded_targets':[], 'network_ranges':[]}}
    return {'mission_scope':deepcopy(source), 'pentest_context':{
        'boundary':deepcopy(source),'task':deepcopy(source)}}


def broker(answers):
    def resolve(*args,**kwargs):
        return [(socket.AF_INET6 if ':' in ip else socket.AF_INET,
                 socket.SOCK_STREAM,6,'',(ip,443)) for ip in answers]
    return TargetBroker(resolver=resolve)


@pytest.mark.parametrize('ip',['8.8.8.8','2001:4860:4860::8888'])
def test_exact_scoped_url_accepts_public_dns_and_keeps_original_host(ip):
    ctx=context();b=broker([ip]);p=b.pin(REQUEST,ctx,ADAPTER)
    assert (p.host,p.ip,p.port,p.tls)==('scoped.example',ip,443,True)
    b.validate_pin(REQUEST,ctx,ADAPTER,p)
    b.resolver=lambda *a,**kw:pytest.fail('Pinned connection must not re-resolve DNS')
    b.validate_pin(REQUEST,ctx,ADAPTER,p)


@pytest.mark.parametrize('ip',['127.0.0.1','10.0.0.1','192.168.1.1','169.254.169.254',
    '100.64.0.1','0.0.0.0','224.0.0.1','::1','fe80::1','fc00::1','::ffff:127.0.0.1'])
def test_hostname_never_grants_private_or_special_dns_access(ip):
    with pytest.raises(ExecutionSourceRejected,match='RESOLVED_ADDRESS_OUTSIDE_SCOPE'):
        broker(['8.8.8.8',ip]).pin(REQUEST,context(),ADAPTER)


@pytest.mark.parametrize('layer',['mission','boundary','task'])
def test_all_scope_layers_and_current_ip_exclusions_are_enforced(layer):
    ctx=context();b=broker(['8.8.8.8']);p=b.pin(REQUEST,ctx,ADAPTER)
    source=ctx['mission_scope'] if layer=='mission' else ctx['pentest_context'][layer]
    source['scope']['excluded_targets']=[{'target_type':'IP','target_value':p.ip}]
    with pytest.raises(ExecutionSourceRejected):b.validate_pin(REQUEST,ctx,ADAPTER,p)
    with pytest.raises(ExecutionSourceRejected):b.pin(REQUEST,ctx,ADAPTER)
    source['scope']['excluded_targets']=[]
    source['scope']['targets']=[{'target_type':'URL','target_value':'https://other.example:443'}]
    with pytest.raises(ExecutionSourceRejected):b.pin(REQUEST,ctx,ADAPTER)


def test_explicit_network_boundary_cannot_be_bypassed_by_hostname():
    ctx=context();ctx['mission_scope']['scope']['network_ranges']=['1.1.1.0/24']
    with pytest.raises(ExecutionSourceRejected):broker(['8.8.8.8']).pin(REQUEST,ctx,ADAPTER)
    p=broker(['1.1.1.1']).pin(REQUEST,ctx,ADAPTER)
    assert p.ip=='1.1.1.1'
    ctx=context();ctx['pentest_context']['task']['scope']['targets'].append(
        {'target_type':'IP','target_value':'1.1.1.1'})
    with pytest.raises(ExecutionSourceRejected):broker(['8.8.8.8']).pin(REQUEST,ctx,ADAPTER)


def test_url_port_path_and_exclusions_remain_exact():
    for target in ['https://scoped.example:444','https://scoped.example:443/other',
                   'http://scoped.example:443','https://other.example:443']:
        with pytest.raises(ExecutionSourceRejected):
            broker(['8.8.8.8']).pin({'target':{'target_type':'URL','target_value':target}},context(),ADAPTER)
    ctx=context();ctx['mission_scope']['scope']['excluded_targets']=[deepcopy(REQUEST['target'])]
    with pytest.raises(ExecutionSourceRejected):broker(['8.8.8.8']).pin(REQUEST,ctx,ADAPTER)


@pytest.mark.parametrize('answers', [['127.0.0.1'], ['::1'], ['127.0.0.1', '::1']])
def test_lab_localhost_accepts_loopback_only_in_all_scope_layers(answers):
    request = {'target': {'target_type': 'URL', 'target_value': 'http://localhost:8080/WebGoat'}}
    source = {'scope': {'targets': [{**request['target'], 'environment': 'LAB'}],
                        'excluded_targets': [], 'network_ranges': []}}
    ctx = {'mission_scope': deepcopy(source), 'pentest_context': {
        'boundary': deepcopy(source), 'task': deepcopy(source)}}
    b = broker(answers)
    pin = b.pin(request, ctx, ADAPTER)
    b.validate_pin(request, ctx, ADAPTER, pin)
    for layer in [ctx['mission_scope'], ctx['pentest_context']['boundary'], ctx['pentest_context']['task']]:
        layer['scope']['targets'][0]['environment'] = 'PRODUCTION'
        with pytest.raises(ExecutionSourceRejected): b.pin(request, ctx, ADAPTER)
        layer['scope']['targets'][0]['environment'] = 'LAB'
    ctx['mission_scope']['scope']['network_ranges'] = ['10.0.0.0/8']
    with pytest.raises(ExecutionSourceRejected): b.pin(request, ctx, ADAPTER)
    ctx['mission_scope']['scope']['network_ranges'] = []
    ctx['mission_scope']['scope']['excluded_targets'] = [{'target_type':'IP','target_value':answers[0]}]
    with pytest.raises(ExecutionSourceRejected): b.pin(request, ctx, ADAPTER)


def test_lab_localhost_rejects_non_loopback_dns():
    request = {'target': {'target_type':'URL','target_value':'http://localhost:8080/WebGoat'}}
    source = {'scope': {'targets': [{**request['target'], 'environment':'LAB'}]}}
    ctx = {'mission_scope':source,'pentest_context':{'boundary':source,'task':source}}
    for ip in ['8.8.8.8','10.0.0.1']:
        with pytest.raises(ExecutionSourceRejected): broker([ip]).pin(request,ctx,ADAPTER)
