from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .db_adapter import make_json_safe


INTEGRITY_PROBE_SCHEMA_V1 = "cti-integrity-probe-v1"


class IntegrityViolationProbe:
    """Stage 2.9.5 deterministic integrity/violation classifier.

    The probe is deliberately read-only. It consumes the canonical Stage 2.9.1/2.9.3
    lineage projection plus the Stage 2.9.4 Governance correlation facts already
    attached by the orchestrator. It never repairs persisted state, creates authority,
    or changes a Governance decision.

    Classification rules are evidence based:
      * governed dispatch without an exact PolicyDecision binding;
      * dispatch after task-level revocation;
      * TaskContract scope that differs from authoritative PolicyDecision scope;
      * terminal COMPLETED state without a prior TASK_DISPATCHED event;
      * unresolved/mismatched authoritative Governance provenance from Stage 2.9.4.

    A correctly blocked task after revocation is explicitly treated as enforcement,
    not as a violation.
    """

    _COMPLETION_EVENT_TYPES = {
        "TASK_COMPLETED",
        "SOURCE_SYNC_COMPLETED",
    }
    _REVOCATION_EVENT_TYPES = {"TASK_AUTHORIZATION_REVOKED"}
    _BLOCK_EVENT_TYPES = {"TASK_DISPATCH_BLOCKED"}
    _STRICT_EVENT_QUALITIES = {"CANONICAL_V2"}

    def probe_task(self, projection: Dict[str, Any]) -> Dict[str, Any]:
        identity = projection.get("identity") or {}
        mission_id = self._text(identity.get("mission_id"))
        task_id = self._text(identity.get("task_id"))
        if not mission_id:
            raise ValueError("task projection has no mission_id")
        if not task_id:
            raise ValueError("task projection has no task_id")

        corr_envelope = projection.get("governance_correlation") or {}
        correlation = corr_envelope.get("task_correlation") if isinstance(corr_envelope, Mapping) else None
        result = self._evaluate_task(projection, correlation=correlation)
        enriched = dict(projection)
        enriched["integrity_probe"] = result
        correlation_enriched = dict(enriched.get("governance_correlation") or {})
        if correlation_enriched:
            correlation_enriched["integrity_classification_status"] = result.get("status")
            enriched["governance_correlation"] = correlation_enriched

        binding = dict(enriched.get("governance_binding") or {})
        binding["integrity_status"] = result.get("status")
        enriched["governance_binding"] = binding

        metadata = dict(enriched.get("projection_metadata") or {})
        metadata["integrity_classification_status"] = result.get("status")
        metadata["integrity_violation_count"] = result.get("violation_count", 0)
        enriched["projection_metadata"] = metadata
        return make_json_safe(enriched)

    def probe_mission(self, projection: Dict[str, Any]) -> Dict[str, Any]:
        mission_id = self._text((projection.get("identity") or {}).get("mission_id"))
        if not mission_id:
            raise ValueError("mission projection has no mission_id")

        corr = projection.get("governance_correlation") or {}
        task_correlations = {
            self._text(row.get("task_id")): row
            for row in (corr.get("task_correlations") or [])
            if self._text(row.get("task_id"))
        }

        task_results = [
            self._evaluate_task(
                lineage,
                correlation=task_correlations.get(self._text((lineage.get("identity") or {}).get("task_id"))),
            )
            for lineage in (projection.get("task_lineages") or [])
        ]

        mission_violations: List[Dict[str, Any]] = []
        mission_checks: List[Dict[str, Any]] = []
        verification_reasons: List[str] = []

        correlation_status = self._text(corr.get("status")).upper()
        if correlation_status in {"UNAVAILABLE", "PROTOCOL_ERROR", "ERROR"}:
            verification_reasons.append(f"GOVERNANCE_CORRELATION_{correlation_status}")
            mission_checks.append(self._check(
                "AUTHORITATIVE_GOVERNANCE_CORRELATION_AVAILABLE",
                "UNVERIFIABLE",
                evidence={"correlation_status": correlation_status},
            ))
        elif corr:
            mission_checks.append(self._check(
                "AUTHORITATIVE_GOVERNANCE_CORRELATION_AVAILABLE",
                "PASS",
                evidence={"correlation_status": correlation_status or "UNKNOWN"},
            ))
        else:
            governed = any(self._required_authority(lineage) for lineage in (projection.get("task_lineages") or []))
            if governed:
                verification_reasons.append("GOVERNANCE_CORRELATION_NOT_ATTACHED")
                mission_checks.append(self._check(
                    "AUTHORITATIVE_GOVERNANCE_CORRELATION_AVAILABLE",
                    "UNVERIFIABLE",
                    evidence={"correlation_status": None},
                ))

        for row in corr.get("external_event_correlations") or []:
            if self._text(row.get("status")).upper() == "MISSING_GOVERNANCE_RECORD":
                mission_violations.append(self._violation(
                    "GOVERNANCE_EVENT_REFERENCE_MISSING",
                    category="CROSS_SUBSYSTEM_PROVENANCE",
                    severity="HIGH",
                    task_id=None,
                    message="A local CTI event references a Governance event that is absent from the authoritative mission snapshot.",
                    evidence={
                        "local_event_id": row.get("local_event_id"),
                        "local_event_type": row.get("local_event_type"),
                        "governance_event_id": row.get("governance_event_id"),
                    },
                ))

        for task in task_results:
            mission_violations.extend(task.get("violations") or [])
            if not task.get("verification_complete", True):
                for reason in task.get("verification_reasons") or []:
                    if reason not in verification_reasons:
                        verification_reasons.append(reason)

        violation_count = len(mission_violations)
        status = self._status(violation_count, verification_reasons)
        severity_counts = self._severity_counts(mission_violations)
        code_counts = self._code_counts(mission_violations)
        clean_task_count = sum(1 for row in task_results if row.get("status") == "PASS")
        violated_task_count = sum(1 for row in task_results if row.get("violation_count", 0) > 0)
        unverifiable_task_count = sum(1 for row in task_results if not row.get("verification_complete", True))

        result = make_json_safe({
            "schema_version": INTEGRITY_PROBE_SCHEMA_V1,
            "scope": "MISSION",
            "mission_id": mission_id,
            "status": status,
            "classification": "LINEAGE_INTEGRITY_VIOLATION_CLASSIFICATION_STAGE_2_9_5",
            "read_only": True,
            "verification_complete": not verification_reasons,
            "verification_reasons": verification_reasons,
            "task_integrity": task_results,
            "mission_checks": mission_checks,
            "violations": mission_violations,
            "violation_count": violation_count,
            "severity_counts": severity_counts,
            "violation_code_counts": code_counts,
            "summary": {
                "task_count": len(task_results),
                "clean_task_count": clean_task_count,
                "violated_task_count": violated_task_count,
                "unverifiable_task_count": unverifiable_task_count,
                "violation_count": violation_count,
            },
        })

        enriched = dict(projection)
        enriched["integrity_probe"] = result
        correlation_enriched = dict(enriched.get("governance_correlation") or {})
        if correlation_enriched:
            correlation_enriched["integrity_classification_status"] = status
            enriched["governance_correlation"] = correlation_enriched
        metadata = dict(enriched.get("projection_metadata") or {})
        metadata["integrity_classification_status"] = status
        metadata["integrity_violation_count"] = violation_count
        metadata["integrity_verification_complete"] = not verification_reasons
        enriched["projection_metadata"] = metadata
        return make_json_safe(enriched)

    def _evaluate_task(
        self,
        lineage: Mapping[str, Any],
        *,
        correlation: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        identity = lineage.get("identity") or {}
        mission_id = self._text(identity.get("mission_id"))
        task_id = self._text(identity.get("task_id"))
        task = lineage.get("task_contract") or {}
        binding = lineage.get("governance_binding") or {}
        lifecycle = lineage.get("lifecycle") or {}
        events = list(lineage.get("events") or [])
        required = self._required_authority(lineage)

        violations: List[Dict[str, Any]] = []
        checks: List[Dict[str, Any]] = []
        verification_reasons: List[str] = []

        quality = self._text((lineage.get("projection_metadata") or {}).get("quality")).upper()
        strict_event_history = quality in self._STRICT_EVENT_QUALITIES or not quality
        if quality and quality not in self._STRICT_EVENT_QUALITIES:
            verification_reasons.append(f"LINEAGE_QUALITY_{quality}")

        event_positions = self._event_positions(events)
        dispatches = event_positions.get("TASK_DISPATCHED", [])
        revocations = [
            position
            for event_type in self._REVOCATION_EVENT_TYPES
            for position in event_positions.get(event_type, [])
        ]
        blocks = [
            position
            for event_type in self._BLOCK_EVENT_TYPES
            for position in event_positions.get(event_type, [])
        ]
        completions = [
            position
            for event_type in self._COMPLETION_EVENT_TYPES
            for position in event_positions.get(event_type, [])
        ]

        # INV-295-01: A governed dispatch must carry the exact PolicyDecision binding.
        if required and dispatches:
            policy_decision_id = self._nullable(binding.get("policy_decision_id") or task.get("policy_decision_id"))
            dispatch_without_event_binding = []
            for fallback, event in enumerate(events, start=1):
                if self._text((event or {}).get("event_type")).upper() != "TASK_DISPATCHED":
                    continue
                try:
                    sequence = int((event or {}).get("sequence_no") or fallback)
                except (TypeError, ValueError):
                    sequence = fallback
                if not self._event_policy_decision(event):
                    dispatch_without_event_binding.append(sequence)
            if not policy_decision_id or dispatch_without_event_binding:
                violations.append(self._violation(
                    "DISPATCH_WITHOUT_POLICY_DECISION",
                    category="AUTHORIZATION_BINDING",
                    severity="CRITICAL",
                    task_id=task_id,
                    message="A governed TaskContract was dispatched without a complete PolicyDecision binding.",
                    evidence={
                        "task_policy_decision_id": policy_decision_id,
                        "dispatch_sequence_numbers": dispatches,
                        "dispatch_without_event_policy_decision": dispatch_without_event_binding,
                    },
                ))
                checks.append(self._check("GOVERNED_DISPATCH_REQUIRES_POLICY_DECISION", "FAIL"))
            else:
                checks.append(self._check(
                    "GOVERNED_DISPATCH_REQUIRES_POLICY_DECISION",
                    "PASS",
                    evidence={"policy_decision_id": policy_decision_id},
                ))
        else:
            checks.append(self._check(
                "GOVERNED_DISPATCH_REQUIRES_POLICY_DECISION",
                "NOT_APPLICABLE" if not required else "PASS",
            ))

        # INV-295-02: No dispatch may occur after a task-level revocation projection.
        dispatch_after_revocation = []
        if revocations and dispatches:
            first_revocation = min(revocations)
            dispatch_after_revocation = [position for position in dispatches if position > first_revocation]
        if dispatch_after_revocation:
            violations.append(self._violation(
                "DISPATCH_AFTER_REVOCATION",
                category="REVOCATION_ENFORCEMENT",
                severity="CRITICAL",
                task_id=task_id,
                message="Task dispatch occurred after authorization revocation had already been projected for the TaskContract.",
                evidence={
                    "revocation_sequence_numbers": sorted(revocations),
                    "dispatch_sequence_numbers": dispatches,
                    "dispatch_after_revocation_sequence_numbers": dispatch_after_revocation,
                },
            ))
            checks.append(self._check("REVOCATION_PREVENTS_LATER_DISPATCH", "FAIL"))
        elif revocations:
            blocked_after_revocation = [position for position in blocks if position > min(revocations)]
            contract_status = self._text(task.get("status") or lifecycle.get("contract_status")).upper()
            enforced = bool(blocked_after_revocation) or contract_status in {"BLOCKED", "BLOCKED_REVOKED", "CANCELLED", "FAILED"}
            checks.append(self._check(
                "REVOCATION_PREVENTS_LATER_DISPATCH",
                "PASS" if enforced or not dispatch_after_revocation else "FAIL",
                evidence={
                    "revocation_sequence_numbers": sorted(revocations),
                    "blocked_after_revocation_sequence_numbers": blocked_after_revocation,
                    "contract_status": contract_status,
                    "classification": "CORRECTLY_BLOCKED_AFTER_REVOCATION" if enforced else "NO_LATER_DISPATCH_OBSERVED",
                },
            ))
        else:
            checks.append(self._check("REVOCATION_PREVENTS_LATER_DISPATCH", "NOT_APPLICABLE"))

        # INV-295-03: local TaskContract scope must equal authoritative PolicyDecision scope.
        scope_comparison = self._comparison(correlation, "decision.scope_contract_id")
        if scope_comparison and self._text(scope_comparison.get("status")).upper() == "MISMATCH":
            violations.append(self._violation(
                "TASK_SCOPE_POLICY_SCOPE_MISMATCH",
                category="SCOPE_BINDING",
                severity="CRITICAL",
                task_id=task_id,
                message="TaskContract scope_contract_id differs from the authoritative PolicyDecision scope_contract_id.",
                evidence={
                    "task_scope_contract_id": scope_comparison.get("local"),
                    "policy_decision_scope_contract_id": scope_comparison.get("authoritative"),
                },
            ))
            checks.append(self._check("TASK_SCOPE_EQUALS_POLICY_DECISION_SCOPE", "FAIL"))
        elif required and correlation is None:
            verification_reasons.append("AUTHORITATIVE_TASK_CORRELATION_NOT_AVAILABLE")
            checks.append(self._check("TASK_SCOPE_EQUALS_POLICY_DECISION_SCOPE", "UNVERIFIABLE"))
        elif required:
            checks.append(self._check(
                "TASK_SCOPE_EQUALS_POLICY_DECISION_SCOPE",
                "PASS" if scope_comparison else "UNVERIFIABLE",
            ))
            if not scope_comparison:
                verification_reasons.append("AUTHORITATIVE_SCOPE_COMPARISON_NOT_AVAILABLE")
        else:
            checks.append(self._check("TASK_SCOPE_EQUALS_POLICY_DECISION_SCOPE", "NOT_APPLICABLE"))

        # INV-295-04: a completed task must have crossed TASK_DISPATCHED first.
        contract_status = self._text(task.get("status") or lifecycle.get("contract_status")).upper()
        canonical_state = self._text(lifecycle.get("canonical_state")).upper()
        completed = bool(completions) or contract_status == "COMPLETED" or canonical_state == "COMPLETED"
        if completed and not dispatches:
            if strict_event_history:
                violations.append(self._violation(
                    "COMPLETED_WITHOUT_DISPATCHED",
                    category="LIFECYCLE_ORDER",
                    severity="HIGH",
                    task_id=task_id,
                    message="TaskContract reached COMPLETED without a canonical TASK_DISPATCHED event.",
                    evidence={
                        "contract_status": contract_status,
                        "canonical_state": canonical_state,
                        "completion_sequence_numbers": sorted(completions),
                    },
                ))
                checks.append(self._check("COMPLETION_REQUIRES_PRIOR_DISPATCH", "FAIL"))
            else:
                checks.append(self._check(
                    "COMPLETION_REQUIRES_PRIOR_DISPATCH",
                    "UNVERIFIABLE",
                    evidence={"projection_quality": quality},
                ))
        elif completed:
            first_completion = min(completions) if completions else None
            prior_dispatch = bool(dispatches) and (first_completion is None or min(dispatches) < first_completion)
            if first_completion is not None and not prior_dispatch and strict_event_history:
                violations.append(self._violation(
                    "COMPLETED_WITHOUT_DISPATCHED",
                    category="LIFECYCLE_ORDER",
                    severity="HIGH",
                    task_id=task_id,
                    message="Task completion precedes the first canonical TASK_DISPATCHED event.",
                    evidence={
                        "dispatch_sequence_numbers": dispatches,
                        "completion_sequence_numbers": sorted(completions),
                    },
                ))
                checks.append(self._check("COMPLETION_REQUIRES_PRIOR_DISPATCH", "FAIL"))
            else:
                checks.append(self._check("COMPLETION_REQUIRES_PRIOR_DISPATCH", "PASS"))
        else:
            checks.append(self._check("COMPLETION_REQUIRES_PRIOR_DISPATCH", "NOT_APPLICABLE"))

        # Stage 2.9.4 facts now become explicit Stage 2.9.5 integrity classifications.
        if required:
            if correlation is None:
                if "AUTHORITATIVE_TASK_CORRELATION_NOT_AVAILABLE" not in verification_reasons:
                    verification_reasons.append("AUTHORITATIVE_TASK_CORRELATION_NOT_AVAILABLE")
            else:
                for ref in correlation.get("references") or []:
                    status = self._text(ref.get("status")).upper()
                    if status in {"MISSING_GOVERNANCE_RECORD", "MISSING_LOCAL_REFERENCE"} and not ref.get("optional"):
                        violations.append(self._violation(
                            "GOVERNANCE_REQUIRED_REFERENCE_MISSING",
                            category="CROSS_SUBSYSTEM_PROVENANCE",
                            severity="HIGH",
                            task_id=task_id,
                            message="A required Governance provenance reference cannot be resolved consistently.",
                            evidence={
                                "reference_kind": ref.get("kind"),
                                "reference_id": ref.get("reference_id"),
                                "correlation_status": status,
                            },
                        ))
                for comparison in correlation.get("field_comparisons") or []:
                    if self._text(comparison.get("status")).upper() != "MISMATCH":
                        continue
                    if self._text(comparison.get("field")) == "decision.scope_contract_id":
                        continue  # classified by the specific scope invariant above
                    violations.append(self._violation(
                        "GOVERNANCE_FIELD_MISMATCH",
                        category="CROSS_SUBSYSTEM_PROVENANCE",
                        severity="HIGH",
                        task_id=task_id,
                        message="A local Governance binding field differs from the authoritative Governance record.",
                        evidence={
                            "field": comparison.get("field"),
                            "local": comparison.get("local"),
                            "authoritative": comparison.get("authoritative"),
                        },
                    ))

        correlation_status = self._text((lineage.get("governance_correlation") or {}).get("status")).upper()
        if required and correlation_status in {"UNAVAILABLE", "PROTOCOL_ERROR", "ERROR"}:
            reason = f"GOVERNANCE_CORRELATION_{correlation_status}"
            if reason not in verification_reasons:
                verification_reasons.append(reason)

        # Deduplicate exact violations because a malformed record can be surfaced by
        # multiple read-side facts while still representing one invariant breach.
        violations = self._dedupe_violations(violations)
        violation_count = len(violations)
        status = self._status(violation_count, verification_reasons)
        return make_json_safe({
            "schema_version": INTEGRITY_PROBE_SCHEMA_V1,
            "scope": "TASK",
            "mission_id": mission_id,
            "task_id": task_id,
            "status": status,
            "classification": "LINEAGE_INTEGRITY_VIOLATION_CLASSIFICATION_STAGE_2_9_5",
            "read_only": True,
            "required_authority": required,
            "verification_complete": not verification_reasons,
            "verification_reasons": verification_reasons,
            "checks": checks,
            "violations": violations,
            "violation_count": violation_count,
            "severity_counts": self._severity_counts(violations),
            "violation_code_counts": self._code_counts(violations),
        })

    @classmethod
    def _required_authority(cls, lineage: Mapping[str, Any]) -> bool:
        binding = lineage.get("governance_binding") or {}
        return bool(binding.get("required_authority")) or cls._text(binding.get("authorization_mode")).upper() == "REQUIRED"

    @classmethod
    def _event_positions(cls, events: Sequence[Mapping[str, Any]]) -> Dict[str, List[int]]:
        result: Dict[str, List[int]] = {}
        for fallback, event in enumerate(events, start=1):
            event_type = cls._text((event or {}).get("event_type")).upper()
            if not event_type:
                continue
            try:
                sequence = int((event or {}).get("sequence_no") or fallback)
            except (TypeError, ValueError):
                sequence = fallback
            result.setdefault(event_type, []).append(sequence)
        return result

    @classmethod
    def _event_policy_decision(cls, event: Mapping[str, Any]) -> Optional[str]:
        direct = cls._nullable((event or {}).get("policy_decision_id"))
        if direct:
            return direct
        payload = (event or {}).get("payload") or {}
        if isinstance(payload, Mapping):
            return cls._nullable(payload.get("policy_decision_id") or payload.get("decision_id"))
        return None

    @classmethod
    def _comparison(cls, correlation: Optional[Mapping[str, Any]], field: str) -> Optional[Mapping[str, Any]]:
        if not correlation:
            return None
        for row in correlation.get("field_comparisons") or []:
            if cls._text(row.get("field")) == field:
                return row
        return None

    @staticmethod
    def _check(name: str, status: str, evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        return make_json_safe({
            "invariant": name,
            "status": status,
            "evidence": dict(evidence or {}),
        })

    @staticmethod
    def _violation(
        code: str,
        *,
        category: str,
        severity: str,
        task_id: Optional[str],
        message: str,
        evidence: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return make_json_safe({
            "code": code,
            "category": category,
            "severity": severity,
            "task_id": task_id,
            "message": message,
            "evidence": dict(evidence or {}),
        })

    @staticmethod
    def _status(violation_count: int, verification_reasons: Sequence[str]) -> str:
        if violation_count:
            return "VIOLATION_DETECTED"
        if verification_reasons:
            return "UNVERIFIABLE"
        return "PASS"

    @staticmethod
    def _severity_counts(violations: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
        result = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for row in violations:
            severity = str(row.get("severity") or "LOW").upper()
            result[severity] = result.get(severity, 0) + 1
        return result

    @staticmethod
    def _code_counts(violations: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for row in violations:
            code = str(row.get("code") or "UNKNOWN")
            result[code] = result.get(code, 0) + 1
        return result

    @staticmethod
    def _dedupe_violations(violations: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        result: List[Dict[str, Any]] = []
        for row in violations:
            evidence = row.get("evidence") or {}
            key = (
                row.get("code"),
                row.get("task_id"),
                str(evidence.get("field") or evidence.get("reference_kind") or evidence.get("local_event_id") or ""),
                str(evidence.get("reference_id") or evidence.get("governance_event_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(row))
        return result

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _nullable(cls, value: Any) -> Optional[str]:
        text = cls._text(value)
        return text or None
