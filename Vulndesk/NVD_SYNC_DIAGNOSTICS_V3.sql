-- VulnDesk NVD Sync Packet-Safe V3 diagnostics

SELECT @@global.max_allowed_packet AS global_max_allowed_packet,
       @@session.max_allowed_packet AS session_max_allowed_packet;

SELECT setting_key, setting_value, updated_at
FROM app_settings
WHERE setting_key IN ('nvd_full_sync_start_index', 'nvd_incremental_checkpoint');

SELECT id, sync_type, status_value, started_at, finished_at,
       total_fetched, total_inserted, total_updated, total_failed,
       LEFT(error_message, 500) AS error_message
FROM sync_audit
ORDER BY id DESC
LIMIT 20;

SELECT COUNT(*) AS vulnerability_count,
       MAX(modified_at) AS latest_modified_at,
       MAX(OCTET_LENGTH(raw_json)) AS largest_legacy_raw_json_bytes
FROM vulnerabilities;

SELECT COUNT(*) AS raw_json_chunk_count,
       COUNT(DISTINCT vulnerability_id) AS vulnerabilities_with_compressed_json,
       MAX(OCTET_LENGTH(compressed_data)) AS largest_chunk_bytes,
       MAX(original_size) AS largest_original_json_bytes,
       MAX(compressed_size) AS largest_compressed_json_bytes
FROM vulnerability_raw_json_chunks;

SELECT v.cve_id,
       COUNT(c.id) AS chunks,
       MAX(c.original_size) AS original_bytes,
       MAX(c.compressed_size) AS compressed_bytes,
       ROUND(100 * MAX(c.compressed_size) / NULLIF(MAX(c.original_size), 0), 2)
         AS compressed_percent
FROM vulnerability_raw_json_chunks c
JOIN vulnerabilities v ON v.id = c.vulnerability_id
GROUP BY v.id, v.cve_id
ORDER BY original_bytes DESC
LIMIT 20;

-- Optional server-side mitigation. The application patch does not require it.
-- Requires sufficient privilege and affects only new connections.
-- SET GLOBAL max_allowed_packet = 67108864; -- 64 MiB
