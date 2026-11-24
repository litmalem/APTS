from test_web_console import web, login
import pytest

@pytest.mark.parametrize('route',['pip-build','pip-binding'])
def test_viewer_cannot_initialize_pip(web,route):
    server,url,session,_,_=web
    headers,_=login(web)
    r=session.post(url+'/api/human/missions/mission-1/'+route,json={},headers=headers)
    assert r.status_code==403
    assert not server._mission_calls


def test_author_binding_uses_session_principal_and_csrf(web):
    server,url,session,_,_=web
    server.upstream=lambda *a,**k:{'principal_id':'operator-real','capabilities':['read','mission_author']}
    headers,_=login(web)
    path=url+'/api/human/missions/mission-1/pip-binding'
    assert session.post(path,json={},headers={'Origin':url}).status_code==403
    p={'actor':'forged','pip_id':'pip-1','pip_version':'1','expected_envelope_version':1,'idempotency_key':'key','reason':'test'}
    assert session.post(path,json=p,headers=headers).status_code==200
    assert server._mission_calls[-1][1]['actor']=='operator-real'
    assert server._mission_calls[-1][0]=='/api/missions/mission-1/pip-binding'


def test_author_can_build_and_read_pip_status(web):
    server,url,session,_,_=web
    server.upstream=lambda *a,**k:{'principal_id':'operator-real','capabilities':['read','mission_author']}
    headers,_=login(web)
    assert session.post(url+'/api/human/missions/mission-1/pip-build',json={'asset_profiles':[]},headers=headers).status_code==200
    assert server._mission_calls[-1]==('/api/missions/mission-1/pip-build',{'asset_profiles':[]})
    assert session.get(url+'/api/human/missions/mission-1/pip-binding').status_code==200
    assert server._mission_calls[-1]==('/api/missions/mission-1/pip-binding',None)
