-- ============================================================================
-- VulnDesk CTI Harmonized Runtime - Stage 2 PolicyDecision <-> TaskContract
-- Target: MariaDB 10.11+
-- Stage : 2.1-2.5 (PolicyDecision-bound TaskContract)
--
-- Architectural ownership:
--   * aptsGSS / GOV-PLANE owns authoritative PolicyDecision.
--   * VulnDesk CTI-A01 owns TaskContract proposal/commit/dispatch lifecycle.
--   * Local CTI guards may only be more restrictive; they never manufacture
--     external authority.
--   * No cross-database foreign key is introduced.
-- ============================================================================

USE `vulndesk`;
SET NAMES utf8mb4;

ALTER TABLE `cti_task_contracts`
  ADD COLUMN IF NOT EXISTS `authorization_mode` varchar(40) NOT NULL DEFAULT 'NOT_REQUIRED_INTERNAL' AFTER `trace_id`,
  ADD COLUMN IF NOT EXISTS `authorization_authority` varchar(80) DEFAULT NULL AFTER `authorization_mode`,
  ADD COLUMN IF NOT EXISTS `authorization_authority_component` varchar(80) DEFAULT NULL AFTER `authorization_authority`,
  ADD COLUMN IF NOT EXISTS `policy_decision_id` varchar(100) DEFAULT NULL AFTER `authorization_authority_component`,
  ADD COLUMN IF NOT EXISTS `authorization_request_id` varchar(100) DEFAULT NULL AFTER `policy_decision_id`,
  ADD COLUMN IF NOT EXISTS `policy_decision_hash` char(64) DEFAULT NULL AFTER `authorization_request_id`,
  ADD COLUMN IF NOT EXISTS `authorization_decision` varchar(20) DEFAULT NULL AFTER `policy_decision_hash`,
  ADD COLUMN IF NOT EXISTS `authorization_status` varchar(30) DEFAULT NULL AFTER `authorization_decision`,
  ADD COLUMN IF NOT EXISTS `authorization_valid_from` datetime DEFAULT NULL AFTER `authorization_status`,
  ADD COLUMN IF NOT EXISTS `authorization_valid_until` datetime DEFAULT NULL AFTER `authorization_valid_from`,
  ADD COLUMN IF NOT EXISTS `scope_contract_id` varchar(100) DEFAULT NULL AFTER `authorization_valid_until`,
  ADD COLUMN IF NOT EXISTS `scope_version` bigint DEFAULT NULL AFTER `scope_contract_id`,
  ADD COLUMN IF NOT EXISTS `policy_set_id` varchar(100) DEFAULT NULL AFTER `scope_version`,
  ADD COLUMN IF NOT EXISTS `approval_request_id` varchar(100) DEFAULT NULL AFTER `policy_set_id`,
  ADD COLUMN IF NOT EXISTS `governance_action_class` varchar(100) DEFAULT NULL AFTER `approval_request_id`,
  ADD COLUMN IF NOT EXISTS `governance_action_name` varchar(120) DEFAULT NULL AFTER `governance_action_class`,
  ADD COLUMN IF NOT EXISTS `governance_resource_type` varchar(100) DEFAULT NULL AFTER `governance_action_name`,
  ADD COLUMN IF NOT EXISTS `governance_resource_value` varchar(500) DEFAULT NULL AFTER `governance_resource_type`,
  ADD COLUMN IF NOT EXISTS `governance_subject_component` varchar(120) DEFAULT NULL AFTER `governance_resource_value`,
  ADD COLUMN IF NOT EXISTS `governance_reason_codes_json` longtext DEFAULT NULL AFTER `governance_subject_component`,
  ADD COLUMN IF NOT EXISTS `governance_constraints_json` longtext DEFAULT NULL AFTER `governance_reason_codes_json`,
  ADD COLUMN IF NOT EXISTS `governance_request_json` longtext DEFAULT NULL AFTER `governance_constraints_json`,
  ADD COLUMN IF NOT EXISTS `authorization_bound_at` datetime DEFAULT NULL AFTER `governance_request_json`;

CREATE INDEX IF NOT EXISTS `idx_cti_task_policy_decision`
    ON `cti_task_contracts` (`policy_decision_id`,`status`);
CREATE INDEX IF NOT EXISTS `idx_cti_task_auth_request`
    ON `cti_task_contracts` (`authorization_request_id`);
CREATE INDEX IF NOT EXISTS `idx_cti_task_scope_binding`
    ON `cti_task_contracts` (`scope_contract_id`,`scope_version`);
CREATE INDEX IF NOT EXISTS `idx_cti_task_authorization_expiry`
    ON `cti_task_contracts` (`authorization_mode`,`authorization_valid_until`);

-- Existing pre-Stage-2 rows are explicitly internal/not externally bound.  The
-- application never interprets these legacy rows as authorized external tasks.
UPDATE `cti_task_contracts`
   SET `authorization_mode` = 'NOT_REQUIRED_INTERNAL'
 WHERE `authorization_mode` IS NULL OR TRIM(`authorization_mode`) = '';

INSERT INTO `cti_component_registry`
(`component_id`,`service_key`,`service_name`,`component_type`,`mechanism`,`authority_boundary`,`optional_component`,`service_side`,`enabled`,`status`,`config_json`,`sort_order`)
VALUES
('CTI-INF05','governance_client','Governance Client','Infrastructure Service',
 'Authoritative HTTP policy adapter',
 'Transport/contract validation only; aptsGSS remains policy authority',
 0,'vulndesk',1,'idle',
 '{"architecture_version":"2026-08-harmonized","stage":"2-policy-bound-task-contract","authority":"aptsGSS","mode":"fail-closed"}',940)
ON DUPLICATE KEY UPDATE
`service_name`=VALUES(`service_name`),
`component_type`=VALUES(`component_type`),
`mechanism`=VALUES(`mechanism`),
`authority_boundary`=VALUES(`authority_boundary`),
`optional_component`=VALUES(`optional_component`),
`sort_order`=VALUES(`sort_order`),
`updated_at`=CURRENT_TIMESTAMP;

-- Verification queries -------------------------------------------------------
SELECT
    COUNT(*) AS total_task_contracts,
    SUM(`authorization_mode` = 'REQUIRED') AS externally_authorized_tasks,
    SUM(`authorization_mode` = 'NOT_REQUIRED_INTERNAL') AS internal_tasks
FROM `cti_task_contracts`;

SELECT
    `task_id`, `mission_id`, `task_type`, `status`, `authorization_mode`,
    `policy_decision_id`, `authorization_request_id`, `authorization_decision`,
    `authorization_status`, `scope_contract_id`, `scope_version`,
    `governance_resource_type`, `governance_resource_value`,
    `authorization_valid_until`
FROM `cti_task_contracts`
ORDER BY `id` DESC
LIMIT 20;
