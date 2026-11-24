# PATCH NOTES — Stage 3.7.8 Hotfix 1

## Change

Rebase four stale `supported_controls` expectations so the canonical Stage 3.7 tail is:

`3.7.1 -> 3.7.2 -> 3.7.3 -> 3.7.4 -> 3.7.5 -> 3.7.6 -> 3.7.7 -> 3.7.8`

## Why

Authoritative host acceptance completed all 1322 tests and reported only four assertion failures. Each failure expected Stage 3.7.8 immediately after Stage 3.7.6, or used a seven-element Stage 3.7 tail. The active runtime correctly contains Stage 3.7.7 before Stage 3.7.8.

## Scope

Test-only correction. Stage 3.7.8 runtime implementation, migration `52`, API, persistence, event semantics, supersession/handoff authority, and control version are unchanged.
