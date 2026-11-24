from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from execution_subsystem.runtime_service import ExecutionRuntimeService
import execution_subsystem.runtime_service as runtime_module


@pytest.mark.parametrize('second_tick,expected', [(10, []), (17, [('ABORTED', 'RUNTIME_GOVERNANCE_REVALIDATION_STALE')])])
def test_probe_timeout_starts_after_source_validation(monkeypatch, second_tick, expected):
    tick = [0.0]
    monkeypatch.setattr(runtime_module.time, 'monotonic', lambda: tick[0])
    monkeypatch.setattr(runtime_module, 'REVALIDATE_SECONDS', 0)
    monkeypatch.setattr(runtime_module, 'REVALIDATION_PROBE_TIMEOUT_SECONDS', 8)
    monkeypatch.setattr(runtime_module, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    now = datetime.now(timezone.utc)
    instant = lambda d: d.isoformat().replace('+00:00', 'Z')
    claim = {'authorization_id': 'eauth-initial', 'reserved_at': instant(now),
             'controls': {'deadline': instant(now + timedelta(seconds=60))},
             'lifetime_deadlines': {}, 'authorization_record': {'evaluation': {'current_context': {}}}}
    class Done:
        calls = 0
        def wait(self, _seconds):
            self.calls += 1
            if self.calls == 1: tick[0] = 1
            if self.calls == 2: tick[0] = second_tick
            return self.calls > 2
    stops = []
    guard = SimpleNamespace(done=Done(), check_authorization=lambda: None,
                            tighten_deadline=lambda _: None, stop=lambda *args: stops.append(args))
    repository = SimpleNamespace(
        get_attempt=lambda _: {'record': {'owner_id': 'owner'}, 'state': 'RUNNING'},
        requested_stop=lambda _: None, append_event=lambda *args: None)
    def context(_envelope):
        tick[0] = 8  # Seven seconds spent validating immutable current sources.
        return {}
    service = SimpleNamespace(repository=repository, owner_id='owner', clock=lambda: now,
                              _current_context=context, _probe_authority=lambda *args: None)
    ExecutionRuntimeService._supervise(service, 'xattempt-test', guard, claim, {})
    assert stops == expected
