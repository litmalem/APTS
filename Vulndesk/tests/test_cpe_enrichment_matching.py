from contextlib import nullcontext
from unittest.mock import patch

from cpe_dictionary_services import CpeDictionaryService, normalize_technology


def match(name, version, rows):
    service = CpeDictionaryService()
    with patch('cpe_dictionary_services.session_scope', return_value=nullcontext(None)), patch('cpe_dictionary_services.CpeDictionaryRepository') as repo:
        repo.return_value.search_matching_products.return_value = rows
        return service.match_technology({'name': name, 'version': version}, auto_fetch=False)


def row(product, version, vendor='php'):
    return {'product': product, 'version': version, 'vendor': vendor,
            'cpe23_uri': f'cpe:2.3:a:{vendor}:{product}:{version}:*:*:*:*:*:*:*', 'title': product}


def test_embedded_php_version_does_not_select_other_release_or_similar_product():
    rows = [row('php', '8.0.30'), row('adobe_php_ria_sdk', '*'), row('php', '8.4.27')]
    result = match('PHP/8.4.27', '', rows)
    assert len(result) == 1
    assert result[0]['technology_name'] == 'PHP'
    assert result[0]['technology_version'] == '8.4.27'
    assert result[0]['version'] == '8.4.27'


def test_no_version_does_not_invent_concrete_release_or_accept_related_product():
    rows = [row('nginx', '1.24.0', 'f5'), row('nginx_unit', '*', 'f5'), row('nginx', '*', 'f5')]
    result = match('nginx', '', rows)
    assert len(result) == 1
    assert result[0]['product'] == 'nginx' and result[0]['version'] == '*'


def test_angular_and_juice_shop_reject_keyword_only_matches():
    assert match('Angular', '', [row('angular-http-server', '*')]) == []
    assert match('OWASP Juice Shop', '', [row('ecwid_ecommerce_shopping_cart', '*')]) == []


def test_normalization_preserves_explicit_version():
    result = normalize_technology({'name': 'PHP/8.4.27', 'version': '8.4.28'})
    assert result['name'] == 'PHP' and result['version'] == '8.4.28'


def resolve(name, version, identities):
    with patch('cpe_dictionary_services.session_scope', return_value=nullcontext(None)), patch('cpe_dictionary_services.CpeDictionaryRepository') as repo:
        repo.return_value.search_matching_products.return_value = []
        repo.return_value.product_identities.return_value = identities
        return CpeDictionaryService().resolve_technology({'name':name, 'version':version})


def test_unknown_version_exposes_product_identity_without_inventing_target_cpe():
    identity = {'vendor':'f5', 'product':'nginx', 'reference_cpe23_uri':row('nginx','1.24.0','f5')['cpe23_uri']}
    result = resolve('nginx', '', [identity])
    assert result['status'] == 'VERSION_UNKNOWN'
    candidate = result['candidates'][0]
    assert candidate['cpe23_uri'] is None
    assert candidate['reference_cpe23_uri'] == identity['reference_cpe23_uri']
    assert candidate['match_level'] == 'PRODUCT'
    assert candidate['technology_version'] == ''
    assert candidate['version_verified'] is False


def test_missing_version_remains_diagnostic_not_matching_other_release():
    result = resolve('PHP', '8.4.27', [{'vendor':'php','product':'php','reference_cpe23_uri':row('php','8.0.30')['cpe23_uri']}])
    assert result['status'] == 'VERSION_NOT_FOUND'
    assert result['candidates'][0]['cpe23_uri'] is None
    assert result['candidates'][0]['technology_version'] == '8.4.27'


def test_missing_product_has_explicit_diagnostic_without_candidate():
    result = resolve('Angular', '', [])
    assert result['status'] == 'PRODUCT_NOT_FOUND'
    assert result['candidates'] == []


def test_repository_filters_identity_and_version_before_limit_without_loading_raw_json():
    from sqlalchemy.dialects import mysql
    from unittest.mock import MagicMock
    from cpe_dictionary_repositories import CpeDictionaryRepository
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = []
    CpeDictionaryRepository(session).search_matching_products({'php'}, '8.4.27')
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={'literal_binds': True}))
    assert "product IN ('php')" in sql
    assert "version IN ('8.4.27', '*', '')" in sql
    assert 'raw_json' not in sql
    assert 'LIKE' not in sql


def test_stable_version_does_not_match_release_candidate_update():
    candidates = [{**row('php','8.4.27'),'update_value':'rc1'}, {**row('php','8.4.27'),'update_value':'-'}]
    result = match('PHP','8.4.27',candidates)
    assert len(result) == 1


def test_laravel_framework_alias_is_restricted_to_laravel_vendor():
    result = match('Laravel', '10.0.0', [row('framework', '10.0.0', 'other_vendor'), row('framework', '10.0.0', 'laravel')])
    assert len(result) == 1 and result[0]['vendor'] == 'laravel'


def test_product_identity_query_filters_vendor_and_does_not_assign_version():
    from sqlalchemy.dialects import mysql
    from unittest.mock import MagicMock
    from cpe_dictionary_repositories import CpeDictionaryRepository
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = []
    CpeDictionaryRepository(session).product_identities({'framework'}, vendors={'laravel'})
    sql = str(session.execute.call_args.args[0].compile(dialect=mysql.dialect(), compile_kwargs={'literal_binds': True}))
    assert "vendor IN ('laravel')" in sql
    assert 'reference_cpe23_uri' in sql
    assert 'GROUP BY' in sql
