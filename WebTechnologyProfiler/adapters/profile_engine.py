"""Bounded, deterministic web technology signature extraction.

This module has no network client. A registered Mission/Stage 6 adapter must
perform each planned request through its authorized target broker. Fingerprint
scores describe evidence strength, not calibrated probabilities or vulnerabilities.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

FINGERPRINT_PATHS = ('/', '/favicon.ico')
ENUMERATION_PATHS = ('/', '/robots.txt', '/sitemap.xml', '/.well-known/security.txt', '/favicon.ico')
SENSITIVE_HEADERS = {'set-cookie', 'authorization', 'proxy-authorization', 'www-authenticate'}
MAX_HTML_BYTES = 262144

# CTI-driven follow-up surface probes. A FIXED registry keyed by CPE vendor /
# product (or an observed technology name), NOT arbitrary probes: enumeration may
# only ever request the deterministic, bounded, low-impact well-known paths listed
# here when the Vulndesk CTI enrichment identifies that technology. Each path is a
# single bounded GET under the authorized scope prefix; nothing here follows
# redirects, carries a body, or probes outside the registry.
CTI_SURFACE_PROBES = {
    'nginx': ('/nginx_status',),
    'apache': ('/server-status', '/server-info'),
    'http_server': ('/server-status', '/server-info'),
    'httpd': ('/server-status', '/server-info'),
    'tomcat': ('/manager/status',),
    'iis': ('/trace.axd',),
    'asp.net': ('/trace.axd', '/elmah.axd'),
    'php': ('/phpinfo.php',),
    'wordpress': ('/wp-login.php', '/wp-json/'),
    'drupal': ('/user/login', '/CHANGELOG.txt'),
    'jenkins': ('/login',),
}
# Hard ceiling on CTI-derived probes appended to the fixed enumeration base,
# so the bounded request plan can never grow unbounded from enrichment data.
MAX_CTI_SURFACE_PROBES = 4


def _cti_surface_tokens(enumeration_context) -> set:
    """Lowercased vendor/product/technology tokens from verified CTI enrichment."""
    tokens: set = set()
    if not isinstance(enumeration_context, dict):
        return tokens
    for technology in enumeration_context.get('technologies') or ():
        name = technology.get('name') if isinstance(technology, dict) else None
        if isinstance(name, str) and name.strip():
            tokens.add(name.strip().lower())
    for candidate in enumeration_context.get('cpe_candidates') or ():
        uri = candidate.get('cpe23_uri') if isinstance(candidate, dict) else None
        if not isinstance(uri, str) or not uri.startswith('cpe:2.3:'):
            continue
        parts = uri.split(':')
        # cpe:2.3:<part>:<vendor>:<product>:<version>:...
        for component in parts[3:5]:
            if component and component not in ('*', '-'):
                tokens.add(component.strip().lower())
    return tokens


def cti_surface_paths(enumeration_context) -> tuple:
    """Deterministic, bounded CTI follow-up paths; empty without matching enrichment."""
    tokens = _cti_surface_tokens(enumeration_context)
    derived: list = []
    for token in sorted(tokens):
        for path in CTI_SURFACE_PROBES.get(token, ()):
            if path not in derived and path not in ENUMERATION_PATHS:
                derived.append(path)
    return tuple(sorted(derived)[:MAX_CTI_SURFACE_PROBES])
SESSION_PATH_PARAMETER = re.compile(r'(?i)(;(?:jsessionid|sessionid|sid)=)[^/?#;]+')
TECHNOLOGY_TYPES = {
    'nginx': 'web_server_or_reverse_proxy',
    'PHP': 'server_runtime',
    'Yii Framework': 'application_framework',
}


class _HTMLSignals(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_text = []
        self.meta = []
        self.scripts = []
        self.links = []
        self.attributes = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title': self.in_title = True
        if tag == 'meta':
            name = (attrs.get('name') or attrs.get('property') or '').lower()
            if name in ('generator', 'application-name', 'og:site_name') and attrs.get('content'):
                self.meta.append({'name': name, 'value': attrs['content'][:200]})
        if tag == 'script' and attrs.get('src'): self.scripts.append(attrs['src'][:500])
        if tag == 'a' and attrs.get('href'): self.links.append(attrs['href'][:500])
        for key, value in attrs.items():
            if key in ('ng-version', 'data-reactroot', 'data-v-app', 'data-vue-meta'):
                self.attributes.append({'name': key, 'value': str(value or '')[:100]})
            if key in ('id', 'class', 'src', 'href', 'name', 'content', 'action') and value:
                self.attributes.append({'name': key, 'value': str(value)[:500]})
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
    def handle_data(self, data):
        if self.in_title and sum(map(len, self.title_text)) < 300:
            self.title_text.append(data[:300])


def plan_requests(target: str, mode: str, enumeration_context=None) -> list[dict]:
    """Return the fixed small request set; caller binds it to authorized scope.

    For enumeration, verified Vulndesk CTI enrichment (``enumeration_context``)
    deterministically appends bounded follow-up probes from ``CTI_SURFACE_PROBES``.
    The base set is unchanged and fingerprinting ignores the context entirely, so
    callers that pass nothing keep the original behaviour.
    """
    parsed = urlparse(target)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Invalid web target URL')
    if mode not in ('fingerprinting', 'enumeration'): raise ValueError('Unsupported profile mode')
    if mode == 'fingerprinting':
        paths = FINGERPRINT_PATHS
        cti_paths = ()
    else:
        cti_paths = cti_surface_paths(enumeration_context)
        paths = ENUMERATION_PATHS + cti_paths
    return [{'method': 'GET' if path == '/' or (mode == 'fingerprinting' and path == '/favicon.ico') else 'HEAD',
             'url': urljoin(target.rstrip('/') + '/', path.lstrip('/')),
             'purpose': ('technology_signature' if path == '/' else 'favicon_fingerprint') if mode == 'fingerprinting'
                        else 'cti_surface_metadata' if path in cti_paths else 'bounded_surface_metadata',
             'max_response_bytes': MAX_HTML_BYTES if path == '/' else 65536 if path == '/favicon.ico' else 0,
             'follow_redirects': False} for path in paths]


def _clean(value, limit=200):
    return ' '.join(str(value).split())[:limit]


def _extract_findings(headers, html, parser, cookie_names=(), redirect_locations=()):
    """Apply explicit signatures and aggregate unique evidence into a 0..100 index."""
    evidence: dict[str, list[dict]] = {}
    versions: dict[str, str] = {}
    def add(product, signal_id, family, value, weight):
        entry = {'signal': signal_id, 'family': family, 'value': _clean(value), 'weight': weight}
        bucket = evidence.setdefault(product, [])
        if not any(item['signal'] == signal_id and item['value'] == entry['value'] for item in bucket):
            bucket.append(entry)

    for meta in parser.meta:
        product = _clean(meta['value'])
        version_match = re.match(r'^(.+?)\s+v?(\d+(?:\.\d+){1,3}(?:[-+][\w.-]+)?)$', product, re.I)
        if version_match:
            product = version_match.group(1).strip()
            versions[product] = version_match.group(2)
        if meta['name'] == 'generator': add(product, 'html.meta.generator', 'html_meta', meta['value'], 90)
        else: add(product, 'html.meta.' + meta['name'], 'html_meta', meta['value'], 45)
    powered = headers.get('x-powered-by')
    if powered:
        match=re.fullmatch(r'([A-Za-z][A-Za-z .-]*?)/([0-9][A-Za-z0-9._+-]*)',powered.strip())
        product=match[1] if match else powered
        if match:versions[product]=match[2]
        add(product, 'http.x-powered-by', 'http_header', powered, 70)
    generator = headers.get('x-generator')
    if generator: add(generator, 'http.x-generator', 'http_header', generator, 85)
    server = headers.get('server')
    if server:
        # Avoid turning a generic server banner into a CMS/framework claim.
        tokens=re.findall(r'(?i)\b(Apache|nginx|OpenSSL|PHP|Microsoft-IIS)/([0-9][A-Za-z0-9._+-]*)',server)
        if tokens:
            aliases={'apache':'Apache HTTP Server','nginx':'nginx','openssl':'OpenSSL','php':'PHP','microsoft-iis':'Microsoft IIS'}
            for name,version in tokens:
                product=aliases[name.lower()];versions[product]=version
                add(product,'http.server','http_header',name+'/'+version,65)
        else:
            add(server, 'http.server', 'http_header', server, 65)
    header_signatures = [
        ('ASP.NET', 'http.x-aspnet-version', 'x-aspnet-version', 70),
        ('Drupal', 'http.x-drupal-cache', 'x-drupal-cache', 45),
        ('Ruby on Rails', 'http.x-runtime', 'x-runtime', 50),
    ]
    for product, signal, key, weight in header_signatures:
        if headers.get(key): add(product, signal, 'http_header', headers[key], weight)

    cookie_rules = [
        ('PHP', r'^phpsessid$', 58),
        ('WordPress', 'wordpress_logged_in_|wordpress_test_cookie', 65),
        ('Laravel', r'laravel_session|xsrf-token', 65),
        ('Django', r'^csrftoken$|^sessionid$', 50),
        ('Java Servlet', r'^jsessionid$', 55),
        ('ASP.NET', r'^asp\.net_sessionid$', 65),
        ('Express.js', r'^connect\.sid$', 55),
        ('Drupal', r'^s?se?ss[a-f0-9]+$', 45),
    ]
    for cookie_name in cookie_names:
        for product, pattern, weight in cookie_rules:
            if re.search(pattern, cookie_name, re.I):
                add(product, 'http.cookie_name', 'cookie_name', cookie_name, weight)

    # URL-based servlet session tracking is a useful signal when Set-Cookie is
    # absent and the server places its session identifier in a redirect path.
    for location in redirect_locations:
        if SESSION_PATH_PARAMETER.search(str(location)):
            add('Java Servlet', 'http.redirect.jsessionid', 'redirect_behavior',
                SESSION_PATH_PARAMETER.sub(r'\1[REDACTED]', str(location)), 65)

    text = html.lower()
    attrs = ' '.join(item['name'] + '=' + item['value'] for item in parser.attributes).lower()
    scripts = ' '.join(parser.scripts).lower()
    combined = text + '\n' + attrs + '\n' + scripts
    # Yii 2 commonly registers yii.js plus its validation/ActiveForm assets
    # under hashed /assets/<bundle>/ paths. Require a small asset cluster so a
    # coincidental file named yii.js alone does not create a framework claim.
    yii_asset_names = {'yii.js', 'yii.validation.js', 'yii.activeform.js'}
    observed_yii_assets = sorted({
        urlparse(src).path.rsplit('/', 1)[-1].lower()
        for src in parser.scripts
        if urlparse(src).path.rsplit('/', 1)[-1].lower() in yii_asset_names
    })
    if 'yii.js' in observed_yii_assets and len(observed_yii_assets) >= 2:
        add('Yii Framework', 'html.yii.asset_bundle', 'html_asset',
            ', '.join(observed_yii_assets), 78)
    patterns = [
        ('WordPress', 'html.path.wp-content', r'/wp-content/|/wp-includes/', 'html_asset', 60),
        ('Drupal', 'html.drupal.settings', r'drupalsettings|drupal\.js|/sites/default/files/', 'html_runtime', 65),
        ('Joomla', 'html.joomla.marker', r'/media/system/js/|com_content|joomla!', 'html_asset', 60),
        ('Next.js', 'html.next.marker', r'/_next/static/|__next_data__', 'html_runtime', 65),
        ('Nuxt', 'html.nuxt.marker', r'/_nuxt/|__nuxt__', 'html_runtime', 65),
        ('Angular', 'html.angular.marker', r'ng-version=|ng-app=|<app-root\b', 'html_attribute', 65),
        ('Vue.js', 'html.vue.marker', r'data-v-[0-9a-f]{6,}|data-v-app=|__vue__', 'html_runtime', 55),
        ('React', 'html.react.marker', r'data-reactroot=|__react_devtools|react\.production\.min\.js', 'html_runtime', 55),
        ('Django', 'html.django.csrf', r'name=["\']csrfmiddlewaretoken["\']|csrfmiddlewaretoken', 'html_form', 45),
        ('ASP.NET', 'html.aspnet.marker', r'__viewstate|__aspnetform', 'html_form', 65),
        ('OWASP Juice Shop', 'html.title.juice-shop', r'<title[^>]*>\s*owasp juice shop\s*</title>', 'html_title', 80),
    ]
    for product, signal, pattern, family, weight in patterns:
        match = re.search(pattern, combined, re.I)
        if match: add(product, signal, family, match.group(0), weight)

    findings = []
    for product, items in sorted(evidence.items()):
        # Strongest observation dominates; independent signal families add support.
        families = sorted({item['family'] for item in items})
        score = min(100, max(item['weight'] for item in items) + 12 * (len(items) - 1) + 8 * (len(families) - 1))
        level = 'high' if score >= 75 else 'medium' if score >= 45 else 'low'
        finding = {'technology': product, 'evidence_strength_score': score,
                         'confidence_level': level, 'evidence_count': len(items),
                         'independent_evidence_families': families, 'evidence': items}
        if product in TECHNOLOGY_TYPES:
            finding['technology_type'] = TECHNOLOGY_TYPES[product]
        if product in versions: finding['observed_version'] = versions[product]
        findings.append(finding)
    return findings


def _security_review_hints(observations, target, tls_status):
    """Suggest configuration checks from bounded observations, not vulnerability claims."""
    response = next((item for item in observations
                     if item.get('status_code') is not None and 'html' in item.get('headers', {}).get('content-type', '').lower()), {})
    headers = response.get('headers', {})
    hints = []

    def missing(header, category, recommendation):
        if header not in headers:
            hints.append({'category':category,'status':'NOT_OBSERVED_ON_PROBED_RESPONSE',
                          'evidence':f'Header {header} tidak tampak pada respons HTML yang diuji.',
                          'recommendation':recommendation})

    if urlparse(target).scheme == 'https':
        missing('strict-transport-security','HSTS',
                'Pastikan HTTPS berlaku konsisten; setelah subdomain dan kebutuhan aplikasi diverifikasi, pertimbangkan HSTS dengan masa berlaku yang sesuai.')
    missing('content-security-policy','Content Security Policy',
            'Tinjau CSP yang sesuai dengan kebutuhan aplikasi. Mulai dengan Content-Security-Policy-Report-Only agar asset sah tidak terblokir.')
    missing('referrer-policy','Referrer Policy',
            'Tetapkan Referrer-Policy sesuai kebutuhan aplikasi, misalnya strict-origin-when-cross-origin.')
    missing('permissions-policy','Permissions Policy',
            'Tinjau Permissions-Policy dan nonaktifkan fitur browser yang tidak digunakan aplikasi.')
    if 'x-frame-options' in headers or "frame-ancestors" in headers.get('content-security-policy','').lower():
        frame_policy = headers.get('x-frame-options') or 'CSP frame-ancestors'
        hints.append({'category':'Clickjacking protection','status':'OBSERVED',
                      'evidence':f'Proteksi framing teramati: {frame_policy}.',
                      'recommendation':'Pertahankan kebijakan ini dan pastikan nilainya sesuai kebutuhan embedding aplikasi.'})
    else:
        hints.append({'category':'Clickjacking protection','status':'NOT_OBSERVED_ON_PROBED_RESPONSE',
                      'evidence':'X-Frame-Options dan arahan frame-ancestors CSP tidak tampak pada respons HTML yang diuji.',
                      'recommendation':'Tetapkan frame-ancestors pada CSP atau X-Frame-Options yang sesuai dengan kebutuhan embedding.'})

    if 'x-content-type-options' in headers:
        hints.append({'category':'MIME sniffing protection','status':'OBSERVED',
                      'evidence':f"X-Content-Type-Options teramati: {headers['x-content-type-options']}.",
                      'recommendation':'Pertahankan nilai nosniff pada respons aplikasi.'})
    if 'no-store' in headers.get('cache-control','').lower():
        hints.append({'category':'Cache control','status':'OBSERVED',
                      'evidence':'Cache-Control memuat no-store pada respons yang diuji.',
                      'recommendation':'Pertahankan no-store untuk halaman autentikasi dan respons yang memuat data sensitif.'})

    cookie_names = sorted({name for item in observations for name in item.get('cookie_names', [])})
    session_cookies = [name for name in cookie_names if name.lower() in ('phpsessid','_csrf')]
    if session_cookies:
        hints.append({'category':'Cookie sesi', 'status':'FLAGS_NOT_ASSESSED',
                      'evidence':'Nama cookie teramati: ' + ', '.join(session_cookies) + '. Atribut Set-Cookie tidak disimpan oleh WTP.',
                      'recommendation':'Verifikasi konfigurasi server-side agar cookie sesi memakai Secure, HttpOnly, dan SameSite yang sesuai; hasil ini tidak membuktikan atribut tersebut hilang.'})
    server = headers.get('server','')
    if server:
        hints.append({'category':'Banner server','status':'OBSERVED',
                      'evidence':f'Header Server mengungkap {server}; versi tidak terlihat pada respons ini.',
                      'recommendation':'Jika sesuai kebijakan, minimalkan banner server. Header ini sendiri bukan bukti kerentanan.'})
    if tls_status == 'UNAVAILABLE':
        has_https_response = any(item.get('status_code') is not None for item in observations)
        hints.append({'category':'Metadata TLS','status':'NOT_CAPTURED',
                      'evidence':('Respons HTTPS diterima, tetapi metadata sertifikat/protokol tidak tersedia pada capture WTP.'
                                  if has_https_response else 'Tidak ada respons HTTPS yang dapat digunakan untuk mengambil metadata TLS.'),
                      'recommendation':'Verifikasi masa berlaku, nama host, rantai kepercayaan, dan konfigurasi protokol TLS melalui pemeriksaan TLS yang disetujui.'})
    return hints


def normalize_responses(target: str, mode: str, responses: list[dict], enumeration_context=None) -> dict:
    """Normalize broker-captured responses; omit cookies, auth and page bodies."""
    planned = plan_requests(target, mode, enumeration_context)
    if not isinstance(responses, list) or len(responses) > len(planned):
        raise ValueError('Response count exceeds bounded request plan')
    observations, candidates = [], []
    response_count = html_count = request_error_count = 0
    for i, response in enumerate(responses):
        if not isinstance(response, dict): continue
        request = planned[i]
        status = response.get('status_code')
        if status is not None: response_count += 1
        if response.get('error'): request_error_count += 1
        headers = {}
        for key, value in (response.get('headers') or {}).items():
            key = str(key).lower()
            if key in SENSITIVE_HEADERS: continue
            value = str(value)[:500]
            if key in ('location', 'content-location'):
                value = SESSION_PATH_PARAMETER.sub(r'\1[REDACTED]', value)
            headers[key] = value
        item = {'url': request['url'], 'method': request['method'], 'status_code': status,
                'headers': headers, 'observed_at': response.get('observed_at')}
        for key in ('request_started_at', 'response_received_at', 'duration_ms', 'http_version',
                    'error', 'error_code', 'redirect_blocked', 'redirect_count'):
            if response.get(key) is not None: item[key] = response[key]
        if response.get('error_code') == 'CONNECTION_FAILED':
            item['diagnostic'] = 'Target tidak menerima koneksi atau timeout. Pastikan WebGoat aktif, port 8080 listening, dan proses WTP berjalan pada host/network namespace yang dapat menjangkaunya.'
        elif response.get('error_code') == 'REDIRECT_BLOCKED':
            item['diagnostic'] = 'Redirect keluar dari origin atau prefix path target. Gunakan URL konteks aplikasi yang benar, misalnya /WebGoat, lalu cek apakah redirect tetap di bawah prefix tersebut.'
        if response.get('final_url'):
            item['final_url'] = _clean(SESSION_PATH_PARAMETER.sub(r'\1[REDACTED]', str(response['final_url'])), 2048)
        tls = response.get('tls')
        if isinstance(tls, dict):
            cert = tls.get('certificate') if isinstance(tls.get('certificate'), dict) else {}
            item['tls'] = {
                'protocol': _clean(tls.get('protocol') or '', 80),
                'cipher': _clean(tls.get('cipher') or '', 160),
                'validation_status': _clean(tls.get('validation_status') or 'UNKNOWN', 40),
                'certificate': {
                    'subject': cert.get('subject', []), 'issuer': cert.get('issuer', []),
                    'san': cert.get('san', [])[:100] if isinstance(cert.get('san', []), list) else [],
                    'not_before': _clean(cert.get('not_before') or '', 80),
                    'not_after': _clean(cert.get('not_after') or '', 80),
                    'sha256': str(cert.get('sha256') or '').lower() if re.fullmatch(r'[a-fA-F0-9]{64}', str(cert.get('sha256') or '')) else None,
                }
            }
        cookie_names = sorted({_clean(n, 100) for n in response.get('cookie_names', []) if n})[:30]
        if cookie_names: item['cookie_names'] = cookie_names
        content_type = headers.get('content-type', '')
        raw_html = str(response.get('html_excerpt') or '')[:MAX_HTML_BYTES]
        html = raw_html if ('html' in content_type.lower() or request['url'].endswith('/')) else ''
        parser = _HTMLSignals()
        if html:
            html_count += 1
            try: parser.feed(html)
            except Exception: pass
            title = _clean(' '.join(parser.title_text), 300)
            if title: item['page_title'] = title
            if parser.meta: item['meta_signals'] = parser.meta[:20]
            item['script_sources'] = parser.scripts[:40]
            item['html_bytes_observed'] = len(html.encode('utf-8', errors='replace'))
        digest = str(response.get('body_sha256') or '').lower()
        if (request.get('purpose') == 'favicon_fingerprint' and status is not None and 200 <= status < 300
                and headers.get('content-type', '').split(';', 1)[0].strip().lower().startswith('image/')
                and int(response.get('body_bytes_observed') or 0) > 0 and re.fullmatch(r'[a-f0-9]{64}', digest)):
            item['favicon_fingerprint'] = {'sha256': digest,
                                           'bytes_observed': int(response.get('body_bytes_observed') or 0),
                                           'media_type': headers.get('content-type', '')}
        if status in (301, 302, 303, 307, 308): item['redirect_observed'] = True
        if status is not None and status not in (404, 410):
            candidates.append({'url': request['url'], 'status_code': status, 'source': 'bounded_probe'})
        observations.append(item)

    root_index = next((i for i, obs in enumerate(observations) if obs['url'].endswith('/')), None)
    root_response = responses[root_index] if root_index is not None and root_index < len(responses) and isinstance(responses[root_index], dict) else {}
    findings = _extract_findings(
        observations[root_index]['headers'] if root_index is not None else {},
        str(root_response.get('html_excerpt') or '')[:MAX_HTML_BYTES],
        _parse_html(str(root_response.get('html_excerpt') or '')[:MAX_HTML_BYTES]),
        sorted({name for response in responses if isinstance(response, dict)
                for name in response.get('cookie_names', []) if name}),
        [value for obs in observations for key, value in obs.get('headers', {}).items()
         if key in ('location', 'content-location')]
    ) if mode == 'fingerprinting' else []
    claims = [{'technology': f['technology'], 'evidence': f['evidence'],
               'confidence': f['confidence_level'], 'evidence_strength_score': f['evidence_strength_score']}
              for f in findings]
    planned_count = len(planned)
    favicon_observation = next((o for o in observations if o.get('url') == next(
        (p['url'] for p in planned if p.get('purpose') == 'favicon_fingerprint'), None)), None)
    favicon_status = ('CAPTURED' if favicon_observation and favicon_observation.get('favicon_fingerprint')
                      else 'REDIRECTED' if favicon_observation and favicon_observation.get('status_code') in (301,302,303,307,308)
                      else 'MISSING' if favicon_observation and favicon_observation.get('status_code') in (404,410)
                      else 'UNAVAILABLE' if favicon_observation is None or favicon_observation.get('status_code') is None
                      else 'NON_IMAGE_RESPONSE' if favicon_observation and 200 <= (favicon_observation.get('status_code') or 0) < 300
                           and not favicon_observation.get('headers', {}).get('content-type', '').split(';', 1)[0].strip().lower().startswith('image/')
                      else 'NO_SIGNATURE')
    tls_observations = [{'url': o['url'], **o['tls']} for o in observations if isinstance(o.get('tls'), dict)]
    tls_status = 'NOT_APPLICABLE_HTTP' if urlparse(target).scheme == 'http' else 'OBSERVED' if tls_observations else 'UNAVAILABLE'
    tls_diagnostic = None
    if tls_status == 'UNAVAILABLE':
        if response_count:
            tls_diagnostic = ('Respons HTTPS diterima, tetapi metadata sertifikat/protokol tidak tertangkap pada hasil ini. '
                              'Status ini bukan hasil validasi kepercayaan sertifikat.')
        else:
            tls_diagnostic = 'Tidak ada respons HTTPS untuk mengambil metadata TLS; status ini bukan hasil validasi sertifikat.'
    security_review_hints = _security_review_hints(observations, target, tls_status)
    result = {'schema_version': 'web-technology-observation-v3', 'target': target, 'mode': mode,
              'request_count': len(responses), 'observations': observations,
              'tls_status': tls_status, 'tls_diagnostic': tls_diagnostic, 'tls_observations': tls_observations,
              'fingerprint_status': 'SIGNATURES_FOUND' if findings else 'NO_MATCH',
              'favicon_status': favicon_status,
              'technology_claims': claims, 'technology_findings': findings,
              'security_review_hints': security_review_hints,
              'scan_metrics': {'scan_status': 'NO_RESPONSE' if response_count == 0 else 'PARTIAL' if response_count < planned_count else 'COMPLETED',
                               'requests_planned': planned_count, 'responses_received': response_count,
                               'response_rate_percent': round(100 * response_count / planned_count) if planned_count else 0,
                               'request_errors': request_error_count,
                               'html_responses': html_count, 'headers_observed': sum(len(o['headers']) for o in observations),
                               'favicon_fingerprints': sum(1 for o in observations if o.get('favicon_fingerprint')),
                               'redirects_observed': sum(1 for o in observations if o.get('redirect_count') or o.get('redirect_observed')),
                               'redirects_blocked': sum(1 for o in observations if o.get('redirect_blocked')),
                               'tls_sessions': len(tls_observations),
                               'fingerprints_matched': len(findings),
                               'evidence_strength_index_max': max((f['evidence_strength_score'] for f in findings), default=0)},
              'surface_candidates': candidates if mode == 'enumeration' else [],
              'limitations': ['evidence-strength scores are deterministic rule-based indices, not probabilities',
                              'claims are indicators, not verified product/version facts',
                              'versions are not inferred unless an explicit version indicator is observed',
                              'redirects are followed only up to two hops on the same origin and target path prefix',
                              'TLS metadata is observational; certificate trust is not assessed',
                              'no vulnerability was tested', 'response bodies and cookie values are excluded; cookie names only are retained']}
    return result


def _parse_html(html):
    parser = _HTMLSignals()
    try: parser.feed(html)
    except Exception: pass
    return parser
