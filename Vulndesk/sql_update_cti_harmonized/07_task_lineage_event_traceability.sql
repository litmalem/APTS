-- ============================================================================
-- VulnDesk CTI Harmonized Runtime - Stage 2.8.1-2.8.3
-- End-to-End Task Lineage & Event Traceability Foundation
-- Target: MariaDB 10.11+
--
-- Semantics
-- ---------
-- event_id              : unique local event identity
-- trace_id              : stable proposal/task lifecycle lineage root
-- causation_event_id    : immediate parent event inside VulnDesk
-- upstream_event_id     : external subsystem event identity (e.g. gevent-*)
-- proposal_id/task_id/policy_decision_id/authorization_request_id/
-- revalidation_id       : first-class business identifiers
--
-- Historical rows are intentionally labelled cti-event-v1.  No synthetic
-- lineage is backfilled.  The Stage 2.8 runtime writes new rows as cti-event-v2.
-- ============================================================================

USE `vulndesk`;
SET NAMES utf8mb4;

ALTER TABLE `cti_events`
  ADD COLUMN IF NOT EXISTS `event_schema_version` varchar(40) NOT NULL DEFAULT 'cti-event-v1' AFTER `event_id`,
  ADD COLUMN IF NOT EXISTS `trace_id` varchar(120) DEFAULT NULL AFTER `severity`,
  ADD COLUMN IF NOT EXISTS `causation_event_id` varchar(120) DEFAULT NULL AFTER `trace_id`,
  ADD COLUMN IF NOT EXISTS `upstream_event_id` varchar(120) DEFAULT NULL AFTER `causation_event_id`,
  ADD COLUMN IF NOT EXISTS `proposal_id` varchar(120) DEFAULT NULL AFTER `upstream_event_id`,
  ADD COLUMN IF NOT EXISTS `task_id` varchar(120) DEFAULT NULL AFTER `proposal_id`,
  ADD COLUMN IF NOT EXISTS `policy_decision_id` varchar(100) DEFAULT NULL AFTER `task_id`,
  ADD COLUMN IF NOT EXISTS `authorization_request_id` varchar(100) DEFAULT NULL AFTER `policy_decision_id`,
  ADD COLUMN IF NOT EXISTS `revalidation_id` varchar(120) DEFAULT NULL AFTER `authorization_request_id`;

CREATE INDEX IF NOT EXISTS `idx_cti_event_mission_trace`
    ON `cti_events` (`mission_id`, `trace_id`, `id`);
CREATE INDEX IF NOT EXISTS `idx_cti_event_task`
    ON `cti_events` (`task_id`, `id`);
CREATE INDEX IF NOT EXISTS `idx_cti_event_policy_decision`
    ON `cti_events` (`policy_decision_id`, `id`);
CREATE INDEX IF NOT EXISTS `idx_cti_event_upstream`
    ON `cti_events` (`upstream_event_id`, `id`);
CREATE INDEX IF NOT EXISTS `idx_cti_event_causation`
    ON `cti_events` (`causation_event_id`, `id`);

ALTER TABLE `cti_decision_traces`
  ADD COLUMN IF NOT EXISTS `lineage_trace_id` varchar(120) DEFAULT NULL AFTER `trace_id`,
  ADD COLUMN IF NOT EXISTS `proposal_id` varchar(120) DEFAULT NULL AFTER `lineage_trace_id`,
  ADD COLUMN IF NOT EXISTS `task_id` varchar(120) DEFAULT NULL AFTER `proposal_id`,
  ADD COLUMN IF NOT EXISTS `policy_decision_id` varchar(100) DEFAULT NULL AFTER `task_id`,
  ADD COLUMN IF NOT EXISTS `authorization_request_id` varchar(100) DEFAULT NULL AFTER `policy_decision_id`,
  ADD COLUMN IF NOT EXISTS `revalidation_id` varchar(120) DEFAULT NULL AFTER `authorization_request_id`;

CREATE INDEX IF NOT EXISTS `idx_cti_decision_lineage`
    ON `cti_decision_traces` (`mission_id`, `lineage_trace_id`, `id`);
CREATE INDEX IF NOT EXISTS `idx_cti_decision_task`
    ON `cti_decision_traces` (`task_id`, `id`);
CREATE INDEX IF NOT EXISTS `idx_cti_decision_policy`
    ON `cti_decision_traces` (`policy_decision_id`, `id`);

-- Declare the Event Bus capability without changing historical event records.
UPDATE `cti_component_registry`
   SET `config_json` = JSON_SET(
         CASE WHEN JSON_VALID(`config_json`) THEN `config_json` ELSE '{}' END,
         '$.event_schema_version', 'cti-event-v2',
         '$.lineage_model', 'trace-causation-upstream',
         '$.stage_2_8_foundation', TRUE
       ),
       `updated_at` = CURRENT_TIMESTAMP
 WHERE `component_id` = 'CTI-INF02';

-- --------------------------------------------------------------------------
-- Acceptance probes
-- --------------------------------------------------------------------------
SELECT
    event_schema_version,
    COUNT(*) AS event_count,
    SUM(trace_id IS NOT NULL) AS events_with_trace,
    SUM(task_id IS NOT NULL) AS events_with_task,
    SUM(policy_decision_id IS NOT NULL) AS events_with_policy_decision,
    SUM(upstream_event_id IS NOT NULL) AS events_with_upstream_event
FROM cti_events
GROUP BY event_schema_version
ORDER BY event_schema_version;

SELECT
    event_id,
    event_schema_version,
    mission_id,
    event_type,
    trace_id,
    causation_event_id,
    upstream_event_id,
    proposal_id,
    task_id,
    policy_decision_id,
    authorization_request_id,
    revalidation_id,
    created_at
FROM cti_events
ORDER BY id DESC
LIMIT 50;
