-- VulnDesk NVD packet-safe raw JSON storage migration v3.1
-- Corrected for the current VulnDesk schema where vulnerabilities.id is
-- BIGINT(20) UNSIGNED. MariaDB requires an FK column to match the parent
-- column type exactly, including UNSIGNED.

USE `vulndesk`;

-- Diagnostic: both values must be bigint(...) unsigned.
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    COLUMN_TYPE,
    IS_NULLABLE,
    COLUMN_KEY
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND (
       (TABLE_NAME = 'vulnerabilities' AND COLUMN_NAME = 'id')
       OR
       (TABLE_NAME = 'vulnerability_raw_json_chunks' AND COLUMN_NAME = 'vulnerability_id')
  )
ORDER BY TABLE_NAME, COLUMN_NAME;

-- The previous failed CREATE TABLE normally leaves no table, but DROP makes
-- this migration safe if a partial table was created without the FK.
DROP TABLE IF EXISTS `vulnerability_raw_json_chunks`;

CREATE TABLE `vulnerability_raw_json_chunks` (
  `id` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `vulnerability_id` BIGINT(20) UNSIGNED NOT NULL,
  `chunk_index` INT NOT NULL,
  `compressed_data` LONGBLOB NOT NULL,
  `original_size` BIGINT UNSIGNED NOT NULL,
  `compressed_size` BIGINT UNSIGNED NOT NULL,
  `sha256_hex` VARCHAR(64) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_vulnerability_raw_json_chunk`
    (`vulnerability_id`, `chunk_index`),
  KEY `idx_vulnerability_raw_json_chunks_vulnerability_id`
    (`vulnerability_id`),
  CONSTRAINT `fk_raw_json_chunks_vulnerability`
    FOREIGN KEY (`vulnerability_id`)
    REFERENCES `vulnerabilities` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

SHOW CREATE TABLE `vulnerability_raw_json_chunks`;
