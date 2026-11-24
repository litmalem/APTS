import json
from io import BytesIO
from threading import Lock, Thread
from types import SimpleNamespace

import pytest
import requests
from gss_web.server import Server, Handler

TOKEN='internal-local-test-'+'x'*40

@pytest.fixture
def web():
    servers=[]
    def start(enabled=True):
        server=Server(0,quick_login_token=TOKEN if enabled else '')
        calls=[]
        def upstream(path,token,body=None):
            calls.append((path,token))
            return {'principal_id':'local-test-operator','roles':['GOVERNANCE_ADMIN'],'capabilities':['read','scope']}
        server.upstream=upstream
        Thread(target=server.serve_forever,daemon=True).start();servers.append(server)
        base=f'http://127.0.0.1:{server.server_port}'
        session=requests.Session();session.headers['Origin']=base
        return base,session,calls
    yield start
    for server in servers:server.shutdown();server.server_close()

def test_quick_login_keeps_internal_token_out_of_browser_and_preserves_csrf(web):
    base,client,calls=web()
    options=client.get(base+'/api/login-options')
    assert options.json()=={'quick_login':True,'mode':'LOCAL_TEST'}
    result=client.post(base+'/api/login',json={'quick_login':True,'roles':['FORGED']})
    assert result.status_code==200
    assert result.json()['principal_id']=='local-test-operator'
    assert result.json()['roles']==['GOVERNANCE_ADMIN']
    assert TOKEN not in result.text and TOKEN not in str(result.headers)
    assert calls==[('/api/governance/console/me',TOKEN)]
    assert 'HttpOnly' in result.headers['Set-Cookie'] and 'SameSite=Strict' in result.headers['Set-Cookie']
    assert client.post(base+'/api/logout',json={}).status_code==403
    csrf=result.json()['csrf']
    assert client.get(base+'/api/session').status_code==200
    assert client.post(base+'/api/logout',json={},headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.get(base+'/api/session').status_code==401

def test_default_server_requires_credential(web):
    base,client,calls=web(False)
    assert client.get(base+'/api/login-options').json()['quick_login'] is False
    assert client.post(base+'/api/login',json={'quick_login':True}).status_code==403
    assert client.post(base+'/api/login',json={}).status_code==401
    assert not calls

def test_quick_login_rejects_cross_origin(web):
    base,client,calls=web()
    assert client.post(base+'/api/login',json={'quick_login':True},headers={'Origin':'https://outside.test'}).status_code==403
    assert not calls

def test_standard_token_login_remains_available(web):
    base,client,calls=web()
    personal='personal-'+'z'*40
    assert client.post(base+'/api/login',json={'token':personal}).status_code==200
    assert calls[0][1]==personal

def test_quick_login_rejects_non_loopback_peer():
    handler=object.__new__(Handler)
    body=json.dumps({'quick_login':True}).encode()
    handler.server=SimpleNamespace(server_port=8802,lock=Lock(),login_attempts=[],quick_login_token=TOKEN)
    handler.client_address=('192.0.2.10',1234)
    handler.path='/api/login'
    handler.headers={'Host':'127.0.0.1:8802','Origin':'http://127.0.0.1:8802','Content-Length':str(len(body)),'Content-Type':'application/json'}
    handler.rfile=BytesIO(body)
    replies=[];handler.reply=lambda status,data:replies.append((status,data))
    handler.do_POST()
    assert replies[0][0]==403
