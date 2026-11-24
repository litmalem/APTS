-- ============================================================================
-- Default APTS Governance policy set
-- Deny-by-default. Scope contracts must explicitly allow action classes.
-- ============================================================================
USE apts_governance;

INSERT INTO gov_policy_sets
    (policy_set_id, name, version, status, default_effect, effective_from, description)
VALUES
    ('default-policy', 'APTS Default Governance Policy', 1, 'ACTIVE', 'DENY',
     CURRENT_TIMESTAMP,
     'Deny-by-default baseline policy for CTI and future Pentest subsystems.')
ON DUPLICATE KEY UPDATE
    name=VALUES(name),
    status='ACTIVE',
    default_effect='DENY',
    description=VALUES(description),
    updated_at=CURRENT_TIMESTAMP;

INSERT INTO gov_policy_rules
    (rule_id, policy_set_id, priority, rule_name, rule_type, effect,
     action_class, condition_json, obligations_json, enabled)
VALUES
    ('GOV-R001', 'default-policy', 1,
     'Emergency stop preempts target actions', 'HARD_GUARD', 'DENY', NULL,
     '{"when":"emergency_stop_active","except":["INTERNAL_REASONING","REPORTING"]}',
     '{"reason_code":"EMERGENCY_STOP_ACTIVE"}', 1),
    ('GOV-R010', 'default-policy', 10,
     'Destructive actions are forbidden', 'HARD_GUARD', 'DENY', 'DESTRUCTIVE_ACTION',
     '{"always":true}',
     '{"reason_code":"HARD_DENY_DESTRUCTIVE_ACTION"}', 1),
    ('GOV-R020', 'default-policy', 20,
     'Unknown actions are deny-by-default', 'DEFAULT', 'DENY', NULL,
     '{"unknown_action":true}',
     '{"reason_code":"UNKNOWN_ACTION_DENIED"}', 1),
    ('GOV-R100', 'default-policy', 100,
     'Internal reasoning has no target actuation authority', 'BOUNDARY', 'ALLOW', 'INTERNAL_REASONING',
     '{"target_actuation":false}',
     '{"constraints":{"target_actuation":false}}', 1),
    ('GOV-R110', 'default-policy', 110,
     'Reporting has no target actuation authority', 'BOUNDARY', 'ALLOW', 'REPORTING',
     '{"target_actuation":false}',
     '{"constraints":{"target_actuation":false}}', 1),
    ('GOV-R200', 'default-policy', 200,
     'CTI source reads require source allowlist', 'SCOPE_GUARD', 'ALLOW', 'CTI_SOURCE_READ',
     '{"requires_source_allowlist":true}',
     '{"reason_code":"SOURCE_ALLOWLIST_REQUIRED"}', 1)
ON DUPLICATE KEY UPDATE
    priority=VALUES(priority),
    rule_name=VALUES(rule_name),
    rule_type=VALUES(rule_type),
    effect=VALUES(effect),
    action_class=VALUES(action_class),
    condition_json=VALUES(condition_json),
    obligations_json=VALUES(obligations_json),
    enabled=VALUES(enabled),
    updated_at=CURRENT_TIMESTAMP;

INSERT INTO gov_compliance_obligations
    (obligation_id, policy_set_id, action_class, obligation_type, description,
     mandatory, config_json, enabled)
VALUES
    ('GOV-O001', 'default-policy', NULL, 'AUDIT',
     'Every policy decision must be written to the immutable-style chained audit log.',
     1, '{"chain_hash":"sha256"}', 1),
    ('GOV-O002', 'default-policy', 'CTI_SOURCE_READ', 'PROVENANCE',
     'External CTI acquisition must retain source/provenance references in downstream artifacts.',
     1, '{"required":true}', 1),
    ('GOV-O003', 'default-policy', 'CONTROLLED_EXPLOITATION', 'HUMAN_APPROVAL',
     'Controlled exploitation requires an explicit scope action constraint and approval when configured.',
     1, '{"approval_role":"SECURITY_APPROVER"}', 1)
ON DUPLICATE KEY UPDATE
    description=VALUES(description),
    mandatory=VALUES(mandatory),
    config_json=VALUES(config_json),
    enabled=VALUES(enabled),
    updated_at=CURRENT_TIMESTAMP;
