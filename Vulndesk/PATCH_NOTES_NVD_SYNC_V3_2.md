# VulnDesk NVD Sync V3.2

## Fixed

- Fixed MariaDB error 1062 on `reference_links.uq_reference_link` when NVD sends the same URL using different letter case.
- Reference/CPE/CVSS unique-key deduplication now follows the case-insensitive 255-character prefix semantics of the supplied `utf8mb4_unicode_ci` schema.
- Added vulnerability navigation buttons: **First**, **Previous**, **Next**, and **Last**.
- Added explicit **Filtered results** and **Total vulnerabilities** counters.
- Cached the unfiltered database total during navigation and refresh it after sync completion or failure.

No database migration is required for this patch.
