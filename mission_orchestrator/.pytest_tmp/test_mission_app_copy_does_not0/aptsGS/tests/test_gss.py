from run import TOKEN as RUN
from execution_subsystem import TOKEN as EXECUTION
from tests._mission_helper import TOKEN as HELPER
from app import TOKEN as GSS
assert RUN == EXECUTION == 'complete-mission'
assert HELPER == 'mission-test-helper'
assert GSS == 'native-gss'
def test_gss():
    assert True
