-- Run against the same MariaDB database used by Vulndesk's CTI DbAdapter.
-- Additive migration only: does not alter or delete existing CTI records.
CREATE TABLE IF NOT EXISTS cti_wpt_verified_evidence (
  intake_id VARCHAR(192) NOT NULL PRIMARY KEY,
  mission_id VARCHAR(192) NOT NULL,
  task_id VARCHAR(192) NOT NULL,
  recon_run_id VARCHAR(192) NOT NULL,
  input_sha256 CHAR(64) NOT NULL,
  evidence_manifest_sha256 CHAR(64) NOT NULL,
  result_json LONGTEXT NOT NULL CHECK (JSON_VALID(result_json)),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_cti_wpt_mission (mission_id,created_at),
  KEY idx_cti_wpt_recon (recon_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
