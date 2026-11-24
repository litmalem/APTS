"""Strict sanitized metadata contract for bounded fingerprint collection."""
import re
from urllib.parse import urlsplit
SAFE_HEADERS=frozenset({'server','x-powered-by','x-generator','content-type','x-aspnet-version','x-drupal-cache','x-runtime',
'x-frame-options','x-content-type-options','content-security-policy','strict-transport-security','referrer-policy','permissions-policy','cache-control'})
TOP={'schema_version','target','mode','network_binding','observations','technology_findings','scan_metrics','fingerprint_status','favicon_status','tls_status','collection_errors'}
OBS={'url','method','status_code','headers','final_url','redirect_count','redirect_blocked','cookie_names','page_title','script_sources','favicon_fingerprint'}
FIND={'technology','evidence_strength_score','confidence_level','evidence_count','independent_evidence_families','evidence','technology_type','observed_version'}
METRICS={'scan_status','requests_planned','requests_performed','request_budget','responses_received','response_rate_percent','request_errors','html_responses','headers_observed','favicon_fingerprints','redirects_observed','redirects_blocked','tls_sessions','fingerprints_matched','evidence_strength_index_max'}
def validate_profile(v):
    def check(ok):
        if not ok:raise ValueError('INVALID_BOUNDED_WEB_PROFILE_RESULT')
    def text(s,n=500):check(isinstance(s,str) and len(s)<=n and not any(ord(c)<32 and c!='\t' for c in s))
    def number(n,cap=1000000):check(type(n) is int and 0<=n<=cap)
    def digest(s):check(isinstance(s,str) and re.fullmatch('[a-f0-9]{64}',s) is not None)
    def url(s):
        text(s,2048);u=urlsplit(s);check(u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password and not u.query and not u.fragment)
    check(isinstance(v,dict) and v.get('mode') in ('fingerprinting','enumeration'))
    enumeration=v['mode']=='enumeration'
    planned_urls=None
    if enumeration:
        from adapters.profile_engine import plan_requests,ENUMERATION_PATHS,MAX_CTI_SURFACE_PROBES
        enumeration_context=v.get('enumeration_context')
        check(enumeration_context is None or isinstance(enumeration_context,dict))
        planned_urls=[p['url'] for p in plan_requests(v['target'],'enumeration',enumeration_context)]
        count=len(planned_urls);cap=len(ENUMERATION_PATHS)+MAX_CTI_SURFACE_PROBES
    else:
        count=2;cap=6
    allowed=TOP|({'surface_candidates'} if enumeration else set())
    if enumeration and 'enumeration_context' in v:
        allowed=allowed|{'enumeration_context'}
    check(set(v)==allowed and v['schema_version']=='web-technology-observation-v4')
    url(v['target']);b=v['network_binding']
    check(isinstance(b,dict) and set(b)=={'connected','peer_ip','response_bytes','response_sha256','byte_limit_reached','http_status'})
    check(type(b['connected']) is bool and type(b['byte_limit_reached']) is bool)
    import ipaddress
    ipaddress.ip_address(b['peer_ip']);number(b['response_bytes'],393216);digest(b['response_sha256']);check(type(b['http_status']) is int and 100<=b['http_status']<=599)
    check(isinstance(v['observations'],list) and len(v['observations'])==count)
    for o in v['observations']:
        check(isinstance(o,dict) and set(o)<=OBS and {'url','method','status_code','headers'}<=set(o));url(o['url']);check(o['method']=='GET')
        check(o['status_code'] is None or type(o['status_code']) is int and 100<=o['status_code']<=599)
        check(isinstance(o['headers'],dict) and set(o['headers'])<=SAFE_HEADERS)
        for value in o['headers'].values():text(value)
        if 'final_url' in o:url(o['final_url'])
        if 'redirect_count' in o:number(o['redirect_count'],2)
        if 'redirect_blocked' in o:check(type(o['redirect_blocked']) is bool)
        if 'page_title' in o:text(o['page_title'],300)
        names=o.get('cookie_names',[]);check(isinstance(names,list) and len(names)<=30)
        for name in names:check(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_!#$%&*+.^`|~-]{1,100}',name) is not None)
        assets=o.get('script_sources',[]);check(isinstance(assets,list) and len(assets)<=40)
        for asset in assets:
            text(asset);p=urlsplit(asset);check(not p.query and not p.fragment and not p.netloc)
        if 'favicon_fingerprint' in o:
            f=o['favicon_fingerprint'];check(isinstance(f,dict) and set(f)=={'sha256','bytes_observed','media_type'})
            digest(f['sha256']);number(f['bytes_observed'],65536);text(f['media_type']);check(f['media_type'].lower().startswith('image/'))
    findings=v['technology_findings'];check(isinstance(findings,list) and len(findings)<=32)
    for f in findings:
        check(isinstance(f,dict) and set(f)<=FIND and {'technology','evidence_strength_score','confidence_level','evidence_count','independent_evidence_families','evidence'}<=set(f))
        text(f['technology'],200);number(f['evidence_strength_score'],100);number(f['evidence_count'],100);check(f['confidence_level'] in ('low','medium','high'))
        for key in ('technology_type','observed_version'):
            if key in f:text(f[key],100)
        families=f['independent_evidence_families'];check(isinstance(families,list) and len(families)<=10)
        for family in families:text(family,100)
        check(isinstance(f['evidence'],list) and len(f['evidence'])<=100)
        for e in f['evidence']:
            check(isinstance(e,dict) and set(e)=={'signal','family','value','weight'})
            for key in ('signal','family','value'):text(e[key],200)
            number(e['weight'],100)
    m=v['scan_metrics'];check(isinstance(m,dict) and set(m)==METRICS and m['scan_status'] in ('COMPLETED','PARTIAL','NO_RESPONSE'))
    for key,n in m.items():
        if key!='scan_status':number(n)
    check(m['requests_planned']==count and 1<=m['requests_performed']<=m['request_budget']<=cap and 1<=m['responses_received']<=m['requests_performed'])
    if enumeration:
        check({o['url'] for o in v['observations']}==set(planned_urls))
        candidates=v['surface_candidates'];check(isinstance(candidates,list) and len(candidates)<=count)
        observed={(o['url'],o['status_code']) for o in v['observations'] if o['status_code'] is not None}
        for c in candidates:
            check(isinstance(c,dict) and set(c)=={'url','status_code','source'} and c['source']=='bounded_probe')
            check((c['url'],c['status_code']) in observed and c['status_code'] not in (404,410))
    check(m['response_rate_percent']==round(100*m['responses_received']/m['requests_performed']) and m['fingerprints_matched']==len(findings))
    check(v['fingerprint_status'] in ('SIGNATURES_FOUND','NO_MATCH'))
    check(v['favicon_status'] in ('CAPTURED','REDIRECTED','MISSING','UNAVAILABLE','NON_IMAGE_RESPONSE','NO_SIGNATURE'))
    check(v['tls_status'] in ('NOT_APPLICABLE_HTTP','UNAVAILABLE'))
    errors=v['collection_errors'];check(isinstance(errors,list) and len(errors)<=6)
    for e in errors:check(isinstance(e,dict) and set(e)=={'probe','error_code'} and type(e['probe']) is int and 0<=e['probe']<count and e['error_code'] in ('BUDGET_EXHAUSTED','CONNECTION_FAILED'))
    import json
    check(len(json.dumps(v,ensure_ascii=False).encode('utf-8'))<=55000)
    return v
