# Patch Notes — Stage 3.4.5 Acceptance Hotfix 1

- Fixed Windows PowerShell wildcard handling in Stage-3.1 and Stage-3.2 regression partitions.
- Replaced literal pytest wildcard arguments with explicit `Get-ChildItem` discovery.
- Added fail-closed checks when a regression partition discovers zero test files.
- Runtime Stage-3.4.5 implementation is unchanged.
