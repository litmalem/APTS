/*
SQLyog Professional v13.1.1 (32 bit)
MySQL - 10.11.18-MariaDB : Database - vulndesk
*********************************************************************
*/

/*!40101 SET NAMES utf8 */;

/*!40101 SET SQL_MODE=''*/;

/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
CREATE DATABASE /*!32312 IF NOT EXISTS*/`vulndesk` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci */;

USE `vulndesk`;

/*Table structure for table `app_settings` */

DROP TABLE IF EXISTS `app_settings`;

CREATE TABLE `app_settings` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `setting_key` varchar(100) NOT NULL,
  `setting_value` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_app_settings_key` (`setting_key`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_aliases` */

DROP TABLE IF EXISTS `attack_aliases`;

CREATE TABLE `attack_aliases` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `parent_stix_id` varchar(80) NOT NULL,
  `parent_type` varchar(30) NOT NULL,
  `alias_value` varchar(255) NOT NULL,
  `malware_id` bigint(20) unsigned DEFAULT NULL,
  `threat_actor_id` bigint(20) unsigned DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_alias` (`parent_stix_id`,`parent_type`,`alias_value`),
  KEY `idx_attack_alias_parent_stix_id` (`parent_stix_id`),
  KEY `idx_attack_alias_parent_type` (`parent_type`),
  KEY `idx_attack_alias_value` (`alias_value`),
  KEY `idx_attack_alias_malware_id` (`malware_id`),
  KEY `idx_attack_alias_threat_actor_id` (`threat_actor_id`),
  CONSTRAINT `fk_attack_alias_malware` FOREIGN KEY (`malware_id`) REFERENCES `attack_malware` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_attack_alias_threat_actor` FOREIGN KEY (`threat_actor_id`) REFERENCES `attack_threat_actors` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=13962 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_external_references` */

DROP TABLE IF EXISTS `attack_external_references`;

CREATE TABLE `attack_external_references` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `parent_stix_id` varchar(80) NOT NULL,
  `parent_type` varchar(30) NOT NULL,
  `source_name` varchar(150) NOT NULL,
  `external_id` varchar(100) DEFAULT NULL,
  `url` varchar(1000) DEFAULT NULL,
  `description_text` longtext DEFAULT NULL,
  `attack_pattern_id` bigint(20) unsigned DEFAULT NULL,
  `malware_id` bigint(20) unsigned DEFAULT NULL,
  `threat_actor_id` bigint(20) unsigned DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_ext_ref` (`parent_stix_id`,`parent_type`,`source_name`,`external_id`),
  KEY `idx_attack_ext_ref_parent_stix_id` (`parent_stix_id`),
  KEY `idx_attack_ext_ref_parent_type` (`parent_type`),
  KEY `idx_attack_ext_ref_source_name` (`source_name`),
  KEY `idx_attack_ext_ref_external_id` (`external_id`),
  KEY `idx_attack_ext_ref_attack_pattern_id` (`attack_pattern_id`),
  KEY `idx_attack_ext_ref_malware_id` (`malware_id`),
  KEY `idx_attack_ext_ref_threat_actor_id` (`threat_actor_id`),
  CONSTRAINT `fk_attack_ext_ref_attack_pattern` FOREIGN KEY (`attack_pattern_id`) REFERENCES `attack_patterns` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_attack_ext_ref_malware` FOREIGN KEY (`malware_id`) REFERENCES `attack_malware` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_attack_ext_ref_threat_actor` FOREIGN KEY (`threat_actor_id`) REFERENCES `attack_threat_actors` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=76211 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_kill_chain_phases` */

DROP TABLE IF EXISTS `attack_kill_chain_phases`;

CREATE TABLE `attack_kill_chain_phases` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `parent_stix_id` varchar(80) NOT NULL,
  `kill_chain_name` varchar(100) NOT NULL,
  `phase_name` varchar(100) NOT NULL,
  `attack_pattern_id` bigint(20) unsigned DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_kill_chain_phase` (`parent_stix_id`,`kill_chain_name`,`phase_name`),
  KEY `idx_attack_kill_chain_parent_stix_id` (`parent_stix_id`),
  KEY `idx_attack_kill_chain_name` (`kill_chain_name`),
  KEY `idx_attack_phase_name` (`phase_name`),
  KEY `idx_attack_kill_chain_attack_pattern_id` (`attack_pattern_id`),
  CONSTRAINT `fk_attack_kill_chain_attack_pattern` FOREIGN KEY (`attack_pattern_id`) REFERENCES `attack_patterns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=10249 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_malware` */

DROP TABLE IF EXISTS `attack_malware`;

CREATE TABLE `attack_malware` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `stix_id` varchar(80) NOT NULL,
  `software_id` varchar(30) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `description_text` longtext DEFAULT NULL,
  `created_at_source` datetime DEFAULT NULL,
  `modified_at_source` datetime DEFAULT NULL,
  `platforms_json` longtext DEFAULT NULL,
  `domains_json` longtext DEFAULT NULL,
  `aliases_json` longtext DEFAULT NULL,
  `version_value` varchar(20) DEFAULT NULL,
  `attack_spec_version` varchar(20) DEFAULT NULL,
  `stix_spec_version` varchar(10) DEFAULT NULL,
  `is_family` tinyint(1) NOT NULL DEFAULT 0,
  `revoked` tinyint(1) NOT NULL DEFAULT 0,
  `deprecated` tinyint(1) NOT NULL DEFAULT 0,
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_malware_stix_id` (`stix_id`),
  KEY `idx_attack_malware_software_id` (`software_id`),
  KEY `idx_attack_malware_name` (`name`),
  KEY `idx_attack_malware_modified_at_source` (`modified_at_source`),
  KEY `idx_attack_malware_revoked` (`revoked`),
  KEY `idx_attack_malware_deprecated` (`deprecated`)
) ENGINE=InnoDB AUTO_INCREMENT=2191 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_patterns` */

DROP TABLE IF EXISTS `attack_patterns`;

CREATE TABLE `attack_patterns` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `stix_id` varchar(80) NOT NULL,
  `attack_id` varchar(30) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `description_text` longtext DEFAULT NULL,
  `created_at_source` datetime DEFAULT NULL,
  `modified_at_source` datetime DEFAULT NULL,
  `is_subtechnique` tinyint(1) NOT NULL DEFAULT 0,
  `platforms_json` longtext DEFAULT NULL,
  `domains_json` longtext DEFAULT NULL,
  `data_sources_json` longtext DEFAULT NULL,
  `detection_text` longtext DEFAULT NULL,
  `version_value` varchar(20) DEFAULT NULL,
  `attack_spec_version` varchar(20) DEFAULT NULL,
  `stix_spec_version` varchar(10) DEFAULT NULL,
  `revoked` tinyint(1) NOT NULL DEFAULT 0,
  `deprecated` tinyint(1) NOT NULL DEFAULT 0,
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_patterns_stix_id` (`stix_id`),
  KEY `idx_attack_patterns_attack_id` (`attack_id`),
  KEY `idx_attack_patterns_name` (`name`),
  KEY `idx_attack_patterns_modified_at_source` (`modified_at_source`),
  KEY `idx_attack_patterns_is_subtechnique` (`is_subtechnique`),
  KEY `idx_attack_patterns_revoked` (`revoked`),
  KEY `idx_attack_patterns_deprecated` (`deprecated`)
) ENGINE=InnoDB AUTO_INCREMENT=2109 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_relationships` */

DROP TABLE IF EXISTS `attack_relationships`;

CREATE TABLE `attack_relationships` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `stix_id` varchar(80) NOT NULL,
  `relationship_type` varchar(50) DEFAULT NULL,
  `source_ref` varchar(80) NOT NULL,
  `target_ref` varchar(80) NOT NULL,
  `source_type` varchar(50) DEFAULT NULL,
  `target_type` varchar(50) DEFAULT NULL,
  `description_text` longtext DEFAULT NULL,
  `created_at_source` datetime DEFAULT NULL,
  `modified_at_source` datetime DEFAULT NULL,
  `stix_spec_version` varchar(10) DEFAULT NULL,
  `revoked` tinyint(1) NOT NULL DEFAULT 0,
  `deprecated` tinyint(1) NOT NULL DEFAULT 0,
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_relationships_stix_id` (`stix_id`),
  KEY `idx_attack_relationships_relationship_type` (`relationship_type`),
  KEY `idx_attack_relationships_source_ref` (`source_ref`),
  KEY `idx_attack_relationships_target_ref` (`target_ref`),
  KEY `idx_attack_relationships_source_type` (`source_type`),
  KEY `idx_attack_relationships_target_type` (`target_type`),
  KEY `idx_attack_relationships_modified_at_source` (`modified_at_source`),
  KEY `idx_attack_rel_src_combo` (`relationship_type`,`source_type`,`target_type`,`source_ref`),
  KEY `idx_attack_rel_tgt_combo` (`relationship_type`,`source_type`,`target_type`,`target_ref`)
) ENGINE=InnoDB AUTO_INCREMENT=47148 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `attack_threat_actors` */

DROP TABLE IF EXISTS `attack_threat_actors`;

CREATE TABLE `attack_threat_actors` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `stix_id` varchar(80) NOT NULL,
  `group_id` varchar(30) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `description_text` longtext DEFAULT NULL,
  `created_at_source` datetime DEFAULT NULL,
  `modified_at_source` datetime DEFAULT NULL,
  `first_seen_source` datetime DEFAULT NULL,
  `last_seen_source` datetime DEFAULT NULL,
  `aliases_json` longtext DEFAULT NULL,
  `goals_json` longtext DEFAULT NULL,
  `resource_level` varchar(50) DEFAULT NULL,
  `primary_motivation` varchar(100) DEFAULT NULL,
  `secondary_motivations_json` longtext DEFAULT NULL,
  `domains_json` longtext DEFAULT NULL,
  `version_value` varchar(20) DEFAULT NULL,
  `attack_spec_version` varchar(20) DEFAULT NULL,
  `stix_spec_version` varchar(10) DEFAULT NULL,
  `revoked` tinyint(1) NOT NULL DEFAULT 0,
  `deprecated` tinyint(1) NOT NULL DEFAULT 0,
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_attack_threat_actors_stix_id` (`stix_id`),
  KEY `idx_attack_threat_actors_group_id` (`group_id`),
  KEY `idx_attack_threat_actors_name` (`name`),
  KEY `idx_attack_threat_actors_modified_at_source` (`modified_at_source`),
  KEY `idx_attack_threat_actors_revoked` (`revoked`),
  KEY `idx_attack_threat_actors_deprecated` (`deprecated`)
) ENGINE=InnoDB AUTO_INCREMENT=525 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `capec_attack_mappings` */

DROP TABLE IF EXISTS `capec_attack_mappings`;

CREATE TABLE `capec_attack_mappings` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `capec_id` varchar(40) NOT NULL,
  `attack_pattern_stix_id` varchar(120) DEFAULT NULL,
  `attack_id` varchar(40) DEFAULT NULL,
  `attack_name` varchar(255) DEFAULT NULL,
  `tactic_name` varchar(160) DEFAULT NULL,
  `confidence` decimal(5,4) NOT NULL DEFAULT 0.7500,
  `rationale` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_cam_capec_id` (`capec_id`),
  KEY `idx_cam_attack_id` (`attack_id`),
  KEY `idx_cam_attack_stix` (`attack_pattern_stix_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `capec_cwe_mappings` */

DROP TABLE IF EXISTS `capec_cwe_mappings`;

CREATE TABLE `capec_cwe_mappings` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `capec_id` varchar(40) NOT NULL,
  `cwe_id` varchar(40) NOT NULL,
  `mapping_type` varchar(80) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_capec_cwe` (`capec_id`,`cwe_id`),
  KEY `idx_ccm_capec_id` (`capec_id`),
  KEY `idx_ccm_cwe_id` (`cwe_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `capec_patterns` */

DROP TABLE IF EXISTS `capec_patterns`;

CREATE TABLE `capec_patterns` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `capec_id` varchar(40) NOT NULL,
  `name` varchar(255) NOT NULL,
  `abstraction` varchar(80) DEFAULT NULL,
  `status` varchar(80) DEFAULT NULL,
  `description` mediumtext DEFAULT NULL,
  `likelihood` varchar(80) DEFAULT NULL,
  `severity` varchar(80) DEFAULT NULL,
  `prerequisites` mediumtext DEFAULT NULL,
  `mitigations` mediumtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_capec_id` (`capec_id`),
  KEY `idx_capec_name` (`name`),
  KEY `idx_capec_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cpe_matches` */

DROP TABLE IF EXISTS `cpe_matches`;

CREATE TABLE `cpe_matches` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `vulnerability_id` bigint(20) unsigned NOT NULL,
  `is_vulnerable` tinyint(1) NOT NULL DEFAULT 1,
  `criteria_uri` varchar(1024) NOT NULL,
  `match_criteria_id` varchar(100) DEFAULT NULL,
  `version_start_including` varchar(100) DEFAULT NULL,
  `version_start_excluding` varchar(100) DEFAULT NULL,
  `version_end_including` varchar(100) DEFAULT NULL,
  `version_end_excluding` varchar(100) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cpe_match_unique` (`vulnerability_id`,`criteria_uri`(255),`version_start_including`,`version_start_excluding`,`version_end_including`,`version_end_excluding`),
  KEY `idx_cpe_matches_vulnerability_id` (`vulnerability_id`),
  KEY `idx_cpe_matches_is_vulnerable` (`is_vulnerable`),
  KEY `idx_cpe_matches_match_criteria_id` (`match_criteria_id`),
  CONSTRAINT `fk_cpe_matches_vulnerability` FOREIGN KEY (`vulnerability_id`) REFERENCES `vulnerabilities` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3222828 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_action_proposals` */

DROP TABLE IF EXISTS `cti_action_proposals`;

CREATE TABLE `cti_action_proposals` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `proposal_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `proposal_kind` varchar(40) NOT NULL,
  `action_type` varchar(120) NOT NULL,
  `target_component` varchar(120) DEFAULT NULL,
  `target_source_id` varchar(120) DEFAULT NULL,
  `reason_code` varchar(160) DEFAULT NULL,
  `priority_utility` decimal(12,6) DEFAULT NULL,
  `state_version` bigint(20) DEFAULT NULL,
  `plan_version` bigint(20) DEFAULT NULL,
  `policy_version` varchar(100) DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `proposal_json` longtext NOT NULL,
  `guard_decision` varchar(30) DEFAULT NULL,
  `committed_task_id` varchar(120) DEFAULT NULL,
  `status` varchar(40) NOT NULL DEFAULT 'PROPOSED',
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_proposal_id` (`proposal_id`),
  KEY `idx_cti_proposal_mission` (`mission_id`,`status`),
  KEY `idx_cti_proposal_target` (`target_component`,`target_source_id`),
  KEY `idx_cti_proposal_versions` (`state_version`,`plan_version`)
) ENGINE=InnoDB AUTO_INCREMENT=242 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_asset_profiles` */

DROP TABLE IF EXISTS `cti_asset_profiles`;

CREATE TABLE `cti_asset_profiles` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `asset_profile_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `asset_id` varchar(255) NOT NULL,
  `asset_type` varchar(80) DEFAULT NULL,
  `target_url` varchar(2000) DEFAULT NULL,
  `hostname` varchar(255) DEFAULT NULL,
  `ip_address` varchar(100) DEFAULT NULL,
  `exposure` varchar(80) DEFAULT NULL,
  `criticality` decimal(7,6) DEFAULT NULL,
  `observed_json` longtext NOT NULL,
  `inferred_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `verification_status` varchar(50) DEFAULT NULL,
  `profile_version` int(11) NOT NULL DEFAULT 1,
  `observed_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_asset_profile_id` (`asset_profile_id`),
  KEY `idx_cti_asset_profile_mission_asset` (`mission_id`,`asset_id`),
  KEY `idx_cti_asset_profile_target` (`hostname`,`ip_address`)
) ENGINE=InnoDB AUTO_INCREMENT=26 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_attack_graph_snapshots` */

DROP TABLE IF EXISTS `cti_attack_graph_snapshots`;

CREATE TABLE `cti_attack_graph_snapshots` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `graph_snapshot_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `graph_version` bigint(20) NOT NULL DEFAULT 1,
  `nodes_json` longtext NOT NULL,
  `edges_json` longtext NOT NULL,
  `policy_context_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_attack_graph_snapshot_id` (`graph_snapshot_id`),
  KEY `idx_cti_attack_graph_mission` (`mission_id`,`graph_version`)
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_attack_mappings` */

DROP TABLE IF EXISTS `cti_attack_mappings`;

CREATE TABLE `cti_attack_mappings` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `mapping_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `correlation_id` varchar(500) DEFAULT NULL,
  `asset_id` varchar(255) DEFAULT NULL,
  `cve_id` varchar(40) DEFAULT NULL,
  `evidence_ref` varchar(500) DEFAULT NULL,
  `attack_pattern_stix_id` varchar(120) DEFAULT NULL,
  `technique_id` varchar(40) DEFAULT NULL,
  `technique_name` varchar(255) DEFAULT NULL,
  `tactic_name` varchar(255) DEFAULT NULL,
  `probability_score` decimal(7,6) DEFAULT NULL,
  `verification_state` varchar(50) NOT NULL,
  `symbolic_rules_json` longtext DEFAULT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `provenance_json` longtext DEFAULT NULL,
  `contradictions_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `revoked` tinyint(1) NOT NULL DEFAULT 0,
  `deprecated` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_attack_mapping_id` (`mapping_id`),
  KEY `idx_cti_attack_mapping_corr` (`correlation_id`),
  KEY `idx_cti_attack_mapping_technique` (`technique_id`),
  KEY `idx_cti_attack_mapping_state` (`verification_state`,`confidence`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_attack_paths` */

DROP TABLE IF EXISTS `cti_attack_paths`;

CREATE TABLE `cti_attack_paths` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `path_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `graph_snapshot_id` varchar(120) NOT NULL,
  `rank_no` int(11) DEFAULT NULL,
  `asset_id` varchar(255) DEFAULT NULL,
  `correlation_id` varchar(500) DEFAULT NULL,
  `cve_id` varchar(40) DEFAULT NULL,
  `mapping_id` varchar(120) DEFAULT NULL,
  `technique_id` varchar(40) DEFAULT NULL,
  `technique_name` varchar(255) DEFAULT NULL,
  `path_nodes_json` longtext NOT NULL,
  `path_confidence` decimal(7,6) DEFAULT NULL,
  `feasibility_state` varchar(60) NOT NULL,
  `reason_code` varchar(160) DEFAULT NULL,
  `preconditions_json` longtext DEFAULT NULL,
  `postconditions_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `policy_state_json` longtext DEFAULT NULL,
  `rule_trace_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `execution_authorized` tinyint(1) NOT NULL DEFAULT 0,
  `authority_state` varchar(120) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_attack_path_id` (`path_id`),
  KEY `idx_cti_attack_path_mission_rank` (`mission_id`,`rank_no`),
  KEY `idx_cti_attack_path_corr` (`correlation_id`),
  KEY `idx_cti_attack_path_state` (`feasibility_state`,`path_confidence`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_audit_log` */

DROP TABLE IF EXISTS `cti_audit_log`;

CREATE TABLE `cti_audit_log` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `audit_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `component_id` varchar(32) NOT NULL,
  `event_type` varchar(120) NOT NULL,
  `reason_code` varchar(160) DEFAULT NULL,
  `input_snapshot_json` longtext DEFAULT NULL,
  `candidate_alternatives_json` longtext DEFAULT NULL,
  `selected_output_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `versions_json` longtext DEFAULT NULL,
  `upstream_event_ref` varchar(120) DEFAULT NULL,
  `downstream_event_ref` varchar(120) DEFAULT NULL,
  `trace_id` varchar(120) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_audit_id` (`audit_id`),
  KEY `idx_cti_audit_mission` (`mission_id`,`created_at`),
  KEY `idx_cti_audit_component` (`component_id`,`event_type`),
  KEY `idx_cti_audit_trace` (`trace_id`),
  KEY `idx_cti_audit_upstream_event` (`upstream_event_ref`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=765 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_beliefs` */

DROP TABLE IF EXISTS `cti_beliefs`;

CREATE TABLE `cti_beliefs` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `belief_id` varchar(120) NOT NULL,
  `belief_snapshot_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `belief_category` varchar(60) NOT NULL,
  `subject_ref` varchar(500) DEFAULT NULL,
  `belief_json` longtext NOT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `source_refs_json` longtext DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_belief_id` (`belief_id`),
  KEY `idx_cti_belief_snapshot` (`belief_snapshot_id`,`belief_category`),
  KEY `idx_cti_belief_mission` (`mission_id`)
) ENGINE=InnoDB AUTO_INCREMENT=199 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_component_registry` */

DROP TABLE IF EXISTS `cti_component_registry`;

CREATE TABLE `cti_component_registry` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `component_id` varchar(32) NOT NULL,
  `service_key` varchar(120) NOT NULL,
  `service_name` varchar(180) NOT NULL,
  `component_type` varchar(40) NOT NULL,
  `mechanism` varchar(220) NOT NULL,
  `authority_boundary` varchar(255) NOT NULL,
  `optional_component` tinyint(1) NOT NULL DEFAULT 0,
  `service_side` varchar(30) NOT NULL DEFAULT 'vulndesk',
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `status` varchar(30) NOT NULL DEFAULT 'idle',
  `config_json` longtext DEFAULT NULL,
  `sort_order` int(11) NOT NULL DEFAULT 0,
  `last_run_at` datetime DEFAULT NULL,
  `last_error` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_component_id` (`component_id`),
  UNIQUE KEY `uq_cti_component_service_key` (`service_key`),
  KEY `idx_cti_component_type` (`component_type`),
  KEY `idx_cti_component_status` (`status`),
  KEY `idx_cti_component_enabled` (`enabled`),
  KEY `idx_cti_component_sort` (`sort_order`)
) ENGINE=InnoDB AUTO_INCREMENT=2484881 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_cpe_resolution_claims` */

DROP TABLE IF EXISTS `cti_cpe_resolution_claims`;

CREATE TABLE `cti_cpe_resolution_claims` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `resolution_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `asset_profile_id` varchar(120) DEFAULT NULL,
  `asset_id` varchar(255) NOT NULL,
  `technology_key` varchar(500) DEFAULT NULL,
  `candidate_rank` int(11) DEFAULT NULL,
  `cpe_wfn` varchar(1500) DEFAULT NULL,
  `cpe23_formatted` varchar(1500) DEFAULT NULL,
  `dictionary_ref` varchar(255) DEFAULT NULL,
  `status` varchar(50) NOT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `observed_attributes_json` longtext DEFAULT NULL,
  `inferred_attributes_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `contradiction_refs_json` longtext DEFAULT NULL,
  `rule_trace_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `dictionary_version` varchar(120) DEFAULT NULL,
  `decision_time` datetime DEFAULT NULL,
  `supersedes` varchar(120) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_cpe_resolution_id` (`resolution_id`),
  KEY `idx_cti_cpe_claim_mission_asset` (`mission_id`,`asset_id`),
  KEY `idx_cti_cpe_claim_status` (`status`,`confidence`),
  KEY `idx_cti_cpe_claim_dictionary` (`dictionary_ref`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_decision_traces` */

DROP TABLE IF EXISTS `cti_decision_traces`;

CREATE TABLE `cti_decision_traces` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `trace_id` varchar(120) NOT NULL,
  `lineage_trace_id` varchar(120) DEFAULT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `proposal_id` varchar(120) DEFAULT NULL,
  `task_id` varchar(120) DEFAULT NULL,
  `policy_decision_id` varchar(100) DEFAULT NULL,
  `authorization_request_id` varchar(100) DEFAULT NULL,
  `revalidation_id` varchar(120) DEFAULT NULL,
  `upstream_event_id` varchar(120) DEFAULT NULL,
  `component_id` varchar(32) NOT NULL,
  `decision_type` varchar(120) NOT NULL,
  `state_version` bigint(20) DEFAULT NULL,
  `plan_version` bigint(20) DEFAULT NULL,
  `policy_version` varchar(100) DEFAULT NULL,
  `observations_json` longtext DEFAULT NULL,
  `candidate_actions_json` longtext DEFAULT NULL,
  `score_breakdown_json` longtext DEFAULT NULL,
  `selected_action_json` longtext DEFAULT NULL,
  `policy_decision_json` longtext DEFAULT NULL,
  `execution_outcome_json` longtext DEFAULT NULL,
  `algorithm_version` varchar(120) DEFAULT NULL,
  `config_version` varchar(120) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_decision_trace_id` (`trace_id`),
  KEY `idx_cti_decision_mission` (`mission_id`,`created_at`),
  KEY `idx_cti_decision_component` (`component_id`,`decision_type`),
  KEY `idx_cti_decision_lineage` (`mission_id`,`lineage_trace_id`,`created_at`),
  KEY `idx_cti_decision_task` (`task_id`,`created_at`),
  KEY `idx_cti_decision_policy` (`policy_decision_id`,`created_at`),
  KEY `idx_cti_decision_upstream_event` (`upstream_event_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=431 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_enrichment_requirements` */

DROP TABLE IF EXISTS `cti_enrichment_requirements`;

CREATE TABLE `cti_enrichment_requirements` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `requirement_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `asset_id` varchar(255) NOT NULL,
  `technology_key` varchar(500) DEFAULT NULL,
  `required_evidence_json` longtext NOT NULL,
  `reason_code` varchar(160) NOT NULL,
  `authority_state` varchar(120) NOT NULL,
  `status` varchar(50) NOT NULL DEFAULT 'OPEN',
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `resolved_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_enrichment_requirement_id` (`requirement_id`),
  KEY `idx_cti_enrichment_mission_status` (`mission_id`,`status`),
  KEY `idx_cti_enrichment_asset` (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_event_deliveries` */

DROP TABLE IF EXISTS `cti_event_deliveries`;

CREATE TABLE `cti_event_deliveries` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `delivery_id` varchar(300) NOT NULL,
  `event_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `subscriber_id` varchar(180) NOT NULL,
  `delivery_status` varchar(40) NOT NULL DEFAULT 'PENDING',
  `attempt_count` int(11) NOT NULL DEFAULT 0,
  `last_error` text DEFAULT NULL,
  `delivered_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_event_delivery_id` (`delivery_id`),
  KEY `idx_cti_event_delivery_event` (`event_id`,`delivery_status`),
  KEY `idx_cti_event_delivery_mission` (`mission_id`,`created_at`),
  KEY `idx_cti_event_delivery_subscriber` (`subscriber_id`,`delivery_status`)
) ENGINE=InnoDB AUTO_INCREMENT=479 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_events` */

DROP TABLE IF EXISTS `cti_events`;

CREATE TABLE `cti_events` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `event_schema_version` varchar(32) NOT NULL DEFAULT 'cti-event-v1',
  `event_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `event_type` varchar(120) NOT NULL,
  `source_component` varchar(120) NOT NULL,
  `severity` varchar(30) NOT NULL DEFAULT 'INFO',
  `trace_id` varchar(120) DEFAULT NULL,
  `causation_event_id` varchar(120) DEFAULT NULL,
  `upstream_event_id` varchar(120) DEFAULT NULL,
  `proposal_id` varchar(120) DEFAULT NULL,
  `task_id` varchar(120) DEFAULT NULL,
  `policy_decision_id` varchar(100) DEFAULT NULL,
  `authorization_request_id` varchar(100) DEFAULT NULL,
  `revalidation_id` varchar(120) DEFAULT NULL,
  `payload_json` longtext DEFAULT NULL,
  `state_version` bigint(20) DEFAULT NULL,
  `plan_version` bigint(20) DEFAULT NULL,
  `policy_version` varchar(100) DEFAULT NULL,
  `evidence_ref` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_event_id` (`event_id`),
  KEY `idx_cti_event_mission` (`mission_id`,`created_at`),
  KEY `idx_cti_event_type` (`event_type`),
  KEY `idx_cti_event_component` (`source_component`),
  KEY `idx_cti_event_mission_trace` (`mission_id`,`trace_id`,`created_at`),
  KEY `idx_cti_event_task` (`task_id`,`created_at`),
  KEY `idx_cti_event_policy_decision` (`policy_decision_id`,`created_at`),
  KEY `idx_cti_event_upstream` (`upstream_event_id`,`created_at`),
  KEY `idx_cti_event_causation` (`causation_event_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=4626 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_intentions` */

DROP TABLE IF EXISTS `cti_intentions`;

CREATE TABLE `cti_intentions` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `intention_id` varchar(120) NOT NULL,
  `portfolio_id` varchar(120) NOT NULL,
  `belief_snapshot_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `target_ref` varchar(500) NOT NULL,
  `asset_id` varchar(255) DEFAULT NULL,
  `cve_id` varchar(40) DEFAULT NULL,
  `correlation_id` varchar(500) DEFAULT NULL,
  `priority_band` varchar(40) NOT NULL,
  `priority_rank` int(11) NOT NULL,
  `utility_total` decimal(7,6) NOT NULL,
  `utility_components_json` longtext NOT NULL,
  `penalty_components_json` longtext DEFAULT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `reason_codes_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `dependencies_json` longtext DEFAULT NULL,
  `approval_requirement` varchar(255) NOT NULL,
  `commitment_state` varchar(80) NOT NULL,
  `reconsider_after` datetime DEFAULT NULL,
  `policy_version` varchar(100) DEFAULT NULL,
  `feasibility_json` longtext DEFAULT NULL,
  `execution_authorized` tinyint(1) NOT NULL DEFAULT 0,
  `authority_state` varchar(120) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_intention_id` (`intention_id`),
  KEY `idx_cti_intention_portfolio_rank` (`portfolio_id`,`priority_rank`),
  KEY `idx_cti_intention_mission` (`mission_id`,`priority_band`),
  KEY `idx_cti_intention_corr` (`correlation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_missions` */

DROP TABLE IF EXISTS `cti_missions`;

CREATE TABLE `cti_missions` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `mission_id` varchar(100) NOT NULL,
  `objective_json` longtext NOT NULL,
  `asset_scope_json` longtext NOT NULL,
  `intelligence_requirements_json` longtext DEFAULT NULL,
  `priority_level` int(11) NOT NULL DEFAULT 50,
  `time_window_json` longtext DEFAULT NULL,
  `policy_context_json` longtext DEFAULT NULL,
  `status` varchar(40) NOT NULL DEFAULT 'RUNNING',
  `state_version` bigint(20) NOT NULL DEFAULT 1,
  `plan_version` bigint(20) NOT NULL DEFAULT 1,
  `policy_version` varchar(100) DEFAULT NULL,
  `pip_readiness` varchar(40) DEFAULT NULL,
  `latest_pip_id` varchar(120) DEFAULT NULL,
  `last_error` text DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_mission_id` (`mission_id`),
  KEY `idx_cti_mission_status` (`status`),
  KEY `idx_cti_mission_versions` (`state_version`,`plan_version`),
  KEY `idx_cti_mission_pip` (`latest_pip_id`)
) ENGINE=InnoDB AUTO_INCREMENT=48 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_normalized_objects` */

DROP TABLE IF EXISTS `cti_normalized_objects`;

CREATE TABLE `cti_normalized_objects` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `normalized_object_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `artifact_id` varchar(120) DEFAULT NULL,
  `object_type` varchar(80) DEFAULT NULL,
  `canonical_id` varchar(255) DEFAULT NULL,
  `schema_version` varchar(100) NOT NULL,
  `object_version` int(11) NOT NULL DEFAULT 1,
  `canonical_json` longtext DEFAULT NULL,
  `object_hash` varchar(128) DEFAULT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `provenance_completeness` decimal(7,6) DEFAULT NULL,
  `quality_status` varchar(50) NOT NULL,
  `quality_metrics_json` longtext DEFAULT NULL,
  `decision_trace_json` longtext DEFAULT NULL,
  `exception_list_json` longtext DEFAULT NULL,
  `freshness_status` varchar(50) DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_normalized_object_id` (`normalized_object_id`),
  KEY `idx_cti_normalized_mission` (`mission_id`,`object_type`),
  KEY `idx_cti_normalized_canonical` (`canonical_id`),
  KEY `idx_cti_normalized_status` (`quality_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_pip_artifacts` */

DROP TABLE IF EXISTS `cti_pip_artifacts`;

CREATE TABLE `cti_pip_artifacts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `pip_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `revision_no` int(11) NOT NULL,
  `schema_version` varchar(120) NOT NULL,
  `readiness` varchar(40) NOT NULL,
  `canonical_sha256` char(64) NOT NULL,
  `artifact_json` longtext NOT NULL,
  `validation_summary_json` longtext DEFAULT NULL,
  `immutable` tinyint(1) NOT NULL DEFAULT 1,
  `execution_authorized` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_pip_id` (`pip_id`),
  UNIQUE KEY `uq_cti_pip_mission_revision` (`mission_id`,`revision_no`),
  KEY `idx_cti_pip_readiness` (`readiness`),
  KEY `idx_cti_pip_hash` (`canonical_sha256`)
) ENGINE=InnoDB AUTO_INCREMENT=122 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_pip_validation_results` */

DROP TABLE IF EXISTS `cti_pip_validation_results`;

CREATE TABLE `cti_pip_validation_results` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `validation_id` varchar(120) NOT NULL,
  `pip_id` varchar(120) NOT NULL,
  `gate_id` varchar(30) NOT NULL,
  `gate_name` varchar(160) NOT NULL,
  `passed` tinyint(1) NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `details_json` longtext DEFAULT NULL,
  `validator_version` varchar(120) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_pip_validation_id` (`validation_id`),
  UNIQUE KEY `uq_cti_pip_gate` (`pip_id`,`gate_id`),
  KEY `idx_cti_pip_validation_passed` (`pip_id`,`passed`)
) ENGINE=InnoDB AUTO_INCREMENT=1211 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_plans` */

DROP TABLE IF EXISTS `cti_plans`;

CREATE TABLE `cti_plans` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `plan_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `plan_version` bigint(20) NOT NULL,
  `plan_json` longtext NOT NULL,
  `status` varchar(40) NOT NULL DEFAULT 'ACTIVE',
  `invalidated_reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_plan_id` (`plan_id`),
  KEY `idx_cti_plan_mission_version` (`mission_id`,`plan_version`),
  KEY `idx_cti_plan_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=59 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_policy_decision_revocations` */

DROP TABLE IF EXISTS `cti_policy_decision_revocations`;

CREATE TABLE `cti_policy_decision_revocations` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `revocation_id` varchar(120) NOT NULL,
  `governance_event_id` varchar(120) DEFAULT NULL,
  `local_event_id` varchar(120) DEFAULT NULL,
  `decision_id` varchar(100) DEFAULT NULL,
  `request_id` varchar(100) DEFAULT NULL,
  `mission_id` varchar(100) NOT NULL,
  `decision_hash` char(64) DEFAULT NULL,
  `decision_status` varchar(30) DEFAULT NULL,
  `revocation_scope` varchar(60) NOT NULL DEFAULT 'POLICY_DECISION',
  `reason` text DEFAULT NULL,
  `revoked_by` varchar(255) DEFAULT NULL,
  `source_component` varchar(120) DEFAULT NULL,
  `verification_status` varchar(100) NOT NULL,
  `verification_error` text DEFAULT NULL,
  `affected_task_count` int(11) NOT NULL DEFAULT 0,
  `active_affected_count` int(11) NOT NULL DEFAULT 0,
  `payload_json` longtext DEFAULT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `received_at` datetime NOT NULL DEFAULT current_timestamp(),
  `verified_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_policy_revocation_id` (`revocation_id`),
  UNIQUE KEY `uq_cti_policy_revocation_governance_event` (`governance_event_id`),
  KEY `idx_cti_policy_revocation_decision` (`decision_id`,`mission_id`,`received_at`),
  KEY `idx_cti_policy_revocation_verification` (`verification_status`,`received_at`),
  CONSTRAINT `chk_cti_policy_revocation_payload_json` CHECK (`payload_json` is null or json_valid(`payload_json`))
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_priority_portfolios` */

DROP TABLE IF EXISTS `cti_priority_portfolios`;

CREATE TABLE `cti_priority_portfolios` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `portfolio_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `belief_snapshot_id` varchar(120) NOT NULL,
  `selection_rule` varchar(160) NOT NULL,
  `weights_json` longtext NOT NULL,
  `penalties_json` longtext DEFAULT NULL,
  `ranked_intentions_json` longtext NOT NULL,
  `inadmissible_candidates_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `execution_authorized` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_priority_portfolio_id` (`portfolio_id`),
  KEY `idx_cti_priority_portfolio_mission` (`mission_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_provenance_records` */

DROP TABLE IF EXISTS `cti_provenance_records`;

CREATE TABLE `cti_provenance_records` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `provenance_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `normalized_object_id` varchar(120) NOT NULL,
  `source_id` varchar(120) DEFAULT NULL,
  `artifact_id` varchar(120) DEFAULT NULL,
  `raw_hash` varchar(128) DEFAULT NULL,
  `activity_id` varchar(120) DEFAULT NULL,
  `parser_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `provenance_json` longtext NOT NULL,
  `completeness_score` decimal(7,6) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_provenance_id` (`provenance_id`),
  KEY `idx_cti_provenance_mission` (`mission_id`),
  KEY `idx_cti_provenance_normalized` (`normalized_object_id`),
  KEY `idx_cti_provenance_artifact` (`artifact_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_raw_artifacts` */

DROP TABLE IF EXISTS `cti_raw_artifacts`;

CREATE TABLE `cti_raw_artifacts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `artifact_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) DEFAULT NULL,
  `source_id` varchar(120) NOT NULL,
  `acquisition_id` varchar(120) DEFAULT NULL,
  `retrieved_at_utc` datetime DEFAULT NULL,
  `source_published_at` datetime DEFAULT NULL,
  `protocol` varchar(50) DEFAULT NULL,
  `endpoint_ref` varchar(500) DEFAULT NULL,
  `watermark_before` varchar(500) DEFAULT NULL,
  `watermark_after` varchar(500) DEFAULT NULL,
  `content_type` varchar(160) DEFAULT NULL,
  `content_hash` varchar(128) DEFAULT NULL,
  `content_size` bigint(20) DEFAULT NULL,
  `transport_status` varchar(50) DEFAULT NULL,
  `validation_status` varchar(50) DEFAULT NULL,
  `duplicate_flag` tinyint(1) NOT NULL DEFAULT 0,
  `raw_payload_ref` varchar(1000) DEFAULT NULL,
  `trace_id` varchar(120) DEFAULT NULL,
  `connector_version` varchar(120) DEFAULT NULL,
  `policy_version` varchar(120) DEFAULT NULL,
  `envelope_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_raw_artifact_id` (`artifact_id`),
  KEY `idx_cti_raw_source_time` (`source_id`,`retrieved_at_utc`),
  KEY `idx_cti_raw_mission` (`mission_id`),
  KEY `idx_cti_raw_hash` (`content_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_source_monitor_state` */

DROP TABLE IF EXISTS `cti_source_monitor_state`;

CREATE TABLE `cti_source_monitor_state` (
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
) ENGINE=InnoDB AUTO_INCREMENT=697 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_source_registry` */

DROP TABLE IF EXISTS `cti_source_registry`;

CREATE TABLE `cti_source_registry` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `source_id` varchar(120) NOT NULL,
  `protocol` varchar(50) NOT NULL,
  `endpoint_ref` varchar(500) NOT NULL,
  `credential_ref` varchar(255) DEFAULT NULL,
  `incremental_strategy` varchar(80) DEFAULT NULL,
  `freshness_sla_seconds` int(11) NOT NULL DEFAULT 86400,
  `criticality` decimal(5,4) NOT NULL DEFAULT 0.5000,
  `rate_limit_per_window` int(11) DEFAULT NULL,
  `rate_window_seconds` int(11) DEFAULT NULL,
  `max_payload_bytes` bigint(20) DEFAULT NULL,
  `trust_tier` varchar(80) DEFAULT NULL,
  `config_json` longtext DEFAULT NULL,
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_source_id` (`source_id`),
  KEY `idx_cti_source_enabled` (`enabled`),
  KEY `idx_cti_source_criticality` (`criticality`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_source_state` */

DROP TABLE IF EXISTS `cti_source_state`;

CREATE TABLE `cti_source_state` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `source_id` varchar(120) NOT NULL,
  `status` varchar(50) NOT NULL DEFAULT 'NEW',
  `watermark_value` varchar(500) DEFAULT NULL,
  `last_success_at` datetime DEFAULT NULL,
  `last_attempt_at` datetime DEFAULT NULL,
  `failure_count` int(11) NOT NULL DEFAULT 0,
  `circuit_state` varchar(30) NOT NULL DEFAULT 'CLOSED',
  `next_retry_at` datetime DEFAULT NULL,
  `health_score` decimal(6,5) NOT NULL DEFAULT 1.00000,
  `remaining_quota` int(11) DEFAULT NULL,
  `change_signal` decimal(6,5) DEFAULT NULL,
  `estimated_cost` decimal(10,5) DEFAULT NULL,
  `last_observation_json` longtext DEFAULT NULL,
  `state_version` bigint(20) NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_source_state_source` (`source_id`),
  KEY `idx_cti_source_state_status` (`status`,`circuit_state`),
  KEY `idx_cti_source_state_retry` (`next_retry_at`)
) ENGINE=InnoDB AUTO_INCREMENT=710 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_task_contracts` */

DROP TABLE IF EXISTS `cti_task_contracts`;

CREATE TABLE `cti_task_contracts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `task_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `plan_id` varchar(120) DEFAULT NULL,
  `assigned_component` varchar(120) NOT NULL,
  `task_type` varchar(120) NOT NULL,
  `priority` int(11) NOT NULL DEFAULT 50,
  `input_refs_json` longtext DEFAULT NULL,
  `output_refs_json` longtext DEFAULT NULL,
  `constraints_json` longtext DEFAULT NULL,
  `deadline` datetime DEFAULT NULL,
  `timeout_seconds` int(11) DEFAULT NULL,
  `retry_policy_json` longtext DEFAULT NULL,
  `success_criteria_json` longtext DEFAULT NULL,
  `plan_version` bigint(20) DEFAULT NULL,
  `policy_version` varchar(100) DEFAULT NULL,
  `state_version` bigint(20) DEFAULT NULL,
  `trace_id` varchar(120) DEFAULT NULL,
  `authorization_mode` varchar(40) NOT NULL DEFAULT 'NOT_REQUIRED_INTERNAL',
  `authorization_authority` varchar(80) DEFAULT NULL,
  `authorization_authority_component` varchar(80) DEFAULT NULL,
  `authorization_governance_event_id` varchar(120) DEFAULT NULL,
  `policy_decision_id` varchar(100) DEFAULT NULL,
  `authorization_request_id` varchar(100) DEFAULT NULL,
  `policy_decision_hash` char(64) DEFAULT NULL,
  `authorization_decision` varchar(20) DEFAULT NULL,
  `authorization_status` varchar(30) DEFAULT NULL,
  `authorization_valid_from` datetime DEFAULT NULL,
  `authorization_valid_until` datetime DEFAULT NULL,
  `scope_contract_id` varchar(100) DEFAULT NULL,
  `scope_version` bigint(20) DEFAULT NULL,
  `policy_set_id` varchar(100) DEFAULT NULL,
  `approval_request_id` varchar(100) DEFAULT NULL,
  `governance_action_class` varchar(100) DEFAULT NULL,
  `governance_action_name` varchar(120) DEFAULT NULL,
  `governance_resource_type` varchar(100) DEFAULT NULL,
  `governance_resource_value` varchar(500) DEFAULT NULL,
  `governance_subject_component` varchar(120) DEFAULT NULL,
  `governance_reason_codes_json` longtext DEFAULT NULL,
  `governance_constraints_json` longtext DEFAULT NULL,
  `governance_request_json` longtext DEFAULT NULL,
  `authorization_bound_at` datetime DEFAULT NULL,
  `pre_dispatch_revalidation_id` varchar(120) DEFAULT NULL,
  `pre_dispatch_governance_event_id` varchar(120) DEFAULT NULL,
  `pre_dispatch_revalidation_status` varchar(30) DEFAULT NULL,
  `pre_dispatch_reason_codes_json` longtext DEFAULT NULL,
  `pre_dispatch_decision_status` varchar(30) DEFAULT NULL,
  `pre_dispatch_decision_hash` char(64) DEFAULT NULL,
  `pre_dispatch_scope_version` bigint(20) DEFAULT NULL,
  `pre_dispatch_policy_version` varchar(100) DEFAULT NULL,
  `pre_dispatch_revalidated_at` datetime DEFAULT NULL,
  `dispatch_authorized_at` datetime DEFAULT NULL,
  `dispatch_blocked_at` datetime DEFAULT NULL,
  `revocation_id` varchar(120) DEFAULT NULL,
  `revocation_event_id` varchar(120) DEFAULT NULL,
  `revocation_status` varchar(80) DEFAULT NULL,
  `revocation_reason` text DEFAULT NULL,
  `revoked_by` varchar(255) DEFAULT NULL,
  `revocation_decision_status` varchar(30) DEFAULT NULL,
  `revocation_decision_hash` char(64) DEFAULT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `revocation_received_at` datetime DEFAULT NULL,
  `revocation_verified_at` datetime DEFAULT NULL,
  `status` varchar(40) NOT NULL DEFAULT 'COMMITTED',
  `error_text` text DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_task_id` (`task_id`),
  KEY `idx_cti_task_mission` (`mission_id`,`status`),
  KEY `idx_cti_task_component` (`assigned_component`,`status`),
  KEY `idx_cti_task_plan` (`plan_id`,`plan_version`),
  KEY `idx_cti_task_policy_decision` (`policy_decision_id`,`status`),
  KEY `idx_cti_task_auth_request` (`authorization_request_id`),
  KEY `idx_cti_task_scope_binding` (`scope_contract_id`,`scope_version`),
  KEY `idx_cti_task_authorization_expiry` (`authorization_mode`,`authorization_valid_until`),
  KEY `idx_cti_task_pre_dispatch_status` (`pre_dispatch_revalidation_status`,`pre_dispatch_revalidated_at`),
  KEY `idx_cti_task_dispatch_blocked` (`dispatch_blocked_at`,`status`),
  KEY `idx_cti_task_revocation_lookup` (`policy_decision_id`,`authorization_mode`,`status`),
  KEY `idx_cti_task_revocation_status` (`revocation_status`,`revoked_at`),
  KEY `idx_cti_task_auth_governance_event` (`authorization_governance_event_id`),
  KEY `idx_cti_task_revalidation_governance_event` (`pre_dispatch_governance_event_id`)
) ENGINE=InnoDB AUTO_INCREMENT=199 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_threat_contexts` */

DROP TABLE IF EXISTS `cti_threat_contexts`;

CREATE TABLE `cti_threat_contexts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `context_id` varchar(120) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `asset_id` varchar(255) DEFAULT NULL,
  `correlation_id` varchar(500) DEFAULT NULL,
  `mapping_id` varchar(120) DEFAULT NULL,
  `technique_id` varchar(40) DEFAULT NULL,
  `target_asset_ids_json` longtext DEFAULT NULL,
  `dimensions_json` longtext NOT NULL,
  `relations_json` longtext DEFAULT NULL,
  `evidence_refs_json` longtext DEFAULT NULL,
  `contradictions_json` longtext DEFAULT NULL,
  `missing_evidence_json` longtext DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `confidence` decimal(7,6) DEFAULT NULL,
  `verification_status` varchar(60) DEFAULT NULL,
  `belief_components_json` longtext DEFAULT NULL,
  `rule_trace_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `authority_state` varchar(120) NOT NULL,
  `execution_authorized` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_threat_context_id` (`context_id`),
  KEY `idx_cti_threat_context_mission` (`mission_id`,`asset_id`),
  KEY `idx_cti_threat_context_mapping` (`mapping_id`),
  KEY `idx_cti_threat_context_technique` (`technique_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_vulnerability_correlations` */

DROP TABLE IF EXISTS `cti_vulnerability_correlations`;

CREATE TABLE `cti_vulnerability_correlations` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `correlation_id` varchar(500) NOT NULL,
  `mission_id` varchar(100) NOT NULL,
  `asset_id` varchar(255) NOT NULL,
  `asset_profile_id` varchar(120) DEFAULT NULL,
  `cpe_resolution_id` varchar(120) DEFAULT NULL,
  `vulnerability_id` bigint(20) DEFAULT NULL,
  `cve_id` varchar(40) DEFAULT NULL,
  `cwe_id` varchar(40) DEFAULT NULL,
  `status` varchar(60) NOT NULL,
  `probability_score` decimal(7,6) DEFAULT NULL,
  `symbolic_result` varchar(20) NOT NULL DEFAULT 'UNKNOWN',
  `confidence` decimal(7,6) DEFAULT NULL,
  `matched_evidence_json` longtext DEFAULT NULL,
  `contradictions_json` longtext DEFAULT NULL,
  `missing_prerequisites_json` longtext DEFAULT NULL,
  `rule_trace_json` longtext DEFAULT NULL,
  `provenance_json` longtext DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `evaluated_at` datetime DEFAULT NULL,
  `freshness_status` varchar(50) DEFAULT NULL,
  `downstream_hints_json` longtext DEFAULT NULL,
  `model_version` varchar(120) DEFAULT NULL,
  `rule_version` varchar(120) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cti_vulnerability_correlation_id` (`correlation_id`),
  KEY `idx_cti_vuln_corr_mission_asset` (`mission_id`,`asset_id`),
  KEY `idx_cti_vuln_corr_cve` (`cve_id`),
  KEY `idx_cti_vuln_corr_status` (`status`,`symbolic_result`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cti_wpt_verified_evidence` */

DROP TABLE IF EXISTS `cti_wpt_verified_evidence`;

CREATE TABLE `cti_wpt_verified_evidence` (
  `intake_id` varchar(192) NOT NULL,
  `mission_id` varchar(192) NOT NULL,
  `task_id` varchar(192) NOT NULL,
  `recon_run_id` varchar(192) NOT NULL,
  `input_sha256` char(64) NOT NULL,
  `evidence_manifest_sha256` char(64) NOT NULL,
  `result_json` longtext NOT NULL CHECK (json_valid(`result_json`)),
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`intake_id`),
  KEY `idx_cti_wpt_mission` (`mission_id`,`created_at`),
  KEY `idx_cti_wpt_recon` (`recon_run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cvss_metrics` */

DROP TABLE IF EXISTS `cvss_metrics`;

CREATE TABLE `cvss_metrics` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `vulnerability_id` bigint(20) unsigned NOT NULL,
  `cvss_version` varchar(10) DEFAULT NULL,
  `source_name` varchar(150) DEFAULT NULL,
  `metric_type` varchar(50) DEFAULT NULL,
  `vector_string` varchar(255) DEFAULT NULL,
  `base_score` decimal(4,1) DEFAULT NULL,
  `base_severity` varchar(20) DEFAULT NULL,
  `attack_vector` varchar(50) DEFAULT NULL,
  `attack_complexity` varchar(50) DEFAULT NULL,
  `privileges_required` varchar(50) DEFAULT NULL,
  `user_interaction` varchar(50) DEFAULT NULL,
  `scope_value` varchar(50) DEFAULT NULL,
  `confidentiality_impact` varchar(50) DEFAULT NULL,
  `integrity_impact` varchar(50) DEFAULT NULL,
  `availability_impact` varchar(50) DEFAULT NULL,
  `exploitability_score` decimal(6,2) DEFAULT NULL,
  `impact_score` decimal(6,2) DEFAULT NULL,
  `is_preferred` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cvss_unique_metric` (`vulnerability_id`,`cvss_version`,`source_name`,`metric_type`),
  KEY `idx_cvss_vulnerability_id` (`vulnerability_id`),
  KEY `idx_cvss_base_severity` (`base_severity`),
  KEY `idx_cvss_base_score` (`base_score`),
  KEY `idx_cvss_is_preferred` (`is_preferred`),
  CONSTRAINT `fk_cvss_vulnerability` FOREIGN KEY (`vulnerability_id`) REFERENCES `vulnerabilities` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=610977 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `cwe_catalog` */

DROP TABLE IF EXISTS `cwe_catalog`;

CREATE TABLE `cwe_catalog` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `cwe_id` varchar(30) NOT NULL,
  `cwe_name` varchar(255) DEFAULT NULL,
  `cwe_url` varchar(500) DEFAULT NULL,
  `description_text` mediumtext DEFAULT NULL,
  `extended_description` mediumtext DEFAULT NULL,
  `abstraction` varchar(80) DEFAULT NULL,
  `structure_value` varchar(80) DEFAULT NULL,
  `status_value` varchar(80) DEFAULT NULL,
  `likelihood_of_exploit` varchar(80) DEFAULT NULL,
  `source_name` varchar(100) DEFAULT 'MITRE CWE',
  `api_version` varchar(50) DEFAULT NULL,
  `api_synced_at` datetime DEFAULT NULL,
  `related_weaknesses_json` longtext DEFAULT NULL,
  `alternate_terms_json` longtext DEFAULT NULL,
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cwe_catalog_cwe_id` (`cwe_id`),
  KEY `idx_cwe_catalog_name` (`cwe_name`),
  KEY `idx_cwe_catalog_abstraction` (`abstraction`),
  KEY `idx_cwe_catalog_status` (`status_value`),
  KEY `idx_cwe_catalog_likelihood` (`likelihood_of_exploit`),
  KEY `idx_cwe_catalog_api_synced` (`api_synced_at`)
) ENGINE=InnoDB AUTO_INCREMENT=820 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `dataset_uploads` */

DROP TABLE IF EXISTS `dataset_uploads`;

CREATE TABLE `dataset_uploads` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `dataset_type` varchar(40) NOT NULL,
  `file_name` varchar(255) NOT NULL,
  `stored_file_path` varchar(500) DEFAULT NULL,
  `file_size_bytes` bigint(20) DEFAULT NULL,
  `row_count` int(11) NOT NULL DEFAULT 0,
  `uploaded_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_dataset_uploads_type` (`dataset_type`),
  KEY `idx_dataset_uploads_uploaded_at` (`uploaded_at`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `nvd_cpe_dictionary` */

DROP TABLE IF EXISTS `nvd_cpe_dictionary`;

CREATE TABLE `nvd_cpe_dictionary` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `cpe_name_id` varchar(100) DEFAULT NULL,
  `cpe23_uri` varchar(1024) DEFAULT NULL,
  `part` varchar(20) DEFAULT NULL,
  `vendor` varchar(255) DEFAULT NULL,
  `product` varchar(255) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `update_value` varchar(255) DEFAULT NULL,
  `edition` varchar(255) DEFAULT NULL,
  `language` varchar(255) DEFAULT NULL,
  `sw_edition` varchar(255) DEFAULT NULL,
  `target_sw` varchar(255) DEFAULT NULL,
  `target_hw` varchar(255) DEFAULT NULL,
  `other` varchar(255) DEFAULT NULL,
  `title` mediumtext DEFAULT NULL,
  `titles_json` longtext DEFAULT NULL,
  `references_json` longtext DEFAULT NULL,
  `deprecated` tinyint(1) NOT NULL DEFAULT 0,
  `deprecated_by_json` longtext DEFAULT NULL,
  `created_at_source` datetime DEFAULT NULL,
  `modified_at_source` datetime DEFAULT NULL,
  `last_synced_at` datetime DEFAULT NULL,
  `source_name` varchar(100) DEFAULT 'NVD Official CPE Dictionary',
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_nvd_cpe_name_id` (`cpe_name_id`),
  KEY `idx_nvd_cpe_part` (`part`),
  KEY `idx_nvd_cpe_vendor` (`vendor`),
  KEY `idx_nvd_cpe_product` (`product`),
  KEY `idx_nvd_cpe_version` (`version`),
  KEY `idx_nvd_cpe_deprecated` (`deprecated`),
  KEY `idx_nvd_cpe_modified` (`modified_at_source`),
  KEY `idx_nvd_cpe_synced` (`last_synced_at`)
) ENGINE=InnoDB AUTO_INCREMENT=1135 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `pentest_enrichment_request_results` */

DROP TABLE IF EXISTS `pentest_enrichment_request_results`;

CREATE TABLE `pentest_enrichment_request_results` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `enrichment_request_id` bigint(20) unsigned NOT NULL,
  `result_type` enum('vulnerability_candidate','attack_context','threat_context','log') NOT NULL,
  `result_payload_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`result_payload_json`)),
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_perr_request` (`enrichment_request_id`),
  KEY `idx_perr_type` (`result_type`)
) ENGINE=InnoDB AUTO_INCREMENT=52143 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `pentest_enrichment_requests` */

DROP TABLE IF EXISTS `pentest_enrichment_requests`;

CREATE TABLE `pentest_enrichment_requests` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `external_scan_job_id` bigint(20) unsigned DEFAULT NULL,
  `target_url` text DEFAULT NULL,
  `source_app` varchar(80) NOT NULL DEFAULT 'pentest',
  `request_payload_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`request_payload_json`)),
  `response_payload_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`response_payload_json`)),
  `status` enum('received','running','completed','failed') NOT NULL DEFAULT 'received',
  `error_text` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_per_ext_scan` (`external_scan_job_id`),
  KEY `idx_per_status` (`status`),
  KEY `idx_per_created_at` (`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=63 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `reference_links` */

DROP TABLE IF EXISTS `reference_links`;

CREATE TABLE `reference_links` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `vulnerability_id` bigint(20) unsigned NOT NULL,
  `url` varchar(1000) NOT NULL,
  `source_name` varchar(150) DEFAULT NULL,
  `tags_json` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_reference_link` (`vulnerability_id`,`url`(255)),
  KEY `idx_reference_links_vulnerability_id` (`vulnerability_id`),
  KEY `idx_reference_links_source_name` (`source_name`),
  CONSTRAINT `fk_reference_links_vulnerability` FOREIGN KEY (`vulnerability_id`) REFERENCES `vulnerabilities` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=1251714 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `sync_audit` */

DROP TABLE IF EXISTS `sync_audit`;

CREATE TABLE `sync_audit` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `sync_type` varchar(30) NOT NULL,
  `started_at` datetime NOT NULL,
  `finished_at` datetime DEFAULT NULL,
  `status_value` varchar(30) NOT NULL,
  `last_successful_modified_at` datetime DEFAULT NULL,
  `page_size` int(11) DEFAULT NULL,
  `total_fetched` int(11) NOT NULL DEFAULT 0,
  `total_inserted` int(11) NOT NULL DEFAULT 0,
  `total_updated` int(11) NOT NULL DEFAULT 0,
  `total_failed` int(11) NOT NULL DEFAULT 0,
  `error_message` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_sync_audit_started_at` (`started_at`),
  KEY `idx_sync_audit_status_value` (`status_value`),
  KEY `idx_sync_audit_last_successful_modified_at` (`last_successful_modified_at`)
) ENGINE=InnoDB AUTO_INCREMENT=93 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `topic_master_records` */

DROP TABLE IF EXISTS `topic_master_records`;

CREATE TABLE `topic_master_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `upload_id` int(11) NOT NULL,
  `topic_text` longtext NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_topic_master_upload_id` (`upload_id`),
  KEY `idx_topic_master_topic_text` (`topic_text`(191)),
  KEY `idx_topic_master_created_at` (`created_at`),
  CONSTRAINT `fk_topic_master_upload` FOREIGN KEY (`upload_id`) REFERENCES `dataset_uploads` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=334 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `tweet_topic_records` */

DROP TABLE IF EXISTS `tweet_topic_records`;

CREATE TABLE `tweet_topic_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `upload_id` int(11) NOT NULL,
  `tweet_text` longtext NOT NULL,
  `topic_text` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_tweet_topic_upload_id` (`upload_id`),
  CONSTRAINT `fk_tweet_topic_upload` FOREIGN KEY (`upload_id`) REFERENCES `dataset_uploads` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=112721 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `vuln_attack_mappings` */

DROP TABLE IF EXISTS `vuln_attack_mappings`;

CREATE TABLE `vuln_attack_mappings` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `cve_id` varchar(32) DEFAULT NULL,
  `cwe_id` varchar(40) DEFAULT NULL,
  `capec_id` varchar(40) DEFAULT NULL,
  `vuln_type` varchar(160) DEFAULT NULL,
  `keyword_pattern` varchar(255) DEFAULT NULL,
  `attack_pattern_stix_id` varchar(120) DEFAULT NULL,
  `attack_id` varchar(40) DEFAULT NULL,
  `attack_name` varchar(255) DEFAULT NULL,
  `tactic_name` varchar(160) DEFAULT NULL,
  `mapping_level` enum('cve_to_attack','cwe_to_attack','capec_to_attack','vuln_type_to_attack','keyword_to_attack','endpoint_heuristic') NOT NULL,
  `mapping_source` enum('manual','rule','capec','nvd_description','analyst','ml_similarity','seed') NOT NULL DEFAULT 'manual',
  `confidence` decimal(5,4) NOT NULL DEFAULT 0.5000,
  `rationale` text DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_vam_cve_id` (`cve_id`),
  KEY `idx_vam_cwe_id` (`cwe_id`),
  KEY `idx_vam_capec_id` (`capec_id`),
  KEY `idx_vam_vuln_type` (`vuln_type`),
  KEY `idx_vam_attack_id` (`attack_id`),
  KEY `idx_vam_attack_stix` (`attack_pattern_stix_id`),
  KEY `idx_vam_level` (`mapping_level`),
  KEY `idx_vam_active` (`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=53 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `vulndesk_service_registry` */

DROP TABLE IF EXISTS `vulndesk_service_registry`;

CREATE TABLE `vulndesk_service_registry` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `service_key` varchar(120) NOT NULL,
  `service_name` varchar(180) NOT NULL,
  `service_side` varchar(30) NOT NULL DEFAULT 'vulndesk',
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `status` varchar(30) NOT NULL DEFAULT 'idle',
  `config_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`config_json`)),
  `last_run_at` datetime DEFAULT NULL,
  `last_error` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_vulndesk_service_key` (`service_key`),
  KEY `idx_vulndesk_service_status` (`status`),
  KEY `idx_vulndesk_service_enabled` (`enabled`)
) ENGINE=InnoDB AUTO_INCREMENT=16047 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `vulnerabilities` */

DROP TABLE IF EXISTS `vulnerabilities`;

CREATE TABLE `vulnerabilities` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `cve_id` varchar(32) NOT NULL,
  `description_text` longtext DEFAULT NULL,
  `source_name` varchar(100) DEFAULT 'NVD',
  `vuln_status` varchar(50) DEFAULT NULL,
  `published_at` datetime DEFAULT NULL,
  `modified_at` datetime DEFAULT NULL,
  `nvd_url` varchar(500) DEFAULT NULL,
  `has_cvss` tinyint(1) NOT NULL DEFAULT 0,
  `preferred_cvss_version` varchar(10) DEFAULT NULL,
  `preferred_base_score` decimal(4,1) DEFAULT NULL,
  `preferred_base_severity` varchar(20) DEFAULT NULL,
  `preferred_vector_string` varchar(255) DEFAULT NULL,
  `raw_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_vulnerabilities_cve_id` (`cve_id`),
  KEY `idx_vulnerabilities_modified_at` (`modified_at`),
  KEY `idx_vulnerabilities_published_at` (`published_at`),
  KEY `idx_vulnerabilities_status` (`vuln_status`),
  KEY `idx_vulnerabilities_preferred_severity` (`preferred_base_severity`),
  KEY `idx_vulnerabilities_preferred_score` (`preferred_base_score`)
) ENGINE=InnoDB AUTO_INCREMENT=378102 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `vulnerability_cwes` */

DROP TABLE IF EXISTS `vulnerability_cwes`;

CREATE TABLE `vulnerability_cwes` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `vulnerability_id` bigint(20) unsigned NOT NULL,
  `cwe_catalog_id` bigint(20) unsigned NOT NULL,
  `source_name` varchar(100) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_vulnerability_cwe` (`vulnerability_id`,`cwe_catalog_id`),
  KEY `idx_vulnerability_cwes_vulnerability_id` (`vulnerability_id`),
  KEY `idx_vulnerability_cwes_cwe_catalog_id` (`cwe_catalog_id`),
  CONSTRAINT `fk_vuln_cwe_catalog` FOREIGN KEY (`cwe_catalog_id`) REFERENCES `cwe_catalog` (`id`),
  CONSTRAINT `fk_vuln_cwe_vulnerability` FOREIGN KEY (`vulnerability_id`) REFERENCES `vulnerabilities` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=336530 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*Table structure for table `vulnerability_raw_json_chunks` */

DROP TABLE IF EXISTS `vulnerability_raw_json_chunks`;

CREATE TABLE `vulnerability_raw_json_chunks` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `vulnerability_id` bigint(20) unsigned NOT NULL,
  `chunk_index` int(11) NOT NULL,
  `compressed_data` longblob NOT NULL,
  `original_size` bigint(20) unsigned NOT NULL,
  `compressed_size` bigint(20) unsigned NOT NULL,
  `sha256_hex` varchar(64) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_vulnerability_raw_json_chunk` (`vulnerability_id`,`chunk_index`),
  KEY `idx_vulnerability_raw_json_chunks_vulnerability_id` (`vulnerability_id`),
  CONSTRAINT `fk_raw_json_chunks_vulnerability` FOREIGN KEY (`vulnerability_id`) REFERENCES `vulnerabilities` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=166458 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;
