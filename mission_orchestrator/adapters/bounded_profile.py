"""Pure metadata parser, loaded before sandbox filesystem/network lockdown."""
from http.client import HTTPResponse,IncompleteRead
from io import BytesIO
import hashlib,re
from urllib.parse import urlsplit
from adapters.profile_engine import normalize_responses,_extract_findings,_parse_html,plan_requests
from adapters.profile_contract import SAFE_HEADERS,OBS
class Socket:
    def __init__(self,data):self.data=data
    def makefile(self,*args):return BytesIO(self.data)
def safe_url(value):
    u=urlsplit(value);path=re.sub(r'(?i);(?:jsessionid|sessionid|sid)=[^/;]*',';session=[REDACTED]',u.path)
    return u._replace(path=path,query='',fragment='').geturl()[:2048]
def parse_batch(observation,data):
    mode=observation.get('mode','fingerprinting');enumeration=mode=='enumeration'
    if mode not in ('fingerprinting','enumeration'):raise ValueError('invalid profile')
    enumeration_context=observation.get('enumeration_context') if enumeration else None
    count=len(plan_requests(observation['target'],'enumeration',enumeration_context)) if enumeration else 2
    frames=observation['frames']
    if not isinstance(frames,list) or not 1<=len(frames)<=6:raise ValueError('invalid frames')
    responses=[{'status_code':None,'headers':{}} for _ in range(count)]
    extra={};statuses=[];end=0
    for frame in frames:
        start,size,probe=frame['offset'],frame['length'],frame['probe']
        if (type(start) is not int or type(size) is not int or type(probe) is not int or not 0<=probe<count
            or start<end or size<0 or start+size>len(data)):raise ValueError('invalid frame range')
        end=start+size;response=HTTPResponse(Socket(data[start:end]));response.begin()
        try:body=response.read(262144 if probe==0 else 65536)
        except IncompleteRead as exc:body=exc.partial[:262144 if probe==0 else 65536]
        headers={k.lower():v[:500] for k,v in response.getheaders() if k.lower() in SAFE_HEADERS}
        names=[]
        for cookie in response.headers.get_all('set-cookie',[]):
            name=cookie.split('=',1)[0].strip()
            if re.fullmatch(r'[A-Za-z0-9_!#$%&*+.^`|~-]{1,100}',name):names.append(name)
        html=body.decode('utf-8',errors='replace') if 'html' in headers.get('content-type','').lower() and response.headers.get('content-encoding','identity').lower()=='identity' else ''
        for f in _extract_findings(headers,html,_parse_html(html),names):
            old=extra.get(f['technology'])
            if old is None or f['evidence_strength_score']>old['evidence_strength_score']:extra[f['technology']]=f
        responses[probe]={'status_code':response.status,'headers':headers,'html_excerpt':html,
            'cookie_names':sorted(set(names+responses[probe].get('cookie_names',[])))[:30],
            'final_url':safe_url(frame['url']),'redirect_count':frame['redirect_count'],'redirect_blocked':frame['redirect_blocked'],
            'body_sha256':hashlib.sha256(body).hexdigest() if not frame['truncated'] else '', 'body_bytes_observed':len(body)}
        statuses.append(response.status)
    normalized=normalize_responses(observation['target'],mode,responses,enumeration_context)
    observations=[]
    for item in normalized['observations']:
        item={k:v for k,v in item.items() if k in OBS}
        # The governed collector uses GET for its fixed metadata probes.
        item['method']='GET'
        item['url']=safe_url(item['url'])
        if 'script_sources' in item:item['script_sources']=[urlsplit(safe_url(a)).path[:500] for a in item['script_sources']][:40]
        observations.append(item)
    findings=list(extra.values())[:32]
    metrics=normalized['scan_metrics']
    metrics.update(requests_planned=count,requests_performed=observation['requests_performed'],request_budget=observation['request_budget'],
        responses_received=len(frames),response_rate_percent=round(100*len(frames)/observation['requests_performed']),
        request_errors=len(observation['collection_errors']),fingerprints_matched=len(findings),
        redirects_observed=sum(s in (301,302,303,307,308) for s in statuses),redirects_blocked=sum(f['redirect_blocked'] for f in frames),
        evidence_strength_index_max=max((f['evidence_strength_score'] for f in findings),default=0),
        scan_status='PARTIAL' if observation['collection_errors'] or any(f['redirect_blocked'] or f['truncated'] for f in frames) else 'COMPLETED')
    binding={k:observation[k] for k in ('connected','peer_ip','response_bytes','response_sha256','byte_limit_reached')};binding['http_status']=statuses[0]
    return {'schema_version':'web-technology-observation-v4','target':observation['target'],'mode':mode,
        **({'surface_candidates':normalized['surface_candidates']} if enumeration else {}),
        **({'enumeration_context':enumeration_context} if enumeration and enumeration_context is not None else {}),
        'observations':observations,'technology_findings':findings,'scan_metrics':metrics,'network_binding':binding,
        'fingerprint_status':'SIGNATURES_FOUND' if findings else 'NO_MATCH','favicon_status':normalized['favicon_status'],
        'tls_status':'NOT_APPLICABLE_HTTP' if urlsplit(observation['target']).scheme=='http' else 'UNAVAILABLE',
        'collection_errors':observation['collection_errors']}
