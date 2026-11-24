-- OPTIONAL EXAMPLE ONLY.
-- Creates a lab mission scope for exercising the API after installation.
-- Edit the target/source values before using this for a real mission.
USE apts_governance;

SET @scope_id = 'scope-lab-demo-001';

INSERT INTO gov_scope_contracts
    (scope_contract_id, mission_id, name, status, policy_set_id, version,
     valid_from, valid_until, created_by, approved_by, approved_at,
     metadata_json, contract_hash)
VALUES
    (@scope_id, 'mission-lab-demo-001', 'Local APTS Lab Demo', 'ACTIVE',
     'default-policy', 1, CURRENT_TIMESTAMP, DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 30 DAY),
     'local-operator', 'local-operator', CURRENT_TIMESTAMP,
     '{"purpose":"local research lab only"}',
     SHA2(CONCAT(@scope_id, ':mission-lab-demo-001'), 256))
ON DUPLICATE KEY UPDATE status='ACTIVE', updated_at=CURRENT_TIMESTAMP;

INSERT IGNORE INTO gov_scope_targets
    (scope_target_id, scope_contract_id, target_type, target_value,
     normalized_value, environment, allowed, notes)
VALUES
    ('stgt-lab-localhost', @scope_id, 'HOST', 'localhost', 'localhost', 'LAB', 1, 'Local lab host'),
    ('stgt-lab-loopback', @scope_id, 'CIDR', '127.0.0.0/8', '127.0.0.0/8', 'LAB', 1, 'Loopback lab range');

INSERT IGNORE INTO gov_scope_sources
    (scope_source_id, scope_contract_id, source_id, source_type, allowed, constraints_json)
VALUES
    ('ssrc-lab-nvd-cve', @scope_id, 'nvd-cve', 'CTI', 1, '{"read_only":true}'),
    ('ssrc-lab-nvd-cpe', @scope_id, 'nvd-cpe', 'CTI', 1, '{"read_only":true}'),
    ('ssrc-lab-mitre', @scope_id, 'mitre-attack', 'CTI', 1, '{"read_only":true}');

INSERT IGNORE INTO gov_scope_action_constraints
    (constraint_id, scope_contract_id, action_class, action_name,
     effect, max_risk_level, requires_approval, constraints_json)
VALUES
    ('sact-lab-cti-read', @scope_id, 'CTI_SOURCE_READ', '*', 'ALLOW', 'LOW', 0,
     '{"read_only":true,"target_actuation":false}'),
    ('sact-lab-recon', @scope_id, 'TARGET_RECON', '*', 'ALLOW', 'MODERATE', 0,
     '{"rate_limit_per_minute":30}'),
    ('sact-lab-enum', @scope_id, 'TARGET_ENUMERATION', '*', 'ALLOW', 'MODERATE', 0,
     '{"rate_limit_per_minute":20}'),
    ('sact-lab-validation', @scope_id, 'VULNERABILITY_VALIDATION', '*', 'REVIEW', 'HIGH', 1,
     '{"required_approver_role":"SECURITY_APPROVER"}'),
    ('sact-lab-exploit', @scope_id, 'CONTROLLED_EXPLOITATION', '*', 'REVIEW', 'CRITICAL', 1,
     '{"required_approver_role":"SECURITY_APPROVER","reversible_required":true}'),
    ('sact-lab-destructive', @scope_id, 'DESTRUCTIVE_ACTION', '*', 'DENY', 'LOW', 1,
     '{}');
