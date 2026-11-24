-- Adaptive external CTI source monitoring state.
-- Apply once to the Vulndesk database before enabling the Web adaptive scheduler.
CREATE TABLE IF NOT EXISTS `cti_source_monitor_state` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `source_id` varchar(120) NOT NULL,
  `detector_strategy` varchar(80) DEFAULT NULL,
  `scheduler_status` varchar(60) NOT NULL DEFAULT 'NEW',
  `last_probe_at` datetime DEFAULT NULL,
  `last_change_at` datetime DEFAULT NULL,
  `next_check_at` datetime DEFAULT NULL,
  `unchanged_streak` int(11) NOT NULL DEFAULT 0,
  `change_rate_ema` decimal(8,6) NOT NULL DEFAULT 0.000000,
  `last_fingerprint` char(64) DEFAULT NULL,
  `etag` varchar(500) DEFAULT NULL,
  `last_modified_header` varchar(255) DEFAULT NULL,
  `source_version` longtext DEFAULT NULL,
  `last_total_results` bigint(20) DEFAULT NULL,
  `last_probe_status` varchar(50) DEFAULT NULL,
  `last_error` text DEFAULT NULL,
  `last_probe_json` longtext DEFAULT NULL,
  `last_auto_mission_id` varchar(100) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_source_monitor_source` (`source_id`),
  KEY `idx_cti_source_monitor_due` (`next_check_at`,`scheduler_status`),
  KEY `idx_cti_source_monitor_change` (`last_change_at`),
  KEY `idx_cti_source_monitor_mission` (`last_auto_mission_id`),
  CONSTRAINT `chk_cti_source_monitor_probe_json` CHECK (`last_probe_json` is null or json_valid(`last_probe_json`)),
  CONSTRAINT `chk_cti_source_monitor_version_json` CHECK (`source_version` is null or json_valid(`source_version`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- NVD CPE 2.0 supports native last-modified delta retrieval. Upgrade the
-- built-in source if it still carries the former bounded-refresh strategy.
UPDATE `cti_source_registry`
SET `incremental_strategy`='LAST_MODIFIED_WINDOW', `updated_at`=CURRENT_TIMESTAMP
WHERE `source_id`='nvd-cpe' AND `incremental_strategy`='BOUNDED_REFRESH';
