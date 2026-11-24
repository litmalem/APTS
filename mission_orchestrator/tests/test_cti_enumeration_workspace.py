"""Regression coverage for CTI -> Stage 5.3 read-only intake."""
import hashlib
import io
import json
from unittest.mock import patch
import pytest
from pentest_subsystem.cti_enumeration_adapter import (
    fetch_cti_context, project_enumeration_observations,
)
from pentest_subsystem.enumeration import EnumerationAgentValidationError


def fixture():
    digest = "a" * 64
    return {"status": "ok", "lineage": {
        "mission_id": "mission-1", "task_id": "task-1", "recon_run_id": "reconrun-1",
        "intake_id": "intake-1", "evidence_manifest_sha256": digest},
        "enrichment": {"target": {"target_type": "URL", "target_value": "http://127.0.0.1/"},
            "technologies": [{"name": "Apache", "version": "2.4.58"}, {"name": "PHP", "version": ""}],
            "cpe_candidates": [{"cpe23_uri": "cpe:2.3:a:apache:http_server:*:*:*:*:*:*:*:*"}],
            "source_result_sha256": digest, "evidence_manifest_sha256": digest,
            "evidence_status": "SEALED", "enriched_at": "2026-11-09T11:00:00Z"}}


class Response:
    def __init__(self, payload):
        self.buffer = io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, count):
        return self.buffer.read(count)


def test_valid_context_is_read_only_and_candidates_are_not_confirmed():
    calls = []
    def sender(request, timeout):
        calls.append((request.get_method(), request.full_url))
        return Response(fixture())
    with patch.dict("os.environ", {"APTS_WPT_CTI_SHARED_TOKEN": "x" * 40,
                                   "APTS_CTI_ENUMERATION_URL": "http://127.0.0.1:8765"}):
        result = fetch_cti_context("mission-1", "task-1", "reconrun-1", opener=sender)
    observations = project_enumeration_observations(result)
    assert [x["kind"] for x in observations] == ["VERSION", "TECHNOLOGY"]
    assert all(x["attributes"]["classification"] == "CTI_CONTEXT_NOT_CONFIRMED" for x in observations)
    assert calls[0][0] == "GET"
    assert calls[0][1].startswith("http://127.0.0.1:8765/api/cti/wpt/enumeration-context?")


def test_empty_technology_yields_baseline_endpoint_observation():
    """Option A: a verified target with zero resolved technology still produces
    exactly one honest baseline ENDPOINT observation so Stage 5.3 Enumeration
    proceeds instead of stalling on an empty observations array."""
    from pentest_subsystem.enumeration import _normalize_observation
    ctx = fixture()
    ctx["enrichment"]["target"] = {"target_type": "URL",
                                   "target_value": "https://localhost:8443/benchmark/"}
    ctx["enrichment"]["technologies"] = []
    ctx["enrichment"]["cpe_candidates"] = []
    observations = project_enumeration_observations(ctx)
    assert len(observations) == 1
    obs = observations[0]
    assert obs["kind"] == "ENDPOINT"
    assert obs["attributes"]["endpoint"] == "/benchmark/"
    assert obs["attributes"]["classification"] == "CTI_CONTEXT_NOT_CONFIRMED"
    # Must NOT masquerade as resolved technology evidence downstream.
    assert obs["source"]["source_kind"] == "CTI_WPT_BASELINE"
    # The synthesized observation is accepted by the Stage-5.3 normalizer.
    _normalize_observation(obs, 0)


def test_empty_technology_non_url_target_still_fails_closed():
    """Baseline is URL-only; a non-URL target with no technology stays empty so
    the enumeration request fails closed rather than inventing an endpoint."""
    ctx = fixture()
    ctx["enrichment"]["target"] = {"target_type": "DOMAIN", "target_value": "example.test"}
    ctx["enrichment"]["technologies"] = []
    ctx["enrichment"]["cpe_candidates"] = []
    assert project_enumeration_observations(ctx) == []


def test_rejects_mismatched_lineage():
    bad = fixture()
    bad["lineage"]["mission_id"] = "mission-other"
    with patch.dict("os.environ", {"APTS_WPT_CTI_SHARED_TOKEN": "x" * 40,
                                   "APTS_CTI_ENUMERATION_URL": "http://127.0.0.1:8765"}):
        try:
            fetch_cti_context("mission-1", "task-1", "reconrun-1",
                              opener=lambda *a, **kw: Response(bad))
        except EnumerationAgentValidationError:
            pass
        else:
            raise AssertionError("Cross-mission evidence was accepted")


def test_rejects_remote_cti_endpoint():
    with patch.dict("os.environ", {"APTS_WPT_CTI_SHARED_TOKEN": "x" * 40,
                                   "APTS_CTI_ENUMERATION_URL": "http://example.org:8765"}):
        try:
            fetch_cti_context("mission-1", "task-1", "reconrun-1")
        except EnumerationAgentValidationError:
            pass
        else:
            raise AssertionError("Remote CTI endpoint was accepted")


def test_rejects_unsealed_evidence():
    bad = fixture()
    bad["enrichment"]["evidence_status"] = "UNSEALED"
    with patch.dict("os.environ", {"APTS_WPT_CTI_SHARED_TOKEN": "x" * 40,
                                   "APTS_CTI_ENUMERATION_URL": "http://127.0.0.1:8765"}):
        try:
            fetch_cti_context("mission-1", "task-1", "reconrun-1",
                              opener=lambda *a, **kw: Response(bad))
        except EnumerationAgentValidationError:
            pass
        else:
            raise AssertionError("Unsealed CTI evidence was accepted")


@pytest.mark.parametrize("mismatch", [None, "target_type", "target_value"])
def test_context_compares_scoped_identity_and_accepts_task_metadata(tmp_path, mismatch):
    from tests.test_stage5_3_enumeration_agent import _start_repo
    from pentest_subsystem.enumeration import EnumerationAgentService
    from pentest_subsystem.web_ui import cti_enumeration_context_for_recon_run
    repo, _, _, _, run, _, _ = _start_repo(tmp_path, "cti-target")
    service = EnumerationAgentService(repo)
    task = service.get_task(service.get_agentic_orchestration(run["orchestration_id"])["pentest_task_id"])
    context = fixture()
    context["enrichment"]["target"] = {k: task["task"]["target"][k] for k in ("target_type", "target_value")}
    task["task"]["target"].update(environment="LAB", metadata={})
    if mismatch:
        context["enrichment"]["target"][mismatch] = "DOMAIN" if mismatch == "target_type" else "other.example"
    context["lineage"].update(mission_id=run["mission_id"], task_id=task["upstream_task_id"], recon_run_id=run["recon_run_id"])
    handoff = {"intake_id": "intake-1", "source_result_sha256": "a" * 64, "recon_run_id": run["recon_run_id"]}
    with patch("pentest_subsystem.cti_enumeration_adapter.fetch_cti_context", return_value=context), patch(
        "pentest_subsystem.web_ui.wpt_intakes_for_recon_run", return_value=[handoff]
    ), patch.object(service, "get_task", return_value=task):
        if mismatch:
            with pytest.raises(ValueError, match="CTI target differs"):
                cti_enumeration_context_for_recon_run(service, run["recon_run_id"])
        else:
            draft = cti_enumeration_context_for_recon_run(service, run["recon_run_id"])
            result = service.run_enumeration(run["orchestration_id"], draft["enumeration_request_draft"])
            assert result["status"] == "completed"
            assert result["target_actuation"] is False
            assert draft["enumeration_request_draft"]["enumeration_proposals"] == []
