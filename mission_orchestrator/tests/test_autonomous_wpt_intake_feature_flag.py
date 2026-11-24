from mission_orchestrator.mission_wpt_preparation import enabled


def test_autonomous_wpt_intake_is_on_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("APTS_AUTONOMOUS_WPT_INTAKE", raising=False)
    assert enabled() is True
    monkeypatch.setenv("APTS_AUTONOMOUS_WPT_INTAKE", "0")
    assert enabled() is False
    monkeypatch.setenv("APTS_AUTONOMOUS_WPT_INTAKE", "1")
    assert enabled() is True
