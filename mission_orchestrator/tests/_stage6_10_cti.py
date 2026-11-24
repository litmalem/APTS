"""Native VulnDesk PIP assembly with isolated intelligence and SQL fixtures."""
from copy import deepcopy
import importlib
import os
from pathlib import Path
import sys
import types
from unittest.mock import patch

from execution_subsystem.execution_contract import sha256_hex
from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item


def vulndesk_root():
    explicit = os.getenv("APTS_ACCEPTANCE_VULNDESK_ROOT")
    candidates = [Path(explicit)] if explicit else [Path(__file__).resolve().parents[2] / name for name in ("vulndesk", "Vulndesk", "VulnDesk")]
    for path in candidates:
        if (path / "cti_services" / "pip_assembly_validation_service.py").is_file(): return path.resolve()
    raise RuntimeError("Stage 6.10 requires APTS_ACCEPTANCE_VULNDESK_ROOT pointing to the supplied VulnDesk source")


class IsolatedCtiDb:
    """Capture production publication SQL; never open a deployed database."""
    def __init__(self): self.statements = []
    def table_exists(self, name): return name in {"cti_pip_artifacts", "cti_pip_validation_results"}
    def fetch_one(self, *args): return {"n": 0}
    def execute_transaction(self, statements):
        for sql, params in statements:
            if any(isinstance(v, (dict, list, tuple, set)) for v in params.values()):
                raise TypeError("native PIP SQL contains structured scalar values")
            self.statements.append((sql, deepcopy(params)))
        return [1] * len(statements)


class EnabledCtiRegistry:
    def is_enabled(self, key): return True
    def update_status(self, *args): pass


class CtiAuditCapture:
    def __init__(self): self.events = []
    def append(self, **kwargs): self.events.append(deepcopy(kwargs)); return "audit-stage610-cti"


def assemble_native_pip(mission_id, reference, target, scope, governance_binding):
    root = vulndesk_root()
    # Load the native submodule without the application's eager GUI bootstrap,
    # using the same explicit package path as VulnDesk's architecture tests.
    if "cti_services" not in sys.modules:
        package = types.ModuleType("cti_services")
        package.__path__ = [str(root / "cti_services")]
        sys.modules["cti_services"] = package
    module = importlib.import_module("cti_services.pip_assembly_validation_service")
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise RuntimeError("CTI assembly code does not belong to the configured source")
    db, audit = IsolatedCtiDb(), CtiAuditCapture()
    service = module.PipAssemblyValidationService(db=db, registry=EnabledCtiRegistry(), audit=audit)
    upstream = knowledge_item("stage610-connected", match=True)
    upstream["content_sha256"] = sha256_hex({k: v for k, v in upstream.items() if k != "content_sha256"})
    native_id = module.new_id
    # The immutable Mission envelope reserves the publication identity. Only
    # ID allocation is a fixture; all native CTI quality gates and hashing run.
    with patch.object(module, "new_id", side_effect=lambda prefix: reference["pip_id"] if prefix == "pip" else native_id(prefix)):
        result = service.build(mission_id=mission_id,
            mission_binding={"target_url": target, "scope_allowed": True, "scope": scope["contract"]["scope"],
                "scope_sha256": scope["canonical_sha256"], "governance_binding_sha256": governance_binding["canonical_sha256"]},
            asset_profiles=[{"asset_id": "asset-stage610-loopback", "target_url": target, "confidence": upstream["confidence"],
                "evidence_refs": ["fixture:stage610:authorized-loopback-service"]}],
            cpe_claims=[], vulnerability_correlations=[], attack_mappings=[], normalized_objects=[upstream],
            provenance_records=[{"source_id": upstream["source"]["source_id"], "source_ref": upstream["source"]["source_ref"],
                "evidence_refs": ["fixture:stage610:synthetic-cti-feed"]}],
            assumptions_and_gaps=[{"reason": "Synthetic intelligence requires target-side validation; no vulnerability is confirmed."}],
            policy_context={"scope_allowed": True, "execution_authorized": False})
    pip = result["pip"]
    assert result["status"] == "completed" and pip["readiness"] != "REJECTED"
    assert all(g["passed"] for g in service.validate(pip["artifact"]))
    assert pip["pip_id"] == reference["pip_id"] and str(pip["revision"]) == reference["pip_version"]
    assert len(db.statements) == 11 and audit.events[-1]["event_type"] == "pip.published"
    assert not pip["execution_authorized"] and not pip["artifact"]["semantics"]["execution_authorized"]
    return pip
