-- ============================================================================
-- VulnDesk CTI Harmonized Runtime - Stage 2.8.8
-- Cross-Subsystem Governance Event Lineage
-- Target: MariaDB 10.11+
--
-- Adds first-class authoritative aptsGSS outbox-event references for:
--   PolicyDecision issuance -> TaskContract commit
--   PolicyDecision revalidation -> pre-dispatch dispatch decision
--   Revocation -> existing revocation_event_id path (unchanged)
--
-- No cross-database FK is created. aptsGSS remains authoritative and the
-- gevent-* values are immutable external references only.
-- ============================================================================

USE `vulndesk`;
SET NAMES utf8mb4;

ALTER TABLE `cti_task_contracts`
  ADD COLUMN IF NOT EXISTS `authorization_governance_event_id` varchar(120) DEFAULT NULL
    AFTER `authorization_authority_component`,
  ADD COLUMN IF NOT EXISTS `pre_dispatch_governance_event_id` varchar(120) DEFAULT NULL
    AFTER `pre_dispatch_revalidation_id`;

CREATE INDEX IF NOT EXISTS `idx_cti_task_auth_governance_event`
    ON `cti_task_contracts` (`authorization_governance_event_id`);
CREATE INDEX IF NOT EXISTS `idx_cti_task_revalidation_governance_event`
    ON `cti_task_contracts` (`pre_dispatch_governance_event_id`);

ALTER TABLE `cti_decision_traces`
  ADD COLUMN IF NOT EXISTS `upstream_event_id` varchar(120) DEFAULT NULL
    AFTER `revalidation_id`;

CREATE INDEX IF NOT EXISTS `idx_cti_decision_upstream_event`
    ON `cti_decision_traces` (`upstream_event_id`, `created_at`);

ALTER TABLE `cti_audit_log`
  ADD COLUMN IF NOT EXISTS `upstream_event_ref` varchar(120) DEFAULT NULL
    AFTER `versions_json`;

CREATE INDEX IF NOT EXISTS `idx_cti_audit_upstream_event`
    ON `cti_audit_log` (`upstream_event_ref`, `created_at`);

UPDATE `cti_component_registry`
   SET `config_json` = JSON_SET(
         CASE WHEN JSON_VALID(`config_json`) THEN `config_json` ELSE '{}' END,
         '$.cross_subsystem_lineage', 'authoritative-gevent-correlated',
         '$.stage_2_8_8', TRUE
       ),
       `updated_at` = CURRENT_TIMESTAMP
 WHERE `component_id` IN ('CTI-A01', 'CTI-INF02', 'CTI-INF05');

-- --------------------------------------------------------------------------
-- Acceptance probes
-- --------------------------------------------------------------------------
SELECT
    task_id,
    mission_id,
    authorization_mode,
    authorization_governance_event_id,
    policy_decision_id,
    authorization_request_id,
    pre_dispatch_revalidation_id,
    pre_dispatch_governance_event_id,
    revocation_event_id,
    status
FROM cti_task_contracts
WHERE authorization_mode = 'REQUIRED'
ORDER BY id DESC
LIMIT 20;

SELECT
    trace_id,
    decision_type,
    lineage_trace_id,
    task_id,
    policy_decision_id,
    authorization_request_id,
    revalidation_id,
    upstream_event_id,
    created_at
FROM cti_decision_traces
WHERE upstream_event_id IS NOT NULL
ORDER BY id DESC
LIMIT 50;

SELECT
    audit_id,
    event_type,
    trace_id,
    upstream_event_ref,
    downstream_event_ref,
    created_at
FROM cti_audit_log
WHERE upstream_event_ref IS NOT NULL
ORDER BY id DESC
LIMIT 50;
