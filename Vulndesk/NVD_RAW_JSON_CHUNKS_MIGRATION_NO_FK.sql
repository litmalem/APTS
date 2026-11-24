-- Emergency fallback only. Prefer NVD_RAW_JSON_CHUNKS_MIGRATION.sql.
-- This creates the table without an FK if the parent table is not InnoDB or
-- has a nonstandard id definition. The application can operate, but orphan
-- chunk cleanup must then be handled manually.

USE `vulndesk`;
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
    (`vulnerability_id`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
