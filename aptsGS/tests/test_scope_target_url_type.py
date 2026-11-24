import pytest
from pydantic import ValidationError
from app.models import ScopeTargetInput


def test_http_url_cannot_be_published_as_ip():
    with pytest.raises(ValidationError, match='must use target_type URL'):
        ScopeTargetInput(target_type='IP', target_value='http://127.0.0.1:3000/')


@pytest.mark.parametrize('kind,value', [('IP', '127.0.0.1'), ('URL', 'http://127.0.0.1:3000/')])
def test_correct_target_type_preserves_value(kind, value):
    assert ScopeTargetInput(target_type=kind, target_value=value).target_value == value
