import pytest
@pytest.mark.parametrize('value',[1],ids=['intel-λ'])
def test_gss(value):
    assert value == 1
