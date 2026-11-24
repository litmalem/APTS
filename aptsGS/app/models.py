from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW = "REVIEW"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionClass(str, Enum):
    INTERNAL_REASONING = "INTERNAL_REASONING"
    REPORTING = "REPORTING"
    TASK_DELEGATION = "TASK_DELEGATION"
    CTI_SOURCE_READ = "CTI_SOURCE_READ"
    TARGET_RECON = "TARGET_RECON"
    TARGET_ENUMERATION = "TARGET_ENUMERATION"
    VULNERABILITY_VALIDATION = "VULNERABILITY_VALIDATION"
    CONTROLLED_EXPLOITATION = "CONTROLLED_EXPLOITATION"
    POST_EXPLOITATION = "POST_EXPLOITATION"
    CREDENTIAL_USE = "CREDENTIAL_USE"
    PRIVILEGE_ESCALATION = "PRIVILEGE_ESCALATION"
    LATERAL_MOVEMENT = "LATERAL_MOVEMENT"
    DATA_ACCESS = "DATA_ACCESS"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"


class ScopeTargetInput(BaseModel):
    target_type: str = Field(description="IP, CIDR, HOST, DOMAIN, URL, APPLICATION, OTHER")
    target_value: str
    environment: str = "LAB"
    allowed: bool = True
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_url_target_type(self):
        if self.target_value.strip().lower().startswith(("http://", "https://")) and self.target_type.upper() != "URL":
            raise ValueError("HTTP(S) targets must use target_type URL")
        return self


class ScopeSourceInput(BaseModel):
    source_id: str
    source_type: str = "CTI"
    allowed: bool = True
    constraints: Dict[str, Any] = Field(default_factory=dict)


class ActionConstraintInput(BaseModel):
    action_class: ActionClass
    action_name: str = "*"
    effect: Decision = Decision.DENY
    max_risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    constraints: Dict[str, Any] = Field(default_factory=dict)


class ScopeContractCreate(BaseModel):
    mission_id: str
    name: str
    policy_set_id: str = "default-policy"
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    created_by: str
    approved_by: Optional[str] = None
    targets: List[ScopeTargetInput] = Field(default_factory=list)
    sources: List[ScopeSourceInput] = Field(default_factory=list)
    action_constraints: List[ActionConstraintInput] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_allowed_delegation_contract(self):
        # All scope-authoring entry points share this validation (admin UI and
        # compatibility machine endpoint). DENY rules remain valid fail-closed.
        from .delegation_preflight import allow_rule_problems
        for rule in self.action_constraints:
            if rule.action_class == ActionClass.TASK_DELEGATION and rule.effect == Decision.ALLOW:
                values = rule.model_dump(mode="json")
                allowed = rule.constraints.get("allowed_capabilities")
                first = allowed[0] if isinstance(allowed, list) and allowed else ""
                problems = allow_rule_problems(values, first)
                if problems:
                    raise ValueError("Invalid TASK_DELEGATION ALLOW rule: " + ", ".join(problems))
        return self


class AuthorizationRequest(BaseModel):
    mission_id: str
    scope_contract_id: Optional[str] = None
    subject_component: str
    action_class: ActionClass
    action_name: str
    resource_type: str
    resource_value: str
    context: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    requested_by: Optional[str] = None


class PolicyDecisionRevalidationRequest(BaseModel):
    decision_id: str
    request_id: str
    mission_id: str
    scope_contract_id: Optional[str] = None
    scope_version: Optional[int] = None
    policy_set_id: Optional[str] = None
    policy_version: Optional[int] = None
    decision_hash: str
    subject_component: Optional[str] = None
    action_class: ActionClass
    action_name: str
    resource_type: str
    resource_value: str
    task_id: Optional[str] = None
    requested_by: Optional[str] = None


class ApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Optional compatibility assertions; authenticated server identity is authority.
    approver_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    approver_role: Optional[str] = Field(default=None, min_length=1, max_length=100)
    decision: str
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("decision")
    @classmethod
    def normalize_decision(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"APPROVE", "DENY"}:
            raise ValueError("decision must be APPROVE or DENY")
        return value


class EmergencyStopInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    actor_id: str
    reason: str = Field(min_length=3, max_length=4000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RevokeDecisionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    actor_id: str
    reason: str = Field(min_length=3, max_length=4000)


class AuthorizationResponse(BaseModel):
    request_id: str
    decision_id: str
    mission_id: str
    decision: Decision
    risk_score: float
    risk_level: RiskLevel
    reason_codes: List[str]
    constraints: Dict[str, Any]
    requires_human_approval: bool = False
    approval_request_id: Optional[str] = None
    valid_from: str
    valid_until: str
    policy_set_id: Optional[str] = None
    policy_version: Optional[int] = None
    scope_contract_id: Optional[str] = None
    scope_version: Optional[int] = None
    decision_hash: str
