-- ============================================================================
-- VulnDesk / APTS - CTI Event-Driven Runtime Migration
-- Adds durable delivery telemetry and infrastructure registry rows for:
-- CTI-INF02 Event Bus, CTI-INF03 Event Dispatcher, CTI-INF04 Source Sync Connector.
-- Non-destructive; safe to run after 01_cti_harmonized_architecture_migration.sql.
-- ============================================================================

USE `vulndesk`;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `cti_event_deliveries` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `delivery_id` varchar(300) NOT NULL,
  `event_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `subscriber_id` varchar(180) NOT NULL,
  `delivery_status` varchar(40) NOT NULL DEFAULT 'PENDING',
  `attempt_count` int NOT NULL DEFAULT 0,
  `last_error` text DEFAULT NULL,
  `delivered_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_event_delivery_id` (`delivery_id`),
  KEY `idx_cti_event_delivery_event` (`event_id`,`delivery_status`),
  KEY `idx_cti_event_delivery_mission` (`mission_id`,`created_at`),
  KEY `idx_cti_event_delivery_subscriber` (`subscriber_id`,`delivery_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `cti_component_registry`
(`component_id`,`service_key`,`service_name`,`component_type`,`mechanism`,`authority_boundary`,`optional_component`,`service_side`,`enabled`,`status`,`config_json`,`sort_order`)
VALUES
('CTI-INF02','cti_event_bus','CTI Event Bus','Infrastructure Service','Typed event queue + durable event log','Communication only; no domain reasoning',0,'vulndesk',1,'idle','{"architecture_version":"2026-08-harmonized","runtime":"in-process-durable-log"}',910),
('CTI-INF03','cti_event_dispatcher','CTI Event Dispatcher','Infrastructure Service','Subscription routing / event delivery','Dispatch only; no mission agenda',0,'vulndesk',1,'idle','{"architecture_version":"2026-08-harmonized","mode":"background-or-deterministic-drain"}',920),
('CTI-INF04','cti_source_sync_connector','CTI Source Sync Connector','Infrastructure Service','Deterministic source adapter','Authorized read-only CTI acquisition execution only',0,'vulndesk',1,'idle','{"architecture_version":"2026-08-harmonized","target_actuation":false}',930)
ON DUPLICATE KEY UPDATE
`service_name`=VALUES(`service_name`),
`component_type`=VALUES(`component_type`),
`mechanism`=VALUES(`mechanism`),
`authority_boundary`=VALUES(`authority_boundary`),
`optional_component`=VALUES(`optional_component`),
`sort_order`=VALUES(`sort_order`),
`updated_at`=CURRENT_TIMESTAMP;

UPDATE `cti_source_registry`
   SET `config_json`='{"semantic_role":"vulnerability_source","sync_adapter":"SyncService.run_incremental_sync","max_pages":1,"page_size":500,"bounded_agent_refresh":true}',
       `updated_at`=CURRENT_TIMESTAMP
 WHERE `source_id`='nvd-cve';

UPDATE `cti_source_registry`
   SET `config_json`='{"semantic_role":"cpe_dictionary","sync_adapter":"CpeDictionarySyncService.sync_first_pages","max_pages":1,"page_size":500,"bounded_agent_refresh":true,"note":"generic CPE refresh is bounded until cursor-aware CPE source sync is implemented"}',
       `updated_at`=CURRENT_TIMESTAMP
 WHERE `source_id`='nvd-cpe';

UPDATE `cti_source_registry`
   SET `config_json`='{"semantic_role":"attack_ontology","sync_adapter":"MitreAttackSyncService.run_incremental_sync","sync_mode":"INCREMENTAL","bounded_agent_refresh":true}',
       `updated_at`=CURRENT_TIMESTAMP
 WHERE `source_id`='mitre-attack';
