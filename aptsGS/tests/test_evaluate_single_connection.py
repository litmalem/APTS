"""A policy evaluation runs on one DB connection/transaction, not one per query."""
from contextlib import contextmanager

from app.governance_service import GovernanceService


class _CountingDb:
    def __init__(self):
        self.opened = 0
        self.depth = 0

    @contextmanager
    def connect(self):
        if self.depth == 0:
            self.opened += 1
        self.depth += 1
        try:
            yield self
        finally:
            self.depth -= 1


class _Repo:
    def __init__(self):
        self.db = _CountingDb()
        self.inside = []


def test_evaluation_body_runs_inside_one_connection(monkeypatch):
    service = GovernanceService.__new__(GovernanceService)
    service.repo = _Repo()

    def body(self, request, **kwargs):
        # Every repository call made here reuses the open connection.
        self.repo.inside.append(self.repo.db.depth)
        with self.repo.db.connect():
            with self.repo.db.connect():
                pass
        return {"decision": "ALLOW"}

    monkeypatch.setattr(GovernanceService, "_evaluate_authorization_tx", body)
    assert service._evaluate_authorization(object()) == {"decision": "ALLOW"}
    assert service.repo.db.opened == 1
    assert service.repo.inside == [1]


def test_repo_without_db_still_evaluates(monkeypatch):
    service = GovernanceService.__new__(GovernanceService)
    service.repo = object()
    monkeypatch.setattr(GovernanceService, "_evaluate_authorization_tx",
                        lambda self, request, **kw: {"decision": "DENY"})
    assert service._evaluate_authorization(object()) == {"decision": "DENY"}
