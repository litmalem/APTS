"""Server-owned, bounded GSS profile for autonomous Pentest workflow routing.

The profile only compiles a narrow set of existing action classes. It does not
authorize dispatch, execution, exploitation, credential use, or target cleanup.
Every Stage 6 execution still needs a fresh, exact GSS revalidation decision.
"""
from __future__ import annotations

from copy import deepcopy

from .delegation_preflight import allow_rule_problems

PROFILE_ID = "PENTEST_AUTONOMOUS_BOUNDED_V1"
WPT_PROFILE_ID = "WPT_FINGERPRINT_AUTONOMOUS_V1"
PROFILE_LABEL = "Pentest terukur: Recon, WPT, validasi aman, cleanup lokal"
DELEGATION_NAME = "delegate_planned_task"
DELEGATION_SUBJECT_COMPONENT = "APTS-MO01"
DELEGATION_PURPOSE = "PRE_DELEGATION_ONLY"
EXECUTION_NAME = "AUTHORIZE_TARGET_EXECUTION"
DELEGATION_CAPABILITIES = (
    "PENTEST:pentest.recon",
    "PENTEST:pentest.validate",
    "CTI:cti.analyze.context",
)
SAFE_RECON_TECHNIQUES = (
    "TCP_CONNECT_SCAN",
    "TCP_BANNER_READ",
    "WEB_TECHNOLOGY_FINGERPRINT",
    "BOUNDED_WEB_SURFACE_ENUMERATION",
)
SAFE_VALIDATION_TECHNIQUES = (
    "HTTP_HEADER_INSPECTION",
    "SAFE_VERSION_CONFIGURATION_CONFIRMATION",
    "HTTP_RESPONSE_METADATA",
)
# Bounded, read-only TARGET_RECON techniques the WPT autonomous profile authorizes.
# Fingerprinting and bounded surface enumeration are both LOW-risk, GET-only, and
# non-state-changing; enumeration simply probes a fixed, same-origin path set.
WPT_RECON_TECHNIQUES = (
    "WEB_TECHNOLOGY_FINGERPRINT",
    "BOUNDED_WEB_SURFACE_ENUMERATION",
)
# Shared Mission/task network-request budget for the recon tier. It must cover one
# fingerprinting pass plus one bounded enumeration pass within the same task.
WPT_RECON_BUDGET = 12
BLOCKED_ACTION_CLASSES = frozenset({
    "TARGET_ENUMERATION",
    "CONTROLLED_EXPLOITATION",
    "POST_EXPLOITATION",
    "CREDENTIAL_USE",
    "PRIVILEGE_ESCALATION",
    "LATERAL_MOVEMENT",
    "DATA_ACCESS",
    "DESTRUCTIVE_ACTION",
})


def _text(value):
    return value.value if hasattr(value, "value") else value


def default_console_profile(targets, action_constraints, previous_metadata=None):
    """Default only newly authored, unconstrained LAB URL scopes to WPT.

    Revisions inherit the persisted profile; explicit operator rules never
    become implicit grants. Machine-created internal scopes keep their API.
    """
    if previous_metadata is not None:
        return (previous_metadata.get('gss_workflow_profile') or {}).get('profile_id', 'NONE')
    allowed = [t for t in targets if t.get('allowed', True)]
    if (not action_constraints and allowed and all(
            t.get('target_type', '').upper() == 'URL'
            and t.get('environment', 'LAB').upper() == 'LAB' for t in allowed)):
        return WPT_PROFILE_ID
    return 'NONE'


def _fingerprint_profile(rules):
    for rule in rules:
        if rule.get('action_class') == 'TARGET_RECON':
            if rule.get('effect') != 'ALLOW' or _approval(rule):
                raise ValueError('WPT profile cannot override Recon DENY, REVIEW or approval')
            if 'WEB_TECHNOLOGY_FINGERPRINT' in (rule.get('constraints') or {}).get('prohibited_techniques', []):
                raise ValueError('WPT fingerprinting technique is prohibited')
    for name in ('recon', 'web_technology_fingerprinting', EXECUTION_NAME):
        if not any(r.get('action_class') == 'TARGET_RECON' and r.get('action_name') in (name, '*') for r in rules):
            rules.append({'action_class': 'TARGET_RECON', 'action_name': name,
                          'effect': 'ALLOW', 'max_risk_level': 'LOW',
                          'requires_approval': False, 'constraints': {}})
    for rule in rules:
        if rule.get('action_class') != 'TARGET_RECON':
            continue
        limits = rule['constraints']
        techniques = limits.get('allowed_techniques')
        if techniques is not None and not any(t in techniques for t in WPT_RECON_TECHNIQUES):
            raise ValueError('WPT profile requires a permitted bounded recon technique')
        methods = limits.get('allowed_methods')
        if methods is not None and 'GET' not in methods:
            raise ValueError('WPT profile requires permitted GET requests')
        for key in ('max_network_requests', 'max_requests'):
            cap = limits.get(key, WPT_RECON_BUDGET)
            if type(cap) is not int or cap < 1:
                raise ValueError('WPT request budget must be a positive integer')
            limits[key] = min(cap, WPT_RECON_BUDGET)
        limits.update(allowed_methods=['GET'], allowed_techniques=list(WPT_RECON_TECHNIQUES),
                      read_only=True, state_changing_requests=False, workflow_profile=WPT_PROFILE_ID)
        rule['max_risk_level'] = 'LOW'
    delegations = [r for r in rules if r.get('action_class') == 'TASK_DELEGATION'
                   and r.get('action_name') in ('*', DELEGATION_NAME)]
    if not delegations:
        rules.append({'action_class': 'TASK_DELEGATION', 'action_name': DELEGATION_NAME,
                      'effect': 'ALLOW', 'max_risk_level': 'LOW', 'requires_approval': False,
                      'constraints': {'allowed_capabilities': ['PENTEST:pentest.recon'],
                                      'execution_authorized': False, 'target_actuation': False,
                                      'authorized_subject_component': DELEGATION_SUBJECT_COMPONENT,
                                      'authorization_purpose': DELEGATION_PURPOSE,
                                      'workflow_profile': WPT_PROFILE_ID}})
    else:
        for rule in delegations:
            if allow_rule_problems(rule) or rule['constraints']['allowed_capabilities'] != ['PENTEST:pentest.recon']:
                raise ValueError('WPT profile requires exact non-actuating Recon delegation')
            for key, expected in (('authorized_subject_component', DELEGATION_SUBJECT_COMPONENT),
                                  ('authorization_purpose', DELEGATION_PURPOSE)):
                if key in rule['constraints'] and rule['constraints'][key] != expected:
                    raise ValueError('Incompatible WPT delegation binding: ' + key)
                rule['constraints'][key] = expected
    return rules, {'profile_id': WPT_PROFILE_ID, 'profile_label': 'Recon WPT otonom terbatas: fingerprinting dan enumeration',
                   'version': 2, 'execution_authorized': False, 'target_actuation': False,
                   'delegation_capabilities': ['PENTEST:pentest.recon'],
                   'recon_techniques': list(WPT_RECON_TECHNIQUES), 'max_network_requests': WPT_RECON_BUDGET}


def _approval(rule):
    value = rule.get("requires_approval", False)
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError("Workflow profile cannot normalize requires_approval")


def _tighten_action_rules(rules, action_class, safe_techniques, max_risk, network_cap=None):
    """Tighten existing ALLOW rules for a supported class; reject review/deny."""
    applicable = [r for r in rules if _text(r.get("action_class")) == action_class]
    if not any(r.get("action_name") == EXECUTION_NAME for r in applicable):
        generated = {
            "action_class": action_class,
            "action_name": EXECUTION_NAME,
            "effect": "ALLOW",
            "max_risk_level": max_risk,
            "requires_approval": False,
            "constraints": {},
        }
        rules.append(generated)
        applicable.append(generated)

    for rule in applicable:
        effect = str(_text(rule.get("effect", "DENY"))).upper()
        if effect != "ALLOW" or _approval(rule):
            raise ValueError(
                f"{PROFILE_ID} cannot activate while {action_class} has DENY, REVIEW, "
                "or human approval requirements; revise the authoritative scope first"
            )
        current_risk = str(_text(rule.get("max_risk_level", "LOW"))).upper()
        risk_order = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "CRITICAL": 4}
        if current_risk not in risk_order:
            raise ValueError(f"Invalid max_risk_level for {action_class}")
        rule["max_risk_level"] = max_risk if risk_order[current_risk] > risk_order[max_risk] else current_risk
        constraints = rule.get("constraints")
        if not isinstance(constraints, dict):
            raise ValueError(f"Invalid constraints for {action_class}")
        old_techniques = constraints.get("allowed_techniques")
        if old_techniques is None:
            constraints["allowed_techniques"] = list(safe_techniques)
        elif isinstance(old_techniques, list):
            intersection = [x for x in safe_techniques if x in old_techniques]
            if not intersection:
                raise ValueError(f"No bounded techniques remain for {action_class}")
            constraints["allowed_techniques"] = intersection
        else:
            raise ValueError(f"Invalid allowed_techniques for {action_class}")
        old_prohibited = constraints.get("prohibited_techniques", [])
        if not isinstance(old_prohibited, list) or any(not isinstance(x, str) for x in old_prohibited):
            raise ValueError(f"Invalid prohibited_techniques for {action_class}")
        constraints["prohibited_techniques"] = sorted(set(old_prohibited) | (
            set(SAFE_RECON_TECHNIQUES + SAFE_VALIDATION_TECHNIQUES) - set(safe_techniques)
        ))
        constraints["read_only"] = True
        constraints["target_actuation"] = False
        constraints["workflow_profile"] = PROFILE_ID
        if network_cap is not None:
            old_cap = constraints.get("max_network_requests")
            if old_cap is not None and (type(old_cap) is not int or old_cap < 1):
                raise ValueError("max_network_requests must be a positive integer")
            constraints["max_network_requests"] = min(old_cap, network_cap) if old_cap else network_cap


def apply_workflow_profile(action_constraints, profile_id):
    """Return compiled action constraints and profile metadata.

    Existing DENY/REVIEW decisions are never weakened. Existing allowed rules
    are narrowed to the fixed read-only adapter techniques and risk ceilings.
    The delegation rule is exact and explicitly grants no execution authority.
    """
    rules = deepcopy(action_constraints or [])
    if profile_id is None:
        return rules, None
    if profile_id in ("", "NONE"):
        rules = [
            rule for rule in rules
            if (rule.get("constraints") or {}).get("workflow_profile") not in (PROFILE_ID, WPT_PROFILE_ID)
            and (rule.get("constraints") or {}).get("policy_profile") != "GSS_AUTO_RECON_TASK_DELEGATION_V1"
        ]
        return rules, None
    if profile_id == WPT_PROFILE_ID:
        return _fingerprint_profile(rules)
    if profile_id != PROFILE_ID:
        raise ValueError("Unsupported GSS workflow profile")

    for rule in rules:
        action_class = str(_text(rule.get("action_class", ""))).upper()
        if action_class in BLOCKED_ACTION_CLASSES and str(_text(rule.get("effect", "DENY"))).upper() == "ALLOW":
            raise ValueError(
                f"{PROFILE_ID} cannot be combined with an ALLOW for {action_class}; "
                "remove that grant or use a separate explicitly reviewed scope"
            )

    _tighten_action_rules(rules, "TARGET_RECON", SAFE_RECON_TECHNIQUES, "LOW", network_cap=20)
    _tighten_action_rules(
        rules, "VULNERABILITY_VALIDATION", SAFE_VALIDATION_TECHNIQUES, "MODERATE"
    )

    existing_delegation = [
        r for r in rules
        if str(_text(r.get("action_class", ""))).upper() == "TASK_DELEGATION"
        and r.get("action_name") in ("*", DELEGATION_NAME)
    ]
    if existing_delegation:
        for rule in existing_delegation:
            constraints = rule.get("constraints")
            if not isinstance(constraints, dict):
                raise ValueError("Invalid delegation constraints")
            for key, expected in (("authorized_subject_component", DELEGATION_SUBJECT_COMPONENT),
                                  ("authorization_purpose", DELEGATION_PURPOSE)):
                if key in constraints and constraints[key] != expected:
                    raise ValueError("Incompatible delegation binding: " + key)
                constraints[key] = expected
            constraints["workflow_profile"] = PROFILE_ID
            caps = constraints.get("allowed_capabilities")
            problems = allow_rule_problems(rule, DELEGATION_CAPABILITIES[0])
            for capability in DELEGATION_CAPABILITIES[1:]:
                if not isinstance(caps, list) or capability not in caps:
                    problems.append("SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED:" + capability)
            if problems:
                raise ValueError(
                    f"{PROFILE_ID} found an incompatible TASK_DELEGATION rule: "
                    + ", ".join(problems)
                )
    else:
        delegation = {
            "action_class": "TASK_DELEGATION",
            "action_name": DELEGATION_NAME,
            "effect": "ALLOW",
            "max_risk_level": "LOW",
            "requires_approval": False,
            "constraints": {
                "allowed_capabilities": list(DELEGATION_CAPABILITIES),
                "authorized_subject_component": DELEGATION_SUBJECT_COMPONENT,
                "authorization_purpose": DELEGATION_PURPOSE,
                "execution_authorized": False,
                "target_actuation": False,
                "workflow_profile": PROFILE_ID,
            },
        }
        for capability in DELEGATION_CAPABILITIES:
            problems = allow_rule_problems(delegation, capability)
            if problems:
                raise ValueError("Invalid generated delegation rule: " + ", ".join(problems))
        rules.append(delegation)

    return rules, {
        "profile_id": PROFILE_ID,
        "profile_label": PROFILE_LABEL,
        "version": 1,
        "execution_authorized": False,
        "target_actuation": False,
        "destructive_actions_allowed": False,
        "target_rollback_supported": False,
        "delegation_capabilities": list(DELEGATION_CAPABILITIES),
        "recon_techniques": list(SAFE_RECON_TECHNIQUES),
        "validation_techniques": list(SAFE_VALIDATION_TECHNIQUES),
        "max_network_requests": 20,
        "cti_source_authorization_required": True,
    }
